# ModSuite 🛡️

**Version 2.5** — A full-stack Discord community & moderation platform for self-hosted servers, now with a fully operational web dashboard.

ModSuite is a Python bot + FastAPI backend + web dashboard, purpose-built for community owners who want *one* system to handle onboarding, self-roles, ModMail, moderation, warns, jail, notes, reports, starboard, streamer alerts, react-role messages, reminders, forum thread management, AutoMod, and raid response — configured once via `/setup` and manageable end-to-end from Discord *or* the browser.

> MODSUITE is part of the specialized suite of tools developed by **Hammond Digital Studios**.

---

## ✨ What's New in v2.5

The web dashboard is now a full operational tool, not just a read-only monitor.

- **Dashboard** now includes bot health (uptime, latency, memory), 30-day warns trend chart, top offenders card, and an AutoMod status tile.
- **Configuration** page is a sectioned editor for every one of the ~90 config columns (General / Warns / Raid / AutoMod Spam / Links / Invites / Immune Roles), with a persistent Bot Messages editor and Post-as-Bot composer below.
- **Warns**: add warns from the web with type-ahead user search. The bot DMs the user and logs to `#mod-log`.
- **Notes**: add and inline-edit notes from the web.
- **Mod Logs**: date range, user filter, action-type filter, expandable rows with full metadata, CSV export.
- **Tickets**: click any ticket to see its inline transcript. Reply to open tickets from the web (regular or anonymous). Close tickets from the web — the bot builds the transcript, archives it to `#closed-tickets`, and deletes the channel just like `/close`.
- **Server selector** hidden (single-guild).
- **Frontend uses relative URLs** — same-origin, works over SSH tunnel, reverse proxy, or direct.

---

## 🚀 Feature Highlights

### 👥 Onboarding & Roles
Guided `/setup`, 14 color self-roles, custom react-role menus, auto-role on join, verify gate, welcome messages.

### 📬 ModMail
DM-to-ticket, `/reply` with anonymous option, `/close` builds a full transcript zip and archives to `#closed-tickets`.

### 🔨 Moderation
`/kick`, `/ban`, `/unban`, `/softban`, `/mute`, `/unmute`, `/warn`, `/unwarn`, `/history`, `/jail`, `/unjail`, `/tempjail`, `/purge`. Every action logged to `#mod-log`.

### 🛡️ AutoMod
Spam velocity, duplicates, mention floods, emoji floods. Link whitelist/blacklist with per-role and per-channel bypass. Discord invite filter as a separate toggle. Immune roles for trusted members. Filter chain ordering prevents double-punishment. Configure via `/automod` command group or the web dashboard.

### 🚨 Raid Response
Join velocity auto-triggers full lockdown. Verification level auto-raised, restored on unlock. Active-raid joiners auto-kicked or banned. Auto-unlock cooldown. Account age gate. Manual `/lockdown` and `/unlock`. Configure via `/raidcfg` or the web dashboard.

### 🧵 Forum Thread Management
`/delete` — forum-thread owners can permanently delete their own threads via a two-step confirmation, logged to `#mod-log`.

### 📝 Notes, Reports, History
Private staff notes, user-submitted reports, unified per-user moderation timeline.

### 🎨 React-Role Messages, ⭐ Starboards, 📺 Streamer Alerts, ⏰ Reminders
All previously listed features remain fully supported.

---

## 🖥️ Web Dashboard

The dashboard runs alongside the bot in the same process on `127.0.0.1:8000`. Not exposed to the internet by default — front it with SSH tunnel, reverse proxy, Cloudflare Tunnel, or Tailscale for remote access.

| Page | What it does |
|---|---|
| **Dashboard** | Stats grid · recent activity · active jails · 30-day warns trend · top offenders · AutoMod status · bot health |
| **Mod Logs** | Filterable feed (action, user, date range) · expandable rows · CSV export |
| **Warns** | Grouped per user · pardon · add-warn with type-ahead |
| **Notes** | Search · inline edit · add-note with type-ahead |
| **Tickets** | Open/closed/all filters · inline transcript viewer · reply · close |
| **Configuration** | Sectioned editor over ~90 columns · Bot Messages editor · Post-as-Bot |
| **Self-Roles** | Category builder with live preview |
| **Setup** | Guided setup mirror of `/setup` |

---

## 📋 Requirements

- **Python 3.11+**
- Discord bot token — [Discord Developer Portal](https://discord.com/developers/applications)
- Bot must have **Administrator** in your server
- Port `8000` free on the host (loopback only)

### Bot Permissions

| Permission | Used by |
|---|---|
| Manage Roles / Channels | `/setup`, jail, raid lockdown |
| Manage Messages | AutoMod delete, `/purge` |
| Moderate Members | `/mute`, AutoMod timeout |
| Kick / Ban Members | `/kick`, `/ban`, AutoMod escalation, active-raid blocking |
| Manage Guild | Raid auto-verification bump |
| Manage Threads | `/delete` |

### Required Intents

- ✅ Server Members Intent
- ✅ Message Content Intent

---

## 🔧 Installation

```bash
git clone https://github.com/GreyHammond/modsuite.git
cd modsuite/modsuite_v2

python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env → DISCORD_TOKEN=your_token_here

python bot.py
```

The database (`communitybot.db`) auto-creates on first run. Schema auto-migrates on subsequent starts — no manual SQL ever.

---

## ⚡ First-Time Setup

1. Invite the bot with **Administrator**.
2. Run `/setup` as a server admin.
3. Click **Run Setup** — creates all default roles, categories, channels, and the react-role message.
4. Open the dashboard in your browser — everything is now configurable visually.

---

## 🌐 Accessing the Dashboard Remotely

The API binds to `127.0.0.1:8000` (loopback) by default — safe by construction. Pick the option that suits you:

**SSH tunnel** (personal use, safest):
```bash
ssh -i your-key.pem -L 8000:127.0.0.1:8000 user@your-server
```
Then browse to `http://127.0.0.1:8000/`.

**Cloudflare Tunnel** (always-on, real HTTPS URL): `cloudflared tunnel create modsuite` — see Cloudflare docs.

**Tailscale** (private mesh network): install on both, access via Tailscale IP.

**nginx reverse proxy** (real domain): install nginx + Let's Encrypt cert + basic auth.

Do NOT bind the API to `0.0.0.0` without one of these layers in front.

---

## 📖 Command Reference

See the [website](https://greyhammond.github.io/ModSuite/#commands) for the complete filterable command list. Quick summary:

- **Setup & Config** — `/setup`, `/setmessage`, `/viewmessages`, `/resetmessage`, `/presence`, `/say`
- **ModMail** — `/reply`, `/close`
- **Moderation** — `/kick`, `/ban`, `/unban`, `/softban`, `/mute`, `/unmute`, `/purge`
- **Warns** — `/warn`, `/unwarn`, `/history`
- **Jail** — `/jail`, `/unjail`, `/tempjail`, `/setautojail`
- **Notes** — `/note`, `/notes`, `/delnote`
- **AutoMod** — `/automod status|spam|spam_threshold|spam_action|links|link_mode|link_add|link_remove|link_action|link_bypass_channel|link_bypass_role|invites|invite_action|immune`
- **Raid** — `/lockdown`, `/unlock`, `/autorole`, `/raidcfg threshold|account_age|action|auto_verification|cooldown`
- **React Roles** — `/createreactmessage`, `/addrole`, `/editrole`, `/deleterole`, `/editreactmessage`, `/publishreactmessage`, `/cancelreactmessage`
- **Starboard** — `/starboard create|delete|threshold|addemoji|removeemoji|list`
- **Streamer** — `/streamer add|remove|edit`, `/links add|remove|list`
- **Reminders** — `/timezone`, `/remindme`, `/reminders`
- **Panels** — `/panel`, `/mod`, `/userinfo`, `/serverinfo`
- **Verify / Utility / Threads** — `/verify`, `/unverify`, `/move`, `/delete`

---

## 🌐 REST API

FastAPI backend on `127.0.0.1:8000`. Swagger UI at `/docs`.

Key endpoints:

| Group | Endpoints |
|---|---|
| Dashboard | `GET /dashboard/stats`, `/dashboard/activity`, `/health`, `/warns/trends`, `/top-offenders`, `/automod/summary` |
| Config | `GET/PUT /config`, `GET /config-schema`, `GET/PUT/DELETE /bot-messages/{slot}` |
| Warns | `GET /warns`, `POST /warns`, `DELETE /warns/{id}` |
| Notes | `GET /notes`, `POST /notes`, `PUT /notes/{id}`, `DELETE /notes/{id}` |
| Tickets | `GET /tickets`, `GET /tickets/{id}`, `GET /tickets/{id}/transcript`, `POST /tickets/{id}/reply`, `POST /tickets/{id}/close` |
| Users | `GET /users/search` |
| ModLogs | `GET /modlogs` (with filters) |
| Utility | `GET /channels`, `GET /jails`, `POST /post-as-bot` |

Web frontend served at `/` via `StaticFiles` mount.

---

## 📁 File Structure

```
modsuite_v2/
├── bot.py               # Bot entry point + action-queue poller (with dashboard action handlers)
├── api.py               # FastAPI REST API + web dashboard mount
├── config.py            # Constants, color role definitions, default messages
├── database.py          # SQLite layer with auto-migrating schema
├── utils.py             # Shared helpers
├── requirements.txt
├── .env.example
├── cogs/                # 21 cogs
└── web/                 # Vanilla JS SPA
    ├── api.js           # Relative-URL API client
    ├── index.html
    ├── router.js
    ├── shell/           # layout / sidebar / topbar
    ├── pages/           # 8 pages
    └── styles/          # tokens / shell / pages
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| Bot can't create roles/channels | Ensure Administrator in server settings |
| Slash commands not appearing for members | Check "Use Application Commands" on the channel/category |
| `/delete` fails | Bot needs "Manage Threads" on the forum |
| AutoMod not deleting messages | Bot needs "Manage Messages" |
| AutoMod mute failing | Bot needs "Moderate Members" |
| Raid auto-verification failing | Bot needs "Manage Guild" |
| Dashboard shows "Could not load data" | Bot process must be running |
| Dashboard actions delayed 5s | Expected — action queue polls every 5 seconds |
| Schema migration | Automatic on startup — just restart the bot after updating |

---

## 📜 License & Credits

Developed and maintained by **Hammond Digital Studios**.

Built on discord.py 2.4+, FastAPI, Uvicorn, vanilla JavaScript, and SQLite. No build step, no framework tax.

See [CHANGELOG.md](CHANGELOG.md) for release history.
