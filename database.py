import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "communitybot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Column definitions -- add new columns here, migrations happen automatically ─
# Format: (column_name, sqlite_type, default_value_or_None)
GUILD_CONFIG_COLUMNS = [
    # ── Legacy booster rewards (v4.1) ─────────────────────────────────────────
    ("legacy_boost_enabled",  "INTEGER", "0"),
    ("legacy_boost_role",     "INTEGER", None),
    ("legacy_boost_announce", "INTEGER", None),
    ("legacy_boost_thanks",   "TEXT",    "''"),

    # ── Roster + request tracker (v4.0) ───────────────────────────────────────
    ("roster_role_name",      "TEXT", "'Roster'"),
    ("roster_channel_name",   "TEXT", "'roster'"),
    ("roster_intro",          "TEXT", "''"),
    ("tracker_initial_days",  "INTEGER", "5"),
    ("tracker_extension_days","INTEGER", "10"),
    ("tracker_holiday_set",   "TEXT", "'us_federal'"),

    # ── Mute role + public moderation log (v4.1) ──────────────────────────────
    ("muted_role",            "INTEGER", None),
    ("public_modlog_channel", "INTEGER", None),
    ("public_modlog_enabled", "INTEGER", "0"),

    # ── Archive (Sentinel, v4.0) ──────────────────────────────────────────────
    ("archive_enabled",            "INTEGER", "0"),
    ("archive_restore_channel",    "INTEGER", None),
    ("archive_retention_days",     "INTEGER", "30"),
    ("archive_scope",              "TEXT",    "'public'"),   # public | all
    ("archive_excluded_channels",  "TEXT",    "'[]'"),
    ("archive_excluded_categories","TEXT",    "'[]'"),
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
    # Referenced by /setup and the dashboard config schema since v2.0 but never
    # declared, so writes to it silently went nowhere. Auto-migration adds it
    # to existing databases on next startup with the documented 24h default.
    ("warn_mute_duration_hrs", "INTEGER", "24"),
    ("warn_ban_threshold",  "INTEGER", "5"),
    ("raid_join_count",     "INTEGER", "10"),
    ("raid_join_seconds",   "INTEGER", "10"),
    ("setup_complete",      "INTEGER", "0"),
    ("auto_jail_duration",  "TEXT",    "'1d'"),
    # Phase 2: DM preference roles
    ("role_dm_open",                 "TEXT", None),
    ("role_dm_closed",               "TEXT", None),
    ("role_ask_to_dm",               "TEXT", None),
    # Phase 2: Pronoun roles
    ("role_he_him",                  "TEXT", None),
    ("role_she_her",                 "TEXT", None),
    ("role_they_them",               "TEXT", None),
    ("role_xe_xer",                  "TEXT", None),
    ("role_it_its",                  "TEXT", None),
    ("role_any_all",                 "TEXT", None),
    ("role_ask_pronouns",            "TEXT", None),
    # Phase 2: Self-roles message IDs
    ("selfroles_dm_message_id",      "TEXT", None),
    ("selfroles_pronouns_message_id","TEXT", None),
    # v2.0 additions
    ("presence_type",   "TEXT", None),
    ("presence_text",   "TEXT", None),
    ("verified_role_id","TEXT", None),
    # ── v2.1 AutoMod additions ──
    ("automod_immune_roles",       "TEXT",    "'[]'"),   # JSON list of role IDs exempt from all automod
    # Spam detection
    ("spam_enabled",               "INTEGER", "1"),
    ("spam_msg_limit",             "INTEGER", "5"),
    ("spam_window_sec",            "INTEGER", "8"),
    ("spam_dup_limit",             "INTEGER", "3"),
    ("spam_mention_limit",         "INTEGER", "5"),
    ("spam_emoji_limit",           "INTEGER", "15"),
    ("spam_action",                "TEXT",    "'mute'"),   # delete | mute | kick | ban
    ("spam_mute_minutes",          "INTEGER", "10"),
    # Link filtering
    ("link_filter_enabled",        "INTEGER", "0"),        # off by default; opt-in
    ("link_mode",                  "TEXT",    "'whitelist'"),  # whitelist | blacklist
    ("link_whitelist",             "TEXT",
        "'[\"discord.com\",\"discord.gg\",\"youtube.com\",\"youtu.be\",\"twitter.com\",\"x.com\",\"github.com\",\"tenor.com\",\"giphy.com\"]'"),
    ("link_blacklist",             "TEXT",    "'[\"grabify.link\",\"iplogger.org\"]'"),
    ("link_action",                "TEXT",    "'delete'"),
    ("link_bypass_roles",          "TEXT",    "'[]'"),
    ("link_bypass_channels",       "TEXT",    "'[]'"),
    # Invite filtering
    ("invite_filter_enabled",      "INTEGER", "0"),
    ("invite_action",              "TEXT",    "'delete'"),
    # Raid protection upgrades
    ("raid_min_account_age_days",  "INTEGER", "0"),        # 0 = disabled
    ("raid_active_action",         "TEXT",    "'ban'"),    # kick | ban new joiners during active raid (v3.0: default ban)
    ("raid_auto_verification",     "INTEGER", "1"),        # auto-raise verification level during raid
    ("raid_lockdown_cooldown_min", "INTEGER", "5"),        # 0 = no auto-unlock
    # ── v2.5 Honeypot ──
    ("honeypot_channels",          "TEXT",    "'[]'"),   # JSON list of channel IDs that auto-ban on post
    # ── v3.0 Violation engine ──
    ("violation_jail_threshold",   "INTEGER", "5"),      # violations in window before auto-jail
    ("violation_window_minutes",   "INTEGER", "60"),     # sliding window for violation counting
    ("violation_jail_duration",    "TEXT",    "'1d'"),   # duration of auto-jail from violations
    # ── v3.0 Word list filtering ──
    ("wordlist_enabled",           "INTEGER", "0"),
    ("wordlist_action",            "TEXT",    "'delete'"),  # delete | mute | kick | ban
    # ── v3.0 Role persistence ──
    ("role_persist_enabled",       "INTEGER", "1"),      # save/restore roles on leave/rejoin
    # ── v2.7 Anti-phishing ──
    ("antiphish_enabled",          "INTEGER", "1"),      # check URLs against phishing databases
    # ── v2.7 Message length filter ──
    ("max_message_length",         "INTEGER", "0"),      # 0 = disabled; max chars before violation
    ("min_message_length",         "INTEGER", "0"),      # 0 = disabled; min chars before violation
    # ── v2.7 Per-channel slowmode ──
    ("slowmode_enabled",           "INTEGER", "0"),
    ("slowmode_seconds",           "INTEGER", "5"),      # per-user-per-channel: 1 msg every N seconds
    ("slowmode_channels",          "TEXT",    "'[]'"),   # JSON list of channel IDs; empty = all channels
    # ── v2.9 Severity profiles ──
    ("active_profile",             "TEXT",    "'normal'"),  # name of the active automod profile
    ("profile_before_raid",        "TEXT",    "''"),        # profile to restore after raid lockdown ends
    # ── v3.0 Name filtering ──
    ("name_filter_enabled",        "INTEGER", "0"),
    ("name_filter_action",         "TEXT",    "'log'"),     # log | kick | ban
    ("name_filter_words",          "TEXT",    "'[]'"),      # JSON list of blocked name patterns
    ("name_filter_confusables",    "INTEGER", "1"),         # normalize Unicode confusable chars before checking
    # ── v3.0 Verification gate ──
    ("verify_gate_enabled",        "INTEGER", "0"),
    ("verify_gate_role_id",        "INTEGER", None),        # role granted after verification
    ("verify_gate_channel_id",     "INTEGER", None),        # channel where the verify message lives
    ("verify_gate_message_id",     "INTEGER", None),        # the message to react to
    ("verify_gate_emoji",          "TEXT",    "'\\u2705'"), # emoji to react with (default: check mark)
    # ── v3.0 All-caps filter ──
    ("allcaps_enabled",            "INTEGER", "0"),
    ("allcaps_threshold",          "INTEGER", "70"),        # % of chars that are uppercase to trigger
    ("allcaps_min_length",         "INTEGER", "10"),        # min message length to check (ignore short msgs)
]

# ── Column definitions for the jail table -- auto-migration ────────────────────
JAIL_COLUMNS = [
    ("jail_end_time", "TEXT",    None),  # ISO 8601 UTC datetime; NULL = permanent jail
    ("active",        "INTEGER", "1"),   # 1 = currently jailed
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

        # Other tables -- unchanged, safe to CREATE IF NOT EXISTS
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

            CREATE TABLE IF NOT EXISTS notes (
                note_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT    NOT NULL,
                target_id   TEXT    NOT NULL,
                author_id   TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL,
                deleted     INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_notes_guild_target ON notes (guild_id, target_id);

            CREATE TABLE IF NOT EXISTS bot_messages (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT    NOT NULL,
                slot        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                UNIQUE(guild_id, slot)
            );

            CREATE TABLE IF NOT EXISTS selfrole_categories (
                category_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      TEXT    NOT NULL,
                name          TEXT    NOT NULL,
                intro_text    TEXT    NULL,
                enforcement   TEXT    NOT NULL DEFAULT 'single',
                message_id    TEXT    NULL,
                channel_id    TEXT    NULL,
                is_builtin    INTEGER NOT NULL DEFAULT 0,
                display_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS selfrole_roles (
                role_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id   INTEGER NOT NULL REFERENCES selfrole_categories(category_id),
                role_id       TEXT    NOT NULL,
                emoji         TEXT    NOT NULL,
                display_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS mod_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id        TEXT    NOT NULL,
                action          TEXT    NOT NULL,
                target_id       TEXT    NOT NULL,
                target_username TEXT,
                actor_id        TEXT,
                actor_username  TEXT,
                reason          TEXT,
                timestamp       TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_mod_logs_guild ON mod_logs (guild_id, timestamp);

            CREATE TABLE IF NOT EXISTS bot_actions (
                action_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT    NOT NULL,
                action_type  TEXT    NOT NULL,
                payload      TEXT    NOT NULL,
                status       TEXT    NOT NULL DEFAULT 'pending',
                created_at   TEXT    NOT NULL,
                completed_at TEXT    NULL
            );

            CREATE TABLE IF NOT EXISTS react_drafts (
                draft_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id          TEXT    NOT NULL,
                author_id         TEXT    NOT NULL,
                draft_message_id  TEXT    NOT NULL,
                draft_channel_id  TEXT    NOT NULL,
                target_message_id TEXT    NULL,
                target_channel_id TEXT    NULL,
                title             TEXT    NOT NULL,
                intro_text        TEXT    NOT NULL DEFAULT '',
                created_at        TEXT    NOT NULL,
                UNIQUE(guild_id)
            );

            CREATE TABLE IF NOT EXISTS react_draft_roles (
                entry_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                draft_id    INTEGER NOT NULL REFERENCES react_drafts(draft_id) ON DELETE CASCADE,
                emoji       TEXT    NOT NULL,
                role_id     TEXT    NOT NULL,
                toggle      INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS user_prefs (
                user_id   TEXT PRIMARY KEY,
                timezone  TEXT NOT NULL DEFAULT 'UTC'
            );

            CREATE TABLE IF NOT EXISTS reminders (
                reminder_id  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT    NOT NULL,
                guild_id     TEXT    NOT NULL,
                channel_id   TEXT    NOT NULL,
                message      TEXT    NOT NULL,
                fire_at      TEXT    NOT NULL,
                fired        INTEGER NOT NULL DEFAULT 0,
                created_at   TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reminders_fire_at ON reminders (fire_at, fired);

            CREATE TABLE IF NOT EXISTS softban_roles (
                guild_id      TEXT NOT NULL,
                user_id       TEXT NOT NULL,
                saved_roles   TEXT NOT NULL,
                softbanned_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS starboards (
                board_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT NOT NULL,
                name         TEXT NOT NULL,
                channel_id   TEXT NOT NULL,
                threshold    INTEGER NOT NULL DEFAULT 5,
                nsfw_only    INTEGER NOT NULL DEFAULT 0,
                UNIQUE(guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS starboard_emojis (
                emoji_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id     INTEGER NOT NULL REFERENCES starboards(board_id) ON DELETE CASCADE,
                emoji        TEXT NOT NULL,
                UNIQUE(board_id, emoji)
            );

            CREATE TABLE IF NOT EXISTS starboard_entries (
                entry_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                board_id          INTEGER NOT NULL REFERENCES starboards(board_id) ON DELETE CASCADE,
                source_message_id TEXT NOT NULL,
                source_channel_id TEXT NOT NULL,
                board_message_id  TEXT NOT NULL,
                original_content  TEXT NOT NULL DEFAULT '',
                created_at        TEXT NOT NULL,
                UNIQUE(board_id, source_message_id)
            );

            CREATE TABLE IF NOT EXISTS streamers (
                streamer_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id        TEXT NOT NULL,
                user_id         TEXT NOT NULL,
                twitch_username TEXT NOT NULL,
                platform        TEXT NOT NULL DEFAULT 'twitch',
                channel_id      TEXT NOT NULL,
                is_live         INTEGER NOT NULL DEFAULT 0,
                stream_title    TEXT NOT NULL DEFAULT '',
                stream_game     TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL,
                UNIQUE(guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS streamer_links (
                link_id     INTEGER PRIMARY KEY AUTOINCREMENT,
                streamer_id INTEGER NOT NULL REFERENCES streamers(streamer_id) ON DELETE CASCADE,
                label       TEXT NOT NULL,
                url         TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS violations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                name        TEXT    NOT NULL,
                trigger     TEXT    NOT NULL DEFAULT '',
                created_at  TEXT    NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_violations_guild_user ON violations (guild_id, user_id, name, created_at);

            CREATE TABLE IF NOT EXISTS member_roles (
                guild_id    TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                saved_roles TEXT NOT NULL,
                saved_at    TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS timed_bans (
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                unban_at    TEXT    NOT NULL,
                reason      TEXT    DEFAULT '',
                banned_by   TEXT    DEFAULT '',
                PRIMARY KEY (guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS word_lists (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT    NOT NULL,
                list_name   TEXT    NOT NULL,
                words       TEXT    NOT NULL DEFAULT '[]',
                UNIQUE(guild_id, list_name)
            );

            CREATE TABLE IF NOT EXISTS automod_profiles (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT    NOT NULL,
                name        TEXT    NOT NULL,
                overrides   TEXT    NOT NULL DEFAULT '{}',
                built_in    INTEGER NOT NULL DEFAULT 0,
                UNIQUE(guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS autoresponses (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT    NOT NULL,
                trigger     TEXT    NOT NULL,
                response    TEXT    NOT NULL,
                enabled     INTEGER NOT NULL DEFAULT 1,
                match_mode  TEXT    NOT NULL DEFAULT 'contains',
                created_at  TEXT    NOT NULL,
                UNIQUE(guild_id, trigger)
            );

            CREATE TABLE IF NOT EXISTS rss_feeds (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT    NOT NULL,
                name         TEXT    NOT NULL,
                url          TEXT    NOT NULL,
                channel_id   TEXT    NOT NULL,
                make_threads INTEGER NOT NULL DEFAULT 1,
                ping_role_id TEXT    NOT NULL DEFAULT '',
                enabled      INTEGER NOT NULL DEFAULT 1,
                last_checked TEXT,
                last_error   TEXT    NOT NULL DEFAULT '',
                created_at   TEXT    NOT NULL,
                UNIQUE(guild_id, url)
            );

            CREATE TABLE IF NOT EXISTS rss_posted (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_id   INTEGER NOT NULL,
                guid      TEXT    NOT NULL,
                title     TEXT    NOT NULL DEFAULT '',
                posted_at TEXT    NOT NULL,
                UNIQUE(feed_id, guid)
            );

            CREATE TABLE IF NOT EXISTS meetings (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT    NOT NULL,
                name         TEXT    NOT NULL,
                channel_id   TEXT    NOT NULL,
                schedule     TEXT    NOT NULL DEFAULT '{}',
                meeting_time TEXT    NOT NULL DEFAULT '19:00',
                location     TEXT    NOT NULL DEFAULT '',
                agenda_url   TEXT    NOT NULL DEFAULT '',
                ping_role_id TEXT    NOT NULL DEFAULT '',
                enabled      INTEGER NOT NULL DEFAULT 1,
                last_fired   TEXT    NOT NULL DEFAULT '',
                exceptions   TEXT    NOT NULL DEFAULT '{}',
                created_at   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS legacy_boosters (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      TEXT    NOT NULL,
                user_id       TEXT    NOT NULL,
                username      TEXT    NOT NULL DEFAULT '',
                first_boosted TEXT,
                granted_at    TEXT    NOT NULL,
                granted_by    TEXT    NOT NULL DEFAULT 'auto',
                revoked       INTEGER NOT NULL DEFAULT 0,
                revoked_at    TEXT,
                revoked_by    TEXT    NOT NULL DEFAULT '',
                note          TEXT    NOT NULL DEFAULT '',
                UNIQUE(guild_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_legacy_boost_guild
                ON legacy_boosters(guild_id, revoked);

            CREATE TABLE IF NOT EXISTS roster_members (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id     TEXT    NOT NULL,
                user_id      TEXT    NOT NULL,
                display_name TEXT    NOT NULL DEFAULT '',
                organization TEXT    NOT NULL DEFAULT '',
                role_title   TEXT    NOT NULL DEFAULT '',
                notes        TEXT    NOT NULL DEFAULT '',
                added_at     TEXT    NOT NULL,
                UNIQUE(guild_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT    NOT NULL DEFAULT '',
                actor_id    TEXT    NOT NULL DEFAULT '',
                actor_name  TEXT    NOT NULL DEFAULT '',
                method      TEXT    NOT NULL,
                path        TEXT    NOT NULL,
                summary     TEXT    NOT NULL DEFAULT '',
                payload     TEXT    NOT NULL DEFAULT '',
                status      INTEGER NOT NULL DEFAULT 0,
                ip          TEXT    NOT NULL DEFAULT '',
                source      TEXT    NOT NULL DEFAULT 'dashboard',
                target      TEXT    NOT NULL DEFAULT '',
                mutating    INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_guild_time
                ON audit_log(guild_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_actor
                ON audit_log(actor_id);

            CREATE TABLE IF NOT EXISTS foia_requests (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id        TEXT    NOT NULL,
                body            TEXT    NOT NULL,
                subject         TEXT    NOT NULL,
                filed_date      TEXT    NOT NULL,
                response_due    TEXT    NOT NULL,
                extended_due    TEXT,
                status          TEXT    NOT NULL DEFAULT 'filed',
                fee_quoted      REAL,
                notes           TEXT    NOT NULL DEFAULT '',
                filed_by        TEXT    NOT NULL DEFAULT '',
                warned_stages   TEXT    NOT NULL DEFAULT '[]',
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_foia_guild_status
                ON foia_requests(guild_id, status);

            CREATE TABLE IF NOT EXISTS message_archive (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      TEXT    NOT NULL,
                channel_id    TEXT    NOT NULL,
                channel_name  TEXT    NOT NULL DEFAULT '',
                message_id    TEXT    NOT NULL,
                author_id     TEXT    NOT NULL,
                author_name   TEXT    NOT NULL DEFAULT '',
                content       TEXT    NOT NULL DEFAULT '',
                attachments   TEXT    NOT NULL DEFAULT '[]',
                edited        INTEGER NOT NULL DEFAULT 0,
                edit_history  TEXT    NOT NULL DEFAULT '[]',
                deleted       INTEGER NOT NULL DEFAULT 0,
                deleted_at    TEXT,
                created_at    TEXT    NOT NULL,
                UNIQUE(message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_archive_guild_time
                ON message_archive(guild_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_archive_author
                ON message_archive(guild_id, author_id);
            CREATE INDEX IF NOT EXISTS idx_archive_deleted
                ON message_archive(guild_id, deleted);

            CREATE TABLE IF NOT EXISTS blueprints (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id    TEXT,
                name        TEXT    NOT NULL,
                description TEXT    NOT NULL DEFAULT '',
                data        TEXT    NOT NULL,
                source      TEXT    NOT NULL DEFAULT 'custom',
                created_at  TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL,
                UNIQUE(guild_id, name)
            );

            CREATE TABLE IF NOT EXISTS blueprint_runs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id      TEXT    NOT NULL,
                blueprint     TEXT    NOT NULL,
                actor_id      TEXT    NOT NULL,
                actor_name    TEXT    NOT NULL DEFAULT '',
                dry_run       INTEGER NOT NULL DEFAULT 1,
                created_count INTEGER NOT NULL DEFAULT 0,
                skipped_count INTEGER NOT NULL DEFAULT 0,
                failed_count  INTEGER NOT NULL DEFAULT 0,
                log           TEXT    NOT NULL DEFAULT '[]',
                created_at    TEXT    NOT NULL
            );
        """)

        # Migrate modmail_messages -- add attachments column if missing.
        # Media sent through ModMail used to be dropped entirely; this column
        # stores a JSON list of {filename, size, content_type, url, relayed_url}
        # so attachments survive into the transcript.
        existing_mm_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(modmail_messages)")
        }
        if "attachments" not in existing_mm_cols:
            conn.execute(
                "ALTER TABLE modmail_messages ADD COLUMN attachments TEXT NOT NULL DEFAULT '[]'"
            )

        # Migrate selfrole_roles -- add toggle column if missing
        existing_sr_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(selfrole_roles)")
        }
        if "toggle" not in existing_sr_cols:
            conn.execute("ALTER TABLE selfrole_roles ADD COLUMN toggle INTEGER NOT NULL DEFAULT 0")

        # Migrate meetings -- exceptions column added in 4.3.7
        existing_mtg_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(meetings)")
        }
        if "exceptions" not in existing_mtg_cols:
            conn.execute(
                "ALTER TABLE meetings ADD COLUMN exceptions TEXT NOT NULL DEFAULT '{}'"
            )

        # Migrate audit_log -- columns added in 4.3.1 for Discord-side logging
        existing_audit_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(audit_log)")
        }
        for col, decl in (("source", "TEXT NOT NULL DEFAULT 'dashboard'"),
                          ("target", "TEXT NOT NULL DEFAULT ''"),
                          ("mutating", "INTEGER NOT NULL DEFAULT 1")):
            if col not in existing_audit_cols:
                conn.execute(f"ALTER TABLE audit_log ADD COLUMN {col} {decl}")

        # Migrate streamers -- add platform column. Existing rows are Twitch,
        # which is all the table could hold before multi-platform support.
        existing_st_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(streamers)")
        }
        if "platform" not in existing_st_cols:
            conn.execute(
                "ALTER TABLE streamers ADD COLUMN platform TEXT NOT NULL DEFAULT 'twitch'"
            )

        # Migrate jail table -- add new columns without touching existing data
        existing_jail_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(jail)")
        }
        for col_name, col_type, default in JAIL_COLUMNS:
            if col_name not in existing_jail_cols:
                if default is not None:
                    conn.execute(f"ALTER TABLE jail ADD COLUMN {col_name} {col_type} DEFAULT {default}")
                else:
                    conn.execute(f"ALTER TABLE jail ADD COLUMN {col_name} {col_type}")


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
                content: str, direction: str, anonymous: bool = False,
                attachments: "list[dict] | None" = None):
    """
    Record a ModMail message.

    `attachments` is a list of dicts describing any files on the message:
    {filename, size, content_type, url, relayed_url}. `url` is the original
    (which expires), `relayed_url` points at the copy the bot re-uploaded into
    the ticket channel.
    """
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO modmail_messages (ticket_id, author_id, author_name, content, direction, timestamp, anonymous, attachments) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, author_id, author_name, content, direction,
             datetime.utcnow().isoformat(), int(anonymous),
             json.dumps(attachments or [])),
        )


def get_ticket_messages(ticket_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM modmail_messages WHERE ticket_id = ? ORDER BY id", (ticket_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["attachments"] = json.loads(d.get("attachments") or "[]")
        except (TypeError, ValueError):
            d["attachments"] = []
        out.append(d)
    return out


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
             reason: str, jailed_by_id: int, jailed_by_name: str,
             jail_end_time: "datetime | None" = None):
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO jail
               (guild_id, user_id, channel_id, saved_roles, reason, jailed_at,
                jailed_by_id, jailed_by_name, jail_end_time, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (guild_id, user_id, channel_id, json.dumps(saved_roles),
             reason, datetime.utcnow().isoformat(), jailed_by_id, jailed_by_name,
             jail_end_time.isoformat() if jail_end_time else None),
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


def get_expired_jails(now: datetime) -> list[dict]:
    """Return all active temp-jails whose jail_end_time has passed."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jail WHERE jail_end_time IS NOT NULL AND jail_end_time <= ? AND active = 1",
            (now.isoformat(),),
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["saved_roles"] = json.loads(d["saved_roles"])
        result.append(d)
    return result


# ── Notes ─────────────────────────────────────────────────────────────────────

def add_note(guild_id: int, target_id: int, author_id: int, content: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notes (guild_id, target_id, author_id, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, target_id, author_id, content, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_notes(guild_id: int, target_id: int, active_only: bool = True) -> list[dict]:
    with get_conn() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM notes WHERE guild_id = ? AND target_id = ? AND deleted = 0 ORDER BY note_id",
                (guild_id, target_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notes WHERE guild_id = ? AND target_id = ? ORDER BY note_id",
                (guild_id, target_id),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_note(note_id: int) -> bool:
    """Soft-delete a note. Returns True if a row was updated."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE notes SET deleted = 1 WHERE note_id = ? AND deleted = 0", (note_id,)
        )
        return cur.rowcount > 0


def get_note_by_id(note_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM notes WHERE note_id = ?", (note_id,)).fetchone()
    return dict(row) if row else None


# ── Bot Messages ──────────────────────────────────────────────────────────────

def get_bot_message_content(guild_id: str, slot: str) -> str | None:
    """Return the custom content for a slot, or None if no row exists."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT content FROM bot_messages WHERE guild_id = ? AND slot = ?",
            (guild_id, slot),
        ).fetchone()
    return row["content"] if row else None


def seed_bot_messages(guild_id: str, defaults: dict) -> list[str]:
    """
    Insert a default row for every slot that is not yet present.
    Returns a list of slot names that were newly inserted (for warning logs).
    """
    seeded: list[str] = []
    with get_conn() as conn:
        for slot, content in defaults.items():
            cur = conn.execute(
                "INSERT OR IGNORE INTO bot_messages (guild_id, slot, content) VALUES (?, ?, ?)",
                (guild_id, slot, content),
            )
            if cur.rowcount > 0:
                seeded.append(slot)
    return seeded


# ── Self-Role Categories ──────────────────────────────────────────────────────

# Emoji → guild_config key mappings used when migrating the three built-in
# categories from the old guild_config columns into selfrole_categories/roles.
_MIGRATE_DM_PREFS: dict[str, str] = {
    "✅": "role_dm_open",
    "🚫": "role_dm_closed",
    "❓": "role_ask_to_dm",
}
_MIGRATE_PRONOUNS: dict[str, str] = {
    "🔵": "role_he_him",
    "🔴": "role_she_her",
    "🟣": "role_they_them",
    "🟡": "role_xe_xer",
    "🟢": "role_it_its",
    "🌈": "role_any_all",
    "💬": "role_ask_pronouns",
}


def get_selfrole_category_by_message(guild_id: str, message_id: str) -> dict | None:
    """Return the category row whose message_id matches, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM selfrole_categories WHERE guild_id = ? AND message_id = ?",
            (guild_id, message_id),
        ).fetchone()
    return dict(row) if row else None


def get_selfrole_roles(category_id: int) -> list[dict]:
    """Return all role rows for a category, ordered by display_order."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM selfrole_roles WHERE category_id = ? ORDER BY display_order",
            (category_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def migrate_builtin_selfrole_categories(guild_id: int):
    """
    On startup: check whether the three built-in categories (Colors, DM Prefs,
    Pronouns) already exist in selfrole_categories for this guild.  If any are
    missing, insert them -- and their roles -- from the data already stored in
    guild_config.  Does nothing when no config exists yet (fresh install before
    /setup has run).

    The old guild_config columns are intentionally left in place for backward
    compatibility; selfrole_categories is the source of truth going forward.
    """
    cfg = get_config(guild_id)
    if cfg is None:
        return

    guild_id_str = str(guild_id)
    ch_id_str    = str(cfg["selfroles_ch_id"]) if cfg.get("selfroles_ch_id") else None

    with get_conn() as conn:
        existing_names = {
            row[0] for row in conn.execute(
                "SELECT name FROM selfrole_categories WHERE guild_id = ?",
                (guild_id_str,),
            )
        }

        def _insert_category(name: str, enforcement: str, message_id, order: int) -> int:
            cur = conn.execute(
                """INSERT INTO selfrole_categories
                   (guild_id, name, enforcement, message_id, channel_id, is_builtin, display_order)
                   VALUES (?, ?, ?, ?, ?, 1, ?)""",
                (guild_id_str, name, enforcement,
                 str(message_id) if message_id else None,
                 ch_id_str, order),
            )
            return cur.lastrowid

        def _insert_roles(category_id: int, pairs):
            for order, (emoji, role_id) in enumerate(pairs):
                conn.execute(
                    "INSERT INTO selfrole_roles (category_id, role_id, emoji, display_order)"
                    " VALUES (?, ?, ?, ?)",
                    (category_id, str(role_id), emoji, order),
                )

        # ── Colors ────────────────────────────────────────────────────────────
        if "Colors" not in existing_names:
            cat_id = _insert_category(
                "Colors", "single", cfg.get("selfroles_msg_id"), 0
            )
            color_roles: dict = cfg.get("color_roles") or {}
            if color_roles:
                _insert_roles(cat_id, color_roles.items())

        # ── DM Prefs ──────────────────────────────────────────────────────────
        if "DM Prefs" not in existing_names:
            cat_id = _insert_category(
                "DM Prefs", "single", cfg.get("selfroles_dm_message_id"), 1
            )
            pairs = [
                (emoji, cfg[cfg_key])
                for emoji, cfg_key in _MIGRATE_DM_PREFS.items()
                if cfg.get(cfg_key)
            ]
            if pairs:
                _insert_roles(cat_id, pairs)

        # ── Pronouns ──────────────────────────────────────────────────────────
        if "Pronouns" not in existing_names:
            cat_id = _insert_category(
                "Pronouns", "multi", cfg.get("selfroles_pronouns_message_id"), 2
            )
            pairs = [
                (emoji, cfg[cfg_key])
                for emoji, cfg_key in _MIGRATE_PRONOUNS.items()
                if cfg.get(cfg_key)
            ]
            if pairs:
                _insert_roles(cat_id, pairs)

# ── Mod Logs ──────────────────────────────────────────────────────────────────

def add_mod_log(guild_id: str, action: str, target_id: str,
                reason: str = "", actor_id: str = "", actor_username: str = "",
                target_username: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO mod_logs
               (guild_id, action, target_id, target_username, actor_id, actor_username, reason, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, action, target_id, target_username or None,
             actor_id or None, actor_username or None,
             reason or None, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_mod_logs(guild_id: str, action: str = "",
                 limit: int = 50, offset: int = 0) -> tuple[int, list[dict]]:
    """Returns (total_count, rows)."""
    with get_conn() as conn:
        where = "WHERE guild_id = ?"
        params: list = [guild_id]
        if action:
            where += " AND action = ?"
            params.append(action)
        total = conn.execute(
            f"SELECT COUNT(*) FROM mod_logs {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM mod_logs {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return total, [dict(r) for r in rows]


# ── Bot Actions ───────────────────────────────────────────────────────────────

def queue_bot_action(guild_id: str, action_type: str, payload: dict) -> int:
    import json as _json
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO bot_actions (guild_id, action_type, payload, created_at)
               VALUES (?, ?, ?, ?)""",
            (guild_id, action_type, _json.dumps(payload), datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_pending_actions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bot_actions WHERE status = 'pending' ORDER BY action_id"
        ).fetchall()
    return [dict(r) for r in rows]


def complete_action(action_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE bot_actions SET status = 'completed', completed_at = ? WHERE action_id = ?",
            (datetime.utcnow().isoformat(), action_id),
        )


def fail_action(action_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE bot_actions SET status = 'failed', completed_at = ? WHERE action_id = ?",
            (datetime.utcnow().isoformat(), action_id),
        )


# ── Selfrole helpers needed by api.py ─────────────────────────────────────────

def get_all_selfrole_categories(guild_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM selfrole_categories WHERE guild_id = ? ORDER BY display_order",
            (guild_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_selfrole_category(category_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM selfrole_categories WHERE category_id = ?", (category_id,)
        ).fetchone()
    return dict(row) if row else None


def insert_selfrole_category(guild_id: str, name: str, enforcement: str,
                              intro_text: str | None) -> int:
    with get_conn() as conn:
        # put custom categories after builtins
        max_order = conn.execute(
            "SELECT COALESCE(MAX(display_order), -1) FROM selfrole_categories WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()[0]
        cur = conn.execute(
            """INSERT INTO selfrole_categories
               (guild_id, name, intro_text, enforcement, is_builtin, display_order)
               VALUES (?, ?, ?, ?, 0, ?)""",
            (guild_id, name, intro_text, enforcement, max_order + 1),
        )
        return cur.lastrowid


def update_selfrole_category(category_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE selfrole_categories SET {sets} WHERE category_id = ?",
            (*kwargs.values(), category_id),
        )


def delete_selfrole_category(category_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM selfrole_roles WHERE category_id = ?", (category_id,))
        conn.execute("DELETE FROM selfrole_categories WHERE category_id = ?", (category_id,))


# ── Warns helpers (additional) ─────────────────────────────────────────────────

def get_all_warns(guild_id: str, target_id: str = "",
                  active_only: bool = True,
                  limit: int = 50, offset: int = 0) -> tuple[int, list[dict]]:
    """Returns (total_count, rows)."""
    with get_conn() as conn:
        where = "WHERE guild_id = ?"
        params: list = [guild_id]
        if target_id:
            where += " AND user_id = ?"
            params.append(target_id)
        if active_only:
            where += " AND active = 1"
        total = conn.execute(
            f"SELECT COUNT(*) FROM warns {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM warns {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return total, [dict(r) for r in rows]


def get_warn_by_id(warn_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM warns WHERE id = ?", (warn_id,)).fetchone()
    return dict(row) if row else None


# ── Jail helpers (additional) ──────────────────────────────────────────────────

def get_all_jails(guild_id: str, active_only: bool = True) -> list[dict]:
    with get_conn() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT rowid as jail_id, * FROM jail WHERE guild_id = ? AND active = 1",
                (guild_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT rowid as jail_id, * FROM jail WHERE guild_id = ?",
                (guild_id,),
            ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        if "saved_roles" in d:
            import json as _json
            try:
                d["saved_roles"] = _json.loads(d["saved_roles"])
            except Exception:
                pass
        result.append(d)
    return result


# ── Ticket helpers (additional) ────────────────────────────────────────────────

def get_all_tickets(guild_id: str, status: str = "open") -> list[dict]:
    with get_conn() as conn:
        if status == "all":
            rows = conn.execute(
                """SELECT t.*, COUNT(m.id) as message_count
                   FROM modmail_tickets t
                   LEFT JOIN modmail_messages m ON m.ticket_id = t.id
                   WHERE t.guild_id = ?
                   GROUP BY t.id ORDER BY t.id DESC""",
                (guild_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT t.*, COUNT(m.id) as message_count
                   FROM modmail_tickets t
                   LEFT JOIN modmail_messages m ON m.ticket_id = t.id
                   WHERE t.guild_id = ? AND t.status = ?
                   GROUP BY t.id ORDER BY t.id DESC""",
                (guild_id, status),
            ).fetchall()
    return [dict(r) for r in rows]


# ── Notes helpers (additional) ─────────────────────────────────────────────────

def get_all_notes(guild_id: str, target_id: str = "") -> list[dict]:
    with get_conn() as conn:
        if target_id:
            rows = conn.execute(
                "SELECT * FROM notes WHERE guild_id = ? AND target_id = ? AND deleted = 0 ORDER BY note_id",
                (guild_id, target_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notes WHERE guild_id = ? AND deleted = 0 ORDER BY note_id",
                (guild_id,),
            ).fetchall()
    return [dict(r) for r in rows]


# ── Bot Message helpers (slash command access) ────────────────────────────────

def upsert_bot_message(guild_id: str, slot: str, content: str) -> None:
    """Insert or update a custom message slot."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO bot_messages (guild_id, slot, content) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, slot) DO UPDATE SET content = excluded.content",
            (guild_id, slot, content),
        )


def delete_bot_message(guild_id: str, slot: str) -> None:
    """Delete a custom message slot so it falls back to the default."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM bot_messages WHERE guild_id = ? AND slot = ?",
            (guild_id, slot),
        )


def get_all_bot_messages(guild_id: str) -> dict:
    """Return all stored custom message slots for a guild as {slot: content}."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT slot, content FROM bot_messages WHERE guild_id = ?",
            (guild_id,),
        ).fetchall()
    return {row["slot"]: row["content"] for row in rows}


# ── React Draft helpers ────────────────────────────────────────────────────────

def get_draft(guild_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM react_drafts WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    return dict(row) if row else None


def create_draft(guild_id: str, author_id: str, draft_message_id: str,
                 draft_channel_id: str, target_message_id: str | None,
                 target_channel_id: str | None, title: str, intro_text: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO react_drafts
               (guild_id, author_id, draft_message_id, draft_channel_id,
                target_message_id, target_channel_id, title, intro_text, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (guild_id, author_id, draft_message_id, draft_channel_id,
             target_message_id, target_channel_id, title, intro_text,
             datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def update_draft(guild_id: str, **kwargs) -> None:
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE react_drafts SET {sets} WHERE guild_id = ?",
            (*kwargs.values(), guild_id),
        )


def delete_draft(guild_id: str) -> None:
    with get_conn() as conn:
        # ON DELETE CASCADE will clean react_draft_roles automatically
        conn.execute("DELETE FROM react_drafts WHERE guild_id = ?", (guild_id,))


def get_draft_roles(draft_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM react_draft_roles WHERE draft_id = ? ORDER BY entry_id",
            (draft_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def add_draft_role(draft_id: int, emoji: str, role_id: str, toggle: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO react_draft_roles (draft_id, emoji, role_id, toggle) VALUES (?, ?, ?, ?)",
            (draft_id, emoji, role_id, toggle),
        )


def remove_draft_role(draft_id: int, emoji: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM react_draft_roles WHERE draft_id = ? AND emoji = ?",
            (draft_id, emoji),
        )
        return cur.rowcount > 0


def update_draft_role(draft_id: int, old_emoji: str, new_emoji: str, new_role_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE react_draft_roles SET emoji = ?, role_id = ? WHERE draft_id = ? AND emoji = ?",
            (new_emoji, new_role_id, draft_id, old_emoji),
        )
        return cur.rowcount > 0


# ── User Prefs ────────────────────────────────────────────────────────────────

def get_user_prefs(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_prefs WHERE user_id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def upsert_user_prefs(user_id: str, **kwargs) -> None:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT user_id FROM user_prefs WHERE user_id = ?", (user_id,)
        ).fetchone()
        if existing:
            sets = ", ".join(f"{k} = ?" for k in kwargs)
            conn.execute(
                f"UPDATE user_prefs SET {sets} WHERE user_id = ?",
                (*kwargs.values(), user_id),
            )
        else:
            kwargs["user_id"] = user_id
            cols = ", ".join(kwargs.keys())
            placeholders = ", ".join("?" for _ in kwargs)
            conn.execute(
                f"INSERT INTO user_prefs ({cols}) VALUES ({placeholders})",
                tuple(kwargs.values()),
            )


# ── Reminders ────────────────────────────────────────────────────────────────

def add_reminder(user_id: str, guild_id: str, channel_id: str,
                 message: str, fire_at_utc_iso: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO reminders (user_id, guild_id, channel_id, message, fire_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, guild_id, channel_id, message,
             fire_at_utc_iso, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_pending_reminders(now: "datetime") -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE fired = 0 AND fire_at <= ? ORDER BY fire_at",
            (now.isoformat(),),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_reminder_fired(reminder_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE reminders SET fired = 1 WHERE reminder_id = ?", (reminder_id,)
        )


def get_user_reminders(user_id: str, include_fired: bool = False) -> list[dict]:
    with get_conn() as conn:
        if include_fired:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE user_id = ? ORDER BY fire_at",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE user_id = ? AND fired = 0 ORDER BY fire_at",
                (user_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_reminder(reminder_id: int, user_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM reminders WHERE reminder_id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        return cur.rowcount > 0


# ── Softban ───────────────────────────────────────────────────────────────────

def save_softban_roles(guild_id: str, user_id: str, role_ids: list[int]) -> None:
    import json as _json
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO softban_roles (guild_id, user_id, saved_roles, softbanned_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   saved_roles = excluded.saved_roles,
                   softbanned_at = excluded.softbanned_at""",
            (guild_id, user_id, _json.dumps(role_ids), datetime.utcnow().isoformat()),
        )


def get_softban_roles(guild_id: str, user_id: str) -> list[int] | None:
    import json as _json
    with get_conn() as conn:
        row = conn.execute(
            "SELECT saved_roles FROM softban_roles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return _json.loads(row["saved_roles"])


def clear_softban_roles(guild_id: str, user_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM softban_roles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )


# ── Starboard ────────────────────────────────────────────────────────────────

def create_starboard(guild_id: str, name: str, channel_id: str,
                     threshold: int, nsfw_only: int = 0) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO starboards (guild_id, name, channel_id, threshold, nsfw_only)
               VALUES (?, ?, ?, ?, ?)""",
            (guild_id, name, channel_id, threshold, nsfw_only),
        )
        return cur.lastrowid


def delete_starboard(guild_id: str, name: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM starboards WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        )
        return cur.rowcount > 0


def get_starboard(guild_id: str, name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM starboards WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        ).fetchone()
    return dict(row) if row else None


def get_all_starboards(guild_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM starboards WHERE guild_id = ? ORDER BY name",
            (guild_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_starboard_threshold(board_id: int, threshold: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE starboards SET threshold = ? WHERE board_id = ?",
            (threshold, board_id),
        )


def add_starboard_emoji(board_id: int, emoji: str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO starboard_emojis (board_id, emoji) VALUES (?, ?)",
                (board_id, emoji),
            )
        return True
    except Exception:
        return False


def remove_starboard_emoji(board_id: int, emoji: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM starboard_emojis WHERE board_id = ? AND emoji = ?",
            (board_id, emoji),
        )
        return cur.rowcount > 0


def get_starboard_emojis(board_id: int) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT emoji FROM starboard_emojis WHERE board_id = ?",
            (board_id,),
        ).fetchall()
    return [r["emoji"] for r in rows]


def get_board_for_emoji(guild_id: str, emoji: str) -> dict | None:
    """Find which board (if any) this emoji triggers in this guild."""
    with get_conn() as conn:
        row = conn.execute(
            """SELECT s.* FROM starboards s
               JOIN starboard_emojis e ON s.board_id = e.board_id
               WHERE s.guild_id = ? AND e.emoji = ?""",
            (guild_id, emoji),
        ).fetchone()
    return dict(row) if row else None


def get_starboard_entry(board_id: int, source_message_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM starboard_entries WHERE board_id = ? AND source_message_id = ?",
            (board_id, source_message_id),
        ).fetchone()
    return dict(row) if row else None


def add_starboard_entry(board_id: int, source_message_id: str, source_channel_id: str,
                        board_message_id: str, original_content: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO starboard_entries
               (board_id, source_message_id, source_channel_id, board_message_id,
                original_content, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (board_id, source_message_id, source_channel_id, board_message_id,
             original_content, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def update_starboard_entry_content(entry_id: int, board_message_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE starboard_entries SET board_message_id = ? WHERE entry_id = ?",
            (board_message_id, entry_id),
        )


# ── Streamers ────────────────────────────────────────────────────────────────

def add_streamer(guild_id: str, user_id: str, twitch_username: str,
                 channel_id: str, platform: str = "twitch") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO streamers (guild_id, user_id, twitch_username, channel_id, created_at, platform)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (guild_id, user_id, twitch_username, channel_id,
             datetime.utcnow().isoformat(), platform),
        )
        return cur.lastrowid


def remove_streamer(guild_id: str, user_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM streamers WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        return cur.rowcount > 0


def get_streamer(guild_id: str, user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM streamers WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def get_streamer_by_twitch(guild_id: str, twitch_username: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM streamers WHERE guild_id = ? AND LOWER(twitch_username) = LOWER(?)",
            (guild_id, twitch_username),
        ).fetchone()
    return dict(row) if row else None


def get_all_streamers(guild_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM streamers WHERE guild_id = ? ORDER BY twitch_username",
            (guild_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_streamer(streamer_id: int, **kwargs) -> None:
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE streamers SET {sets} WHERE streamer_id = ?",
            (*kwargs.values(), streamer_id),
        )


def add_streamer_link(streamer_id: int, label: str, url: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO streamer_links (streamer_id, label, url) VALUES (?, ?, ?)",
            (streamer_id, label, url),
        )
        return cur.lastrowid


def remove_streamer_link(streamer_id: int, label: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM streamer_links WHERE streamer_id = ? AND LOWER(label) = LOWER(?)",
            (streamer_id, label),
        )
        return cur.rowcount > 0


def get_streamer_links(streamer_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM streamer_links WHERE streamer_id = ? ORDER BY label",
            (streamer_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Violations (v3.0) ────────────────────────────────────────────────────────

def add_violation(guild_id: int, user_id: int, name: str, trigger: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO violations (guild_id, user_id, name, trigger, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, name, trigger, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_violation_count(guild_id: int, user_id: int, name: str = "",
                        window_minutes: int = 60) -> int:
    cutoff = (datetime.utcnow() - __import__("datetime").timedelta(minutes=window_minutes)).isoformat()
    with get_conn() as conn:
        if name:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM violations WHERE guild_id = ? AND user_id = ? AND name = ? AND created_at >= ?",
                (guild_id, user_id, name, cutoff),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM violations WHERE guild_id = ? AND user_id = ? AND created_at >= ?",
                (guild_id, user_id, cutoff),
            ).fetchone()
    return row["cnt"] if row else 0


def get_all_violation_count(guild_id: int, user_id: int,
                            window_minutes: int = 60) -> int:
    """Count ALL violations for a user within the window, across all names."""
    return get_violation_count(guild_id, user_id, name="", window_minutes=window_minutes)


def get_recent_violations(guild_id: int, user_id: int, limit: int = 25) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM violations WHERE guild_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
            (guild_id, user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_violations_summary(guild_id: int, limit: int = 10) -> list[dict]:
    """Top offenders by violation count in the last 24h."""
    cutoff = (datetime.utcnow() - __import__("datetime").timedelta(hours=24)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT user_id, COUNT(*) as cnt
               FROM violations WHERE guild_id = ? AND created_at >= ?
               GROUP BY user_id ORDER BY cnt DESC LIMIT ?""",
            (guild_id, cutoff, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def cleanup_old_violations(days: int = 30) -> int:
    cutoff = (datetime.utcnow() - __import__("datetime").timedelta(days=days)).isoformat()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM violations WHERE created_at < ?", (cutoff,))
        return cur.rowcount


# ── Member Roles (v3.0) ──────────────────────────────────────────────────────

def save_member_roles(guild_id: str, user_id: str, role_ids: list[int]) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO member_roles (guild_id, user_id, saved_roles, saved_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, user_id) DO UPDATE SET
                   saved_roles = excluded.saved_roles,
                   saved_at = excluded.saved_at""",
            (guild_id, user_id, json.dumps(role_ids), datetime.utcnow().isoformat()),
        )


def get_member_roles(guild_id: str, user_id: str) -> list[int] | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT saved_roles FROM member_roles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["saved_roles"])


def clear_member_roles(guild_id: str, user_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM member_roles WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )


# ── Timed Bans (v3.0) ────────────────────────────────────────────────────────

def add_timed_ban(guild_id: int, user_id: int, unban_at: datetime,
                  reason: str = "", banned_by: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO timed_bans (guild_id, user_id, unban_at, reason, banned_by) VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, unban_at.isoformat(), reason, banned_by),
        )


def get_expired_bans(now: datetime) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM timed_bans WHERE unban_at <= ?", (now.isoformat(),)
        ).fetchall()
    return [dict(r) for r in rows]


def remove_timed_ban(guild_id: int, user_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM timed_bans WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))


def get_timed_ban(guild_id: int, user_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM timed_bans WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        ).fetchone()
    return dict(row) if row else None


# ── Word Lists (v3.0) ────────────────────────────────────────────────────────

def create_word_list(guild_id: str, list_name: str, words: list[str] | None = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO word_lists (guild_id, list_name, words) VALUES (?, ?, ?)",
            (guild_id, list_name, json.dumps(words or [])),
        )
        return cur.lastrowid


def get_word_list(guild_id: str, list_name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM word_lists WHERE guild_id = ? AND list_name = ?",
            (guild_id, list_name),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["words"] = json.loads(d["words"])
    return d


def get_all_word_lists(guild_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM word_lists WHERE guild_id = ? ORDER BY list_name",
            (guild_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["words"] = json.loads(d["words"])
        result.append(d)
    return result


def update_word_list(guild_id: str, list_name: str, words: list[str]) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE word_lists SET words = ? WHERE guild_id = ? AND list_name = ?",
            (json.dumps(words), guild_id, list_name),
        )
        return cur.rowcount > 0


def delete_word_list(guild_id: str, list_name: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM word_lists WHERE guild_id = ? AND list_name = ?",
            (guild_id, list_name),
        )
        return cur.rowcount > 0


# ── Automod Profiles (v2.9) ─────────────────────────────────────────────────

# Built-in profiles: normal (baseline), strict (lower thresholds), raid (aggressive)
BUILTIN_PROFILES = {
    "normal": {
        "spam_msg_limit": 5,
        "spam_window_sec": 8,
        "spam_dup_limit": 3,
        "spam_mention_limit": 5,
        "spam_emoji_limit": 15,
        "violation_jail_threshold": 5,
        "violation_window_minutes": 60,
    },
    "strict": {
        "spam_msg_limit": 3,
        "spam_window_sec": 10,
        "spam_dup_limit": 2,
        "spam_mention_limit": 3,
        "spam_emoji_limit": 8,
        "violation_jail_threshold": 3,
        "violation_window_minutes": 30,
    },
    "raid": {
        "spam_msg_limit": 2,
        "spam_window_sec": 15,
        "spam_dup_limit": 1,
        "spam_mention_limit": 2,
        "spam_emoji_limit": 5,
        "violation_jail_threshold": 2,
        "violation_window_minutes": 15,
        "invite_filter_enabled": 1,
        "link_filter_enabled": 1,
        "wordlist_enabled": 1,
        "slowmode_enabled": 1,
        "slowmode_seconds": 10,
    },
}


def seed_profiles(guild_id: str) -> None:
    """Insert built-in profiles if they don't exist yet."""
    with get_conn() as conn:
        for name, overrides in BUILTIN_PROFILES.items():
            conn.execute(
                """INSERT OR IGNORE INTO automod_profiles (guild_id, name, overrides, built_in)
                   VALUES (?, ?, ?, 1)""",
                (guild_id, name, json.dumps(overrides)),
            )


def get_profile(guild_id: str, name: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM automod_profiles WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["overrides"] = json.loads(d["overrides"])
    return d


def get_all_profiles(guild_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM automod_profiles WHERE guild_id = ? ORDER BY built_in DESC, name",
            (guild_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["overrides"] = json.loads(d["overrides"])
        result.append(d)
    return result


def upsert_profile(guild_id: str, name: str, overrides: dict, built_in: bool = False) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO automod_profiles (guild_id, name, overrides, built_in)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(guild_id, name) DO UPDATE SET
                   overrides = excluded.overrides""",
            (guild_id, name, json.dumps(overrides), int(built_in)),
        )


def delete_profile(guild_id: str, name: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM automod_profiles WHERE guild_id = ? AND name = ? AND built_in = 0",
            (guild_id, name),
        )
        return cur.rowcount > 0


def get_effective_config(guild_id: int) -> dict:
    """
    Return guild config with the active profile's overrides applied.
    This is what the automod pipeline should use instead of raw get_config().
    """
    cfg = get_config(guild_id)
    if cfg is None:
        return {}
    active = cfg.get("active_profile") or "normal"
    profile = get_profile(str(guild_id), active)
    if profile and profile.get("overrides"):
        cfg = dict(cfg)  # copy so we don't mutate the cached version
        cfg.update(profile["overrides"])
    return cfg


# -- Autoresponses ---------------------------------------------------------------

def add_autoresponse(guild_id: str, trigger: str, response: str, match_mode: str = "contains") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO autoresponses (guild_id, trigger, response, match_mode, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, trigger.lower(), response, match_mode, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_autoresponses(guild_id: str, enabled_only: bool = False) -> list[dict]:
    with get_conn() as conn:
        if enabled_only:
            rows = conn.execute(
                "SELECT * FROM autoresponses WHERE guild_id = ? AND enabled = 1 ORDER BY trigger",
                (guild_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM autoresponses WHERE guild_id = ? ORDER BY trigger",
                (guild_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_autoresponse(ar_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM autoresponses WHERE id = ?", (ar_id,)).fetchone()
    return dict(row) if row else None


def update_autoresponse(ar_id: int, **kwargs) -> bool:
    if not kwargs:
        return False
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE autoresponses SET {sets} WHERE id = ?",
            (*kwargs.values(), ar_id),
        )
        return cur.rowcount > 0


def delete_autoresponse(ar_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM autoresponses WHERE id = ?", (ar_id,))
        return cur.rowcount > 0


# ── Starboard / reminder helpers added for dashboard parity (v3.5) ───────────

def update_starboard(board_id: int, **fields) -> bool:
    """
    Update any subset of a starboard's mutable columns.

    update_starboard_threshold() only ever covered `threshold`, which meant the
    channel and nsfw_only flag could be set at creation and never changed.
    """
    allowed = {"name", "channel_id", "threshold", "nsfw_only"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    sets = ", ".join(f"{k} = ?" for k in updates)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE starboards SET {sets} WHERE board_id = ?",
            (*updates.values(), board_id),
        )
        return cur.rowcount > 0


def get_starboard_by_id(board_id: int) -> "dict | None":
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM starboards WHERE board_id = ?", (board_id,)
        ).fetchone()
    return dict(row) if row else None


def count_starboard_entries(board_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM starboard_entries WHERE board_id = ?",
            (board_id,),
        ).fetchone()
    return int(row["n"]) if row else 0


def get_guild_reminders(guild_id: str, include_fired: bool = False,
                        limit: int = 200) -> list[dict]:
    """
    Every reminder in a guild, not just one user's.

    get_user_reminders() is keyed on user_id only, so staff had no way to see
    what was scheduled server-wide.
    """
    sql = "SELECT * FROM reminders WHERE guild_id = ?"
    if not include_fired:
        sql += " AND fired = 0"
    sql += " ORDER BY fire_at LIMIT ?"
    with get_conn() as conn:
        rows = conn.execute(sql, (str(guild_id), int(limit))).fetchall()
    return [dict(r) for r in rows]


def delete_reminder_by_id(reminder_id: int, guild_id: str) -> bool:
    """
    Delete a reminder without needing to know whose it is.

    delete_reminder() requires a matching user_id, which is correct for the
    self-service /remindme flow but makes staff cleanup impossible.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM reminders WHERE reminder_id = ? AND guild_id = ?",
            (reminder_id, str(guild_id)),
        )
        return cur.rowcount > 0


# ── Blueprints (v3.6) ─────────────────────────────────────────────────────────
# A blueprint is a declarative JSON description of a server's roles, categories,
# and channels. Blueprints are stored per-guild; a row with guild_id NULL is a
# global/bundled blueprint available to every guild.

def upsert_blueprint(guild_id: str | None, name: str, data: dict,
                     description: str = "", source: str = "custom") -> int:
    """Insert or replace a blueprint. Returns its row id."""
    now = datetime.utcnow().isoformat()
    payload = json.dumps(data)
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM blueprints WHERE guild_id IS ? AND name = ?",
            (guild_id, name),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE blueprints SET data = ?, description = ?, source = ?, "
                "updated_at = ? WHERE id = ?",
                (payload, description, source, now, existing["id"]),
            )
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO blueprints (guild_id, name, description, data, source, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, name, description, payload, source, now, now),
        )
        return cur.lastrowid


def get_blueprint(guild_id: str | None, name: str) -> dict | None:
    """
    Look up a blueprint by name. Guild-owned blueprints win over global ones,
    so a server can override a bundled blueprint without editing files on disk.
    """
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM blueprints WHERE guild_id = ? AND name = ?",
            (guild_id, name),
        ).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM blueprints WHERE guild_id IS NULL AND name = ?",
                (name,),
            ).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["data"] = json.loads(out["data"])
    return out


def get_blueprints(guild_id: str | None = None) -> list[dict]:
    """All blueprints visible to a guild: its own plus every global one."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM blueprints WHERE guild_id IS NULL OR guild_id = ? "
            "ORDER BY (guild_id IS NULL) DESC, name",
            (guild_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d["data"])
        except json.JSONDecodeError:
            d["data"] = {}
        out.append(d)
    return out


def delete_blueprint(guild_id: str | None, name: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM blueprints WHERE guild_id IS ? AND name = ?",
            (guild_id, name),
        )
        return cur.rowcount > 0


def add_blueprint_run(guild_id: str, blueprint: str, actor_id: str,
                      actor_name: str, dry_run: bool, created: int,
                      skipped: int, failed: int, log_lines: list[str]) -> int:
    """Record an apply (or preview) so there is an audit trail of who ran what."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO blueprint_runs (guild_id, blueprint, actor_id, actor_name, "
            "dry_run, created_count, skipped_count, failed_count, log, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, blueprint, actor_id, actor_name, int(dry_run), created,
             skipped, failed, json.dumps(log_lines), datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_blueprint_runs(guild_id: str, limit: int = 25) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM blueprint_runs WHERE guild_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["log"] = json.loads(d["log"])
        except json.JSONDecodeError:
            d["log"] = []
        out.append(d)
    return out


# ── Message archive (v4.0) ────────────────────────────────────────────────────
# Replaces Sentinel's logs.json. That file was read and rewritten in full on
# every single message, which does not survive a public server and corrupts the
# whole archive if the process dies mid-write.

def archive_message(guild_id: str, channel_id: str, channel_name: str,
                    message_id: str, author_id: str, author_name: str,
                    content: str, attachments: list, created_at: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO message_archive "
            "(guild_id, channel_id, channel_name, message_id, author_id, "
            " author_name, content, attachments, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, channel_name, message_id, author_id,
             author_name, content, json.dumps(attachments), created_at),
        )
        return cur.lastrowid


def archive_record_edit(message_id: str, new_content: str) -> bool:
    """Keep the original and append each revision, so edits are visible too."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT content, edit_history FROM message_archive WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if row is None:
            return False
        try:
            history = json.loads(row["edit_history"])
        except json.JSONDecodeError:
            history = []
        history.append({"content": row["content"],
                        "replaced_at": datetime.utcnow().isoformat()})
        conn.execute(
            "UPDATE message_archive SET content = ?, edited = 1, edit_history = ? "
            "WHERE message_id = ?",
            (new_content, json.dumps(history), message_id),
        )
        return True


def archive_mark_deleted(message_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM message_archive WHERE message_id = ?", (message_id,)
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE message_archive SET deleted = 1, deleted_at = ? WHERE message_id = ?",
            (datetime.utcnow().isoformat(), message_id),
        )
    out = dict(row)
    try:
        out["attachments"] = json.loads(out["attachments"])
    except json.JSONDecodeError:
        out["attachments"] = []
    return out


def archive_search(guild_id: str, query: str = "", author_id: str = "",
                   channel_id: str = "", deleted_only: bool = False,
                   limit: int = 100, offset: int = 0) -> list[dict]:
    sql = "SELECT * FROM message_archive WHERE guild_id = ?"
    params: list = [guild_id]
    if query:
        sql += " AND content LIKE ?"
        params.append(f"%{query}%")
    if author_id:
        sql += " AND author_id = ?"
        params.append(author_id)
    if channel_id:
        sql += " AND channel_id = ?"
        params.append(channel_id)
    if deleted_only:
        sql += " AND deleted = 1"
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("attachments", "edit_history"):
            try:
                d[k] = json.loads(d[k])
            except (json.JSONDecodeError, TypeError):
                d[k] = []
        out.append(d)
    return out


def archive_expired(guild_id: str, cutoff_iso: str) -> list[dict]:
    """Rows past the retention window, returned so their vault files can go too."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, attachments FROM message_archive "
            "WHERE guild_id = ? AND created_at < ?",
            (guild_id, cutoff_iso),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["attachments"] = json.loads(d["attachments"])
        except json.JSONDecodeError:
            d["attachments"] = []
        out.append(d)
    return out


def archive_delete_ids(ids: list[int]) -> int:
    if not ids:
        return 0
    with get_conn() as conn:
        cur = conn.execute(
            f"DELETE FROM message_archive WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
        return cur.rowcount


def archive_stats(guild_id: str) -> dict:
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM message_archive WHERE guild_id = ?", (guild_id,)
        ).fetchone()["c"]
        deleted = conn.execute(
            "SELECT COUNT(*) c FROM message_archive WHERE guild_id = ? AND deleted = 1",
            (guild_id,),
        ).fetchone()["c"]
        oldest = conn.execute(
            "SELECT MIN(created_at) m FROM message_archive WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()["m"]
    return {"total": total, "deleted": deleted, "oldest": oldest}


# ── FOIA tracker (v4.1) ───────────────────────────────────────────────────────
# Michigan FOIA (MCL 15.235): a public body has 5 business days to respond, and
# may take one 10-business-day extension. Missing the deadline is itself
# actionable, so the deadline math has to be right.

FOIA_STATUSES = ("filed", "acknowledged", "extended", "fee_quoted",
                 "granted", "partial", "denied", "appealed", "closed")


def add_foia(guild_id: str, body: str, subject: str, filed_date: str,
             response_due: str, filed_by: str = "", notes: str = "") -> int:
    now = datetime.utcnow().isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO foia_requests (guild_id, body, subject, filed_date, "
            "response_due, filed_by, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, body, subject, filed_date, response_due, filed_by,
             notes, now, now),
        )
        return cur.lastrowid


def get_foia(guild_id: str, foia_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM foia_requests WHERE guild_id = ? AND id = ?",
            (guild_id, foia_id),
        ).fetchone()
    return dict(row) if row else None


def get_foias(guild_id: str, open_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM foia_requests WHERE guild_id = ?"
    params: list = [guild_id]
    if open_only:
        sql += " AND status NOT IN ('closed', 'granted', 'denied')"
    sql += " ORDER BY response_due ASC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update_foia(guild_id: str, foia_id: int, **fields) -> bool:
    allowed = {"body", "subject", "status", "response_due", "extended_due",
               "fee_quoted", "notes", "warned_stages"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return False
    sets["updated_at"] = datetime.utcnow().isoformat()
    clause = ", ".join(f"{k} = ?" for k in sets)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE foia_requests SET {clause} WHERE guild_id = ? AND id = ?",
            [*sets.values(), guild_id, foia_id],
        )
        return cur.rowcount > 0


def delete_foia(guild_id: str, foia_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM foia_requests WHERE guild_id = ? AND id = ?",
            (guild_id, foia_id),
        )
        return cur.rowcount > 0


# ── Dashboard audit trail (v4.3) ──────────────────────────────────────────────
# Every state-changing request through the dashboard is recorded here. The
# mod-log answers "what happened to this member"; this answers "what did this
# staff account do", which is the question an audit actually asks.

def add_audit(guild_id: str, actor_id: str, actor_name: str, method: str,
              path: str, summary: str = "", payload: str = "",
              status: int = 0, ip: str = "", source: str = "dashboard",
              target: str = "", mutating: bool = True) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO audit_log (guild_id, actor_id, actor_name, method, path, "
            "summary, payload, status, ip, source, target, mutating, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, actor_id, actor_name, method, path, summary,
             payload[:4000], status, ip, source, target, int(mutating),
             datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_audit(guild_id: str = "", actor_id: str = "", path_like: str = "",
              source: str = "", mutating_only: bool = False,
              limit: int = 100, offset: int = 0) -> list[dict]:
    sql = "SELECT * FROM audit_log WHERE 1=1"
    params: list = []
    if guild_id:
        sql += " AND (guild_id = ? OR guild_id = '')"
        params.append(guild_id)
    if actor_id:
        sql += " AND actor_id = ?"
        params.append(actor_id)
    if path_like:
        sql += " AND (path LIKE ? OR summary LIKE ? OR target LIKE ?)"
        params.extend([f"%{path_like}%"] * 3)
    if source:
        sql += " AND source = ?"
        params.append(source)
    if mutating_only:
        sql += " AND mutating = 1"
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([min(limit, 500), offset])
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def audit_actors(guild_id: str = "") -> list[dict]:
    """Distinct actors with a count, for the audit page filter."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT actor_id, actor_name, COUNT(*) n, MAX(created_at) last, "
            "SUM(CASE WHEN source = 'discord' THEN 1 ELSE 0 END) discord_n, "
            "SUM(CASE WHEN source = 'dashboard' THEN 1 ELSE 0 END) dashboard_n "
            "FROM audit_log WHERE actor_id != '' "
            "GROUP BY actor_id ORDER BY n DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def purge_audit(older_than_iso: str) -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM audit_log WHERE created_at < ?",
                           (older_than_iso,))
        return cur.rowcount


# ── RSS feeds (v4.3.2) ────────────────────────────────────────────────────────

def add_feed(guild_id: str, name: str, url: str, channel_id: str,
             make_threads: bool = True, ping_role_id: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR REPLACE INTO rss_feeds (guild_id, name, url, channel_id, "
            "make_threads, ping_role_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, name, url, channel_id, int(make_threads), ping_role_id,
             datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_feeds(guild_id: str = "", enabled_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM rss_feeds WHERE 1=1"
    params: list = []
    if guild_id:
        sql += " AND guild_id = ?"
        params.append(guild_id)
    if enabled_only:
        sql += " AND enabled = 1"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql + " ORDER BY name", params)]


def update_feed(feed_id: int, **fields) -> bool:
    allowed = {"name", "url", "channel_id", "make_threads", "ping_role_id",
               "enabled", "last_checked", "last_error"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return False
    clause = ", ".join(f"{k} = ?" for k in sets)
    with get_conn() as conn:
        cur = conn.execute(f"UPDATE rss_feeds SET {clause} WHERE id = ?",
                           [*sets.values(), feed_id])
        return cur.rowcount > 0


def delete_feed(guild_id: str, feed_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM rss_posted WHERE feed_id = ?", (feed_id,))
        cur = conn.execute("DELETE FROM rss_feeds WHERE guild_id = ? AND id = ?",
                           (guild_id, feed_id))
        return cur.rowcount > 0


def feed_item_seen(feed_id: int, guid: str) -> bool:
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM rss_posted WHERE feed_id = ? AND guid = ?",
            (feed_id, guid),
        ).fetchone() is not None


def mark_feed_item(feed_id: int, guid: str, title: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO rss_posted (feed_id, guid, title, posted_at) "
            "VALUES (?, ?, ?, ?)",
            (feed_id, guid, title, datetime.utcnow().isoformat()),
        )


def recent_feed_items(feed_id: int, limit: int = 10) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM rss_posted WHERE feed_id = ? ORDER BY id DESC LIMIT ?",
            (feed_id, limit))]


# ── Meetings (v4.3.2) ─────────────────────────────────────────────────────────

def add_meeting(guild_id: str, name: str, channel_id: str, schedule: dict,
                meeting_time: str = "19:00", location: str = "",
                agenda_url: str = "", ping_role_id: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO meetings (guild_id, name, channel_id, schedule, "
            "meeting_time, location, agenda_url, ping_role_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, name, channel_id, json.dumps(schedule), meeting_time,
             location, agenda_url, ping_role_id, datetime.utcnow().isoformat()),
        )
        return cur.lastrowid


def get_meetings(guild_id: str = "", enabled_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM meetings WHERE 1=1"
    params: list = []
    if guild_id:
        sql += " AND guild_id = ?"
        params.append(guild_id)
    if enabled_only:
        sql += " AND enabled = 1"
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql + " ORDER BY name", params)]
    for r in rows:
        try:
            r["schedule"] = json.loads(r["schedule"])
        except (json.JSONDecodeError, TypeError):
            r["schedule"] = {}
        try:
            r["exceptions"] = json.loads(r.get("exceptions") or "{}")
        except (json.JSONDecodeError, TypeError):
            r["exceptions"] = {}
    return rows


def update_meeting(guild_id: str, meeting_id: int, **fields) -> bool:
    allowed = {"name", "channel_id", "schedule", "meeting_time", "location",
               "agenda_url", "ping_role_id", "enabled", "last_fired",
               "exceptions"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    for key in ("schedule", "exceptions"):
        if key in sets and isinstance(sets[key], dict):
            sets[key] = json.dumps(sets[key])
    if not sets:
        return False
    clause = ", ".join(f"{k} = ?" for k in sets)
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE meetings SET {clause} WHERE guild_id = ? AND id = ?",
            [*sets.values(), guild_id, meeting_id])
        return cur.rowcount > 0


def delete_meeting(guild_id: str, meeting_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM meetings WHERE guild_id = ? AND id = ?",
                           (guild_id, meeting_id))
        return cur.rowcount > 0


# ── Round Table roster (v4.3.2) ───────────────────────────────────────────────

def upsert_roster_member(guild_id: str, user_id: str, display_name: str = "",
                         organization: str = "", role_title: str = "",
                         notes: str = "") -> int:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM roster_members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)).fetchone()
        if existing:
            conn.execute(
                "UPDATE roster_members SET display_name = ?, organization = ?, "
                "role_title = ?, notes = ? WHERE id = ?",
                (display_name, organization, role_title, notes, existing["id"]))
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO roster_members (guild_id, user_id, display_name, "
            "organization, role_title, notes, added_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, display_name, organization, role_title, notes,
             datetime.utcnow().isoformat()))
        return cur.lastrowid


def get_roster(guild_id: str) -> list[dict]:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM roster_members WHERE guild_id = ? "
            "ORDER BY organization COLLATE NOCASE, display_name COLLATE NOCASE",
            (guild_id,))]


def get_roster_member(guild_id: str, user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM roster_members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)).fetchone()
    return dict(row) if row else None


def remove_roster_member(guild_id: str, user_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM roster_members WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id))
        return cur.rowcount > 0


# ── Legacy boosters (v4.1) ────────────────────────────────────────────────────
# A record of everyone who has ever boosted and been granted the permanent
# reward role. The row is the source of truth, not the Discord role, because
# roles are lost when a member leaves and we want the grant to survive that.

def grant_legacy_boost(guild_id: str, user_id: str, username: str = "",
                       first_boosted: str = "", granted_by: str = "auto",
                       note: str = "") -> bool:
    """Record a grant. Returns False if this member already had one."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, revoked FROM legacy_boosters "
            "WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()
        if existing:
            if existing["revoked"]:
                conn.execute(
                    "UPDATE legacy_boosters SET revoked = 0, revoked_at = NULL, "
                    "revoked_by = '' WHERE id = ?", (existing["id"],))
                return True
            return False
        conn.execute(
            "INSERT INTO legacy_boosters (guild_id, user_id, username, "
            "first_boosted, granted_at, granted_by, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, username, first_boosted or None,
             datetime.utcnow().isoformat(), granted_by, note),
        )
        return True


def get_legacy_boosters(guild_id: str, include_revoked: bool = False) -> list[dict]:
    sql = "SELECT * FROM legacy_boosters WHERE guild_id = ?"
    if not include_revoked:
        sql += " AND revoked = 0"
    sql += " ORDER BY granted_at DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, (guild_id,))]


def is_legacy_booster(guild_id: str, user_id: str) -> bool:
    with get_conn() as conn:
        return conn.execute(
            "SELECT 1 FROM legacy_boosters WHERE guild_id = ? AND user_id = ? "
            "AND revoked = 0", (guild_id, user_id)
        ).fetchone() is not None


def revoke_legacy_boost(guild_id: str, user_id: str, revoked_by: str = "",
                        note: str = "") -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE legacy_boosters SET revoked = 1, revoked_at = ?, "
            "revoked_by = ?, note = ? WHERE guild_id = ? AND user_id = ? "
            "AND revoked = 0",
            (datetime.utcnow().isoformat(), revoked_by, note, guild_id, user_id),
        )
        return cur.rowcount > 0
