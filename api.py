"""
api.py -- ModSuite v2.0 REST API
Runs alongside bot.py in the same process (uvicorn as asyncio task).
All endpoints are localhost-only; no auth required for v2.0.
"""

import logging
import os
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

app = FastAPI(title="ModSuite API", version="3.0.0")

# CORS origins: always allow localhost; add your server's public IP/domain via
# CORS_ORIGINS in .env (comma-separated, e.g. "http://myserver.com,http://10.0.0.5:8000")
_default_origins = [
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
_extra = os.getenv("CORS_ORIGINS", "")
if _extra.strip():
    _default_origins.extend([o.strip() for o in _extra.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth (Discord OAuth2) ─────────────────────────────────────────────────────
# register_auth() is called by bot.py after set_bot(), so the bot reference
# is available for role resolution.  See auth.py for details.

_auth_registered = False

def register_auth_routes(bot=None):
    """Called once by bot.py to wire up Discord OAuth2 login."""
    global _auth_registered
    if _auth_registered:
        return
    _auth_registered = True
    from auth import register_auth
    register_auth(app, bot_ref=bot)

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
    _err(503, "Bot not ready -- guild_id cannot be inferred yet.")


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

    # Merge recent warns + jails + mod_logs (tickets excluded -- no actor info)
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
    guild = _get_guild(gid)
    rows = db.get_all_notes(gid, target_id or "")
    return [
        {
            "note_id":         r["note_id"],
            "guild_id":        r["guild_id"],
            "target_id":       str(r["target_id"]),
            "target_username": _member_name(guild, str(r["target_id"])),
            "author_id":       str(r["author_id"]),
            "author_username": _member_name(guild, str(r["author_id"])),
            "content":         r["content"],
            "created_at":      _fmt_ts(r.get("created_at")),
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
# =============================================================================
# ── Wave 1 additions ── (append to api.py before the static-mount block) ─────
# =============================================================================
#
# New endpoints:
#   GET  /health                -- bot uptime, latency, guilds, memory
#   GET  /warns/trends?days=30  -- warns count per day for last N days
#   GET  /top-offenders?limit=5 -- users with the most warns
#   GET  /automod/summary       -- quick AutoMod status (on/off + counts)
#   GET  /config                -- full guild_config as a dict
#   PUT  /config                -- bulk-update guild_config columns
#
# All read-only unless noted. PUT /config validates known columns only.

import time as _time
import os as _os

# Track process start for uptime
_START_TIME = _time.time()

# Attempt psutil for memory; degrade gracefully if not installed
try:
    import psutil as _psutil
    _PROC = _psutil.Process(_os.getpid())
except Exception:
    _PROC = None


# ── Config schema (labels + sections for the frontend editor) ────────────────
# The FE reads /config-schema to render the sectioned editor.
# Add new sections/fields here as the bot grows.

CONFIG_SECTIONS = [
    {
        "id": "general",
        "label": "General",
        "description": "Core roles, channels, and welcome behaviour.",
        "fields": [
            {"key": "owner_role_id",    "label": "Owner Role ID",    "type": "text",   "hint": "Role granted server-owner permissions."},
            {"key": "mod_role_id",      "label": "Moderator Role ID","type": "text",   "hint": "Role granted staff permissions."},
            {"key": "verified_role_id", "label": "Verified Role ID", "type": "text",   "hint": "Auto-assigned via /verify."},
            {"key": "auto_role_id",     "label": "Auto-Role ID",     "type": "text",   "hint": "Auto-assigned on member join."},
            {"key": "modmail_ch_id",    "label": "ModMail Channel",  "type": "text"},
            {"key": "modlog_ch_id",     "label": "Mod-Log Channel",  "type": "text"},
            {"key": "closed_ch_id",     "label": "Closed Tickets Channel", "type": "text"},
            {"key": "selfroles_ch_id",  "label": "Self-Roles Channel","type": "text"},
        ],
    },
    {
        "id": "warns",
        "label": "Warns & Thresholds",
        "description": "Automatic escalation when a member hits a warn count.",
        "fields": [
            {"key": "warn_mute_threshold",   "label": "Mute at N warns",  "type": "number", "min": 0, "max": 20},
            {"key": "warn_mute_duration_hrs","label": "Auto-mute duration (hours)", "type": "number", "min": 0},
            {"key": "warn_ban_threshold",    "label": "Ban at N warns",   "type": "number", "min": 0, "max": 20},
        ],
    },
    {
        "id": "raid",
        "label": "Raid Response",
        "description": "Detects join floods and locks the server automatically.",
        "fields": [
            {"key": "raid_join_count",          "label": "Trigger: joins in window", "type": "number", "min": 3, "max": 100},
            {"key": "raid_join_seconds",        "label": "Trigger window (seconds)", "type": "number", "min": 5, "max": 600},
            {"key": "raid_min_account_age_days","label": "Flag joins younger than (days, 0 = off)", "type": "number", "min": 0, "max": 365},
            {"key": "raid_active_action",       "label": "During raid, joiners are",  "type": "select",
                "options": [{"value": "kick", "label": "Kicked"}, {"value": "ban", "label": "Banned"}]},
            {"key": "raid_auto_verification",   "label": "Auto-raise verification during lockdown", "type": "bool"},
            {"key": "raid_lockdown_cooldown_min","label": "Auto-unlock after (minutes, 0 = manual only)", "type": "number", "min": 0, "max": 1440},
        ],
    },
    {
        "id": "automod_spam",
        "label": "AutoMod · Spam",
        "description": "Message velocity, duplicates, mention floods, emoji floods.",
        "fields": [
            {"key": "spam_enabled",         "label": "Enabled",                       "type": "bool"},
            {"key": "spam_msg_limit",       "label": "Messages allowed in window",    "type": "number", "min": 2, "max": 30},
            {"key": "spam_window_sec",      "label": "Window (seconds)",              "type": "number", "min": 3, "max": 60},
            {"key": "spam_dup_limit",       "label": "Duplicate messages allowed",    "type": "number", "min": 2, "max": 10},
            {"key": "spam_mention_limit",   "label": "Mentions per message",          "type": "number", "min": 2, "max": 20},
            {"key": "spam_emoji_limit",     "label": "Emojis per message",            "type": "number", "min": 3, "max": 50},
            {"key": "spam_action",          "label": "Action on trigger",             "type": "select",
                "options": [
                    {"value": "delete", "label": "Delete only"},
                    {"value": "mute",   "label": "Delete + mute (timeout)"},
                    {"value": "kick",   "label": "Delete + kick"},
                    {"value": "ban",    "label": "Delete + ban"},
                ]},
            {"key": "spam_mute_minutes",    "label": "Mute duration (minutes)",       "type": "number", "min": 1, "max": 1440},
        ],
    },
    {
        "id": "automod_links",
        "label": "AutoMod · Links",
        "description": "Whitelist or blacklist domains. Bypass by role or channel.",
        "fields": [
            {"key": "link_filter_enabled",  "label": "Enabled",                 "type": "bool"},
            {"key": "link_mode",            "label": "Mode",                    "type": "select",
                "options": [
                    {"value": "whitelist", "label": "Whitelist (block all except approved)"},
                    {"value": "blacklist", "label": "Blacklist (allow all except blocked)"},
                ]},
            {"key": "link_whitelist",       "label": "Whitelist (JSON array of domains)", "type": "json_list"},
            {"key": "link_blacklist",       "label": "Blacklist (JSON array of domains)", "type": "json_list"},
            {"key": "link_action",          "label": "Action on trigger",       "type": "select",
                "options": [
                    {"value": "delete", "label": "Delete only"},
                    {"value": "mute",   "label": "Delete + mute"},
                    {"value": "kick",   "label": "Delete + kick"},
                    {"value": "ban",    "label": "Delete + ban"},
                ]},
            {"key": "link_bypass_roles",    "label": "Bypass role IDs (JSON array)",    "type": "json_list"},
            {"key": "link_bypass_channels", "label": "Bypass channel IDs (JSON array)", "type": "json_list"},
        ],
    },
    {
        "id": "automod_invites",
        "label": "AutoMod · Invites",
        "description": "Block Discord invite links independently of the link filter.",
        "fields": [
            {"key": "invite_filter_enabled","label": "Enabled",           "type": "bool"},
            {"key": "invite_action",        "label": "Action on trigger", "type": "select",
                "options": [
                    {"value": "delete", "label": "Delete only"},
                    {"value": "mute",   "label": "Delete + mute"},
                    {"value": "kick",   "label": "Delete + kick"},
                    {"value": "ban",    "label": "Delete + ban"},
                ]},
        ],
    },
    {
        "id": "automod_immune",
        "label": "AutoMod · Immune Roles",
        "description": "Members with these roles bypass all AutoMod filters.",
        "fields": [
            {"key": "automod_immune_roles", "label": "Immune role IDs (JSON array)", "type": "json_list"},
        ],
    },
]


def _all_editable_keys() -> set:
    keys = set()
    for section in CONFIG_SECTIONS:
        for f in section["fields"]:
            keys.add(f["key"])
    return keys


# ── /config-schema -- used by the FE to render the editor ─────────────────────

@app.get("/config-schema")
async def get_config_schema():
    return {"sections": CONFIG_SECTIONS}


# ── /config -- get everything as a flat dict ──────────────────────────────────

@app.get("/config")
async def get_config_endpoint(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    cfg = db.get_config(int(gid))
    if cfg is None:
        _err(404, f"No config for guild {gid}. Run /setup first.")
    # Ensure JSON-serializable
    out = {}
    for k, v in cfg.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        else:
            out[k] = str(v)
    return out


# ── /config -- bulk update (partial, only known keys) ─────────────────────────

class ConfigPatch(BaseModel):
    values: dict


@app.put("/config")
async def update_config_endpoint(body: ConfigPatch, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    editable = _all_editable_keys()
    updates = {k: v for k, v in body.values.items() if k in editable}
    if not updates:
        _err(400, "No editable fields in request.")

    # Coerce bools to int (SQLite has no bool type)
    for k, v in list(updates.items()):
        if isinstance(v, bool):
            updates[k] = 1 if v else 0
        # Normalize empty strings on ID fields → None
        if v == "" and (k.endswith("_id") or k.endswith("_ch_id")):
            updates[k] = None

    db.upsert_config(int(gid), **updates)
    return {"updated": list(updates.keys()), "count": len(updates)}


# ── /health -- bot process metrics ────────────────────────────────────────────

@app.get("/health")
async def get_health():
    uptime_seconds = int(_time.time() - _START_TIME)

    latency_ms = None
    guilds_count = 0
    total_members = 0
    bot_user = None
    if _bot is not None:
        try:
            latency_ms = round(_bot.latency * 1000, 1)
        except Exception:
            pass
        guilds_count = len(_bot.guilds)
        total_members = sum(g.member_count or 0 for g in _bot.guilds)
        if _bot.user:
            bot_user = {
                "id":       str(_bot.user.id),
                "username": _bot.user.name,
                "avatar":   str(_bot.user.display_avatar.url) if _bot.user.display_avatar else None,
            }

    memory_mb = None
    cpu_pct = None
    if _PROC is not None:
        try:
            memory_mb = round(_PROC.memory_info().rss / (1024 * 1024), 1)
            cpu_pct = _PROC.cpu_percent(interval=None)
        except Exception:
            pass

    return {
        "uptime_seconds": uptime_seconds,
        "latency_ms":     latency_ms,
        "guilds":         guilds_count,
        "total_members":  total_members,
        "memory_mb":      memory_mb,
        "cpu_percent":    cpu_pct,
        "bot":            bot_user,
        "ready":          _bot is not None and getattr(_bot, "is_ready", lambda: False)(),
    }


# ── /warns/trends -- warns per day for last N days ────────────────────────────

@app.get("/warns/trends")
async def get_warns_trends(days: int = 30, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    days = max(1, min(days, 90))

    from datetime import datetime, timedelta
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT DATE(timestamp) AS day, COUNT(*) AS n
               FROM warns
               WHERE guild_id = ? AND timestamp >= ?
               GROUP BY DATE(timestamp)
               ORDER BY day ASC""",
            (str(gid), cutoff),
        ).fetchall()

    by_day = {r["day"]: r["n"] for r in rows}

    # Fill in missing days with 0
    from datetime import date
    today = date.today()
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        out.append({"date": d, "count": by_day.get(d, 0)})
    return out


# ── /top-offenders -- users with most warns ───────────────────────────────────

@app.get("/top-offenders")
async def get_top_offenders(limit: int = 5, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    limit = max(1, min(limit, 25))

    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT user_id, COUNT(*) AS warn_count
               FROM warns
               WHERE guild_id = ? AND (active = 1 OR active IS NULL)
               GROUP BY user_id
               ORDER BY warn_count DESC
               LIMIT ?""",
            (str(gid), limit),
        ).fetchall()

    guild = _get_guild(gid)
    out = []
    for r in rows:
        uid = r["user_id"]
        name = f"User {uid}"
        avatar = None
        if guild:
            member = guild.get_member(int(uid))
            if member:
                name = member.display_name
                if member.display_avatar:
                    avatar = str(member.display_avatar.url)
        out.append({
            "user_id":     str(uid),
            "username":    name,
            "avatar":      avatar,
            "warn_count":  r["warn_count"],
        })
    return out


# ── /automod/summary -- quick AutoMod dashboard tile ──────────────────────────

# ── Violations (v3.0) ─────────────────────────────────────────────────────────

@app.get("/violations/summary")
async def get_violations_summary(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    summary = db.get_violations_summary(int(gid), limit=10)
    guild = _get_guild(gid)
    out = []
    for row in summary:
        uid = str(row["user_id"])
        username = _member_name(guild, uid)
        out.append({
            "user_id": uid,
            "username": username,
            "count": row["cnt"],
        })
    return out


@app.get("/violations/{user_id}")
async def get_user_violations(user_id: str, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    cfg = db.get_config(int(gid)) or {}
    window = cfg.get("violation_window_minutes") or 60
    threshold = cfg.get("violation_jail_threshold") or 5
    active_count = db.get_all_violation_count(int(gid), int(user_id), window_minutes=window)
    recent = db.get_recent_violations(int(gid), int(user_id), limit=25)
    return {
        "user_id": user_id,
        "active_count": active_count,
        "threshold": threshold,
        "window_minutes": window,
        "recent": [
            {
                "id": v["id"],
                "name": v["name"],
                "trigger": v["trigger"],
                "created_at": _fmt_ts(v.get("created_at")),
            }
            for v in recent
        ],
    }


@app.get("/timed-bans")
async def get_timed_bans(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM timed_bans WHERE guild_id = ? ORDER BY unban_at",
            (int(gid),),
        ).fetchall()
    guild = _get_guild(gid)
    out = []
    for row in rows:
        r = dict(row)
        uid = str(r["user_id"])
        r["username"] = _member_name(guild, uid)
        r["unban_at"] = _fmt_ts(r.get("unban_at"))
        out.append(r)
    return out


@app.get("/word-lists")
async def get_word_lists(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    return db.get_all_word_lists(gid)


@app.get("/profiles")
async def get_profiles(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    db.seed_profiles(gid)
    profiles = db.get_all_profiles(gid)
    cfg = db.get_config(int(gid)) or {}
    active = cfg.get("active_profile") or "normal"
    return {
        "active": active,
        "profiles": [
            {
                "name": p["name"],
                "built_in": bool(p.get("built_in")),
                "overrides": p.get("overrides", {}),
                "is_active": p["name"] == active,
            }
            for p in profiles
        ],
    }


class ProfileSwitch(BaseModel):
    name: str


@app.put("/profiles/active")
async def switch_profile(body: ProfileSwitch, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    name = body.name.strip().lower()
    db.seed_profiles(gid)
    profile = db.get_profile(gid, name)
    if profile is None:
        _err(404, f"Profile '{name}' not found.")
    db.upsert_config(int(gid), active_profile=name)
    db.add_mod_log(
        guild_id=gid,
        action="PROFILE_SWITCH",
        target_id="",
        target_username="",
        actor_id="",
        actor_username="Dashboard",
        reason=f"Profile switched to {name}",
    )
    return {"active": name}


@app.get("/automod/summary")
async def get_automod_summary(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    cfg = db.get_config(int(gid))
    if cfg is None:
        return {"spam": False, "links": False, "invites": False, "immune_count": 0}

    import json as _json_mod
    try:
        immune = _json_mod.loads(cfg.get("automod_immune_roles") or "[]")
        immune_count = len(immune) if isinstance(immune, list) else 0
    except Exception:
        immune_count = 0

    return {
        "spam":         bool(cfg.get("spam_enabled")),
        "links":        bool(cfg.get("link_filter_enabled")),
        "invites":      bool(cfg.get("invite_filter_enabled")),
        "word_lists":   bool(cfg.get("wordlist_enabled")),
        "antiphish":    bool(cfg.get("antiphish_enabled", 1)),
        "slowmode":     bool(cfg.get("slowmode_enabled")),
        "max_message_length": cfg.get("max_message_length") or 0,
        "min_message_length": cfg.get("min_message_length") or 0,
        "slowmode_seconds":   cfg.get("slowmode_seconds") or 5,
        "spam_action":  cfg.get("spam_action") or "mute",
        "link_mode":    cfg.get("link_mode") or "whitelist",
        "immune_count": immune_count,
        "violation_threshold": cfg.get("violation_jail_threshold") or 5,
        "violation_window":    cfg.get("violation_window_minutes") or 60,
        "role_persist":        bool(cfg.get("role_persist_enabled", 1)),
        "active_profile":      cfg.get("active_profile") or "normal",
        "allcaps":             bool(cfg.get("allcaps_enabled")),
        "allcaps_threshold":   cfg.get("allcaps_threshold") or 70,
        "name_filter":         bool(cfg.get("name_filter_enabled")),
        "name_filter_action":  cfg.get("name_filter_action") or "log",
        "verify_gate":         bool(cfg.get("verify_gate_enabled")),
    }
# =============================================================================
# ── Wave 2 additions ── (append to api.py before the static-mount block) ─────
# =============================================================================
#
# New endpoints:
#   POST /warns                  -- queue add-warn action for the bot to execute
#   PUT  /notes/{note_id}        -- edit a note's content
#   GET  /users/search?q=NAME    -- quick member lookup for filters


# ── POST /warns -- queue add-warn action ──────────────────────────────────────

class WarnCreate(BaseModel):
    user_id: str
    reason: str
    mod_id: Optional[str] = None
    mod_name: Optional[str] = None


@app.post("/warns")
async def create_warn(body: WarnCreate, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not body.user_id or not body.reason.strip():
        _err(400, "user_id and reason are required.")

    action_id = db.queue_bot_action(
        str(gid),
        "add_warn",
        {
            "user_id":  str(body.user_id),
            "reason":   body.reason.strip(),
            "mod_id":   str(body.mod_id)  if body.mod_id  else None,
            "mod_name": body.mod_name or "Dashboard",
        },
    )
    return {"queued": True, "action_id": action_id}


# ── PUT /notes/{note_id} -- edit note content ─────────────────────────────────

class NoteUpdate(BaseModel):
    content: str


@app.put("/notes/{note_id}")
async def update_note(note_id: int, body: NoteUpdate, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    text = body.content.strip()
    if not text:
        _err(400, "Note content cannot be empty.")

    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT note_id FROM notes WHERE note_id = ? AND guild_id = ? AND deleted = 0",
            (note_id, str(gid)),
        ).fetchone()
        if row is None:
            _err(404, f"Note {note_id} not found.")
        conn.execute(
            "UPDATE notes SET content = ? WHERE note_id = ?",
            (text, note_id),
        )
    return {"updated": True, "note_id": note_id}


# ── GET /users/search?q=NAME -- member lookup ─────────────────────────────────

@app.get("/users/search")
async def search_users(q: str = "", guild_id: Optional[str] = None, limit: int = 20):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    if guild is None:
        return []

    q = q.strip().lower()
    limit = max(1, min(limit, 50))
    out = []

    for member in guild.members:
        if len(out) >= limit:
            break
        name       = (member.name or "").lower()
        display    = (member.display_name or "").lower()
        if not q or q in name or q in display:
            out.append({
                "user_id":  str(member.id),
                "username": member.display_name,
                "handle":   member.name,
                "avatar":   str(member.display_avatar.url) if member.display_avatar else None,
            })

    return out
# =============================================================================
# ── Wave 3 additions ── (append to api.py before the static-mount block) ─────
# =============================================================================
#
# New endpoints:
#   GET  /tickets/{ticket_id}          -- full ticket detail
#   GET  /tickets/{ticket_id}/transcript -- messages list (for inline viewer)
#   POST /tickets/{ticket_id}/reply    -- queue reply action
#   POST /tickets/{ticket_id}/close    -- queue close action


def _fetch_ticket(gid, ticket_id):
    """Fetch a ticket by id. Returns dict or None."""
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM modmail_tickets WHERE id = ? AND guild_id = ?",
            (ticket_id, gid),
        ).fetchone()
    return dict(row) if row else None


# ── GET /tickets/{ticket_id} -- full ticket detail ────────────────────────────

@app.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    ticket = _fetch_ticket(int(gid), ticket_id)
    if ticket is None:
        _err(404, f"Ticket {ticket_id} not found.")

    guild = _get_guild(gid)
    uid   = str(ticket["user_id"])
    username = _member_name(guild, uid)
    avatar = None
    if guild:
        member = guild.get_member(int(uid))
        if member and member.display_avatar:
            avatar = str(member.display_avatar.url)

    return {
        "ticket_id":       ticket["id"],
        "opener_id":       uid,
        "opener_username": username,
        "opener_avatar":   avatar,
        "channel_id":      str(ticket["channel_id"]),
        "status":          ticket["status"],
        "opened_at":       _fmt_ts(ticket.get("opened_at")),
        "closed_at":       _fmt_ts(ticket.get("closed_at")),
    }


# ── GET /tickets/{ticket_id}/transcript -- full messages list ─────────────────

@app.get("/tickets/{ticket_id}/transcript")
async def get_ticket_transcript(ticket_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    ticket = _fetch_ticket(int(gid), ticket_id)
    if ticket is None:
        _err(404, f"Ticket {ticket_id} not found.")

    messages = db.get_ticket_messages(ticket_id)

    out = []
    for m in messages:
        # direction: "in" (from user) or "out"/"to_user" (from staff)
        direction = m.get("direction", "in")
        is_staff = direction in ("out", "to_user")
        author = m.get("author_name") or ("Staff" if is_staff else f"User {m.get('author_id')}")
        if is_staff and m.get("anonymous"):
            author = "Staff"
        out.append({
            "id":        m.get("id"),
            "author":    author,
            "author_id": str(m.get("author_id", "")),
            "content":   m.get("content", ""),
            "timestamp": _fmt_ts(m.get("timestamp")),
            "is_staff":  is_staff,
            "anonymous": bool(m.get("anonymous")),
        })
    return {
        "ticket_id": ticket_id,
        "status":    ticket["status"],
        "messages":  out,
    }


# ── POST /tickets/{ticket_id}/reply -- queue reply action ─────────────────────

class TicketReply(BaseModel):
    message: str
    anonymous: bool = False


@app.post("/tickets/{ticket_id}/reply")
async def reply_to_ticket(ticket_id: int, body: TicketReply, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    ticket = _fetch_ticket(int(gid), ticket_id)
    if ticket is None:
        _err(404, f"Ticket {ticket_id} not found.")
    if (ticket.get("status") or "").lower() != "open":
        _err(400, "Ticket is not open.")
    if not body.message.strip():
        _err(400, "Reply message cannot be empty.")

    action_id = db.queue_bot_action(
        str(gid),
        "ticket_reply",
        {
            "ticket_id": ticket_id,
            "message":   body.message.strip(),
            "anonymous": bool(body.anonymous),
        },
    )
    return {"queued": True, "action_id": action_id}


# ── POST /tickets/{ticket_id}/close -- queue close action ─────────────────────

@app.post("/tickets/{ticket_id}/close")
async def close_ticket(ticket_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    ticket = _fetch_ticket(int(gid), ticket_id)
    if ticket is None:
        _err(404, f"Ticket {ticket_id} not found.")
    if (ticket.get("status") or "").lower() != "open":
        _err(400, "Ticket is already closed.")

    action_id = db.queue_bot_action(
        str(gid),
        "close_ticket",
        {"ticket_id": ticket_id},
    )
    return {"queued": True, "action_id": action_id}


# =============================================================================
# -- Autoresponses CRUD -------------------------------------------------------
# =============================================================================

class AutoResponseCreate(BaseModel):
    trigger: str
    response: str
    match_mode: str = "contains"


class AutoResponseUpdate(BaseModel):
    trigger: Optional[str] = None
    response: Optional[str] = None
    match_mode: Optional[str] = None
    enabled: Optional[bool] = None


@app.get("/autoresponses")
async def get_autoresponses(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    rows = db.get_autoresponses(gid)
    return [
        {
            "id":         r["id"],
            "trigger":    r["trigger"],
            "response":   r["response"],
            "match_mode": r.get("match_mode", "contains"),
            "enabled":    bool(r.get("enabled", 1)),
            "created_at": _fmt_ts(r.get("created_at")),
        }
        for r in rows
    ]


@app.post("/autoresponses", status_code=201)
async def create_autoresponse(body: AutoResponseCreate, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    trigger = body.trigger.strip().lower()
    response = body.response.strip()
    if not trigger or not response:
        _err(400, "Both trigger and response are required.")
    if body.match_mode not in ("contains", "exact", "startswith"):
        _err(400, "match_mode must be 'contains', 'exact', or 'startswith'.")

    try:
        ar_id = db.add_autoresponse(gid, trigger, response, body.match_mode)
    except Exception:
        _err(409, f"A trigger for '{trigger}' already exists.")

    return {"id": ar_id, "created": True}


@app.put("/autoresponses/{ar_id}")
async def update_autoresponse(ar_id: int, body: AutoResponseUpdate, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    existing = db.get_autoresponse(ar_id)
    if not existing or str(existing["guild_id"]) != str(gid):
        _err(404, f"Autoresponse #{ar_id} not found.")

    updates = {}
    if body.trigger is not None:
        updates["trigger"] = body.trigger.strip().lower()
    if body.response is not None:
        updates["response"] = body.response.strip()
    if body.match_mode is not None:
        if body.match_mode not in ("contains", "exact", "startswith"):
            _err(400, "match_mode must be 'contains', 'exact', or 'startswith'.")
        updates["match_mode"] = body.match_mode
    if body.enabled is not None:
        updates["enabled"] = 1 if body.enabled else 0

    if updates:
        db.update_autoresponse(ar_id, **updates)
    return {"id": ar_id, "updated": True}


@app.delete("/autoresponses/{ar_id}")
async def delete_autoresponse(ar_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    existing = db.get_autoresponse(ar_id)
    if not existing or str(existing["guild_id"]) != str(gid):
        _err(404, f"Autoresponse #{ar_id} not found.")
    db.delete_autoresponse(ar_id)
    return {"id": ar_id, "deleted": True}


# ── Web dashboard mount ───────────────────────────────────────────────────────
# Static file serving has moved into auth.py -> register_auth() so that
# /auth/* routes are registered BEFORE the catch-all "/" mount.
# Do not add a mount("/", ...) here.
