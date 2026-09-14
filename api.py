"""
api.py -- ModSuite v2.0 REST API
Runs alongside bot.py in the same process (uvicorn as asyncio task).
All endpoints are localhost-only; no auth required for v2.0.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel

import config
import database as db
import discord
from utils import DEFAULTS

log = logging.getLogger("ModSuite.API")

# ── Bot reference (set by bot.py before uvicorn starts) ───────────────────────

_bot = None  # type: ignore


def set_bot(bot) -> None:
    """Called by bot.py to inject the running bot instance."""
    global _bot
    _bot = bot


# ── App & CORS ────────────────────────────────────────────────────────────────

# Single source of truth for the version. The dashboard reads this from
# /health rather than hardcoding a string, which is how the Setup page ended
# up displaying v2.0.0 four releases after the fact.
VERSION = "4.1.0"
PRODUCT = "ModSuite"

app = FastAPI(title=f"{PRODUCT} API", version=VERSION)

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

    # Order matters. Starlette applies middleware outermost-first in reverse
    # registration order, so adding audit BEFORE register_auth means the auth
    # layer wraps it and request.state.actor is already set when audit reads it.
    app.add_middleware(AuditMiddleware)

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
            {"key": "reports_ch_id",    "label": "Reports Channel",  "type": "text",   "hint": "Where user-submitted reports land."},
            {"key": "modmail_cat_id",   "label": "ModMail Category", "type": "text",   "hint": "Category new ticket channels are created under."},
            {"key": "jail_cat_id",      "label": "Jail Category",    "type": "text",   "hint": "Category jail channels are created under."},
            {"key": "panel_ch_id",      "label": "Mod Panel Channel","type": "text"},
            {"key": "role_persist_enabled", "label": "Restore roles on rejoin", "type": "bool", "hint": "Saves roles on leave and reapplies them if the member comes back."},
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
    # ── Sections below were implemented in the bot from v2.5 onward but were
    # ── never added here, which is why their settings had no dashboard
    # ── presence and why PUT /config silently discarded writes to them.
    {
        "id": "automod_antiphish",
        "label": "AutoMod · Anti-Phishing",
        "description": "Checks posted URLs against the SinkingYachts phishing database.",
        "fields": [
            {"key": "antiphish_enabled", "label": "Enabled", "type": "bool",
             "hint": "Matches are removed and recorded as a violation."},
        ],
    },
    {
        "id": "automod_length",
        "label": "AutoMod · Message Length",
        "description": "Flags messages that are too long or too short. Set either to 0 to disable it.",
        "fields": [
            {"key": "max_message_length", "label": "Maximum characters (0 = off)", "type": "number", "min": 0, "max": 4000},
            {"key": "min_message_length", "label": "Minimum characters (0 = off)", "type": "number", "min": 0, "max": 500},
        ],
    },
    {
        "id": "automod_allcaps",
        "label": "AutoMod · All Caps",
        "description": "Flags messages above a percentage of uppercase characters.",
        "fields": [
            {"key": "allcaps_enabled",    "label": "Enabled",                        "type": "bool"},
            {"key": "allcaps_threshold",  "label": "Uppercase percentage to trigger","type": "number", "min": 10, "max": 100},
            {"key": "allcaps_min_length", "label": "Ignore messages shorter than",   "type": "number", "min": 1,  "max": 200,
             "hint": "Stops short exclamations from tripping the filter."},
        ],
    },
    {
        "id": "automod_slowmode",
        "label": "AutoMod · Bot Slowmode",
        "description": "Bot-enforced per-user rate limit, independent of Discord's own slowmode.",
        "fields": [
            {"key": "slowmode_enabled",  "label": "Enabled",                  "type": "bool"},
            {"key": "slowmode_seconds",  "label": "Seconds between messages", "type": "number", "min": 1, "max": 300},
            {"key": "slowmode_channels", "label": "Channel IDs (JSON array)", "type": "json_list",
             "hint": "Leave as [] to apply everywhere."},
        ],
    },
    {
        "id": "automod_wordlist",
        "label": "AutoMod · Word Lists",
        "description": "Master switch and action for the named deny lists. Manage list contents on the AutoMod page.",
        "fields": [
            {"key": "wordlist_enabled", "label": "Enabled",           "type": "bool"},
            {"key": "wordlist_action",  "label": "Action on trigger", "type": "select",
                "options": [
                    {"value": "delete", "label": "Delete only"},
                    {"value": "mute",   "label": "Delete + mute"},
                    {"value": "kick",   "label": "Delete + kick"},
                    {"value": "ban",    "label": "Delete + ban"},
                ]},
        ],
    },
    {
        "id": "violations",
        "label": "Violation Engine",
        "description": "How many AutoMod violations inside the window before a member is jailed automatically.",
        "fields": [
            {"key": "violation_jail_threshold", "label": "Violations before auto-jail", "type": "number", "min": 2, "max": 50},
            {"key": "violation_window_minutes", "label": "Counting window (minutes)",   "type": "number", "min": 5, "max": 10080},
            {"key": "violation_jail_duration",  "label": "Auto-jail duration",          "type": "text",
             "hint": "Duration string: 30m, 6h, 1d, 1w."},
            {"key": "auto_jail_duration",       "label": "Default jail duration",       "type": "text",
             "hint": "Used by /setautojail and the mod panel."},
        ],
    },
    {
        "id": "namefilter",
        "label": "Name Filter",
        "description": "Checks usernames and nicknames on join and on change.",
        "fields": [
            {"key": "name_filter_enabled",     "label": "Enabled",                       "type": "bool"},
            {"key": "name_filter_action",      "label": "Action on match",               "type": "select",
                "options": [
                    {"value": "log",  "label": "Log only"},
                    {"value": "kick", "label": "Kick"},
                    {"value": "ban",  "label": "Ban"},
                ]},
            {"key": "name_filter_words",       "label": "Blocked patterns (JSON array)", "type": "json_list"},
            {"key": "name_filter_confusables", "label": "Normalize lookalike characters","type": "bool",
             "hint": "Maps Cyrillic lookalikes, leetspeak, and fullwidth characters to ASCII before matching."},
        ],
    },
    {
        "id": "verify_gate",
        "label": "Verification Gate",
        "description": "New members must react to a posted message before receiving the gate role.",
        "fields": [
            {"key": "verify_gate_enabled",    "label": "Enabled",            "type": "bool"},
            {"key": "verify_gate_role_id",    "label": "Role granted",       "type": "text"},
            {"key": "verify_gate_channel_id", "label": "Channel",            "type": "text"},
            {"key": "verify_gate_message_id", "label": "Message ID",         "type": "text",
             "hint": "Set automatically by /verifygate post. Edit only to point at an existing message."},
            {"key": "verify_gate_emoji",      "label": "Reaction emoji",     "type": "text"},
        ],
    },
    {
        "id": "honeypot",
        "label": "Honeypot Channels",
        "description": "Any non-staff member who posts in these channels is banned immediately.",
        "fields": [
            {"key": "honeypot_channels", "label": "Channel IDs (JSON array)", "type": "json_list",
             "hint": "These should be channels no legitimate member has reason to post in."},
        ],
    },
    {
        "id": "legacy_boost",
        "label": "Legacy Booster Rewards",
        "description": "Grant a permanent role on a member's first boost, so perks survive when they stop boosting.",
        "fields": [
            {"key": "legacy_boost_enabled", "label": "Enabled", "type": "bool"},
            {"key": "legacy_boost_role", "label": "Permanent Role ID", "type": "text",
             "hint": "Not Discord's own booster role -- that one is stripped automatically. Use a separate role and hang the perks off it."},
            {"key": "legacy_boost_announce", "label": "Announcement Channel ID", "type": "text",
             "hint": "Optional. Where the thank-you post goes."},
            {"key": "legacy_boost_thanks", "label": "Thank-you message", "type": "textarea"},
        ],
    },
    {
        "id": "roster",
        "label": "Membership Roster",
        "description": "Publishes a public list of everyone holding a given role, grouped by organization.",
        "fields": [
            {"key": "roster_role_name", "label": "Role to publish", "type": "text",
             "hint": "Role name, not ID. Defaults to 'Roster'."},
            {"key": "roster_channel_name", "label": "Channel name", "type": "text",
             "hint": "Where the roster post lives. Defaults to 'roster'."},
            {"key": "roster_intro", "label": "Intro text", "type": "textarea",
             "hint": "Shown above the list. Explain what the group is and why the list is public."},
        ],
    },
    {
        "id": "tracker",
        "label": "Records Request Tracker",
        "description": "Deadline maths for public records requests. Defaults match Michigan FOIA.",
        "fields": [
            {"key": "tracker_initial_days", "label": "Business days to respond",
             "type": "number", "min": 1, "max": 90},
            {"key": "tracker_extension_days", "label": "Extension length (business days)",
             "type": "number", "min": 0, "max": 90},
            {"key": "tracker_holiday_set", "label": "Holiday calendar", "type": "select",
             "options": [{"value": "us_federal", "label": "US federal"},
                         {"value": "michigan", "label": "Michigan (adds day after Thanksgiving, Christmas Eve, NYE)"},
                         {"value": "none", "label": "None -- weekdays only"}],
             "hint": "Holidays do not count as business days. Use 'none' outside the US."},
        ],
    },
    {
        "id": "mute_modlog",
        "label": "Mute & Public Log",
        "description": "Mute-first moderation. The mute role has no 28-day cap, unlike Discord's native timeout.",
        "fields": [
            {"key": "muted_role", "label": "Muted Role ID", "type": "text",
             "hint": "Created by /mute-setup. Must sit above member roles but below the bot role."},
            {"key": "public_modlog_enabled", "label": "Post moderation publicly", "type": "bool",
             "hint": "Mutes, pulls, kicks, and bans post with a reason. Warnings stay private."},
            {"key": "public_modlog_channel", "label": "Public Mod-Log Channel", "type": "text",
             "hint": "Residents should be able to read it but not post in it."},
        ],
    },
    {
        "id": "archive",
        "label": "Message Archive",
        "description": "Forensic archive of public messages, including deleted and edited ones.",
        "fields": [
            {"key": "archive_enabled", "label": "Archive enabled", "type": "bool"},
            {"key": "archive_restore_channel", "label": "Restore Channel ID", "type": "text",
             "hint": "Where recovered deleted messages are reposted."},
            {"key": "archive_retention_days", "label": "Retention (days)", "type": "number",
             "min": 1, "max": 365,
             "hint": "Older records and their vault files are purged automatically."},
            {"key": "archive_scope", "label": "Scope", "type": "select",
             "options": [{"value": "public", "label": "Public channels only (recommended)"},
                         {"value": "all", "label": "Every channel"}],
             "hint": "'all' includes ModMail and private staff discussion, which is discoverable in litigation."},
            {"key": "archive_excluded_channels", "label": "Excluded Channel IDs", "type": "json_list"},
            {"key": "archive_excluded_categories", "label": "Excluded Category IDs", "type": "json_list"},
        ],
    },
    {
        "id": "presence",
        "label": "Bot Presence",
        "description": "What ModSuite shows as its status.",
        "fields": [
            {"key": "presence_text", "label": "Status text", "type": "text"},
            {"key": "presence_type", "label": "Activity type", "type": "select",
             "options": [{"value": "playing", "label": "Playing"},
                         {"value": "watching", "label": "Watching"},
                         {"value": "listening", "label": "Listening to"},
                         {"value": "competing", "label": "Competing in"}]},
        ],
    },
    {
        "id": "texts",
        "label": "Server Texts",
        "description": "Long-form text the bot posts. Per-DM message templates live under Bot Messages.",
        "fields": [
            {"key": "welcome_msg", "label": "Welcome message", "type": "textarea",
             "hint": "Posted when a new member joins."},
            {"key": "modmail_open_msg", "label": "ModMail opening message", "type": "textarea",
             "hint": "Shown at the top of a new ticket."},
            {"key": "selfroles_msg", "label": "Self-roles message", "type": "textarea"},
        ],
    },
    {
        "id": "selfroles_pronouns",
        "label": "Pronoun Roles",
        "description": "Role IDs used by the self-roles pronoun picker.",
        "fields": [
            {"key": "role_she_her", "label": "she/her Role ID", "type": "text"},
            {"key": "role_he_him", "label": "he/him Role ID", "type": "text"},
            {"key": "role_they_them", "label": "they/them Role ID", "type": "text"},
            {"key": "role_it_its", "label": "it/its Role ID", "type": "text"},
            {"key": "role_xe_xer", "label": "xe/xer Role ID", "type": "text"},
            {"key": "role_any_all", "label": "any/all Role ID", "type": "text"},
            {"key": "role_ask_pronouns", "label": "ask-me Role ID", "type": "text"},
            {"key": "role_dm_open", "label": "DMs open Role ID", "type": "text"},
            {"key": "role_dm_closed", "label": "DMs closed Role ID", "type": "text"},
            {"key": "role_ask_to_dm", "label": "ask-to-DM Role ID", "type": "text"},
            {"key": "color_roles", "label": "Colour Role IDs", "type": "json_list"},
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


# ── Audit middleware ──────────────────────────────────────────────────────────
# Records every state-changing dashboard request. Doing this as middleware
# rather than per-route means a route added later cannot forget to log; the
# audit trail is a property of the API surface, not of each handler.

_AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths that mutate nothing worth auditing, or that would be noisy.
_AUDIT_SKIP_PREFIXES = ("/auth/", "/health", "/word-lists/test")

# Never write these values into the audit payload.
_AUDIT_REDACT = {"token", "secret", "password", "client_secret", "api_key"}


def _audit_summary(method: str, path: str, payload: dict) -> str:
    """A short human line, so the audit page is readable without expanding JSON."""
    parts = path.strip("/").split("/")
    head = parts[0] if parts else path
    verb = {"POST": "created", "PUT": "updated",
            "PATCH": "updated", "DELETE": "deleted"}.get(method, method.lower())
    detail = ""
    for key in ("name", "title", "subject", "user_id", "reason", "slot", "body"):
        if isinstance(payload, dict) and payload.get(key):
            detail = f" -- {str(payload[key])[:80]}"
            break
    return f"{verb} {head}{detail}"


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if (request.method not in _AUDIT_METHODS
                or any(request.url.path.startswith(p) for p in _AUDIT_SKIP_PREFIXES)):
            return await call_next(request)

        # Read the body, then put it back: a Starlette request body can only be
        # consumed once, and the route handler still needs it.
        raw = await request.body()

        async def _receive():
            return {"type": "http.request", "body": raw, "more_body": False}
        request._receive = _receive

        payload: dict = {}
        try:
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    payload = {
                        k: ("[redacted]" if k.lower() in _AUDIT_REDACT else v)
                        for k, v in parsed.items()
                    }
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}

        response = await call_next(request)

        try:
            actor = _actor(request)
            # Resolve the guild without _resolve_guild_id, which raises a 503
            # when the bot is not ready. Auditing must never affect the
            # response, so an unknown guild is recorded as blank instead.
            gid = request.query_params.get("guild_id") or ""
            if not gid:
                guild = _get_guild()
                gid = str(guild.id) if guild else ""
            db.add_audit(
                guild_id=gid,
                actor_id=actor["id"],
                actor_name=actor["name"],
                method=request.method,
                path=request.url.path,
                summary=_audit_summary(request.method, request.url.path, payload),
                payload=json.dumps(payload) if payload else "",
                status=response.status_code,
                ip=(request.client.host if request.client else ""),
            )
        except Exception as e:  # auditing must never break the request
            log.warning(f"Audit write failed: {e}")

        return response


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
        "version":        VERSION,
        "product":        PRODUCT,
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
async def switch_profile(body: ProfileSwitch, request: Request,
                         guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    name = body.name.strip().lower()
    db.seed_profiles(gid)
    profile = db.get_profile(gid, name)
    if profile is None:
        _err(404, f"Profile '{name}' not found.")

    cfg = db.get_config(int(gid)) or {}
    previous = cfg.get("active_profile") or "normal"
    db.upsert_config(int(gid), active_profile=name)

    # Attributed to the logged-in staff member rather than a generic
    # "Dashboard" actor, matching the moderation endpoints.
    actor = _actor(request)
    db.add_mod_log(
        guild_id=gid,
        action="PROFILE_SWITCH",
        target_id="",
        target_username="",
        actor_id=actor["id"],
        actor_username=actor["name"],
        reason=f"AutoMod profile switched from {previous} to {name}",
    )
    return {"active": name, "previous": previous}


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
        # Media used to be dropped on relay, so historic tickets have none.
        # Prefer relayed_url: the original DM link is signed and expires.
        attachments = []
        for a in (m.get("attachments") or []):
            url = a.get("relayed_url") or a.get("url")
            fname = a.get("filename") or "file"
            ctype = a.get("content_type") or ""
            attachments.append({
                "filename": fname,
                "size": a.get("size") or 0,
                "content_type": ctype,
                "url": url,
                "is_image": ctype.startswith("image/") or fname.lower().endswith(
                    (".png", ".jpg", ".jpeg", ".gif", ".webp")),
                "spoiler": bool(a.get("spoiler")),
            })

        out.append({
            "id":        m.get("id"),
            "author":    author,
            "author_id": str(m.get("author_id", "")),
            "content":   m.get("content", ""),
            "timestamp": _fmt_ts(m.get("timestamp")),
            "is_staff":  is_staff,
            "anonymous": bool(m.get("anonymous")),
            "attachments": attachments,
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


# =============================================================================
# ── Wave 4 additions ── Streamers ────────────────────────────────────────────
# =============================================================================
#
#   GET    /streamers                          -- list, with presence flags
#   POST   /streamers                          -- register a streamer
#   PUT    /streamers/{streamer_id}            -- change Twitch username
#   DELETE /streamers/{streamer_id}            -- remove, channel and role too
#   GET    /streamers/{streamer_id}/links      -- list profile links
#   POST   /streamers/{streamer_id}/links      -- add a link
#   DELETE /streamers/{streamer_id}/links/{label}
#
# Discord-side work (creating or deleting the personal channel, granting or
# stripping the Streamer role, refreshing the pinned info card) is queued to
# bot_actions rather than performed here, because the API process holds no
# gateway connection. Database state is written immediately so the dashboard
# reflects the change without waiting on the poll interval.
#
# Every endpoint keys on the numeric user ID. None of them require the target
# to still be in the guild -- removing a departed streamer is the main reason
# this page exists.


class StreamerCreate(BaseModel):
    user_id: str
    twitch_username: str


class StreamerUpdate(BaseModel):
    twitch_username: str


class StreamerLinkCreate(BaseModel):
    label: str
    url: str


def _streamer_or_404(gid: str, streamer_id: int) -> dict:
    for row in db.get_all_streamers(gid):
        if int(row["streamer_id"]) == int(streamer_id):
            return row
    _err(404, f"Streamer #{streamer_id} not found.")


def _decorate_streamer(guild, row: dict) -> dict:
    """Attach display info and, critically, whether they are still present."""
    out = dict(row)
    member = None
    if guild is not None:
        try:
            member = guild.get_member(int(row["user_id"]))
        except Exception:
            member = None
    out["in_guild"] = member is not None
    out["display_name"] = member.display_name if member else None
    out["avatar_url"] = str(member.display_avatar.url) if member else None
    out["is_live"] = bool(row.get("is_live"))
    out["links"] = db.get_streamer_links(row["streamer_id"])

    channel_name = None
    if guild is not None and row.get("channel_id"):
        try:
            ch = guild.get_channel(int(row["channel_id"]))
            channel_name = ch.name if ch else None
        except Exception:
            pass
    out["channel_name"] = channel_name
    out["channel_missing"] = channel_name is None
    return out


@app.get("/streamers")
async def list_streamers(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    rows = db.get_all_streamers(gid)
    decorated = [_decorate_streamer(guild, r) for r in rows]
    return {
        "streamers": decorated,
        "total": len(decorated),
        # Surfaced so the page can show a "needs cleanup" banner.
        "orphaned": sum(1 for s in decorated if not s["in_guild"]),
    }


@app.post("/streamers", status_code=201)
async def create_streamer(body: StreamerCreate, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)

    user_id = str(body.user_id).strip()
    if not user_id.isdigit():
        _err(400, "user_id must be a numeric Discord user ID.")

    twitch = body.twitch_username.strip().lstrip("@")
    if not twitch:
        _err(400, "A Twitch username is required.")

    if db.get_streamer(gid, user_id):
        _err(409, "That user is already registered as a streamer.")

    existing_twitch = db.get_streamer_by_twitch(gid, twitch)
    if existing_twitch:
        _err(409, f"Twitch username '{twitch}' is already assigned to another streamer.")

    # Channel creation needs a real member for the permission overwrite, so
    # this is the one streamer operation that requires presence.
    if guild is not None and guild.get_member(int(user_id)) is None:
        _err(
            422,
            "That user is not in the server. A streamer's personal channel is "
            "created with a permission overwrite for them, so they need to "
            "join before being added.",
        )

    action_id = db.queue_bot_action(
        gid,
        "streamer_add",
        {"user_id": user_id, "twitch_username": twitch},
    )
    return {
        "queued": True,
        "action_id": action_id,
        "user_id": user_id,
        "twitch_username": twitch,
    }


@app.put("/streamers/{streamer_id}")
async def update_streamer_endpoint(streamer_id: int, body: StreamerUpdate,
                                   guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    row = _streamer_or_404(gid, streamer_id)

    twitch = body.twitch_username.strip().lstrip("@")
    if not twitch:
        _err(400, "A Twitch username is required.")

    clash = db.get_streamer_by_twitch(gid, twitch)
    if clash and int(clash["streamer_id"]) != int(streamer_id):
        _err(409, f"Twitch username '{twitch}' is already assigned to another streamer.")

    db.update_streamer(streamer_id, twitch_username=twitch)

    # Rename the channel and refresh the pinned card on the bot side.
    action_id = db.queue_bot_action(
        gid,
        "streamer_edit",
        {"user_id": str(row["user_id"]), "twitch_username": twitch},
    )
    db.add_mod_log(
        guild_id=gid,
        action="STREAMER_EDITED",
        target_id=str(row["user_id"]),
        target_username=str(row["user_id"]),
        actor_id="dashboard",
        actor_username="Dashboard",
        reason=f"Twitch: {row['twitch_username']} -> {twitch}",
    )
    return {"streamer_id": streamer_id, "twitch_username": twitch, "action_id": action_id}


@app.delete("/streamers/{streamer_id}")
async def delete_streamer_endpoint(streamer_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    row = _streamer_or_404(gid, streamer_id)
    user_id = str(row["user_id"])

    # Queue the Discord-side teardown first so the bot can still read the row
    # if it happens to poll mid-request, then clear the database.
    action_id = db.queue_bot_action(
        gid,
        "streamer_remove",
        {
            "user_id": user_id,
            "channel_id": str(row["channel_id"]) if row.get("channel_id") else None,
            "twitch_username": row["twitch_username"],
        },
    )
    db.remove_streamer(gid, user_id)
    db.add_mod_log(
        guild_id=gid,
        action="STREAMER_REMOVED",
        target_id=user_id,
        target_username=str(row["twitch_username"]),
        actor_id="dashboard",
        actor_username="Dashboard",
        reason=f"Removed via dashboard (Twitch: {row['twitch_username']})",
    )
    return {"streamer_id": streamer_id, "deleted": True, "action_id": action_id}


@app.get("/streamers/{streamer_id}/links")
async def list_streamer_links(streamer_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    _streamer_or_404(gid, streamer_id)
    return {"links": db.get_streamer_links(streamer_id)}


@app.post("/streamers/{streamer_id}/links", status_code=201)
async def add_streamer_link_endpoint(streamer_id: int, body: StreamerLinkCreate,
                                     guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    row = _streamer_or_404(gid, streamer_id)

    label = body.label.strip()
    url = body.url.strip()
    if not label or not url:
        _err(400, "Both a label and a URL are required.")
    if not url.lower().startswith(("http://", "https://")):
        _err(400, "URL must start with http:// or https://")

    existing = {l["label"].lower() for l in db.get_streamer_links(streamer_id)}
    if label.lower() in existing:
        _err(409, f"A link labelled '{label}' already exists.")

    link_id = db.add_streamer_link(streamer_id, label, url)
    db.queue_bot_action(gid, "streamer_refresh_card", {"user_id": str(row["user_id"])})
    return {"link_id": link_id, "label": label, "url": url}


@app.delete("/streamers/{streamer_id}/links/{label}")
async def delete_streamer_link_endpoint(streamer_id: int, label: str,
                                        guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    row = _streamer_or_404(gid, streamer_id)
    if not db.remove_streamer_link(streamer_id, label):
        _err(404, f"No link labelled '{label}'.")
    db.queue_bot_action(gid, "streamer_refresh_card", {"user_id": str(row["user_id"])})
    return {"streamer_id": streamer_id, "label": label, "deleted": True}


# =============================================================================
# ── Wave 5 additions ── Moderation actions ───────────────────────────────────
# =============================================================================
#
#   GET    /moderation/active            -- live mutes, jails, timed bans
#   POST   /moderation/warn              -- add a warn (DMs the user)
#   POST   /moderation/kick
#   POST   /moderation/ban               -- optional duration for a temp ban
#   POST   /moderation/unban
#   POST   /moderation/mute              -- Discord timeout
#   POST   /moderation/unmute
#   POST   /moderation/jail
#   POST   /moderation/unjail
#   DELETE /moderation/violations/{user_id}
#   GET    /bot-actions                  -- audit trail of dashboard actions
#
# Every action takes a numeric user ID, so a member who has left the server can
# still be banned, unbanned, unjailed, or have their violations cleared.
#
# Discord-side work is queued to bot_actions. The actor recorded on each action
# is the logged-in staff member from the session (see auth.py), not a generic
# "Dashboard" placeholder, so mod_logs stays a real audit trail. The bot
# re-checks permission hierarchy against that actor before executing.


# Actions that make no sense against someone who is not in the guild. Ban,
# unban, unjail, and violation clearing are deliberately absent -- those are
# exactly the cases where a departed member still needs handling.
_REQUIRES_PRESENCE = {"kick", "mute", "unmute", "jail"}

_VALID_ACTIONS = {
    "warn", "kick", "ban", "unban", "mute", "unmute", "jail", "unjail",
}


def _actor(request: Request) -> dict:
    """
    The authenticated staff member behind this request.

    Falls back to a system actor when auth is not configured -- a local
    deployment without OAuth env vars has no session to read. The fallback is
    clearly labelled so it never reads as a real person in the mod-log.
    """
    actor = getattr(request.state, "actor", None)
    if actor and actor.get("id"):
        return {
            "id": str(actor["id"]),
            "name": actor.get("username") or f"User {actor['id']}",
        }
    return {"id": "0", "name": "Dashboard (unauthenticated)"}


class ModerationAction(BaseModel):
    user_id: str
    reason: str = "No reason provided."
    duration: Optional[str] = None      # e.g. 10m, 2h, 1d -- mute, ban, jail
    delete_days: int = 0                # ban only, 0-7
    notify: bool = True                 # DM the target where applicable


def _require_user_id(raw: str) -> str:
    uid = str(raw or "").strip()
    # Accept a pasted mention as a convenience.
    if uid.startswith("<@") and uid.endswith(">"):
        uid = uid.lstrip("<@!").rstrip(">")
    if not uid.isdigit() or not (15 <= len(uid) <= 20):
        _err(400, "user_id must be a numeric Discord user ID (15-20 digits).")
    return uid


@app.post("/moderation/{action}")
async def moderation_action(action: str, body: ModerationAction, request: Request,
                            guild_id: Optional[str] = None):
    if action not in _VALID_ACTIONS:
        _err(404, f"Unknown moderation action '{action}'.")

    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    uid = _require_user_id(body.user_id)
    actor = _actor(request)

    if uid == actor["id"]:
        _err(422, "You cannot run a moderation action on yourself.")

    member = guild.get_member(int(uid)) if guild is not None else None
    if action in _REQUIRES_PRESENCE and guild is not None and member is None:
        friendly = {
            "kick": "kicked", "mute": "muted",
            "unmute": "unmuted", "jail": "jailed",
        }[action]
        _err(
            422,
            f"That user is not in the server, so they cannot be {friendly}. "
            f"Ban, unban, unjail, and clearing violations all still work on "
            f"members who have left.",
        )

    if body.delete_days and not (0 <= body.delete_days <= 7):
        _err(400, "delete_days must be between 0 and 7.")

    payload = {
        "user_id": uid,
        "reason": body.reason or "No reason provided.",
        "duration": body.duration,
        "delete_days": max(0, min(7, body.delete_days or 0)),
        "notify": bool(body.notify),
        "actor_id": actor["id"],
        "actor_name": actor["name"],
    }
    action_id = db.queue_bot_action(gid, f"mod_{action}", payload)

    log.info(
        "Queued %s on %s by %s (%s) -- action #%s",
        action, uid, actor["name"], actor["id"], action_id,
    )
    return {
        "queued": True,
        "action": action,
        "action_id": action_id,
        "user_id": uid,
        "actor": actor["name"],
    }


@app.get("/moderation/active")
async def moderation_active(guild_id: Optional[str] = None):
    """Everything currently in force: mutes, jails, and pending auto-unbans."""
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)

    def _who(user_id):
        name = _member_name(guild, str(user_id))
        return {
            "user_id": str(user_id),
            "display_name": name,
            "in_guild": name is not None,
        }

    mutes = []
    for row in db.get_all_mutes():
        if str(row.get("guild_id")) != str(gid):
            continue
        mutes.append({**_who(row["user_id"]),
                      "until": _fmt_ts(row.get("unmute_at")),
                      "reason": row.get("reason") or ""})

    jails = []
    for row in db.get_all_jails(gid):
        jails.append({**_who(row["user_id"]),
                      "reason": row.get("reason") or "",
                      "jailed_at": _fmt_ts(row.get("jailed_at")),
                      "jailed_by": row.get("jailed_by_name"),
                      "ends": _fmt_ts(row.get("jail_end_time"))})

    bans = []
    try:
        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM timed_bans WHERE guild_id = ?", (int(gid),)
            ).fetchall()
        for row in rows:
            r = dict(row)
            bans.append({**_who(r["user_id"]),
                         "until": _fmt_ts(r.get("unban_at")),
                         "reason": r.get("reason") or ""})
    except Exception as e:
        log.warning("timed_bans lookup failed: %s", e)

    return {
        "mutes": mutes,
        "jails": jails,
        "timed_bans": bans,
        "counts": {"mutes": len(mutes), "jails": len(jails), "timed_bans": len(bans)},
    }


@app.delete("/moderation/violations/{user_id}")
async def clear_violations(user_id: str, request: Request,
                           guild_id: Optional[str] = None):
    """Clear a user's violation counter. Works after they have left."""
    gid = _resolve_guild_id(guild_id)
    uid = _require_user_id(user_id)
    actor = _actor(request)

    with db.get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM violations WHERE guild_id = ? AND user_id = ?",
            (int(gid), int(uid)),
        )
        count = cur.rowcount

    db.add_mod_log(
        guild_id=gid,
        action="VIOLATIONS_CLEARED",
        target_id=uid,
        target_username=_member_name(_get_guild(gid), uid) or uid,
        actor_id=actor["id"],
        actor_username=actor["name"],
        reason=f"Cleared {count} violation(s) from the dashboard",
    )
    return {"user_id": uid, "cleared": count}


@app.get("/bot-actions")
async def list_bot_actions(guild_id: Optional[str] = None,
                           status: Optional[str] = None,
                           limit: int = Query(50, ge=1, le=200)):
    """
    Audit trail of every dashboard-initiated action, including ones that
    failed. Failures otherwise only surface in the bot log.
    """
    gid = _resolve_guild_id(guild_id)
    sql = "SELECT * FROM bot_actions WHERE guild_id = ?"
    args: list = [gid]
    if status:
        if status not in {"pending", "completed", "failed"}:
            _err(400, "status must be pending, completed, or failed.")
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY action_id DESC LIMIT ?"
    args.append(limit)

    import json as _json
    with db.get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]

    out = []
    for r in rows:
        try:
            payload = _json.loads(r["payload"])
        except Exception:
            payload = {}
        out.append({
            "action_id": r["action_id"],
            "action_type": r["action_type"],
            "status": r["status"],
            "created_at": _fmt_ts(r.get("created_at")),
            "completed_at": _fmt_ts(r.get("completed_at")),
            "target_id": payload.get("user_id"),
            "actor_name": payload.get("actor_name"),
            "reason": payload.get("reason"),
        })
    return {"actions": out, "total": len(out)}


# =============================================================================
# ── Wave 6 additions ── Word lists & severity profiles ───────────────────────
# =============================================================================
#
#   POST   /word-lists                   -- create a list
#   PUT    /word-lists/{name}            -- replace a list's words
#   POST   /word-lists/{name}/words      -- add words to a list
#   DELETE /word-lists/{name}/words/{w}  -- remove one word
#   DELETE /word-lists/{name}            -- delete a list
#   POST   /word-lists/test              -- does a sample message trip a list?
#
#   POST   /profiles                     -- create or update a custom profile
#   POST   /profiles/{name}/snapshot     -- capture current settings as a profile
#   DELETE /profiles/{name}              -- delete a custom profile
#   GET    /profiles/keys                -- overridable keys, typed for the UI
#
# GET /word-lists, GET /profiles, and PUT /profiles/active already existed and
# are unchanged apart from PUT /profiles/active now recording the staff member.
#
# Profile overrides are validated against the same OVERRIDABLE_KEYS the bot
# honours. An override on a key outside that set would be silently ignored by
# get_effective_config, so it is rejected here rather than saved as a lie.


from cogs.profiles import OVERRIDABLE_KEYS

# Keys the UI renders as a toggle rather than a number or free text.
_BOOL_KEYS = {
    "spam_enabled", "link_filter_enabled", "invite_filter_enabled",
    "wordlist_enabled", "antiphish_enabled", "slowmode_enabled",
}
_ACTION_KEYS = {"spam_action", "link_action", "invite_action"}
_TEXT_KEYS = {"violation_jail_duration"}

_RESERVED_LIST_NAMES = {"test"}   # would collide with POST /word-lists/test


class WordListCreate(BaseModel):
    list_name: str
    words: list[str] = []


class WordListWords(BaseModel):
    words: list[str]


class WordListTest(BaseModel):
    content: str


class ProfileUpsert(BaseModel):
    name: str
    overrides: dict


def _clean_words(raw: list[str]) -> list[str]:
    """
    Normalise to lowercase, strip blanks, drop duplicates, keep order.
    Matching is case-insensitive in the bot, so storing mixed case would only
    make the list harder to read without changing behaviour.
    """
    seen, out = set(), []
    for w in raw or []:
        w = str(w).strip().lower()
        if not w or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def _valid_list_name(name: str) -> str:
    n = str(name or "").strip().lower()
    if not n:
        _err(400, "A list name is required.")
    if len(n) > 64:
        _err(400, "List names must be 64 characters or fewer.")
    if n in _RESERVED_LIST_NAMES:
        _err(400, f"'{n}' is a reserved name. Pick something else.")
    return n


@app.post("/word-lists", status_code=201)
async def create_word_list_endpoint(body: WordListCreate, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    name = _valid_list_name(body.list_name)
    if db.get_word_list(gid, name):
        _err(409, f"A list named '{name}' already exists.")
    words = _clean_words(body.words)
    list_id = db.create_word_list(gid, name, words)
    return {"id": list_id, "list_name": name, "words": words, "count": len(words)}


@app.put("/word-lists/{list_name}")
async def replace_word_list(list_name: str, body: WordListWords,
                            guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    name = _valid_list_name(list_name)
    if not db.get_word_list(gid, name):
        _err(404, f"No list named '{name}'.")
    words = _clean_words(body.words)
    db.update_word_list(gid, name, words)
    return {"list_name": name, "words": words, "count": len(words)}


@app.post("/word-lists/{list_name}/words")
async def add_words(list_name: str, body: WordListWords,
                    guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    name = _valid_list_name(list_name)
    existing = db.get_word_list(gid, name)
    if not existing:
        _err(404, f"No list named '{name}'.")
    merged = _clean_words(list(existing.get("words", [])) + list(body.words or []))
    added = len(merged) - len(existing.get("words", []))
    db.update_word_list(gid, name, merged)
    return {"list_name": name, "words": merged, "added": added, "count": len(merged)}


@app.delete("/word-lists/{list_name}/words/{word}")
async def remove_word(list_name: str, word: str, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    name = _valid_list_name(list_name)
    existing = db.get_word_list(gid, name)
    if not existing:
        _err(404, f"No list named '{name}'.")
    target = str(word).strip().lower()
    words = [w for w in existing.get("words", []) if w.lower() != target]
    if len(words) == len(existing.get("words", [])):
        _err(404, f"'{target}' is not in '{name}'.")
    db.update_word_list(gid, name, words)
    return {"list_name": name, "removed": target, "count": len(words)}


@app.delete("/word-lists/{list_name}")
async def delete_word_list_endpoint(list_name: str, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    name = _valid_list_name(list_name)
    if not db.delete_word_list(gid, name):
        _err(404, f"No list named '{name}'.")
    return {"list_name": name, "deleted": True}


@app.post("/word-lists/test")
async def test_word_lists(body: WordListTest, guild_id: Optional[str] = None):
    """
    Check a sample message against every list, using the same matching rules as
    the live filter: single words match whole words only, multi-word entries
    match as substrings, everything case-insensitive.

    This exists because the filter deletes messages silently. Without a way to
    try a phrase, the only way to find out that an entry over-matches is for it
    to over-match on a real member.
    """
    gid = _resolve_guild_id(guild_id)
    import re as _re

    content = str(body.content or "")
    lowered = content.lower()
    content_words = set(_re.findall(r"\w+", lowered))

    matches = []
    for wl in db.get_all_word_lists(gid):
        for word in wl.get("words", []):
            w = str(word).lower().strip()
            if not w:
                continue
            if " " in w:
                if w in lowered:
                    matches.append({"list_name": wl["list_name"], "word": word,
                                    "kind": "phrase"})
            elif w in content_words:
                matches.append({"list_name": wl["list_name"], "word": word,
                                "kind": "word"})

    cfg = db.get_config(int(gid)) or {}
    return {
        "content": content,
        "matched": bool(matches),
        "matches": matches,
        # A match only deletes anything when the filter is actually switched on.
        "filter_enabled": bool(cfg.get("wordlist_enabled")),
        "action": cfg.get("wordlist_action") or "delete",
    }


# ── Profiles ─────────────────────────────────────────────────────────────────


@app.get("/profiles/keys")
async def get_profile_keys():
    """The keys a profile may override, typed so the UI can render them."""
    out = []
    for key in OVERRIDABLE_KEYS:
        if key in _BOOL_KEYS:
            kind = "bool"
        elif key in _ACTION_KEYS:
            kind = "action"
        elif key in _TEXT_KEYS:
            kind = "text"
        else:
            kind = "number"
        out.append({
            "key": key,
            "type": kind,
            "label": key.replace("_", " ").replace("sec", "seconds").capitalize(),
        })
    return {"keys": out,
            "actions": ["delete", "mute", "kick", "ban"]}


def _validate_overrides(overrides: dict) -> dict:
    if not isinstance(overrides, dict) or not overrides:
        _err(400, "At least one override is required.")
    allowed = set(OVERRIDABLE_KEYS)
    unknown = sorted(set(overrides) - allowed)
    if unknown:
        _err(
            400,
            "These keys are not overridable by a profile and would be ignored "
            "at runtime: " + ", ".join(unknown),
        )
    clean = {}
    for k, v in overrides.items():
        if k in _BOOL_KEYS:
            clean[k] = 1 if v in (True, 1, "1", "true", "True") else 0
        elif k in _ACTION_KEYS:
            if v not in ("delete", "mute", "kick", "ban"):
                _err(400, f"{k} must be one of: delete, mute, kick, ban.")
            clean[k] = v
        elif k in _TEXT_KEYS:
            clean[k] = str(v)
        else:
            try:
                clean[k] = int(v)
            except (TypeError, ValueError):
                _err(400, f"{k} must be a whole number.")
    return clean


@app.post("/profiles", status_code=201)
async def upsert_profile_endpoint(body: ProfileUpsert, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    db.seed_profiles(gid)

    name = str(body.name or "").strip().lower()
    if not name:
        _err(400, "A profile name is required.")
    if len(name) > 32:
        _err(400, "Profile names must be 32 characters or fewer.")

    existing = db.get_profile(gid, name)
    if existing and existing.get("built_in"):
        _err(
            409,
            f"'{name}' is a built-in profile and cannot be edited. Create a "
            f"custom profile instead so you always have a known-good baseline "
            f"to fall back to.",
        )

    overrides = _validate_overrides(body.overrides)
    db.upsert_profile(gid, name, overrides, built_in=False)
    return {"name": name, "overrides": overrides,
            "created": existing is None}


@app.post("/profiles/{name}/snapshot", status_code=201)
async def snapshot_profile(name: str, guild_id: Optional[str] = None):
    """
    Create a profile from the guild's current live settings. Easier than
    hand-entering twenty values, and it captures a working configuration you
    can return to after experimenting.
    """
    gid = _resolve_guild_id(guild_id)
    db.seed_profiles(gid)

    pname = str(name or "").strip().lower()
    if not pname:
        _err(400, "A profile name is required.")
    existing = db.get_profile(gid, pname)
    if existing and existing.get("built_in"):
        _err(409, f"'{pname}' is a built-in profile and cannot be overwritten.")

    cfg = db.get_config(int(gid))
    if cfg is None:
        _err(404, "No config for this guild. Run /setup first.")

    overrides = {}
    for key in OVERRIDABLE_KEYS:
        if key in cfg and cfg[key] is not None:
            overrides[key] = cfg[key]
    if not overrides:
        _err(422, "Nothing to snapshot -- no overridable settings are set.")

    db.upsert_profile(gid, pname, overrides, built_in=False)
    return {"name": pname, "overrides": overrides, "captured": len(overrides)}


@app.delete("/profiles/{name}")
async def delete_profile_endpoint(name: str, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    pname = str(name or "").strip().lower()

    profile = db.get_profile(gid, pname)
    if profile is None:
        _err(404, f"No profile named '{pname}'.")
    if profile.get("built_in"):
        _err(409, f"'{pname}' is built in and cannot be deleted.")

    cfg = db.get_config(int(gid)) or {}
    if (cfg.get("active_profile") or "normal") == pname:
        _err(
            409,
            f"'{pname}' is currently active. Switch to another profile before "
            f"deleting it, otherwise AutoMod would fall back to raw config "
            f"mid-flight.",
        )
    # Raid lockdown restores this profile on unlock; deleting it would strand
    # the guild on the raid profile.
    if (cfg.get("profile_before_raid") or "") == pname:
        _err(
            409,
            f"'{pname}' is the profile queued for restore after the current "
            f"raid lockdown ends. Unlock first, then delete it.",
        )

    db.delete_profile(gid, pname)
    return {"name": pname, "deleted": True}


# =============================================================================
# ── Wave 7 additions ── Starboards, reminders, react-role messages ───────────
# =============================================================================
#
# Starboards
#   GET|POST   /starboards
#   PUT|DELETE /starboards/{board_id}
#   POST       /starboards/{board_id}/emojis
#   DELETE     /starboards/{board_id}/emojis/{emoji}
#
# Reminders
#   GET    /reminders                -- guild-wide, not just one user's
#   DELETE /reminders/{reminder_id}
#
# React-role messages
#   GET    /react-messages          -- published messages with their mappings
#   GET    /react-messages/roles    -- assignable roles, for the picker
#   POST   /react-messages          -- compose and publish
#   PUT    /react-messages/{id}     -- edit and republish in place
#   DELETE /react-messages/{id}
#
# The react-role builder maps *existing* roles to emojis, which is what the
# /createreactmessage draft flow does. It is deliberately not a port of that
# flow: the Discord version needs a live draft message in a channel to render
# previews into, whereas the browser already is the preview surface. Composing
# here and publishing once skips the draft round trip entirely.
#
# Note this is distinct from POST /selfroles/categories, which *creates* brand
# new Discord roles from names. Both end up writing selfrole_categories, so the
# same reaction handler drives them.


class StarboardCreate(BaseModel):
    name: str
    channel_id: str
    threshold: int = 5
    nsfw_only: bool = False
    emojis: list[str] = ["\u2B50"]


class StarboardUpdate(BaseModel):
    channel_id: Optional[str] = None
    threshold: Optional[int] = None
    nsfw_only: Optional[bool] = None


class EmojiBody(BaseModel):
    emoji: str


class ReactRoleEntry(BaseModel):
    emoji: str
    role_id: str
    toggle: bool = False       # True = single-choice within the message


class ReactMessageCreate(BaseModel):
    title: str
    channel_id: str
    intro_text: str = ""
    roles: list[ReactRoleEntry]


class ReactMessageUpdate(BaseModel):
    title: Optional[str] = None
    intro_text: Optional[str] = None
    roles: Optional[list[ReactRoleEntry]] = None


def _channel_name(guild, channel_id) -> Optional[str]:
    if guild is None or not channel_id:
        return None
    try:
        ch = guild.get_channel(int(channel_id))
        return ch.name if ch else None
    except Exception:
        return None


# ── Starboards ───────────────────────────────────────────────────────────────


@app.get("/starboards")
async def list_starboards(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    out = []
    for b in db.get_all_starboards(gid):
        name = _channel_name(guild, b.get("channel_id"))
        out.append({
            **b,
            "nsfw_only": bool(b.get("nsfw_only")),
            "emojis": db.get_starboard_emojis(b["board_id"]),
            "channel_name": name,
            # A board pointing at a deleted channel silently stops working.
            "channel_missing": guild is not None and name is None,
            "entry_count": db.count_starboard_entries(b["board_id"]),
        })
    return {"starboards": out, "total": len(out)}


@app.post("/starboards", status_code=201)
async def create_starboard_endpoint(body: StarboardCreate,
                                    guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)

    name = str(body.name or "").strip().lower()
    if not name:
        _err(400, "A board name is required.")
    if len(name) > 32:
        _err(400, "Board names must be 32 characters or fewer.")
    if db.get_starboard(gid, name):
        _err(409, f"A board named '{name}' already exists.")

    if not str(body.channel_id).isdigit():
        _err(400, "channel_id must be a numeric channel ID.")
    if guild is not None and guild.get_channel(int(body.channel_id)) is None:
        _err(404, "That channel does not exist in this server.")

    if not (1 <= body.threshold <= 100):
        _err(400, "threshold must be between 1 and 100.")

    emojis = [e.strip() for e in (body.emojis or []) if e.strip()]
    if not emojis:
        _err(400, "At least one trigger emoji is required, otherwise the board can never fire.")

    board_id = db.create_starboard(
        gid, name, str(body.channel_id), int(body.threshold),
        1 if body.nsfw_only else 0,
    )
    for e in emojis:
        db.add_starboard_emoji(board_id, e)

    return {"board_id": board_id, "name": name, "emojis": emojis}


@app.put("/starboards/{board_id}")
async def update_starboard_endpoint(board_id: int, body: StarboardUpdate,
                                    guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    board = db.get_starboard_by_id(board_id)
    if not board or str(board["guild_id"]) != str(gid):
        _err(404, f"Starboard #{board_id} not found.")

    fields = {}
    if body.channel_id is not None:
        if not str(body.channel_id).isdigit():
            _err(400, "channel_id must be a numeric channel ID.")
        guild = _get_guild(gid)
        if guild is not None and guild.get_channel(int(body.channel_id)) is None:
            _err(404, "That channel does not exist in this server.")
        fields["channel_id"] = str(body.channel_id)
    if body.threshold is not None:
        if not (1 <= body.threshold <= 100):
            _err(400, "threshold must be between 1 and 100.")
        fields["threshold"] = int(body.threshold)
    if body.nsfw_only is not None:
        fields["nsfw_only"] = 1 if body.nsfw_only else 0

    if not fields:
        _err(400, "Nothing to update.")
    db.update_starboard(board_id, **fields)
    return {"board_id": board_id, "updated": sorted(fields)}


@app.delete("/starboards/{board_id}")
async def delete_starboard_endpoint(board_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    board = db.get_starboard_by_id(board_id)
    if not board or str(board["guild_id"]) != str(gid):
        _err(404, f"Starboard #{board_id} not found.")
    db.delete_starboard(gid, board["name"])
    # starboard_emojis and starboard_entries cascade on board_id.
    return {"board_id": board_id, "name": board["name"], "deleted": True}


@app.post("/starboards/{board_id}/emojis", status_code=201)
async def add_starboard_emoji_endpoint(board_id: int, body: EmojiBody,
                                       guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    board = db.get_starboard_by_id(board_id)
    if not board or str(board["guild_id"]) != str(gid):
        _err(404, f"Starboard #{board_id} not found.")

    emoji = str(body.emoji or "").strip()
    if not emoji:
        _err(400, "An emoji is required.")

    # One emoji drives at most one board, since get_board_for_emoji resolves
    # by emoji alone. Registering it twice would make which board wins depend
    # on row order.
    clash = db.get_board_for_emoji(gid, emoji)
    if clash and int(clash["board_id"]) != int(board_id):
        _err(409, f"{emoji} already triggers the '{clash['name']}' board.")

    if not db.add_starboard_emoji(board_id, emoji):
        _err(409, f"{emoji} is already on this board.")
    return {"board_id": board_id, "emoji": emoji,
            "emojis": db.get_starboard_emojis(board_id)}


@app.delete("/starboards/{board_id}/emojis/{emoji}")
async def remove_starboard_emoji_endpoint(board_id: int, emoji: str,
                                          guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    board = db.get_starboard_by_id(board_id)
    if not board or str(board["guild_id"]) != str(gid):
        _err(404, f"Starboard #{board_id} not found.")

    current = db.get_starboard_emojis(board_id)
    if len(current) <= 1:
        _err(
            409,
            "This is the board's only trigger emoji. Removing it would leave a "
            "board that can never fire. Add a replacement first, or delete the "
            "board.",
        )
    if not db.remove_starboard_emoji(board_id, emoji):
        _err(404, f"{emoji} is not on this board.")
    return {"board_id": board_id, "removed": emoji,
            "emojis": db.get_starboard_emojis(board_id)}


# ── Reminders ────────────────────────────────────────────────────────────────


@app.get("/reminders")
async def list_reminders(guild_id: Optional[str] = None,
                         include_fired: bool = False,
                         limit: int = Query(100, ge=1, le=500)):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    rows = db.get_guild_reminders(gid, include_fired=include_fired, limit=limit)

    out = []
    for r in rows:
        name = _member_name(guild, str(r["user_id"]))
        out.append({
            "reminder_id": r["reminder_id"],
            "user_id": str(r["user_id"]),
            "display_name": name,
            "in_guild": name is not None,
            "channel_id": str(r["channel_id"]),
            "channel_name": _channel_name(guild, r["channel_id"]),
            "message": r["message"],
            "fire_at": _fmt_ts(r.get("fire_at")),
            "created_at": _fmt_ts(r.get("created_at")),
            "fired": bool(r.get("fired")),
        })
    return {"reminders": out, "total": len(out),
            "pending": sum(1 for r in out if not r["fired"])}


@app.delete("/reminders/{reminder_id}")
async def delete_reminder_endpoint(reminder_id: int, request: Request,
                                   guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not db.delete_reminder_by_id(reminder_id, gid):
        _err(404, f"Reminder #{reminder_id} not found in this server.")
    actor = _actor(request)
    log.info("Reminder #%s cancelled by %s", reminder_id, actor["name"])
    return {"reminder_id": reminder_id, "deleted": True}


# ── React-role messages ──────────────────────────────────────────────────────


def _react_message_payload(guild, cat: dict) -> dict:
    roles = db.get_selfrole_roles(cat["category_id"])
    out_roles = []
    for r in roles:
        role_name = None
        if guild is not None and r.get("role_id"):
            try:
                role = guild.get_role(int(r["role_id"]))
                role_name = role.name if role else None
            except Exception:
                pass
        out_roles.append({
            "emoji": r.get("emoji"),
            "role_id": str(r.get("role_id")),
            "role_name": role_name,
            # A mapping pointing at a deleted role silently fails on reaction.
            "role_missing": guild is not None and role_name is None,
            "toggle": bool(r.get("toggle")),
        })
    return {
        "category_id": cat["category_id"],
        "title": cat.get("name"),
        "intro_text": cat.get("intro_text") or "",
        "channel_id": str(cat["channel_id"]) if cat.get("channel_id") else None,
        "channel_name": _channel_name(guild, cat.get("channel_id")),
        "message_id": str(cat["message_id"]) if cat.get("message_id") else None,
        "published": bool(cat.get("message_id")),
        "is_builtin": bool(cat.get("is_builtin")),
        "roles": out_roles,
    }


@app.get("/react-messages")
async def list_react_messages(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    cats = db.get_all_selfrole_categories(gid)
    return {"messages": [_react_message_payload(guild, c) for c in cats]}


@app.get("/react-messages/roles")
async def list_assignable_roles(guild_id: Optional[str] = None):
    """
    Roles the bot can actually hand out: not managed, not @everyone, and below
    the bot's own top role. Offering a role the bot cannot assign would produce
    a message that looks fine and silently fails on every reaction.
    """
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)
    if guild is None:
        _err(503, "Bot is not connected to that guild.")

    me = guild.me
    top = me.top_role.position if me and me.top_role else 0
    out = []
    for role in guild.roles:
        if role.is_default() or role.managed:
            continue
        out.append({
            "role_id": str(role.id),
            "name": role.name,
            "color": f"#{role.color.value:06X}" if role.color.value else None,
            "position": role.position,
            "assignable": role.position < top,
        })
    out.sort(key=lambda r: -r["position"])
    return {"roles": out,
            "bot_top_role_position": top,
            "assignable_count": sum(1 for r in out if r["assignable"])}


def _validate_react_roles(guild, entries: list) -> list[dict]:
    if not entries:
        _err(400, "At least one emoji-to-role mapping is required.")
    if len(entries) > 20:
        _err(400, "Discord allows at most 20 reactions on a message.")

    seen_emoji, seen_role, out = set(), set(), []
    for e in entries:
        emoji = str(e.emoji or "").strip()
        role_id = str(e.role_id or "").strip()
        if not emoji:
            _err(400, "Every mapping needs an emoji.")
        if not role_id.isdigit():
            _err(400, f"'{role_id}' is not a valid role ID.")

        # One emoji cannot mean two roles on the same message: the reaction
        # handler resolves by emoji, so the second mapping would be dead.
        if emoji in seen_emoji:
            _err(400, f"{emoji} is used more than once. Each emoji must be unique.")
        if role_id in seen_role:
            _err(400, "The same role is mapped twice. Each role must be unique.")
        seen_emoji.add(emoji)
        seen_role.add(role_id)

        if guild is not None:
            role = guild.get_role(int(role_id))
            if role is None:
                _err(404, f"Role `{role_id}` does not exist in this server.")
            if role.managed:
                _err(422, f"'{role.name}' is managed by an integration and cannot be assigned.")
            me = guild.me
            if me and role.position >= me.top_role.position:
                _err(
                    422,
                    f"'{role.name}' sits above the bot's highest role, so the bot "
                    f"cannot assign it. Move the bot's role higher in Server "
                    f"Settings, or pick a lower role.",
                )
        out.append({"emoji": emoji, "role_id": role_id,
                    "toggle": 1 if e.toggle else 0})
    return out


@app.post("/react-messages", status_code=201)
async def create_react_message(body: ReactMessageCreate,
                               guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)

    title = str(body.title or "").strip()
    if not title:
        _err(400, "A title is required.")
    if len(title) > 256:
        _err(400, "Titles must be 256 characters or fewer.")
    if len(body.intro_text or "") > 3000:
        _err(400, "Intro text must be 3000 characters or fewer.")

    if not str(body.channel_id).isdigit():
        _err(400, "channel_id must be a numeric channel ID.")
    if guild is not None and guild.get_channel(int(body.channel_id)) is None:
        _err(404, "That channel does not exist in this server.")

    roles = _validate_react_roles(guild, body.roles)

    # Any role with toggle=1 makes the whole message single-choice, matching
    # how the reaction handler reads enforcement.
    enforcement = "single" if any(r["toggle"] for r in roles) else "multi"
    cat_id = db.insert_selfrole_category(gid, title, enforcement, body.intro_text or "")
    db.update_selfrole_category(cat_id, channel_id=str(body.channel_id))

    with db.get_conn() as conn:
        for order, r in enumerate(roles):
            conn.execute(
                "INSERT INTO selfrole_roles (category_id, role_id, emoji, display_order, toggle)"
                " VALUES (?, ?, ?, ?, ?)",
                (cat_id, r["role_id"], r["emoji"], order, r["toggle"]),
            )

    action_id = db.queue_bot_action(gid, "react_publish", {
        "category_id": cat_id,
        "channel_id": str(body.channel_id),
        "title": title,
        "intro_text": body.intro_text or "",
        "roles": roles,
    })
    return {"category_id": cat_id, "queued": True, "action_id": action_id,
            "enforcement": enforcement}


@app.put("/react-messages/{category_id}")
async def update_react_message(category_id: int, body: ReactMessageUpdate,
                               guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild(gid)

    cat = db.get_selfrole_category(category_id)
    if not cat or str(cat.get("guild_id")) != str(gid):
        _err(404, f"React message #{category_id} not found.")

    updates = {}
    if body.title is not None:
        title = body.title.strip()
        if not title:
            _err(400, "Title cannot be empty.")
        updates["name"] = title
    if body.intro_text is not None:
        if len(body.intro_text) > 3000:
            _err(400, "Intro text must be 3000 characters or fewer.")
        updates["intro_text"] = body.intro_text

    roles = None
    if body.roles is not None:
        roles = _validate_react_roles(guild, body.roles)
        updates["enforcement"] = "single" if any(r["toggle"] for r in roles) else "multi"

    if updates:
        db.update_selfrole_category(category_id, **updates)

    if roles is not None:
        with db.get_conn() as conn:
            conn.execute("DELETE FROM selfrole_roles WHERE category_id = ?", (category_id,))
            for order, r in enumerate(roles):
                conn.execute(
                    "INSERT INTO selfrole_roles (category_id, role_id, emoji, display_order, toggle)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (category_id, r["role_id"], r["emoji"], order, r["toggle"]),
                )

    fresh = db.get_selfrole_category(category_id)
    action_id = db.queue_bot_action(gid, "react_publish", {
        "category_id": category_id,
        "channel_id": str(fresh.get("channel_id") or ""),
        "message_id": str(fresh.get("message_id") or ""),
        "title": fresh.get("name"),
        "intro_text": fresh.get("intro_text") or "",
        "roles": roles if roles is not None else [
            {"emoji": r["emoji"], "role_id": str(r["role_id"]),
             "toggle": 1 if r.get("toggle") else 0}
            for r in db.get_selfrole_roles(category_id)
        ],
    })
    return {"category_id": category_id, "queued": True, "action_id": action_id}


@app.delete("/react-messages/{category_id}")
async def delete_react_message(category_id: int, delete_message: bool = True,
                               guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    cat = db.get_selfrole_category(category_id)
    if not cat or str(cat.get("guild_id")) != str(gid):
        _err(404, f"React message #{category_id} not found.")
    if cat.get("is_builtin"):
        _err(403, "Built-in categories cannot be deleted.")

    action_id = None
    if delete_message and cat.get("message_id"):
        action_id = db.queue_bot_action(gid, "react_delete", {
            "channel_id": str(cat.get("channel_id") or ""),
            "message_id": str(cat.get("message_id")),
        })

    db.delete_selfrole_category(category_id)
    return {"category_id": category_id, "deleted": True, "action_id": action_id}


# ── Blueprints (v3.6) ─────────────────────────────────────────────────────────


class BlueprintSave(BaseModel):
    name: str
    data: dict
    description: str = ""


class BlueprintApply(BaseModel):
    dry_run: bool = True
    update_existing: bool = False


@app.get("/blueprints")
async def list_blueprints(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    rows = db.get_blueprints(gid)
    out = []
    for r in rows:
        data = r.get("data") or {}
        cats = data.get("categories", []) or []
        out.append({
            "name":        r["name"],
            "description": r.get("description", ""),
            "source":      r.get("source", "custom"),
            "scope":       "global" if r["guild_id"] is None else "guild",
            "roles":       len(data.get("roles", []) or []),
            "categories":  len(cats),
            "channels":    sum(len(c.get("channels", []) or []) for c in cats),
            "updated_at":  _fmt_ts(r.get("updated_at")),
        })
    return out


@app.get("/blueprints/{name}")
async def get_blueprint(name: str, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    record = db.get_blueprint(gid, name)
    if not record:
        _err(404, f"No blueprint named '{name}'.")
    return {
        "name":        record["name"],
        "description": record.get("description", ""),
        "source":      record.get("source", "custom"),
        "scope":       "global" if record["guild_id"] is None else "guild",
        "data":        record["data"],
    }


@app.put("/blueprints/{name}")
async def save_blueprint(name: str, body: BlueprintSave,
                         guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not isinstance(body.data, dict) or not body.data.get("categories"):
        _err(400, "Blueprint data must be an object with a 'categories' list.")
    body.data.setdefault("name", name)
    db.upsert_blueprint(gid, name, body.data,
                        description=body.description, source="dashboard")
    return {"name": name, "saved": True}


@app.delete("/blueprints/{name}")
async def remove_blueprint(name: str, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    ok = db.delete_blueprint(gid, name)
    if not ok:
        _err(404, f"No server-owned blueprint named '{name}'.")
    return {"name": name, "deleted": True}


@app.post("/blueprints/{name}/apply")
async def apply_blueprint(name: str, body: BlueprintApply, request: Request,
                          guild_id: Optional[str] = None):
    """
    Run a blueprint. Defaults to dry_run, so a bare POST is always safe and
    returns the plan without touching the server.
    """
    gid = _resolve_guild_id(guild_id)
    guild = _get_guild()
    if guild is None or str(guild.id) != str(gid):
        guild = _bot.get_guild(int(gid)) if _bot else None
    if guild is None:
        _err(503, "Bot is not connected to that guild yet.")

    record = db.get_blueprint(gid, name)
    if not record:
        _err(404, f"No blueprint named '{name}'.")

    from cogs.blueprint import BlueprintEngine

    engine = BlueprintEngine(guild, record["data"], dry_run=body.dry_run,
                             update_existing=body.update_existing)
    result = await engine.run()

    actor = _actor(request)
    db.add_blueprint_run(gid, name, actor["id"], actor["name"], body.dry_run,
                         result["created"], result["skipped"],
                         result["failed"], result["log"])
    if not body.dry_run:
        db.add_mod_log(
            guild_id=gid, action="BLUEPRINT", target_id=gid,
            target_username=guild.name, actor_id=actor["id"],
            actor_username=actor["name"],
            reason=(f"Applied blueprint '{name}': {result['created']} created, "
                    f"{result['skipped']} skipped, {result['failed']} failed"),
        )
    return {"name": name, "dry_run": body.dry_run, **result}


@app.post("/blueprints/export")
async def export_blueprint(save_as: str = Query(...),
                           include_permissions: bool = False,
                           guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _bot.get_guild(int(gid)) if _bot else None
    if guild is None:
        _err(503, "Bot is not connected to that guild yet.")

    from cogs.blueprint import export_guild

    data = export_guild(guild, include_permissions=include_permissions)
    data["name"] = save_as.strip().lower().replace(" ", "-")
    db.upsert_blueprint(gid, data["name"], data,
                        description=data.get("description", ""), source="export")
    return {"name": data["name"], "exported": True, "data": data}


@app.get("/blueprint-runs")
async def blueprint_runs(guild_id: Optional[str] = None, limit: int = 25):
    gid = _resolve_guild_id(guild_id)
    rows = db.get_blueprint_runs(gid, limit=limit)
    return [
        {
            "id":         r["id"],
            "blueprint":  r["blueprint"],
            "actor":      r.get("actor_name") or r.get("actor_id"),
            "dry_run":    bool(r.get("dry_run", 1)),
            "created":    r.get("created_count", 0),
            "skipped":    r.get("skipped_count", 0),
            "failed":     r.get("failed_count", 0),
            "log":        r.get("log", []),
            "timestamp":  _fmt_ts(r.get("created_at")),
        }
        for r in rows
    ]


# ── Message archive (Sentinel, v4.0) ──────────────────────────────────────────
# Every route here sits behind AuthMiddleware, which is the point of the port.
# Standalone Sentinel served the vault from a public StaticFiles mount with no
# authentication at all, so archived attachments were readable by anyone who
# knew or guessed a message ID.


@app.get("/archive")
async def archive_search(guild_id: Optional[str] = None, q: str = "",
                         author_id: str = "", channel_id: str = "",
                         deleted_only: bool = False,
                         limit: int = 100, offset: int = 0):
    gid = _resolve_guild_id(guild_id)
    rows = db.archive_search(gid, query=q, author_id=author_id,
                             channel_id=channel_id, deleted_only=deleted_only,
                             limit=min(limit, 250), offset=offset)
    return [
        {
            "id":           r["id"],
            "message_id":   r["message_id"],
            "channel":      r.get("channel_name") or r["channel_id"],
            "channel_id":   r["channel_id"],
            "author":       r.get("author_name") or r["author_id"],
            "author_id":    r["author_id"],
            "content":      r.get("content", ""),
            "attachments":  r.get("attachments", []),
            "edited":       bool(r.get("edited")),
            "edit_history": r.get("edit_history", []),
            "deleted":      bool(r.get("deleted")),
            "deleted_at":   _fmt_ts(r.get("deleted_at")),
            "timestamp":    _fmt_ts(r.get("created_at")),
        }
        for r in rows
    ]


@app.get("/archive/stats")
async def archive_stats(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    stats = db.archive_stats(gid)
    cfg = db.get_config(int(gid)) or {}
    return {
        **stats,
        "enabled":        bool(cfg.get("archive_enabled")),
        "scope":          cfg.get("archive_scope") or "public",
        "retention_days": cfg.get("archive_retention_days") or 30,
    }


@app.get("/archive/vault/{filename}")
async def archive_vault_file(filename: str):
    """
    Serve one archived attachment. Authenticated, and path-traversal guarded:
    a filename containing a separator is rejected outright rather than
    normalised, so ../ cannot walk out of the vault directory.
    """
    from fastapi.responses import FileResponse
    from pathlib import Path as _Path

    if "/" in filename or "\\" in filename or ".." in filename:
        _err(400, "Invalid filename.")

    vault_dir = _Path(os.getenv("VAULT_DIR", "vault")).resolve()
    target = (vault_dir / filename).resolve()
    if not str(target).startswith(str(vault_dir)) or not target.is_file():
        _err(404, "Not found in vault.")
    return FileResponse(str(target))


# ── Audit trail + FOIA (v4.3) ─────────────────────────────────────────────────


@app.get("/audit")
async def get_audit_log(guild_id: Optional[str] = None, actor_id: str = "",
                        path: str = "", source: str = "",
                        mutating_only: bool = False,
                        limit: int = 100, offset: int = 0):
    gid = _resolve_guild_id(guild_id)
    rows = db.get_audit(gid, actor_id=actor_id, path_like=path, source=source,
                        mutating_only=mutating_only, limit=limit, offset=offset)
    return [
        {
            "id":        r["id"],
            "actor":     r.get("actor_name") or r.get("actor_id"),
            "actor_id":  r.get("actor_id"),
            "method":    r["method"],
            "path":      r["path"],
            "summary":   r.get("summary", ""),
            "payload":   r.get("payload", ""),
            "status":    r.get("status", 0),
            "ip":        r.get("ip", ""),
            "source":    r.get("source", "dashboard"),
            "target":    r.get("target", ""),
            "mutating":  bool(r.get("mutating", 1)),
            "timestamp": _fmt_ts(r.get("created_at")),
        }
        for r in rows
    ]


@app.get("/audit/actors")
async def get_audit_actors(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    return db.audit_actors(gid)


class AuditPurge(BaseModel):
    older_than_days: int = 90


@app.post("/audit/purge")
async def purge_audit_log(body: AuditPurge):
    if body.older_than_days < 7:
        _err(400, "Audit history must be kept at least 7 days.")
    cutoff = (datetime.utcnow() - timedelta(days=body.older_than_days)).isoformat()
    return {"deleted": db.purge_audit(cutoff)}


class FOIACreate(BaseModel):
    body: str
    subject: str
    filed_date: str = ""
    notes: str = ""


class FOIAUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    fee_quoted: Optional[float] = None
    subject: Optional[str] = None
    body: Optional[str] = None


@app.get("/foia")
async def list_foia(guild_id: Optional[str] = None, open_only: bool = False):
    from cogs.foia import (_effective_due, business_days_between, _holiday_set,
                           STATUS_LABELS, CLOSED_STATUSES)
    from datetime import date

    gid = _resolve_guild_id(guild_id)
    rows = db.get_foias(gid, open_only=open_only)
    today = date.today()
    hs = _holiday_set(int(gid))
    out = []
    for r in rows:
        due = _effective_due(r)
        closed = r["status"] in CLOSED_STATUSES
        left = None if closed else business_days_between(today, due, hs)
        out.append({
            "id":            r["id"],
            "body":          r["body"],
            "subject":       r["subject"],
            "filed_date":    r["filed_date"][:10],
            "response_due":  r["response_due"][:10],
            "extended_due":  (r.get("extended_due") or "")[:10],
            "effective_due": due.isoformat(),
            "status":        r["status"],
            "status_label":  STATUS_LABELS.get(r["status"], r["status"]),
            "fee_quoted":    r.get("fee_quoted"),
            "notes":         r.get("notes", ""),
            "filed_by":      r.get("filed_by", ""),
            "days_left":     left,
            "overdue":       (left is not None and left < 0),
        })
    return out


@app.post("/foia")
async def create_foia(body: FOIACreate, guild_id: Optional[str] = None):
    from cogs.foia import (add_business_days, _days, _holiday_set,
                           INITIAL_BUSINESS_DAYS)
    from datetime import date

    gid = _resolve_guild_id(guild_id)
    try:
        filed = (date.fromisoformat(body.filed_date.strip())
                 if body.filed_date.strip() else date.today())
    except ValueError:
        _err(400, "filed_date must be YYYY-MM-DD.")
    due = add_business_days(
        filed, _days(int(gid), "tracker_initial_days", INITIAL_BUSINESS_DAYS),
        _holiday_set(int(gid)))
    fid = db.add_foia(gid, body.body.strip(), body.subject.strip(),
                      filed.isoformat(), due.isoformat(),
                      filed_by="Dashboard", notes=body.notes)
    return {"id": fid, "response_due": due.isoformat()}


@app.patch("/foia/{foia_id}")
async def patch_foia(foia_id: int, body: FOIAUpdate,
                     guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        _err(400, "Nothing to update.")
    if not db.update_foia(gid, foia_id, **fields):
        _err(404, f"No FOIA #{foia_id}.")
    return {"id": foia_id, "updated": True}


@app.post("/foia/{foia_id}/extend")
async def extend_foia(foia_id: int, guild_id: Optional[str] = None):
    from cogs.foia import (add_business_days, _days, _holiday_set,
                           EXTENSION_BUSINESS_DAYS)
    from datetime import date

    gid = _resolve_guild_id(guild_id)
    row = db.get_foia(gid, foia_id)
    if not row:
        _err(404, f"No request #{foia_id}.")
    base = date.fromisoformat(row["response_due"][:10])
    new_due = add_business_days(
        base, _days(int(gid), "tracker_extension_days", EXTENSION_BUSINESS_DAYS),
        _holiday_set(int(gid)))
    db.update_foia(gid, foia_id, extended_due=new_due.isoformat(),
                   status="extended", warned_stages="[]")
    return {"id": foia_id, "extended_due": new_due.isoformat()}


@app.delete("/foia/{foia_id}")
async def remove_foia(foia_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not db.delete_foia(gid, foia_id):
        _err(404, f"No FOIA #{foia_id}.")
    return {"id": foia_id, "deleted": True}


# ── Feeds, meetings, roster (v4.3.2) ──────────────────────────────────────────


class FeedIn(BaseModel):
    name: str
    url: str
    channel_id: str
    make_threads: bool = True
    ping_role_id: str = ""


@app.get("/feeds")
async def list_feeds(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    return [
        {**f, "make_threads": bool(f["make_threads"]),
         "enabled": bool(f["enabled"]),
         "last_checked": _fmt_ts(f.get("last_checked"))}
        for f in db.get_feeds(gid)
    ]


@app.post("/feeds")
async def create_feed(body: FeedIn, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    fid = db.add_feed(gid, body.name, body.url, body.channel_id,
                      body.make_threads, body.ping_role_id)
    return {"id": fid}


@app.patch("/feeds/{feed_id}")
async def edit_feed(feed_id: int, body: dict):
    if not db.update_feed(feed_id, **body):
        _err(404, f"No feed #{feed_id}.")
    return {"id": feed_id, "updated": True}


@app.delete("/feeds/{feed_id}")
async def drop_feed(feed_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not db.delete_feed(gid, feed_id):
        _err(404, f"No feed #{feed_id}.")
    return {"id": feed_id, "deleted": True}


@app.post("/feeds/{feed_id}/check")
async def check_feed_now(feed_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    feed = next((f for f in db.get_feeds(gid) if f["id"] == feed_id), None)
    if not feed:
        _err(404, f"No feed #{feed_id}.")
    cog = _bot.get_cog("RSS") if _bot else None
    if cog is None:
        _err(503, "Bot is not ready.")
    try:
        posted = await cog._check_feed(feed)
    except Exception as e:
        _err(400, f"Feed check failed: {e}")
    return {"id": feed_id, "posted": posted}


class MeetingIn(BaseModel):
    name: str
    channel_id: str
    schedule: dict
    meeting_time: str = "19:00"
    location: str = ""
    agenda_url: str = ""
    ping_role_id: str = ""


@app.get("/meetings")
async def list_meetings(guild_id: Optional[str] = None):
    from cogs.meetings import next_occurrence, describe
    from datetime import datetime as _dt

    gid = _resolve_guild_id(guild_id)
    now = _dt.now(timezone.utc).astimezone()
    out = []
    for m in db.get_meetings(gid):
        nxt = next_occurrence(m["schedule"], m["meeting_time"], now,
                              m.get("exceptions"))
        out.append({
            **m,
            "enabled": bool(m["enabled"]),
            "description": describe(m["schedule"], m["meeting_time"]),
            "exceptions": m.get("exceptions") or {},
            "next": nxt.isoformat() if nxt else None,
        })
    return out


@app.post("/meetings")
async def create_meeting(body: MeetingIn, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    mid = db.add_meeting(gid, body.name, body.channel_id, body.schedule,
                         body.meeting_time, body.location, body.agenda_url,
                         body.ping_role_id)
    return {"id": mid}


@app.patch("/meetings/{meeting_id}")
async def edit_meeting(meeting_id: int, body: dict,
                       guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not db.update_meeting(gid, meeting_id, **body):
        _err(404, f"No meeting #{meeting_id}.")
    return {"id": meeting_id, "updated": True}


@app.delete("/meetings/{meeting_id}")
async def drop_meeting(meeting_id: int, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not db.delete_meeting(gid, meeting_id):
        _err(404, f"No meeting #{meeting_id}.")
    return {"id": meeting_id, "deleted": True}


class RosterIn(BaseModel):
    user_id: str
    display_name: str = ""
    organization: str = ""
    role_title: str = ""
    notes: str = ""


@app.get("/roster")
async def list_roster(guild_id: Optional[str] = None):
    """
    Stored roster records joined against who actually holds the role, so the
    dashboard can show drift: members with no organization recorded, and
    records for people who no longer hold the role.
    """
    gid = _resolve_guild_id(guild_id)
    stored = {r["user_id"]: r for r in db.get_roster(gid)}

    holders = {}
    guild = _bot.get_guild(int(gid)) if _bot else None
    if guild:
        cfg = db.get_config(int(gid)) or {}
        role = discord.utils.get(
            guild.roles, name=cfg.get("roster_role_name") or "Roster")
        if role:
            holders = {str(m.id): m.display_name for m in role.members}

    out = []
    for uid, name in holders.items():
        rec = stored.get(uid, {})
        out.append({
            "user_id": uid,
            "display_name": rec.get("display_name") or name,
            "organization": rec.get("organization", ""),
            "role_title": rec.get("role_title", ""),
            "notes": rec.get("notes", ""),
            "holds_role": True,
            "needs_org": not rec.get("organization"),
        })
    for uid, rec in stored.items():
        if uid not in holders:
            out.append({**rec, "holds_role": False, "needs_org": False})
    return sorted(out, key=lambda r: (not r["holds_role"],
                                      (r.get("organization") or "zz").lower()))


@app.put("/roster")
async def save_roster_member(body: RosterIn, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    db.upsert_roster_member(gid, body.user_id, body.display_name,
                            body.organization, body.role_title, body.notes)
    return {"user_id": body.user_id, "saved": True}


@app.delete("/roster/{user_id}")
async def drop_roster_member(user_id: str, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not db.remove_roster_member(gid, user_id):
        _err(404, "No roster record for that member.")
    return {"user_id": user_id, "deleted": True}


@app.post("/roster/publish")
async def publish_roster(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _bot.get_guild(int(gid)) if _bot else None
    if guild is None:
        _err(503, "Bot is not ready.")
    cog = _bot.get_cog("Roster")
    if cog is None:
        _err(503, "Roster cog is not loaded.")
    ok = await cog.publish(guild)
    if not ok:
        _err(400, "Roster channel not found. Check Configuration → Roster.")
    _, count, missing = cog.build_embed(guild)
    return {"published": True, "members": count,
            "missing_org": [m.display_name for m in missing]}


# ── Legacy boosters (v4.1) ────────────────────────────────────────────────────


@app.get("/boosters")
async def list_boosters(guild_id: Optional[str] = None,
                        include_revoked: bool = False):
    gid = _resolve_guild_id(guild_id)
    rows = db.get_legacy_boosters(gid, include_revoked=include_revoked)
    guild = _bot.get_guild(int(gid)) if _bot else None
    out = []
    for r in rows:
        member = guild.get_member(int(r["user_id"])) if guild else None
        out.append({
            "user_id":       r["user_id"],
            "username":      (str(member) if member else r.get("username", "")),
            "first_boosted": (r.get("first_boosted") or "")[:10],
            "granted_at":    _fmt_ts(r.get("granted_at")),
            "granted_by":    r.get("granted_by", ""),
            "revoked":       bool(r.get("revoked")),
            "note":          r.get("note", ""),
            "in_server":     member is not None,
            "still_boosting": bool(member and member.premium_since),
        })
    return out


@app.post("/boosters/sync")
async def sync_boosters(guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    guild = _bot.get_guild(int(gid)) if _bot else None
    if guild is None:
        _err(503, "Bot is not ready.")
    cog = _bot.get_cog("Boosters")
    if cog is None:
        _err(503, "Booster cog is not loaded.")
    cfg = db.get_config(int(gid)) or {}
    if not cfg.get("legacy_boost_enabled"):
        _err(400, "Legacy booster rewards are not enabled.")

    new = 0
    for member in guild.premium_subscribers:
        if await cog._record_and_grant(member, cfg, "dashboard",
                                       "sync", announce=False):
            new += 1
    return {"granted": new, "currently_boosting": len(guild.premium_subscribers)}


@app.delete("/boosters/{user_id}")
async def revoke_booster(user_id: str, guild_id: Optional[str] = None):
    gid = _resolve_guild_id(guild_id)
    if not db.revoke_legacy_boost(gid, user_id, revoked_by="dashboard"):
        _err(404, "No active grant for that member.")
    return {"user_id": user_id, "revoked": True}


# ── Web dashboard mount ───────────────────────────────────────────────────────
# Static file serving has moved into auth.py -> register_auth() so that
# /auth/* routes are registered BEFORE the catch-all "/" mount.
# Do not add a mount("/", ...) here.
