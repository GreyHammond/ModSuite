# Changelog

All notable changes to ModSuite are documented here.

---

## [1.0.0] — 2026-05-09

Initial public release. 🎉

### Core Bot
- Bot connects silently on invite and waits for `/setup`
- Guild-specific slash command sync on startup — commands appear instantly
- Persistent SQLite configuration — survives restarts with no re-setup
- Automatic schema migration — new columns added without wiping existing data
- Status presence: *Watching for /setup | DM for help*

### /setup
- Admin-only guided setup with ephemeral panel UI
- **Customise Messages** modal — set welcome message, self-roles message, and ModMail opening message
- **Warn & Raid Settings** modal — configure auto-escalation and raid detection thresholds
- Automatically creates:
  - 14 cosmetic color roles
  - `Owner` role (green, Administrator permissions)
  - `Moderator` role (red)
  - `ModMail` category with `#modmail`, `#mod-log`, `#closed-tickets`, `#mod-panel`, `#reports`
  - `Jail` category for private jail channels
  - `#self-roles` with reaction message posted and emoji reactions added
- Safe to re-run — finds and reuses existing roles and channels

### Self-Roles
- 14 color roles assignable via emoji reaction in `#self-roles`
- Supports both standard Unicode emoji and custom server emoji
- Enforces one color role at a time — switches automatically
- Unknown emoji removed from the self-roles message automatically
- Roles removed when user removes their reaction

### ModMail
- Users DM the bot to open a support ticket
- Bot sends configurable opening message to user
- Private `#ticket-username` channel created in ModMail category
- Owner and Moderator roles pinged in `#modmail` on new ticket
- Staff reply via button modal or `/reply` slash command
- Anonymous reply flag — user sees "Staff" instead of display name
- Staff-side channel always shows the real sender regardless of anon flag
- `/close` command and Close Ticket button — generates plain-text transcript, zips as `MMDDYYYY-username.zip`, posts to `#closed-tickets`, notifies user, deletes ticket channel
- Incoming messages from a user with an open ticket routed to existing channel automatically

### Moderation
- `/kick @user [reason]` — kick with mod-log entry
- `/ban @user [reason] [delete_days]` — ban with optional message purge
- `/unban <user_id> [reason]` — unban by ID
- `/mute @user [duration] [reason]` — Discord timeout with flexible duration parser (`10m`, `2h30m`, `1d`). Default: 30 days
- `/unmute @user [reason]` — remove timeout
- Auto-unmute background loop — handles durations beyond Discord's 28-day timeout limit
- Welcome message posted to system channel on member join

### Warn System
- `/warn @user <reason>` — add a warning, DMs the user
- `/unwarn <warn_id>` — soft-remove a warning by ID (record kept for history)
- `/history @user` — full moderation history showing active and removed warnings
- Configurable auto-escalation: auto-mute at warn threshold, auto-ban at ban threshold
- Thresholds set per-server in `/setup`

### Jail System
- `/jail @user [reason] [notify]` — strips all assignable roles, creates private `#jail-username` channel
- Optional DM notification to jailed user (per-use flag)
- Staff and bot can see and message the jail channel; jailed user can only see their own jail channel
- `/unjail @user` — restores all original roles, generates transcript, zips and archives to `#closed-tickets`, deletes jail channel, DMs user they've been released
- Jail records persisted in DB — bot restart does not lose jail state

### Mod Panel
- `/panel` — posts a persistent button panel in any staff channel. Buttons: Warn, Mute, Kick, Ban, Jail, History, Purge, Lockdown, Unlock
- `/mod` — ephemeral panel usable in any channel, context-aware:
  - In a **ModMail ticket channel**: shows Reply, Close Ticket, Purge
  - In a **Jail channel**: shows Unjail, Warn, Purge, User Info (with warn count and jail reason)
  - Anywhere else: shows full general mod toolkit
- All panel buttons call the same underlying functions as slash commands

### Reports
- Right-click any message → Apps → **Report Message** — anonymous report posted to `#reports`, pings `@Moderator`
- Right-click any message → Apps → **Report Message (Emergency)** — red embed posted to `#reports`, pings both `@Moderator` and `@Owner`
- Reporter identity never shown to staff
- Ephemeral confirmation sent to reporter on submission

### User & Server Info
- `/userinfo [@user]` — account age, join date, roles. Staff also see active warn count and jail status
- `/serverinfo` — member count, boost level, verification level, creation date
- `/purge <amount>` — bulk delete up to 100 messages

### Raid Protection
- Automatic join rate monitoring — configurable threshold (default: 10 joins in 10 seconds)
- Auto-lockdown: sets `send_messages=False` on all text channels for `@everyone` when threshold exceeded
- `/lockdown` — manual lockdown
- `/unlock` — restore all channel permissions
- `/autorole [@role]` — assign a role automatically to every new member. Omit role to disable
- All actions logged to `#mod-log`

### Mod Log
- Automatic embed posted to `#mod-log` for: kicks, bans, unbans, mutes, unmutes, auto-unmutes, warns, jails, unjails, lockdowns, unlocks

---

*ModSuite follows [Semantic Versioning](https://semver.org).*
