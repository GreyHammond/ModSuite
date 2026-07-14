# ModSuite

**Version 3.0** -- A full-stack Discord community and moderation platform for self-hosted servers, with a web dashboard, violation engine, severity profiles, and configurable automod pipeline.

ModSuite is a Python bot + FastAPI backend + web dashboard, purpose-built for community owners who want one system to handle onboarding, self-roles, ModMail, moderation, warns, jail, notes, reports, starboard, streamer alerts, react-role messages, reminders, forum thread management, AutoMod, raid response, and content filtering -- configured once via `/setup` and manageable end-to-end from Discord or the browser.

> ModSuite is part of the specialized suite of tools developed by **Hammond Digital Studios**.

---

## What's New in v3.0

A ground-up rebuild of the automod and moderation pipeline across five phases:

**Phase 0 (v2.6) -- Foundation:** Violation counter engine, word lists, role persistence, timed bans, advanced purge. Every automod trigger now feeds named violations into a central escalation engine. Violations escalate to jail. Raids escalate to ban.

**Phase 1 (v2.7) -- Content pipeline:** Anti-phishing link scanning (SinkingYachts API), message length filter, per-channel bot-enforced slowmode. All feed the violation engine.

**Phase 2 (v2.8) -- Staff utility:** `/tempban` with auto-unban loop, TempBan button in mod panel. `/purge` upgraded with user/contains/bots_only/max_age filters stacking up to 200 messages.

**Phase 3 (v2.9) -- Severity profiles:** Three built-in automod profiles (normal, strict, raid). Custom profiles via `/profile create`. Instant switching. Raid auto-activates the "raid" profile on lockdown, restores previous on unlock.

**Phase 4 (v3.0) -- Name filtering, verification gate, all-caps:** Username/nickname filtering with Unicode confusable normalization. Reaction-based verification gate for new members. All-caps percentage filter. All configurable via `/setup`, slash commands, and the dashboard.

See [CHANGELOG.md](CHANGELOG.md) for the detailed release history of every phase.

---

## Feature Highlights

### Violation Engine (v2.6+)
Central escalation pipeline. Every automod trigger records a named violation. When a user accumulates enough violations within a configurable time window, they are automatically jailed. Violations are separate from manual warns. Raids bypass violations and go straight to ban.

### AutoMod Pipeline (8 filters)
All filters run in order on every message. First match stops the chain. All feed violations.

1. Invite filter -- blocks Discord invite links
2. Link filter -- whitelist/blacklist domain matching with subdomain support
3. Anti-phishing -- checks URLs against SinkingYachts phishing database
4. Word list filter -- named deny lists, whole-word and phrase matching
5. Message length filter -- configurable min/max character thresholds
6. All-caps filter -- percentage threshold of uppercase characters
7. Per-channel slowmode -- bot-enforced rate limit per user per channel
8. Spam detection -- velocity, duplicates, mass mentions, emoji floods

### Severity Profiles (v2.9+)
Named sets of automod thresholds: normal (baseline), strict (lower thresholds), raid (aggressive, all filters on). Custom profiles snapshot current settings. Switching is instant. The raid profile auto-activates during lockdown and restores on unlock.

### Role Persistence (v2.6+)
Saves every member's roles on leave. Restores them automatically on rejoin for kicks, voluntary leaves, and softbans. Banned users get a fresh start (no role restore after unban + rejoin).

### Username/Nickname Filtering (v3.0)
Checks display names on join and nickname change. Configurable word list with Unicode confusable character normalization (Cyrillic lookalikes, l33tspeak, fullwidth characters mapped to ASCII before matching). Actions: log, kick, or ban.

### Verification Gate (v3.0)
New members must react to a posted verification message to gain a configured role. Until verified, they lack the gate role and server permissions control what they can see.

### Autoresponses (v3.1)
Define trigger words or phrases and the bot auto-replies when detected. Three match modes (contains, exact, starts with). Manageable via the dashboard or `/autoresponse` slash commands. Individual triggers can be enabled/disabled without deleting them.

### Onboarding and Roles
Guided `/setup`, 14 color self-roles, custom react-role menus, auto-role on join, welcome messages.

### ModMail
DM-to-ticket, `/reply` with anonymous option, `/close` builds a full transcript zip and archives to `#closed-tickets`.

### Moderation
`/kick`, `/ban`, `/unban`, `/tempban`, `/softban`, `/mute`, `/unmute`, `/warn`, `/unwarn`, `/history`, `/jail`, `/unjail`, `/tempjail`, `/purge`. Every action logged to `#mod-log`.

### Raid Response
Join velocity auto-triggers full lockdown. Verification level auto-raised, restored on unlock. Active-raid joiners auto-banned (configurable). Auto-unlock cooldown. Account age gate. Raid profile auto-activated. Manual `/lockdown` and `/unlock`.

### Forum Thread Management
`/delete` -- forum-thread owners can permanently delete their own threads via a two-step confirmation, logged to `#mod-log`.

### Notes, Reports, History
Private staff notes, user-submitted reports, unified per-user moderation timeline with 16 action types.

### React-Role Messages, Starboards, Streamer Alerts, Reminders
All previously listed features remain fully supported.

---

## Web Dashboard

The dashboard runs alongside the bot in the same process on `127.0.0.1:8000`. Not exposed to the internet by default -- front it with SSH tunnel, reverse proxy, Cloudflare Tunnel, or Tailscale for remote access.

| Page | What it does |
|---|---|
| **Dashboard** | Stats grid, recent activity (19 action types), active jails, 30-day warns trend, top offenders, AutoMod status (13 rows), bot health |
| **Mod Logs** | Filterable feed (action, user, date range), expandable rows, CSV export |
| **Warns** | Grouped per user, pardon, add-warn with type-ahead |
| **Notes** | Search, inline edit, add-note with type-ahead |
| **Tickets** | Open/closed/all filters, inline transcript viewer, reply, close |
| **Autoresponses** | Create, edit, toggle, delete trigger/response pairs with match mode selection |
| **Configuration** | Sectioned editor over ~120 columns, Bot Messages editor, Post-as-Bot |
| **Self-Roles** | Category builder with live preview |
| **Setup** | Guided setup mirror of `/setup` |

---

## Requirements

- **Python 3.11+**
- Discord bot token -- [Discord Developer Portal](https://discord.com/developers/applications)
- Bot must have **Administrator** in your server
- Port `8000` free on the host (loopback only)

### Bot Permissions

| Permission | Used by |
|---|---|
| Manage Roles / Channels | `/setup`, jail, raid lockdown, verification gate |
| Manage Messages | AutoMod delete, `/purge` |
| Moderate Members | `/mute`, AutoMod timeout |
| Kick / Ban Members | `/kick`, `/ban`, `/tempban`, name filter, AutoMod escalation, raid |
| Manage Guild | Raid auto-verification bump |
| Manage Threads | `/delete` |

### Required Intents

- Server Members Intent (for on_member_join, on_member_remove, on_member_update)
- Message Content Intent (for automod message scanning)

---

## Environment Variables

All environment variables are loaded from a `.env` file in the project root. Copy `.env.example` to `.env` and fill in your values.

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Bot token from the Discord Developer Portal |
| `DISCORD_CLIENT_ID` | For dashboard auth | OAuth2 application client ID |
| `DISCORD_CLIENT_SECRET` | For dashboard auth | OAuth2 application client secret |
| `DISCORD_REDIRECT_URI` | For dashboard auth | OAuth2 redirect URI (e.g. `http://localhost:8000/auth/callback`) |
| `MODSUITE_GUILD_ID` | For dashboard auth | Guild ID to restrict dashboard access to |
| `DASHBOARD_ALLOWED_ROLES` | For dashboard auth | Comma-separated role IDs that can access the dashboard |
| `API_HOST` | No | Host to bind the API server to (default: `0.0.0.0`) |
| `API_PORT` | No | Port for the API server (default: `8000`) |
| `CORS_ORIGINS` | No | Additional CORS origins, comma-separated (e.g. `http://myserver.com,http://10.0.0.5:8000`). Localhost origins are always allowed. |
| `TWITCH_CLIENT_ID` | For streamer alerts | Twitch API client ID (optional, only if using `/streamer`) |
| `TWITCH_CLIENT_SECRET` | For streamer alerts | Twitch API client secret (optional, only if using `/streamer`) |

### `.env.example`

```env
DISCORD_TOKEN=
DISCORD_CLIENT_ID=
DISCORD_CLIENT_SECRET=
DISCORD_REDIRECT_URI=
MODSUITE_GUILD_ID=
DASHBOARD_ALLOWED_ROLES=
API_HOST=0.0.0.0
API_PORT=8000
CORS_ORIGINS=
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
```

---

## Installation

```bash
git clone https://github.com/GreyHammond/ModSuite.git
cd ModSuite

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your values (at minimum: DISCORD_TOKEN)

python bot.py
```

The database (`communitybot.db`) auto-creates on first run. Schema auto-migrates on subsequent starts -- no manual SQL ever.

---

## First-Time Setup

1. Invite the bot with **Administrator**.
2. Run `/setup` as a server admin.
3. Click **Run Setup** -- creates all default roles, categories, channels, and the react-role message.
4. Open the dashboard at `http://127.0.0.1:8000` -- everything is now configurable visually.

---

## Accessing the Dashboard Remotely

The API binds to `0.0.0.0:8000` by default. For production, put authentication in front of it:

**SSH tunnel** (personal use, safest):
```bash
ssh -i your-key.pem -L 8000:127.0.0.1:8000 user@your-server
```
Then browse to `http://127.0.0.1:8000/`.

**Cloudflare Tunnel** (always-on, real HTTPS URL): `cloudflared tunnel create modsuite` -- see Cloudflare docs.

**Tailscale** (private mesh network): install on both, access via Tailscale IP.

**nginx reverse proxy** (real domain): install nginx + Let's Encrypt cert + basic auth.

---

## Command Reference

### Setup and Config
`/setup`, `/setmessage`, `/viewmessages`, `/resetmessage`, `/presence`, `/say`

### ModMail
`/reply`, `/close`

### Moderation
`/kick`, `/ban`, `/unban`, `/tempban`, `/softban`, `/mute`, `/unmute`, `/purge`

### Warns
`/warn`, `/unwarn`, `/history`

### Jail
`/jail`, `/unjail`, `/tempjail`, `/setautojail`

### Notes
`/note`, `/notes`, `/delnote`

### Violations
`/violations check`, `/violations clear`, `/violations threshold`, `/violations duration`

### AutoMod
`/automod status` | `spam` | `spam_threshold` | `spam_action` | `links` | `link_mode` | `link_add` | `link_remove` | `link_list` | `link_action` | `link_bypass_channel` | `link_bypass_role` | `invites` | `invite_action` | `immune` | `antiphish` | `max_length` | `min_length` | `allcaps` | `allcaps_threshold` | `slowmode` | `slowmode_interval` | `slowmode_channel` | `wordlist` | `wordlist_add` | `wordlist_remove` | `wordlist_view` | `wordlist_delete`

### Raid
`/lockdown`, `/unlock`, `/autorole`, `/raidcfg threshold` | `account_age` | `action` | `auto_verification` | `cooldown`

### Profiles
`/profile switch` | `list` | `view` | `create` | `delete`

### Name Filter
`/namefilter toggle` | `action` | `confusables` | `add` | `remove` | `list`

### Verification Gate
`/verifygate toggle` | `role` | `channel` | `post` | `status`

### Autoresponses
`/autoresponse add` | `remove` | `list`

### React Roles
`/createreactmessage`, `/addrole`, `/editrole`, `/deleterole`, `/editreactmessage`, `/publishreactmessage`, `/cancelreactmessage`

### Starboard
`/starboard create` | `delete` | `threshold` | `addemoji` | `removeemoji` | `list`

### Streamer
`/streamer add` | `remove` | `edit`, `/links add` | `remove` | `list`

### Utility
`/verify`, `/unverify`, `/move`, `/delete`, `/timezone`, `/remindme`, `/reminders`

### Panels
`/panel`, `/mod`, `/userinfo`, `/serverinfo`

---

## REST API

FastAPI backend on port 8000. Swagger UI at `/docs`. API version 3.0.0.

| Group | Endpoints |
|---|---|
| Dashboard | `GET /dashboard/stats`, `/dashboard/activity`, `/health`, `/warns/trends`, `/top-offenders`, `/automod/summary` |
| Config | `GET/PUT /config`, `GET /config-schema`, `GET/PUT/DELETE /bot-messages/{slot}` |
| Warns | `GET /warns`, `POST /warns`, `DELETE /warns/{id}` |
| Notes | `GET /notes`, `POST /notes`, `PUT /notes/{id}`, `DELETE /notes/{id}` |
| Tickets | `GET /tickets`, `GET /tickets/{id}`, `GET /tickets/{id}/transcript`, `POST /tickets/{id}/reply`, `POST /tickets/{id}/close` |
| Violations | `GET /violations/summary`, `GET /violations/{user_id}` |
| Profiles | `GET /profiles`, `PUT /profiles/active` |
| Timed Bans | `GET /timed-bans` |
| Word Lists | `GET /word-lists` |
| Users | `GET /users/search` |
| ModLogs | `GET /modlogs` (with action, user, date filters) |
| Self-Roles | `GET/POST/PUT/DELETE /selfroles/categories` |
| Utility | `GET /channels`, `GET /jails`, `POST /post-as-bot` |

---

## File Structure

```
ModSuite/
|-- bot.py               # Bot entry point + action-queue poller
|-- api.py               # FastAPI REST API (39 endpoints)
|-- auth.py              # Discord OAuth2 for dashboard
|-- config.py            # Constants, defaults, role definitions
|-- database.py          # SQLite layer with auto-migrating schema (27 tables)
|-- utils.py             # Shared helpers (permissions, templates, formatting)
|-- requirements.txt
|-- .env.example
|-- CHANGELOG.md
|-- cogs/                # 25 cogs
|   |-- setup.py         # /setup wizard + 13 config panels
|   |-- automod.py       # 8-filter message pipeline
|   |-- autoresponse.py  # Trigger-based automatic replies
|   |-- violations.py    # Violation counter engine
|   |-- profiles.py      # Severity profile management
|   |-- namefilter.py    # Username/nickname filter + verification gate
|   |-- moderation.py    # kick/ban/tempban/mute/softban + role persistence
|   |-- raid.py          # Raid detection, lockdown, auto-profile
|   |-- warns.py         # Warn system + /history
|   |-- jail.py          # Jail system with temp-jail
|   |-- panel.py         # /panel and /mod context-aware UI (10 buttons, 8 modals)
|   |-- modmail.py       # DM-to-ticket system
|   |-- userinfo.py      # /userinfo, /serverinfo, /purge
|   |-- honeypot.py      # Honeypot channels
|   |-- notes.py         # Staff notes
|   |-- reports.py       # User reports
|   |-- messages.py      # Bot message slot management
|   |-- verify.py        # Age verification (18+)
|   |-- selfroles.py     # Reaction role assignment
|   |-- reactmessage.py  # Custom react-role message builder
|   |-- starboard.py     # Starboard system
|   |-- streamer.py      # Twitch streamer alerts
|   |-- remindme.py      # Reminders
|   |-- move.py          # /move command
|   |-- threads.py       # Forum thread management
|   |-- admin.py         # Presence, /say
|-- web/                 # Vanilla JS SPA
    |-- api.js           # Relative-URL API client
    |-- index.html
    |-- router.js
    |-- shell/           # Layout, sidebar, topbar
    |-- pages/           # 8 dashboard pages
    |-- styles/          # CSS tokens, shell, page styles
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Bot can't create roles/channels | Ensure Administrator in server settings |
| Slash commands not appearing | Check "Use Application Commands" on the channel/category |
| `/delete` fails | Bot needs "Manage Threads" on the forum |
| AutoMod not deleting messages | Bot needs "Manage Messages" |
| AutoMod mute failing | Bot needs "Moderate Members" |
| Raid auto-verification failing | Bot needs "Manage Guild" |
| Name filter not catching evasion | Enable confusable normalization (`/namefilter confusables true`) |
| Verification gate not granting role | Check bot has Manage Roles and the gate role is below the bot's role |
| Dashboard shows "Could not load data" | Bot process must be running |
| Dashboard actions delayed 5s | Expected -- action queue polls every 5 seconds |
| Schema migration | Automatic on startup -- just restart the bot after updating |
| Anti-phishing not blocking | Check `/automod antiphish` is on; the API may be temporarily down (fails open) |

---

## License and Credits

Developed and maintained by **Hammond Digital Studios**.

Built on discord.py 2.4+, FastAPI, Uvicorn, aiohttp, vanilla JavaScript, and SQLite. No build step, no framework tax.

See [CHANGELOG.md](CHANGELOG.md) for the full release history.
