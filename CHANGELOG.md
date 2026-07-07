# Changelog

All notable changes to ModSuite are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with SemVer.

---

## [2.2.0] — 2026-07-06

### Added — AutoMod
- **New `cogs/automod.py`** with a shared `on_message` listener covering all three filters.
- **Spam detection** — per-user message velocity (default 5 msgs / 8s), duplicate-message detection (default 3), mention-flood limit (default 5), emoji-flood limit (default 15). Default action: delete + 10-minute timeout.
- **Link filtering** — whitelist or blacklist mode, per-domain, with per-role and per-channel bypass. Preset whitelist covers Discord, YouTube, Twitter/X, GitHub, Tenor, Giphy. Preset blacklist covers common IP loggers.
- **Discord invite filtering** as a separate toggle so servers can allow other links but block invites (or vice versa).
- **Immune roles** — exempt specific roles from all AutoMod filters.
- **Filter chain ordering** — invites → links → spam; first match wins to prevent double-punishment.
- **New `/automod` command group** with 14 subcommands: `status`, `spam`, `spam_threshold`, `spam_action`, `links`, `link_mode`, `link_add`, `link_remove`, `link_action`, `link_bypass_channel`, `link_bypass_role`, `invites`, `invite_action`, `immune`.
- **Rich mod-log embeds** for every AutoMod trigger, including offending message snippet, trigger type, action taken, and channel.

### Added — Raid Response upgrades
- **Active-raid auto-block** — new joiners during lockdown are automatically kicked or banned (configurable via `/raidcfg action`).
- **Auto-verification bump** — server verification level raised to *highest* during lockdown, restored to previous level on unlock.
- **Auto-unlock cooldown** — lockdown lifts automatically after N minutes (default 5; set 0 for manual-only).
- **Account age gate** — flags joins from accounts younger than N days in the mod-log (default 0 = disabled).
- **New `/raidcfg` command group**: `threshold`, `account_age`, `action`, `auto_verification`, `cooldown`.

### Added — Database
- 22 new `guild_config` columns for AutoMod + raid upgrades. Auto-migrated on next startup — no manual SQL.

### Changed
- `cogs/raid.py` rewritten to support the new upgrade set while preserving all v2.1 behaviour (`/lockdown`, `/unlock`, `/autorole`, join-velocity detection).
- Bot cog load list bumped to 20 cogs with the addition of `cogs.automod`.

### Documentation
- New GitHub Pages site with hero, features, setup guide, filterable command reference, and this changelog.
- README updated with AutoMod & Raid Response sections and expanded permissions checklist.

---

## [2.1.0] — 2026-07-05

### Added — Forum Thread Deletion
- **New `cogs/threads.py`** with `/delete` command.
- Forum-thread owners can now permanently delete their own threads via a two-step confirmation flow (Yes → ⚠️ Permanent → Delete).
- Ownership check (`thread.owner_id`) enforced before showing confirmation prompts.
- Deletion event logged to `#mod-log` with user mention, thread name, and timestamp.
- 60-second confirmation timeout; buttons scoped to the invoker only.

### Changed
- Bot cog load list updated with `cogs.threads`.
- Rebranded `README.md` from "CommunityBot" to "ModSuite" to match the internal `/setup` command text and Hammond Digital Studios branding.
- README overhauled to document all 19 cogs (previously listed only 4), the FastAPI REST API, and the web dashboard.

### Notes
- No database schema changes required.
- No breaking changes — existing installations upgrade by dropping in two files: `cogs/threads.py` and the updated `bot.py`.

---

## [2.0.0] — 2026-06-XX

### Added — Web Stack
- **New `api.py`** — FastAPI REST API running in-process on `127.0.0.1:8000` (loopback only, no auth by design; front with reverse proxy for remote access).
- **New `web/` directory** — vanilla-JS SPA (no build step, no framework) with hash router.
- Dashboard pages: **Dashboard**, **Setup**, **Configuration**, **Tickets**, **Warns**, **Notes**, **Mod Logs**, **Self-Roles**.
- **Bot actions queue** (`bot_actions` table) — web UI queues Discord actions, bot polls every 5 seconds and executes with proper permissions.
- **Presence persistence** — bot's activity type + text now persist across restarts via `presence_type` / `presence_text` config columns.

### Added — New Cogs
- `cogs/starboard.py` — multi-emoji starboards (`/starboard create|delete|threshold|addemoji|removeemoji|list`).
- `cogs/streamer.py` — streamer tracking + go-live alerts (`/streamer add|remove|edit`, `/links add|remove|list`).
- `cogs/verify.py` — `/verify`, `/unverify` gate flow.
- `cogs/remindme.py` — `/timezone`, `/remindme`, `/reminders`.
- `cogs/reactmessage.py` — custom multi-role react-role builder.
- `cogs/move.py` — `/move` for relocating conversations.
- `cogs/reports.py` — user-submitted content reports.

### Added — Config Columns
- Phase-2 pronoun roles, DM preference roles, self-roles message IDs, verified role ID, presence fields.

### Changed
- Bot title in `/setup` command changed from "CommunityBot" to "ModSuite".
- API version tagged `2.0.0` in FastAPI app metadata.

---

## [1.9.0] — Prior Baseline

### Features
- Core cogs: `setup`, `selfroles`, `modmail`, `moderation`, `warns`, `jail`, `userinfo`, `raid`, `panel`, `notes`, `admin`, `messages`.
- Slash-command based moderation (`/kick`, `/ban`, `/mute`, `/unmute`, `/warn`, `/history`, `/jail`, `/purge`).
- ModMail: DM → private ticket channel, `/reply` + `/close`, transcript zipping, `#closed-tickets` archive.
- Basic raid detection (join velocity → auto-lockdown), manual `/lockdown` and `/unlock`.
- Self-roles: 14 color roles with reaction-based assignment.
- SQLite persistence with auto-migrating schema.
- Guided `/setup` wizard creating all default roles, categories, and channels.

---

## Upgrade Notes

### 2.1 → 2.2
- Overwrite `database.py`, `cogs/raid.py`, `cogs/automod.py` (new), and `bot.py`.
- Restart the bot — schema migration is automatic on startup.
- Run `/automod status` after restart to review defaults and enable link/invite filtering when ready.
- Confirm bot has **Manage Messages**, **Moderate Members**, **Kick / Ban Members**, and **Manage Guild** in target channels/server.

### 2.0 → 2.1
- Drop in `cogs/threads.py` and the updated `bot.py`.
- Restart. No DB migration required.
- Ensure the bot has **Manage Threads** in your forum channels.

### 1.9 → 2.0
- Full replacement of the `modsuite_v2/` folder (excluding `venv/` and `communitybot.db`).
- `pip install -r requirements.txt` — adds `fastapi`, `uvicorn`, `aiohttp`.
- Restart. Schema migration is automatic.
