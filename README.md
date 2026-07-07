# ModSuite 🛡️

**Version 2.2** — A full-stack Discord community & moderation platform for self-hosted servers.

ModSuite is an all-in-one Python bot + FastAPI backend + web dashboard, purpose-built for community owners who want *one* system to handle onboarding, self-roles, ModMail, moderation, warns, jail, notes, reports, starboard, streamer alerts, react-role messages, reminders, forum thread management, AutoMod (spam / link / invite filtering), and raid response — configured once via `/setup` and manageable from Discord or the web UI.

> MODSUITE is part of the specialized suite of tools developed by **Hammond Digital Studios**. Our focus is on creating robust, creative, and functional digital assets for community management and production workflows.

---

## ✨ What's in the Box

| Layer | What it does |
|---|---|
| **Discord Bot** | 20 cogs covering every server-management surface |
| **REST API** | FastAPI on `127.0.0.1:8000`, launched in-process alongside the bot |
| **Web Dashboard** | Static SPA (vanilla JS + hash router) for dashboard, tickets, warns, notes, mod-logs, self-roles, and configuration |
| **SQLite Persistence** | Single-file DB — configs, tickets, warns, notes, reactroles, starboards, streamers, reminders all survive restarts |
| **Auto-Migrating Schema** | Add columns to `GUILD_CONFIG_COLUMNS` and they migrate on next restart — no manual SQL |
| **Bot Actions Queue** | Cross-process action polling (5s interval) so the web UI can queue Discord actions safely |

---

## 🚀 Feature Highlights

### 👥 Onboarding & Roles
- **Guided `/setup`** — Admin-only wizard creates all roles, categories, channels, and the react-role message in one shot.
- **Color Self-Roles** — 14 default color roles; users react in `#self-roles` to pick one. Bot enforces one color at a time.
- **Custom Self-Role Categories** — Build arbitrary reaction-role menus beyond the default color set, managed from the web UI.
- **Auto-Role on Join** — Configurable via `/autorole`.
- **Verify Gate** — Optional `/verify` / `/unverify` flow for gated servers.
- **Welcome Messages** — Customisable greeting with `{server}` / `{user}` variables.

### 📬 ModMail
- **DM-to-Ticket** — Any DM to the bot opens a private staff channel and pings your Owner + Moderator roles.
- **Reply Modal & Slash Command** — `/reply` or the persistent **💬 Reply** button; anonymous mode sends as *"Staff"*.
- **Close & Archive** — `/close` or the **🔒 Close Ticket** button builds a full transcript, packages it as `MMDDYYYY-username.zip`, and posts it to `#closed-tickets`.

### 🔨 Moderation & Enforcement
- `/kick`, `/ban`, `/unban`, `/softban` — full audit-log to `#mod-log`.
- `/mute`, `/unmute` — timeouts with flexible durations (`10m`, `2h30m`, `1d12h`, or default 30 days).
- `/warn`, `/unwarn`, `/history` — warning system with configurable auto-mute and auto-ban thresholds.
- `/jail`, `/unjail`, `/tempjail` — strips a member's roles and drops them in a private jail channel; roles restored on release.
- `/purge` — bulk message delete.

### 🛡️ AutoMod *(new in v2.2)*
- **Spam Detection** — configurable per-user message velocity, duplicate detection, mention-flood and emoji-flood limits. Default action: delete + 10-minute timeout.
- **Link Filtering** — whitelist or blacklist mode, with per-role and per-channel bypass. Preset whitelist covers Discord, YouTube, GitHub, Twitter/X, Tenor, Giphy. Preset blacklist blocks common IP loggers.
- **Invite Filtering** — dedicated Discord-invite toggle so you can allow other links but block invites (or vice versa).
- **Immune Roles** — exempt specific roles from all AutoMod filters.
- **Filter Chain Ordering** — invites → links → spam, first match wins, so a user is never double-punished for the same message.
- Configure via `/automod` command group. `/automod status` shows the full current state in one embed.

### 🚨 Raid Response *(upgraded in v2.2)*
- **Join Velocity Detection** — configurable N joins in S seconds auto-triggers lockdown.
- **Active-Raid Blocking** — new joiners during lockdown are auto-kicked or auto-banned (configurable).
- **Auto-Verification Bump** — raises server verification level to highest during lockdown; restores previous level on unlock.
- **Auto-Unlock Cooldown** — lockdown lifts automatically after a configurable window (default 5 min; set to 0 for manual-only).
- **Account Age Gate** — flags joins from accounts younger than N days in mod-log.
- **Manual Override** — `/lockdown` and `/unlock` for on-demand response.
- Configure via `/raidcfg` command group.

### 🧵 Forum Thread Management *(v2.1)*
- **`/delete`** — Forum-thread owners can permanently delete their own threads via a two-step confirmation. Deletions are logged to `#mod-log` (user, thread name, timestamp).

### 📝 Notes, Reports & History
- `/note`, `/notes`, `/delnote` — private staff notes never visible to the subject.
- **User reports** — members can flag content for staff review.
- `/history` — unified moderation timeline per user.

### 🎨 React-Role Messages
- Build multi-role react-message menus with `/createreactmessage`, then `/addrole` / `/editrole` / `/deleterole` / `/publishreactmessage`.
- Edit live messages with `/editreactmessage`.

### ⭐ Starboard
- `/starboard create`, `/starboard delete`, `/starboard threshold`, `/starboard list`
- `/starboard addemoji`, `/starboard removeemoji` — support multiple reaction emojis per board.

### 📺 Streamer Alerts
- `/streamer add`, `/streamer remove`, `/streamer edit` — track streamers and post go-live notifications.
- `/links add`, `/links remove`, `/links list` — manage supplementary streamer links.

### ⏰ Reminders
- `/timezone` — set your personal timezone once.
- `/remindme` — schedule reminders in human time (`2h`, `tomorrow 9am`, etc.).
- `/reminders` — list your scheduled reminders.

### 🎛️ Admin & Ops
- `/say` — post a message as the bot.
- `/presence` — change the bot's Discord activity at runtime.
- `/panel` — post the persistent Mod Panel in a channel.
- `/mod` — open the ephemeral Mod Panel on demand.
- `/userinfo`, `/serverinfo` — quick lookups.
- `/setmessage`, `/viewmessages`, `/resetmessage` — manage the bot's customisable message templates.
- `/move` — move a conversation to a new channel.

---

## 🖥️ Web Dashboard

ModSuite ships with a lightweight web UI (no build step, no framework) that reads from and writes to the FastAPI backend running alongside the bot.

| Page | Purpose |
|---|---|
| **Dashboard** | At-a-glance server health and activity |
| **Setup** | Guided setup mirror of the `/setup` slash command |
| **Configuration** | Edit every persisted config value (channels, roles, thresholds, messages, AutoMod rules) |
| **Tickets** | Browse open + closed ModMail tickets and read archived transcripts |
| **Warns** | Review the full warning history across the server |
| **Notes** | Staff-only note board, per-user |
| **Mod Logs** | Filterable moderation action feed |
| **Self-Roles** | Build and preview custom self-role categories |

The API listens on `127.0.0.1:8000` and is **not** exposed to the internet by default. Front it with a reverse proxy (nginx, Caddy) with auth if you want remote access.

---

## 📋 Requirements

- **Python 3.11+**
- A Discord bot token — [Discord Developer Portal](https://discord.com/developers/applications)
- Bot must have **Administrator** permission in your server
- Port `8000` free on the host (loopback only)

### Bot Permissions Checklist

For everything to work end-to-end, the bot needs (all covered by **Administrator**):

| Permission | Used by |
|---|---|
| Manage Roles / Channels | `/setup`, jail, raid lockdown |
| Manage Messages | AutoMod delete, `/purge` |
| Moderate Members | `/mute`, AutoMod timeout action |
| Kick / Ban Members | `/kick`, `/ban`, AutoMod escalation, active-raid blocking |
| Manage Guild | Raid auto-verification bump |
| Manage Threads | `/delete` (forum thread owner deletion) |

---

## 🔧 Installation

```bash
# 1. Clone the repo
git clone https://github.com/GreyHammond/modsuite.git
cd modsuite/modsuite_v2

# 2. Create a virtualenv (recommended)
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure your token
cp .env.example .env
# Edit .env and paste your bot token:
#   DISCORD_TOKEN=your_token_here

# 5. Run the bot (this also starts the API + web frontend)
python bot.py
```

The database (`communitybot.db`) auto-creates on first run.

### Required Bot Intents

In the Discord Developer Portal → your application → **Bot**, enable:

- ✅ **Server Members Intent**
- ✅ **Message Content Intent**

Presence Intent is optional and only needed if you want richer presence data in the dashboard.

---

## ⚡ First-Time Setup

1. Invite the bot to your server with **Administrator** permission.
2. Run `/setup` as a server administrator.
3. *(Optional)* Click **Customise Messages** to set your welcome text, self-roles message, and ModMail greeting.
4. Click **Run Setup** — the bot creates all default roles, categories, channels, and posts the react-role message.
5. Run `/automod status` to review AutoMod defaults, then enable/adjust filters as needed.
6. Open the web dashboard in your browser (or via reverse proxy) to configure everything else visually.

---

## 📖 Command Reference

See the full command list in the [website](https://greyhammond.github.io/modsuite/#commands), or browse by category:

- **Setup & Config:** `/setup`, `/setmessage`, `/viewmessages`, `/resetmessage`, `/presence`, `/say`
- **ModMail:** `/reply`, `/close`
- **Moderation:** `/kick`, `/ban`, `/unban`, `/softban`, `/mute`, `/unmute`, `/purge`
- **Warns:** `/warn`, `/unwarn`, `/history`
- **Jail:** `/jail`, `/unjail`, `/tempjail`, `/setautojail`
- **Notes:** `/note`, `/notes`, `/delnote`
- **AutoMod:** `/automod status|spam|spam_threshold|spam_action|links|link_mode|link_add|link_remove|link_action|link_bypass_channel|link_bypass_role|invites|invite_action|immune`
- **Raid:** `/lockdown`, `/unlock`, `/autorole`, `/raidcfg threshold|account_age|action|auto_verification|cooldown`
- **React Roles:** `/createreactmessage`, `/setreactmessage`, `/addrole`, `/editrole`, `/deleterole`, `/editreactmessage`, `/publishreactmessage`, `/cancelreactmessage`
- **Starboard:** `/starboard create|delete|threshold|addemoji|removeemoji|list`
- **Streamer:** `/streamer add|remove|edit`, `/links add|remove|list`
- **Reminders:** `/timezone`, `/remindme`, `/reminders`
- **Panels & Info:** `/panel`, `/mod`, `/userinfo`, `/serverinfo`
- **Verify:** `/verify`, `/unverify`
- **Utility:** `/move`
- **Forum Threads:** `/delete`

### Duration Format (used by `/mute`, `/tempjail`, etc.)

| Input | Result |
|---|---|
| *(omitted)* | Command's default (e.g. `/mute` defaults to 30 days) |
| `10m` | 10 minutes |
| `2h` | 2 hours |
| `1d` | 1 day |
| `2h30m` | 2 hours 30 minutes |
| `1d12h` | 1 day 12 hours |

---

## 📁 File Structure

```
modsuite_v2/
├── bot.py               # Bot entry point + action-queue poller
├── api.py               # FastAPI REST API (loopback :8000)
├── config.py            # Constants, color role definitions, default messages
├── database.py          # SQLite layer (config, tickets, warns, notes, etc.)
├── utils.py             # Shared helpers, defaults, hierarchy checks
├── requirements.txt
├── .env.example
├── communitybot.db      # Auto-created on first run
├── cogs/                # 20 cogs: setup, selfroles, modmail, moderation,
│                        #   warns, jail, userinfo, raid, panel, reports,
│                        #   notes, admin, messages, verify, reactmessage,
│                        #   remindme, move, starboard, streamer,
│                        #   threads (v2.1), automod (v2.2)
└── web/                 # Vanilla JS dashboard (no build step)
```

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| Bot can't create roles/channels | Ensure the bot has **Administrator** in server settings |
| Slash commands not appearing for regular users | Check **Use Application Commands** permission on the channel (or category) for the affected role |
| `/delete` fails with "cannot delete thread" | Bot needs **Manage Threads** on the forum channel |
| AutoMod not deleting messages | Bot needs **Manage Messages** in the channel |
| AutoMod mute action failing | Bot needs **Moderate Members** |
| Auto-verification bump during raid failing | Bot needs **Manage Guild** |
| Slash commands not appearing at all | Wait up to 1 hour for global sync, or restart the bot |
| Bot not responding to DMs | Ensure **Message Content Intent** is enabled |
| Web dashboard shows "connection refused" | The bot process must be running — the API is launched by `bot.py` |
| Actions from the web UI don't apply for ~5s | Expected — the action queue polls every 5 seconds |
| Missing config columns after update | The schema auto-migrates on next startup — restart the bot |

---

## 📜 License & Credits

MODSUITE is developed and maintained by **Hammond Digital Studios**.

Built on:
- [discord.py](https://github.com/Rapptz/discord.py) 2.4+
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/)
- Vanilla JS + SQLite — no build step, no framework tax

See [CHANGELOG.md](CHANGELOG.md) for release history.
