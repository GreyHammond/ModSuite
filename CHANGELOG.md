# Changelog

All notable changes to ModSuite are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with SemVer.

---

## [2.5.0] — 2026-07-08

### Added — Dashboard becomes fully operational

Previously the dashboard was mostly a read-only monitor. In v2.5 every existing page gained operational depth and the API grew to support it.

**Backend — 13 new endpoints:**
- `GET  /health` — bot uptime, latency, memory, guild count, member total, ready state.
- `GET  /warns/trends?days=30` — warns per day for the last N days (chart data).
- `GET  /top-offenders?limit=5` — users with the most active warns.
- `GET  /automod/summary` — quick AutoMod on/off dashboard tile.
- `GET  /config-schema` — sectioned form definition for the editor.
- `GET  /config` — full guild_config as a flat dict.
- `PUT  /config` — partial update over any editable columns (validated).
- `POST /warns` — queues an `add_warn` action.
- `PUT  /notes/{note_id}` — edit note content in place.
- `GET  /users/search?q=` — quick member lookup for filters and add-modals.
- `GET  /tickets/{ticket_id}` — full ticket detail.
- `GET  /tickets/{ticket_id}/transcript` — messages list for inline viewer.
- `POST /tickets/{ticket_id}/reply` — queues a `ticket_reply` action.
- `POST /tickets/{ticket_id}/close` — queues a `close_ticket` action.

**Backend — 3 new action handlers in `bot.py`:**
- `add_warn` — insert warn row, DM user, log to `#mod-log`.
- `ticket_reply` — DM the ticket opener + echo to the ticket channel + log to DB.
- `close_ticket` — invokes the existing `_close_ticket` helper so behaviour matches the `/close` slash command.

**Frontend — page rewrites:**
- **Dashboard** — added 30-day warns trend line chart, top offenders card, AutoMod status tile, and a bot health card (uptime / latency / memory / guilds).
- **Configuration** — sectioned editor with tabs across 7 groups covering ~60 fields with proper labels, hints, and typed inputs (text / number / bool toggle / select / json list). Save/discard flow with dirty-change tracking. Bot Messages editor and Post-as-Bot composer preserved.
- **Warns** — search box, active-only toggle, `+ Add warn` modal with type-ahead user search.
- **Notes** — search box, `+ Add note` modal, inline **Edit** button per note with save/cancel.
- **Mod Logs** — Action / User contains / From / To filter grid, expandable detail rows with full metadata, **Export CSV** button.
- **Tickets** — click any ticket to expand its inline transcript viewer (blue avatars for user, gold for staff, anon badge on anonymous replies). Reply composer with anonymous toggle. **Close ticket** button.

**Frontend — infrastructure:**
- `web/api.js` — base URL changed to empty string so the frontend uses relative URLs. Works over SSH tunnel, reverse proxy, or direct access without CORS gymnastics.
- `web/shell/sidebar.js` — server dropdown hidden (single-guild).

**Bumped:**
- `api.py` version tag → `2.5.0`.
- Added `psutil` to `requirements.txt` (optional; enables memory reporting in `/health`).

### Notes
- No database schema changes in v2.5 — all new endpoints are read-and-queue over existing tables.
- No breaking changes. Existing v2.2 deployments upgrade by replacing files; existing DB, config, and tickets are preserved.

---

## [2.2.0] — 2026-07-06

### Added — AutoMod
- New `cogs/automod.py` with spam detection (message velocity, duplicates, mention floods, emoji floods).
- Link filtering with whitelist/blacklist modes and per-role/channel bypass.
- Discord invite filtering as a separate toggle.
- Immune roles for trusted members.
- Filter chain: invites → links → spam; first match wins.
- `/automod` command group with 14 subcommands and a `status` dashboard embed.

### Added — Raid Response upgrades
- Active-raid auto-block for new joiners (kick or ban).
- Auto-verification level bump during lockdown, restored on unlock.
- Auto-unlock cooldown (default 5 min).
- Account age gate for suspicious young accounts.
- `/raidcfg` command group.

### Added — Database
- 22 new `guild_config` columns for AutoMod + raid config. Auto-migrated on next startup.

---

## [2.1.0] — 2026-07-05

### Added — Forum Thread Deletion
- New `cogs/threads.py` with `/delete` command.
- Forum-thread owners can permanently delete their own threads via a two-step confirmation.
- Ownership enforced via `thread.owner_id`; buttons scoped to the invoker.
- Deletion logged to `#mod-log` with user, thread name, and timestamp.

### Changed
- Rebranded from "CommunityBot" to **ModSuite** in setup wizard and documentation.
- README overhauled to document all cogs, API, and web dashboard.

---

## [2.0.0] — 2026-06

### Added — Web Stack
- FastAPI REST API running in-process on `127.0.0.1:8000`.
- Vanilla-JS SPA dashboard — no build step, no framework.
- Bot actions queue: web UI queues Discord actions, bot polls every 5s and executes.
- Presence persistence across restarts.

### Added — New Cogs
- `starboard`, `streamer`, `verify`, `remindme`, `reactmessage`, `move`, `reports`.

---

## [1.9.0] — Baseline

### Features
- Core cogs: setup, selfroles, modmail, moderation, warns, jail, userinfo, raid, panel, notes, admin, messages.
- Slash-command moderation, ModMail ticketing.
- Basic raid detection (join velocity → auto-lockdown).
- 14 color self-roles with reaction assignment.
- SQLite persistence with auto-migrating schema.

---

## Upgrade Notes

### 2.2 → 2.5
- Overwrite the entire `modsuite_v2/` folder **except** `venv/` and `communitybot.db`.
- Run `pip install -r requirements.txt` — installs `psutil` if you don't have it.
- Restart the bot. No schema migration needed.

### 2.1 → 2.2
- Overwrite `database.py`, `cogs/raid.py`, `cogs/automod.py` (new), and `bot.py`.
- Restart the bot — schema migration is automatic.
- Confirm bot has Manage Messages, Moderate Members, Kick/Ban Members, Manage Guild.

### 2.0 → 2.1
- Drop in `cogs/threads.py` and the updated `bot.py`.
- Restart. Ensure the bot has Manage Threads in your forum channels.

### 1.9 → 2.0
- Full replacement of the `modsuite_v2/` folder (excluding `venv/` and `communitybot.db`).
- `pip install -r requirements.txt`.
- Restart.
