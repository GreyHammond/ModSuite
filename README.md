<div align="center">

# ModSuite

**A self-hosted Discord moderation suite built with Python and discord.py**

[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.4+-5865f2?style=flat-square&logo=discord&logoColor=white)](https://discordpy.readthedocs.io)
[![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.0-eb459e?style=flat-square)](CHANGELOG.md)

One `/setup` command. Everything built automatically.

</div>

---

## Features

| | Feature | Description |
|---|---|---|
| 📬 | **ModMail** | Users DM the bot to open a private staff ticket. Staff reply with optional anonymity. Transcripts zipped and archived on close. |
| 🔒 | **Jail System** | Pull a user aside privately. Strips all roles, creates a dedicated channel, restores everything on unjail. Full transcript archived. |
| 🛡️ | **Mod Panel** | Persistent button UI for staff who prefer clicks over commands. Context-aware — shows different controls in jail, modmail, and general channels. |
| 🎨 | **Self-Roles** | 14 color roles via emoji reactions. One color at a time enforced. Unknown reactions removed automatically. |
| ⚠️ | **Warn System** | Per-user warning tracking with configurable auto-mute and auto-ban thresholds set in `/setup`. |
| 🚨 | **Raid Protection** | Monitors join rate, auto-locks server on detection. Configurable thresholds. Manual `/lockdown` and `/unlock` included. |
| 🚩 | **Message Reports** | Right-click any message → Apps → Report. Anonymous. Standard reports ping Moderators. Emergency reports blast all staff. |
| 💾 | **Auto-Migration** | SQLite with automatic schema migration. Update the bot and restart — new columns added without touching existing data. |
| 📋 | **Mod Log** | Every action logged automatically to a dedicated staff-only channel. |

---

## Requirements

- Python **3.11+**
- A Discord bot token — [Discord Developer Portal](https://discord.com/developers/applications)
- Bot must have **Administrator** permission in your server

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/modsuite.git
cd modsuite

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your token
cp .env.example .env
# Edit .env and paste your bot token

# 4. Start the bot
python bot.py
```

---

## Discord Developer Portal — Required Settings

In your application → **Bot**, enable:

- ✅ Server Members Intent
- ✅ Message Content Intent

In **OAuth2 → URL Generator**, select scopes:

- ✅ `bot`
- ✅ `applications.commands`

---

## First-Time Setup

1. Invite the bot using your generated OAuth2 URL with **Administrator** permission
2. Run `/setup` as a server administrator
3. *(Optional)* Click **Customise Messages** to set welcome text, self-roles message, and ModMail greeting
4. *(Optional)* Click **Warn & Raid Settings** to configure auto-escalation thresholds
5. Click **Run Setup** — the bot will automatically create:
   - 14 color roles + Owner (green) + Moderator (red)
   - `ModMail` category with `#modmail`, `#mod-log`, `#closed-tickets`, `#mod-panel`, `#reports`
   - `Jail` category for private jail channels
   - `#self-roles` with the reaction message posted and ready
6. Run `/panel` in a staff channel to post the persistent Mod Panel

---

## Commands

### Everyone

| Command | Description |
|---|---|
| `/userinfo [@user]` | View user info. Staff also see warn count and jail status. |
| `/serverinfo` | View server info — member count, boosts, creation date. |
| Right-click → **Report Message** | Anonymously report a message to Moderators. |
| Right-click → **Report Message (Emergency)** | Anonymously alert all staff immediately. |

### Staff (Owner or Moderator role)

| Command | Description |
|---|---|
| `/mod` | Open the ephemeral context-aware panel in any channel. |
| `/warn @user <reason>` | Warn a member. Auto-escalates at configured thresholds. |
| `/unwarn <warn_id>` | Remove a specific warning by ID. |
| `/history @user` | View full moderation history for a user. |
| `/mute @user [duration] [reason]` | Timeout a member. Duration: `10m`, `2h30m`, `1d`. Default: 30 days. |
| `/unmute @user [reason]` | Remove a member's timeout. |
| `/kick @user [reason]` | Kick a member. |
| `/ban @user [reason]` | Ban a member. |
| `/unban <user_id> [reason]` | Unban a user by ID. |
| `/jail @user [reason] [notify]` | Jail a member — strips roles, opens private channel. |
| `/unjail @user` | Release a jailed member and restore all roles. |
| `/reply <message> [anonymous]` | Reply to the current ModMail ticket. |
| `/close` | Close and archive the current ModMail ticket. |
| `/purge <amount>` | Bulk delete up to 100 messages. |
| `/lockdown` | Manually lock all channels. |
| `/unlock` | Lift lockdown and restore channel access. |
| `/panel` | Post the persistent Mod Panel in this channel. |

### Admin Only

| Command | Description |
|---|---|
| `/setup` | Run guided server setup. Safe to re-run. |
| `/autorole [@role]` | Set a role to auto-assign to new members. Omit to disable. |

---

## Mute Duration Format

| Input | Result |
|---|---|
| *(omitted)* | 30 days (default) |
| `10m` | 10 minutes |
| `2h` | 2 hours |
| `1d` | 1 day |
| `2h30m` | 2 hours 30 minutes |
| `1d12h` | 1 day and 12 hours |

---

## ModMail Flow

```
User DMs bot
  ↓
Bot sends opening message to user
Bot creates #ticket-username in ModMail category
Bot pings Owner & Moderator in #modmail
  ↓
Staff use [Reply] button or /reply in ticket channel
  /reply anonymous:True  → user sees "Staff"
  /reply anonymous:False → user sees staff member's name
  ↓
[Close Ticket] or /close
  → Transcript built → zipped as MMDDYYYY-username.zip
  → Posted to #closed-tickets
  → User notified
  → Ticket channel deleted
```

---

## Jail Flow

```
/jail @user [reason] [notify]
  ↓
All assignable roles stripped and saved to DB
Private #jail-username channel created in Jail category
Staff can see and message the channel
Optional DM sent to user
  ↓
/unjail @user
  → All original roles restored
  → Transcript zipped and posted to #closed-tickets
  → Jail channel deleted
  → User DM'd that they've been released
```

---

## Project Structure

```
modsuite/
├── bot.py              # Entry point — loads cogs, syncs commands
├── config.py           # Constants, color role definitions, default messages
├── database.py         # SQLite layer with auto-migration
├── requirements.txt
├── .env.example
└── cogs/
    ├── setup.py        # /setup with ephemeral panel UI
    ├── selfroles.py    # Reaction listener → color role assignment
    ├── modmail.py      # DM intake, ticket channels, reply, close, archive
    ├── moderation.py   # kick/ban/mute/unmute + auto-unmute loop + welcome
    ├── warns.py        # /warn, /unwarn, /history + auto-escalation
    ├── jail.py         # /jail, /unjail + role save/restore + transcript
    ├── userinfo.py     # /userinfo, /serverinfo, /purge
    ├── raid.py         # Raid detection, auto-lockdown, /lockdown, /unlock, auto-role
    ├── panel.py        # /panel (persistent) + /mod (ephemeral, context-aware)
    └── reports.py      # Right-click Report Message + Emergency Report
```

---

## Adding New DB Columns

The database uses automatic migration. To add a new column:

1. Add it to the `GUILD_CONFIG_COLUMNS` list in `database.py`
2. Restart the bot — the column is added automatically to all existing databases

No data is lost. No manual SQL required.

---

## License

MIT — see [LICENSE](LICENSE) for details.

---

<div align="center">
Made with Python · <a href="https://discordpy.readthedocs.io">discord.py</a>
</div>
