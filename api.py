"""
api.py — ModSuite v2.0 REST API
Runs alongside bot.py in the same process (uvicorn as asyncio task).
All endpoints are localhost-only; no auth required for v2.0.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import database as db
from utils import DEFAULTS

log = logging.getLogger("ModSuite.API")

# ── Bot reference (set by bot.py before uvicorn starts) ───────────────────────

_bot = None  # type: ignore


def set_bot(bot) -> None:
    """Called by bot.py to inject the running bot instance."""
    global _bot
    _bot = bot


# ── App & CORS ────────────────────────────────────────────────────────────────

app = FastAPI(title="ModSuite API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _err(status: int, msg: str):
    raise HTTPException(status_code=status, detail={"error": msg})


def _get_guild(guild_id: Optional[str] = None):
    """
    Returns the discord.Guild object.
    If guild_id is provided it is looked up; otherwise defaults to the
    first guild the bot is in (single-guild deployment).
    Returns None when the bot reference is not yet available.
    """
    if _bot is None:
        return None
    if guild_id:
        g = _bot.get_guild(int(guild_id))
        return g
    return _bot.guilds[0] if _bot.guilds else None


def _resolve_guild_id(guild_id: Optional[str]) -> str:
    """Return a guild_id string, falling back to the bot's first guild."""
    if guild_id:
        return str(guild_id)
    guild = _get_guild()
    if guild:
        return str(guild.id)
    _err(503, "Bot not ready — guild_id cannot be inferred yet.")


def _member_name(guild, user_id: str) -> Optional[str]:
    """Attempt to resolve a display name from the bot's member cache."""
    if guild is None:
        return None
    try:
        member = guild.get_member(int(user_id))
        if member:
            return member.display_name
    except Exception:
        pass
    return None


def _fmt_ts(ts: Optional[str]) -> Optional[str]:
    """Ensure timestamps end with Z (UTC marker) for consistency."""
    if not ts:
        return None
    if not ts.endswith("Z"):
        return ts + "Z"
    return ts


# ── Request / Response models ─────────────────────────────────────────────────

class NoteCreate(BaseModel):
    guild_id: str
    target_id: str
    author_id: str
    content: str


class BotMessageUpdate(BaseModel):
    content: str


class PostAsBotRequest(BaseModel):
    guild_id: str
    channel_id: str
    content: str


class SelfRoleCategoryCreate(BaseModel):
    guild_id: str
    name: str
    enforcement: str = "single"
    intro_text: Optional[str] = None
    roles: list[dict]  # [{"name": "PC", "emoji": "💻"}]


class SelfRoleCategoryUpdate(BaseModel):
    intro_text: Optional[str] = None
    enforcement: Optional[str] = None


# ── Dashboard ─────────────────────────────────────────────────────────────────


@app.get("/dashboard/stats")
async def dashboard_stats(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)

    with db.get_conn() as conn:
        total_warns = conn.execute(
            "SELECT COUNT(*) FROM warns WHERE guild_id = ?", (gid,)
        ).fetchone()[0]

        active_jails = conn.execute(
            "SELECT COUNT(*) FROM jail WHERE guild_id = ? AND active = 1", (gid,)
        ).fetchone()[0]

        open_tickets = conn.execute(
            "SELECT COUNT(*) FROM modmail_tickets WHERE guild_id = ? AND status = 'open'", (gid,)
        ).fetchone()[0]

    member_count = guild.member_count if guild else 0

    return {
        "total_warns": total_warns,
        "active_jails": active_jails,
        "open_tickets": open_tickets,
        "member_count": member_count,
    }


@app.get("/dashboard/activity")
async def dashboard_activity(
    guild_id: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=200),
):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)

    # Merge recent warns + jails + mod_logs (tickets excluded — no actor info)
    with db.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT 'warn'           AS type,
                   CAST(user_id AS TEXT) AS target_id,
                   NULL              AS target_username,
                   CAST(mod_id AS TEXT)  AS actor_id,
                   mod_name          AS actor_username,
                   reason,
                   timestamp
            FROM warns
            WHERE guild_id = ?

            UNION ALL

            SELECT 'jail'            AS type,
                   CAST(user_id AS TEXT) AS target_id,
                   NULL               AS target_username,
                   CAST(jailed_by_id AS TEXT) AS actor_id,
                   jailed_by_name     AS actor_username,
                   reason,
                   jailed_at          AS timestamp
            FROM jail
            WHERE guild_id = ?

            UNION ALL

            SELECT action           AS type,
                   target_id,
                   target_username,
                   actor_id,
                   actor_username,
                   reason,
                   timestamp
            FROM mod_logs
            WHERE guild_id = ?

            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (gid, gid, gid, limit),
        ).fetchall()

    results = []
    for r in rows:
        row = dict(r)
        # Attempt username resolution from bot cache
        if not row.get("target_username") and row.get("target_id"):
            row["target_username"] = _member_name(guild, row["target_id"])
        results.append({
            "type":            row["type"],
            "target_username": row.get("target_username"),
            "reason":          row.get("reason"),
            "actor_username":  row.get("actor_username"),
            "timestamp":       _fmt_ts(row.get("timestamp")),
        })
    return results


# ── Mod Logs ──────────────────────────────────────────────────────────────────


@app.get("/modlogs")
async def get_modlogs(
    guild_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    total, rows = db.get_mod_logs(gid, action or "", limit, offset)

    results = []
    for r in rows:
        if not r.get("target_username") and r.get("target_id"):
            r["target_username"] = _member_name(guild, r["target_id"])
        results.append({
            "id":              r["id"],
            "action":          r["action"],
            "target_id":       r["target_id"],
            "target_username": r.get("target_username"),
            "actor_id":        r.get("actor_id"),
            "actor_username":  r.get("actor_username"),
            "reason":          r.get("reason"),
            "timestamp":       _fmt_ts(r.get("timestamp")),
        })

    return {"total": total, "results": results}


# ── Warns ─────────────────────────────────────────────────────────────────────


@app.get("/warns")
async def get_warns(
    guild_id: Optional[str] = None,
    target_id: Optional[str] = None,
    active_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    total, rows = db.get_all_warns(gid, target_id or "", active_only, limit, offset)

    results = []
    for r in rows:
        uid = str(r["user_id"])
        results.append({
            "id":              r["id"],
            "target_id":       uid,
            "target_username": _member_name(guild, uid),
            "actor_id":        str(r["mod_id"]),
            "actor_username":  r.get("mod_name"),
            "reason":          r.get("reason"),
            "timestamp":       _fmt_ts(r.get("timestamp")),
            "active":          bool(r.get("active", 1)),
        })

    return {"total": total, "results": results}


@app.delete("/warns/{warn_id}")
async def pardon_warn(warn_id: int):
    warn = db.get_warn_by_id(warn_id)
    if not warn:
        _err(404, f"Warn #{warn_id} not found.")
    if not warn.get("active"):
        _err(400, f"Warn #{warn_id} is already pardoned.")
    db.remove_warn(warn_id)
    return {"pardoned": True, "warn_id": warn_id}


# ── Jails ─────────────────────────────────────────────────────────────────────


@app.get("/jails")
async def get_jails(
    guild_id: Optional[str] = None,
    active_only: bool = Query(default=True),
):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    rows = db.get_all_jails(gid, active_only)

    results = []
    for r in rows:
        uid = str(r["user_id"])
        results.append({
            "jail_id":         r.get("jail_id"),
            "target_id":       uid,
            "target_username": _member_name(guild, uid),
            "reason":          r.get("reason"),
            "jail_end_time":   _fmt_ts(r.get("jail_end_time")),
            "is_temp":         r.get("jail_end_time") is not None,
            "active":          bool(r.get("active", 1)),
        })
    return results


# ── Notes ─────────────────────────────────────────────────────────────────────


@app.get("/notes")
async def get_notes(
    guild_id: Optional[str] = None,
    target_id: Optional[str] = None,
):
    gid = _resolve_guild_id(guild_id)
    rows = db.get_all_notes(gid, target_id or "")
    return [
        {
            "note_id":    r["note_id"],
            "guild_id":   r["guild_id"],
            "target_id":  r["target_id"],
            "author_id":  r["author_id"],
            "content":    r["content"],
            "created_at": _fmt_ts(r.get("created_at")),
        }
        for r in rows
    ]


@app.post("/notes", status_code=201)
async def create_note(body: NoteCreate):
    note_id = db.add_note(
        int(body.guild_id),
        int(body.target_id),
        int(body.author_id),
        body.content,
    )
    return {"note_id": note_id, "created": True}


@app.delete("/notes/{note_id}")
async def delete_note(note_id: int):
    note = db.get_note_by_id(note_id)
    if not note:
        _err(404, f"Note #{note_id} not found.")
    if note.get("deleted"):
        _err(400, f"Note #{note_id} is already deleted.")
    db.delete_note(note_id)
    return {"deleted": True, "note_id": note_id}


# ── Tickets ───────────────────────────────────────────────────────────────────


@app.get("/tickets")
async def get_tickets(
    guild_id: Optional[str] = None,
    status: str = Query(default="open"),
):
    if status not in ("open", "closed", "all"):
        _err(400, "status must be 'open', 'closed', or 'all'.")
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    rows = db.get_all_tickets(gid, status)

    results = []
    for r in rows:
        uid = str(r["user_id"])
        results.append({
            "ticket_id":       r["id"],
            "opener_id":       uid,
            "opener_username": _member_name(guild, uid),
            "subject":         None,   # not stored; placeholder for future
            "status":          r["status"],
            "created_at":      _fmt_ts(r.get("opened_at")),
            "message_count":   r.get("message_count", 0),
        })
    return results


# ── Bot Messages ──────────────────────────────────────────────────────────────


@app.get("/bot-messages")
async def get_bot_messages(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    with db.get_conn() as conn:
        custom_rows = conn.execute(
            "SELECT slot, content FROM bot_messages WHERE guild_id = ?", (gid,)
        ).fetchall()
    custom = {r["slot"]: r["content"] for r in custom_rows}

    return [
        {
            "slot":    slot,
            "content": custom.get(slot, default),
            "default": default,
        }
        for slot, default in DEFAULTS.items()
    ]


@app.put("/bot-messages/{slot}")
async def update_bot_message(slot: str, body: BotMessageUpdate, guild_id: Optional[str] = None):
    if slot not in DEFAULTS:
        _err(404, f"Unknown message slot '{slot}'.")
    gid = _resolve_guild_id(guild_id)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO bot_messages (guild_id, slot, content) VALUES (?, ?, ?)"
            " ON CONFLICT(guild_id, slot) DO UPDATE SET content = excluded.content",
            (gid, slot, body.content),
        )
    return {"slot": slot, "updated": True}


@app.delete("/bot-messages/{slot}")
async def reset_bot_message(slot: str, guild_id: Optional[str] = None):
    if slot not in DEFAULTS:
        _err(404, f"Unknown message slot '{slot}'.")
    gid = _resolve_guild_id(guild_id)
    with db.get_conn() as conn:
        conn.execute(
            "DELETE FROM bot_messages WHERE guild_id = ? AND slot = ?", (gid, slot)
        )
    return {"slot": slot, "reset": True, "default": DEFAULTS[slot]}


# ── Self-Role Categories ──────────────────────────────────────────────────────


def _category_with_roles(cat: dict) -> dict:
    roles = db.get_selfrole_roles(cat["category_id"])
    return {
        "category_id": cat["category_id"],
        "name":        cat["name"],
        "enforcement": cat["enforcement"],
        "is_builtin":  bool(cat.get("is_builtin", 0)),
        "intro_text":  cat.get("intro_text"),
        "message_id":  cat.get("message_id"),
        "roles": [
            {
                "role_entry_id": r["role_entry_id"],
                "role_id":       r["role_id"],
                "emoji":         r["emoji"],
                "display_order": r["display_order"],
            }
            for r in roles
        ],
    }


@app.get("/selfroles/categories")
async def get_selfrole_categories(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    cats = db.get_all_selfrole_categories(gid)
    return [_category_with_roles(c) for c in cats]


@app.post("/selfroles/categories", status_code=201)
async def create_selfrole_category(body: SelfRoleCategoryCreate):
    if body.enforcement not in ("single", "multi"):
        _err(400, "enforcement must be 'single' or 'multi'.")
    if not body.roles:
        _err(400, "At least one role is required.")

    gid = str(body.guild_id)
    cat_id = db.insert_selfrole_category(gid, body.name, body.enforcement, body.intro_text)

    # Queue bot action to create Discord roles and post the message
    action_id = db.queue_bot_action(
        gid,
        "create_selfrole_category",
        {
            "category_id": cat_id,
            "name":        body.name,
            "enforcement": body.enforcement,
            "intro_text":  body.intro_text,
            "roles":       body.roles,  # [{"name": "PC", "emoji": "💻"}]
        },
    )

    return {"category_id": cat_id, "queued": True, "action_id": action_id}


@app.put("/selfroles/categories/{category_id}")
async def update_selfrole_category(category_id: int, body: SelfRoleCategoryUpdate):
    cat = db.get_selfrole_category(category_id)
    if not cat:
        _err(404, f"Category #{category_id} not found.")

    updates: dict = {}
    if body.intro_text is not None:
        updates["intro_text"] = body.intro_text
    if body.enforcement is not None:
        if body.enforcement not in ("single", "multi"):
            _err(400, "enforcement must be 'single' or 'multi'.")
        updates["enforcement"] = body.enforcement

    if updates:
        db.update_selfrole_category(category_id, **updates)
    return {"category_id": category_id, "updated": True}


@app.delete("/selfroles/categories/{category_id}")
async def delete_selfrole_category(category_id: int):
    cat = db.get_selfrole_category(category_id)
    if not cat:
        _err(404, f"Category #{category_id} not found.")
    if cat.get("is_builtin"):
        raise HTTPException(
            status_code=403,
            detail={"error": "Built-in categories cannot be deleted."},
        )
    db.delete_selfrole_category(category_id)
    return {"category_id": category_id, "deleted": True}


# ── Post as Bot ───────────────────────────────────────────────────────────────


@app.post("/post-as-bot")
async def post_as_bot(body: PostAsBotRequest):
    guild = _get_guild(body.guild_id)
    if guild is None and _bot is not None:
        _err(404, f"Guild {body.guild_id} not found.")

    action_id = db.queue_bot_action(
        str(body.guild_id),
        "post_message",
        {"channel_id": str(body.channel_id), "content": body.content},
    )
    return {"queued": True, "action_id": action_id}


# ── Channels ──────────────────────────────────────────────────────────────────


@app.get("/channels")
async def get_channels(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    if guild is None:
        if _bot is None:
            _err(503, "Bot not ready.")
        _err(404, f"Guild {gid} not found.")

    import discord
    results = []
    for ch in guild.text_channels:
        results.append({
            "channel_id": str(ch.id),
            "name":       ch.name,
            "category":   ch.category.name if ch.category else None,
        })
    return results
