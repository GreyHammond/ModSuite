import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "communitybot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Column definitions — add new columns here, migrations happen automatically ─
# Format: (column_name, sqlite_type, default_value_or_None)
GUILD_CONFIG_COLUMNS = [
    ("owner_role_id",       "INTEGER", None),
    ("mod_role_id",         "INTEGER", None),
    ("modmail_cat_id",      "INTEGER", None),
    ("modmail_ch_id",       "INTEGER", None),
    ("selfroles_ch_id",     "INTEGER", None),
    ("modlog_ch_id",        "INTEGER", None),
    ("closed_ch_id",        "INTEGER", None),
    ("selfroles_msg_id",    "INTEGER", None),
    ("panel_msg_id",        "INTEGER", None),
    ("panel_ch_id",         "INTEGER", None),
    ("jail_cat_id",         "INTEGER", None),
    ("auto_role_id",        "INTEGER", None),
    ("reports_ch_id",       "INTEGER", None),
    ("color_roles",         "TEXT",    "'{}'"),
    ("welcome_msg",         "TEXT",    "''"),
    ("selfroles_msg",       "TEXT",    "''"),
    ("modmail_open_msg",    "TEXT",    "''"),
    ("warn_mute_threshold", "INTEGER", "3"),
    ("warn_ban_threshold",  "INTEGER", "5"),
    ("raid_join_count",     "INTEGER", "10"),
    ("raid_join_seconds",   "INTEGER", "10"),
    ("setup_complete",      "INTEGER", "0"),
]


def init_db():
    with get_conn() as conn:
        # Create table if it doesn't exist
        conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY
            )
        """)

        # Migrate: add any missing columns without touching existing data
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(guild_config)")
        }
        for col_name, col_type, default in GUILD_CONFIG_COLUMNS:
            if col_name not in existing_cols:
                if default is not None:
                    conn.execute(f"ALTER TABLE guild_config ADD COLUMN {col_name} {col_type} DEFAULT {default}")
                else:
                    conn.execute(f"ALTER TABLE guild_config ADD COLUMN {col_name} {col_type}")

        # Other tables — unchanged, safe to CREATE IF NOT EXISTS
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS modmail_tickets (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                channel_id  INTEGER NOT NULL,
                opened_at   TEXT NOT NULL,
                closed_at   TEXT,
                status      TEXT DEFAULT 'open'
            );

            CREATE TABLE IF NOT EXISTS modmail_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL,
                author_id   INTEGER NOT NULL,
                author_name TEXT NOT NULL,
                content     TEXT NOT NULL,
                direction   TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                anonymous   INTEGER DEFAULT 0,
                FOREIGN KEY(ticket_id) REFERENCES modmail_tickets(id)
            );

            CREATE TABLE IF NOT EXISTS mutes (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                unmute_at   TEXT NOT NULL,
                reason      TEXT DEFAULT '',
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS warns (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                mod_id      INTEGER NOT NULL,
                mod_name    TEXT NOT NULL,
                reason      TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                active      INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS jail (
                guild_id        INTEGER NOT NULL,
                user_id         INTEGER NOT NULL,
                channel_id      INTEGER NOT NULL,
                saved_roles     TEXT NOT NULL,
                reason          TEXT DEFAULT '',
                jailed_at       TEXT NOT NULL,
                jailed_by_id    INTEGER NOT NULL,
                jailed_by_name  TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );
        """)


# ── Guild Config ──────────────────────────────────────────────────────────────

def get_config(guild_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["color_roles"] = json.loads(d["color_roles"] or "{}")
    return d


def upsert_config(guild_id: int, **kwargs):
    if "color_roles" in kwargs and isinstance(kwargs["color_roles"], dict):
        kwargs["color_roles"] = json.dumps(kwargs["color_roles"])
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT guild_id FROM guild_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            conn.execute(
                f"UPDATE guild_config SET {sets} WHERE guild_id = ?",
                (*kwargs.values(), guild_id),
            )
        else:
            kwargs["guild_id"] = guild_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            conn.execute(
                f"INSERT INTO guild_config ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )


# ── ModMail ───────────────────────────────────────────────────────────────────

def open_ticket(guild_id: int, user_id: int, channel_id: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO modmail_tickets (guild_id, user_id, channel_id, opened_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, channel_id, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_open_ticket_by_user(guild_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM modmail_tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
            (guild_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def get_open_ticket_by_channel(channel_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM modmail_tickets WHERE channel_id = ? AND status = 'open'",
            (channel_id,),
        ).fetchone()
    return dict(row) if row else None


def close_ticket(ticket_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE modmail_tickets SET status = 'closed', closed_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), ticket_id),
        )


def log_message(ticket_id: int, author_id: int, author_name: str,
                content: str, direction: str, anonymous: bool = False):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO modmail_messages (ticket_id, author_id, author_name, content, direction, timestamp, anonymous) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, author_id, author_name, content, direction, datetime.utcnow().isoformat(), int(anonymous)),
        )


def get_ticket_messages(ticket_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM modmail_messages WHERE ticket_id = ? ORDER BY id", (ticket_id,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Mutes ─────────────────────────────────────────────────────────────────────

def add_mute(guild_id: int, user_id: int, unmute_at: datetime, reason: str = ""):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO mutes (guild_id, user_id, unmute_at, reason) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, unmute_at.isoformat(), reason),
        )


def remove_mute(guild_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM mutes WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))


def get_expired_mutes(now: datetime) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM mutes WHERE unmute_at <= ?", (now.isoformat(),)
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_mutes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM mutes").fetchall()
    return [dict(r) for r in rows]


# ── Warns ─────────────────────────────────────────────────────────────────────

def add_warn(guild_id: int, user_id: int, mod_id: int, mod_name: str, reason: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO warns (guild_id, user_id, mod_id, mod_name, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, mod_id, mod_name, reason, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_warns(guild_id: int, user_id: int, active_only: bool = True) -> list[dict]:
    with get_conn() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM warns WHERE guild_id = ? AND user_id = ? AND active = 1 ORDER BY id",
                (guild_id, user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM warns WHERE guild_id = ? AND user_id = ? ORDER BY id",
                (guild_id, user_id),
            ).fetchall()
    return [dict(r) for r in rows]


def remove_warn(warn_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("UPDATE warns SET active = 0 WHERE id = ? AND active = 1", (warn_id,))
        return cur.rowcount > 0


def get_active_warn_count(guild_id: int, user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM warns WHERE guild_id = ? AND user_id = ? AND active = 1",
            (guild_id, user_id),
        ).fetchone()
    return row["cnt"] if row else 0


# ── Jail ──────────────────────────────────────────────────────────────────────

def add_jail(guild_id: int, user_id: int, channel_id: int, saved_roles: list[int],
             reason: str, jailed_by_id: int, jailed_by_name: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO jail
               (guild_id, user_id, channel_id, saved_roles, reason, jailed_at, jailed_by_id, jailed_by_name)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, user_id, channel_id, json.dumps(saved_roles),
             reason, datetime.utcnow().isoformat(), jailed_by_id, jailed_by_name),
        )


def get_jail(guild_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM jail WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["saved_roles"] = json.loads(d["saved_roles"])
    return d


def get_jail_by_channel(channel_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM jail WHERE channel_id = ?", (channel_id,)
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["saved_roles"] = json.loads(d["saved_roles"])
    return d


def remove_jail(guild_id: int, user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM jail WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
