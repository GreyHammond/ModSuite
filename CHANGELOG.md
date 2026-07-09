# Changelog

All notable changes to ModSuite are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with SemVer.

---

## [3.0.0] -- 2026-07-08

### Phase 4: Name filtering, verification gate, all-caps filter

**Username/nickname filtering** (new cog: `cogs/namefilter.py`):
- Checks display names on join (`on_member_join`) and on nickname change (`on_member_update`)
- Configurable word list for blocked name patterns stored in `name_filter_words` config
- Unicode confusable character normalization (Cyrillic lookalikes, l33tspeak, fullwidth chars) mapped to ASCII equivalents before matching -- catches evasion attempts
- Actions: log (flag in #mod-log), kick, or ban
- `/namefilter toggle` / `action` / `confusables` / `add` / `remove` / `list` -- 6 slash commands
- Name Filter panel in `/setup` with toggle, confusables toggle, and action selector
- NAME_FILTER action type in mod_logs, /history, and dashboard activity feed

**Verification gate**:
- New members must react to a verification message to gain a configured role
- Until verified, members lack the gate role (server permissions control access)
- Reaction listener grants the role and logs VERIFIED_GATE to mod_logs
- `/verifygate toggle` / `role` / `channel` / `post` / `status` -- 5 slash commands
- Verify Gate panel in `/setup` with toggle, role picker, and channel picker
- VERIFIED_GATE action type in mod_logs, /history, and dashboard activity feed

**All-caps filter**:
- Configurable percentage threshold (default 70%) of uppercase alphabetic characters
- Minimum character length before checking (default 10 alpha chars, ignores short messages)
- Feeds into the violation engine like all other automod triggers
- `/automod allcaps` / `allcaps_threshold` -- 2 slash commands
- Toggle and threshold in `/setup` > Content Filters panel
- Shown in `/automod status` and dashboard AutoMod card

**Setup hub**:
- 2 new panels: Name Filter, Verify Gate (15 total hub buttons across 5 rows)
- Hub embed shows all-caps, name filter, and verify gate status
- Content Filters panel now includes all-caps toggle and threshold

**Dashboard**:
- AutoMod card shows all-caps, name filter, and verify gate status (13 rows total)
- Activity feed icons and verbs for name_filter, verified_gate, phishing

**API**:
- `/automod/summary` now includes allcaps, name_filter, verify_gate fields
- API version bumped to 3.0.0

---

## [2.9.0] -- 2026-07-08

### Phase 3: Severity profiles (toggleable automod presets)

**Profile system**:
- Named sets of automod thresholds that override guild config values on the fly
- Three built-in profiles ship with every guild:
  - **normal** -- baseline thresholds (default on every server)
  - **strict** -- lower thresholds, faster violation escalation
  - **raid** -- aggressive settings; all filters enabled, very low thresholds
- Custom profiles can be created by snapshotting the current config
- Switching profiles takes effect instantly (no restart, no re-sync)
- Profile overrides are merged onto guild_config via `db.get_effective_config()`

**Slash commands** (`/profile` group):
- `/profile switch <name>` -- activate a profile
- `/profile list` -- view all available profiles with override previews
- `/profile view <name>` -- see full override details for a profile
- `/profile create <name>` -- snapshot current settings into a new custom profile
- `/profile delete <name>` -- remove a custom profile (built-ins cannot be deleted)

**Automatic raid profile activation**:
- When lockdown triggers (auto or manual), the bot switches to the "raid" profile
- The previous profile name is saved in `profile_before_raid`
- When lockdown lifts (auto or manual), the previous profile is restored
- Lockdown and unlock embeds now show profile switch information

**Setup hub**:
- New Profiles panel with a dropdown to switch the active profile
- Shows all profiles with override previews and active indicator
- Hub embed now shows the active profile name in the Raid section

**API**:
- `GET /profiles` -- list all profiles with active indicator
- `PUT /profiles/active` -- switch the active profile from the dashboard
- `/automod/summary` now includes `active_profile`

**Dashboard**:
- AutoMod card shows the active profile name
- PROFILE_SWITCH action in activity feed

**Automod pipeline**:
- `on_message` now reads config via `get_effective_config()` which merges profile overrides
- `/automod status` shows the active profile

---

## [2.8.0] -- 2026-07-08

### Phase 2: Staff utility (timed bans, advanced purge)

**Timed bans**:
- `/tempban @user 7d [reason]` -- temporarily ban a member with automatic unban
- New `timed_bans` table tracks guild_id, user_id, unban_at, reason, banned_by
- Auto-unban loop checks every 60 seconds for expired bans
- Timed bans clear saved roles so unbanned users get a fresh start (no role restore)
- TempBan button added to the mod panel (GeneralPanelView) with a modal for username, duration, reason
- `GET /timed-bans` API endpoint for dashboard display
- TEMPBAN and auto-UNBAN actions logged to mod_logs and #mod-log channel
- `/history` shows TEMPBAN entries with the duration icon

**Advanced purge**:
- `/purge` upgraded with four optional filters that stack:
  - `user` -- only delete messages from a specific member
  - `contains` -- only delete messages containing specific text (case-insensitive)
  - `bots_only` -- only delete messages from bots
  - `max_age` -- only delete messages newer than a duration (e.g. 1h, 30m, 2d)
- Scan limit raised from 100 to 200 messages
- Filter summary shown in the confirmation message

---

## [2.7.0] -- 2026-07-08

### Phase 1: Content pipeline (anti-phishing, message length, slowmode)

All new filters feed into the violation engine from v2.6.

**Anti-phishing link scanning**:
- Every URL in a message is checked against the SinkingYachts phishing database (free API, no key required)
- Phishing links are deleted immediately and record a "phishing" violation
- Enabled by default; toggle with `/automod antiphish` or `/setup` > Content Filters
- Uses a single aiohttp session per check with host deduplication
- Fails open on API timeout (message is not blocked if the API is down)

**Message length filter**:
- Configurable min and max character thresholds per guild
- Messages outside the range are deleted and record a "message_length" violation
- Empty messages (attachments only) skip the min-length check
- `/automod max_length` / `/automod min_length` slash commands
- Configurable via `/setup` > Content Filters panel

**Per-channel slowmode enforcement**:
- Bot-enforced rate limiting: 1 message per user per channel every N seconds
- Independent of Discord's built-in slowmode (bot-level enforcement)
- Can target specific channels or apply to all channels
- `/automod slowmode` / `slowmode_interval` / `slowmode_channel` slash commands
- Configurable via `/setup` > Content Filters panel

**Setup hub**:
- New Content Filters panel with toggles for anti-phishing, slowmode, and threshold editor
- Hub embed now shows anti-phishing and slowmode status

**Dashboard**:
- AutoMod card now shows anti-phishing, message length, and slowmode status

**`/automod status` updated**:
- Now shows anti-phishing, message length limits, and slowmode settings

---

## [2.6.0] -- 2026-07-08

### Phase 0: Foundation (violation engine, role persistence, word lists, timed bans, advanced purge)

**Violation counter engine** (the foundation everything else plugs into):
- New `violations` table tracks named violations per user with timestamps
- Configurable threshold + sliding window: e.g. 5 violations in 60 minutes = auto-jail
- All automod triggers (spam, links, invites, word lists) now feed violations instead of punishing directly
- Violations escalate to jail. Only raids escalate to ban.
- `/violations check @user` -- view a user's active violation count and recent history
- `/violations clear @user` -- clear all violations for a user
- `/violations threshold` / `/violations duration` -- configure escalation settings
- Violations panel added to `/setup` configuration hub
- `GET /violations/summary` and `GET /violations/{user_id}` API endpoints
- Cleanup loop removes violation records older than 30 days

**Word list filtering**:
- New `word_lists` table with named lists of banned words per guild
- Whole-word matching for single words, substring matching for multi-word phrases
- `/automod wordlist` -- toggle word list filtering on/off
- `/automod wordlist_add` / `wordlist_remove` / `wordlist_view` / `wordlist_delete` -- manage lists
- `GET /word-lists` API endpoint
- Word list violations feed into the violation engine

**Role persistence**:
- New `member_roles` table snapshots every member's roles on leave (`on_member_remove`)
- On rejoin, roles are automatically restored for kicks, voluntary leaves, and softbans
- Banned users get a fresh start: no role restore after unban + rejoin
- Configurable via `/setup` > Violations panel or `role_persist_enabled` config key
- Replaces and extends the previous softban-only role restore

**Timed bans**:
- `/tempban @user 7d` -- temporarily ban a member with auto-unban
- New `timed_bans` table with auto-unban loop (checks every 60 seconds)
- Timed bans clear saved roles so unbanned users start fresh
- `GET /timed-bans` API endpoint
- All timed ban/unban actions logged to mod-log and mod_logs table

**Advanced purge**:
- `/purge` now supports filters: `user`, `contains`, `bots_only`, `max_age`
- Scan limit raised from 100 to 200 messages
- Filters stack (e.g. purge 50 messages from @user containing "spam" newer than 1h)

**Raid default changed to ban**:
- `raid_active_action` default changed from `kick` to `ban`
- Raid joiners are now banned by default (configurable back to kick via `/raidcfg action` or `/setup`)
- Raid bans now logged to mod_logs DB for role persistence ban detection

**Automod rewired to violation pipeline**:
- Spam detection, link filter, invite filter all now record violations instead of directly muting/kicking
- Message deletion still happens immediately; punishment is handled by the violation engine
- All automod actions logged as VIOLATION entries in mod_logs for dashboard visibility

**Dashboard + API**:
- Automod summary endpoint now includes word list status, violation thresholds, and role persistence
- New violations summary and per-user violation detail endpoints
- Timed bans endpoint for dashboard display

**Setup hub**:
- New Violations panel with threshold editor and role persistence toggle
- AutoMod summary in hub now shows word list status

---

## [2.5.0] -- 2026-07-08

### Added -- Dashboard becomes fully operational

Previously the dashboard was mostly a read-only monitor. In v2.5 every existing page gained operational depth and the API grew to support it.

**Backend -- 13 new endpoints:**
- `GET  /health` -- bot uptime, latency, memory, guild count, member total, ready state.
- `GET  /warns/trends?days=30` -- warns per day for the last N days (chart data).
- `GET  /top-offenders?limit=5` -- users with the most active warns.
- `GET  /automod/summary` -- quick AutoMod on/off dashboard tile.
- `GET  /config-schema` -- sectioned form definition for the editor.
- `GET  /config` -- full guild_config as a flat dict.
- `PUT  /config` -- partial update over any editable columns (validated).
- `POST /warns` -- queues an `add_warn` action.
- `PUT  /notes/{note_id}` -- edit note content in place.
- `GET  /users/search?q=` -- quick member lookup for filters and add-modals.
- `GET  /tickets/{ticket_id}` -- full ticket detail.
- `GET  /tickets/{ticket_id}/transcript` -- messages list for inline viewer.
- `POST /tickets/{ticket_id}/reply` -- queues a `ticket_reply` action.
- `POST /tickets/{ticket_id}/close` -- queues a `close_ticket` action.

**Backend -- 3 new action handlers in `bot.py`:**
- `add_warn` -- insert warn row, DM user, log to `#mod-log`.
- `ticket_reply` -- DM the ticket opener + echo to the ticket channel + log to DB.
- `close_ticket` -- invokes the existing `_close_ticket` helper so behaviour matches the `/close` slash command.

**Frontend -- page rewrites:**
- **Dashboard** -- added 30-day warns trend line chart, top offenders card, AutoMod status tile, and a bot health card (uptime / latency / memory / guilds).
- **Configuration** -- sectioned editor with tabs across 7 groups covering ~60 fields with proper labels, hints, and typed inputs (text / number / bool toggle / select / json list). Save/discard flow with dirty-change tracking. Bot Messages editor and Post-as-Bot composer preserved.
- **Warns** -- search box, active-only toggle, `+ Add warn` modal with type-ahead user search.
- **Notes** -- search box, `+ Add note` modal, inline **Edit** button per note with save/cancel.
- **Mod Logs** -- Action / User contains / From / To filter grid, expandable detail rows with full metadata, **Export CSV** button.
- **Tickets** -- click any open ticket to view inline transcript. Reply (anonymous or named) from the web. Close from the web.
- **Self-Roles** -- category builder with live preview (unchanged).
- **Setup** -- guided mirror of `/setup` (unchanged).

---

## [2.2.0] -- 2026-07-05

### Added
- Honeypot channels: `/honeypot add`, `remove`, `list`
- Auto-ban on any non-staff message in a honeypot channel

---

## [2.1.0] -- 2026-07-04

### Added
- Full AutoMod system: spam, links, invites, immune roles
- Raid detection and lockdown

---

## [2.0.0] -- 2026-07-03

### Added
- Web dashboard with REST API
- Starboard, streamer alerts, react-role messages, reminders, forum threads

---

## [1.9.0] -- 2026-07-02

### Added
- Initial release: setup wizard, modmail, moderation, warns, jail, notes, reports, self-roles
