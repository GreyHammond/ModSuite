# ModSuite

**Version 4.0** — a self-hosted Discord community platform: bot, REST API, and
web dashboard in one process.

ModSuite handles onboarding, self-roles, ModMail, moderation, warns, jail,
notes, reports, starboard, stream alerts, react-roles, reminders, forum threads,
AutoMod, raid response, and content filtering. Everything is configurable from
Discord or from the browser, and everything either surface does is written to a
single audit trail.

MIT licensed. Bring your own token and your own server.

**[Documentation](https://greyhammond.github.io/ModSuite/)** · [Landing page](https://greyhammond.github.io/ModSuite/index.html)

---

## What is new in 4.0

**Server blueprints.** A JSON file describes a server's roles, categories,
channels, and permission overwrites. `/blueprint apply` builds it. Fully
additive and idempotent — nothing is ever deleted, anything that already exists
is skipped, and running the same blueprint twice creates nothing the second
time. `/blueprint export` snapshots a live server back out to JSON, so an
existing server can seed a new one and a layout can live in version control.

**Unified audit trail.** Every state-changing dashboard request and every slash
command lands in one timeline with actor, target, payload, and result. Captured
as API middleware and a global command listener rather than per-route or
per-cog, so anything added later cannot forget to log. Failures and refusals are
recorded too — a refused `/ban` is often the more interesting entry. Secrets are
redacted before storage.

**Message archive.** Optional forensic archive of public messages, including
edits and deletions. Deleted messages are reposted to a private channel with
their attachments. Retention is enforced by a purge loop that removes rows and
vault files together. Attachments are served through the authenticated
dashboard, never a public static mount.

**Mute that actually works.** Discord's native timeout caps at 28 days, so a
"permanent" mute silently lapsed. Mutes are now enforced by a role with no cap.
`/mute-setup` creates it and applies deny overwrites across every category, and
leaving and rejoining no longer clears it.

**Public moderation log.** Optionally post every mute, jail, kick, and ban with
a reason to a channel members can read. Warnings stay private.

**Multi-platform stream alerts.** Twitch, YouTube, Kick, and Rumble behind one
provider interface. Only Twitch needs credentials.

**RSS feeds.** Watch any RSS or Atom feed and post new items with an optional
discussion thread per item. Falls back to the system `curl` binary when a host
fingerprints the TLS handshake, which is what Cloudflare-fronted sites do to
Python clients.

**Recurring events.** Reminders for meetings that follow a rule (2nd and 4th
Tuesday) or an approved list of dates, with per-occurrence cancel, move, and
restore. Real public bodies rarely follow a clean rule, so both modes exist.

**Records request tracker.** Business-day deadline maths for FOIA-style
requests, with configurable response window, extension length, and holiday
calendar.

**Membership roster.** Publishes a list of everyone holding a chosen role,
grouped by organization, and republishes automatically when the role changes.

**Dashboard parity.** Every editable config column now has an editor —
verified programmatically against the schema, not by eye. The version is read
from the API rather than hardcoded.

---

## Install

```bash
git clone <your-fork> modsuite && cd modsuite
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # add DISCORD_TOKEN
python bot.py
```

Then in Discord: `/setup`.

See `DEPLOY.md` for remote hosting, OAuth2, firewall rules, and systemd.

---

## First run

1. `/setup` — guided configuration
2. `/blueprint preview name:starter` then `/blueprint apply name:starter confirm:True`
3. `/mute-setup` — creates the Muted role and locks it out of every category
4. Drag the bot's role above every role it needs to manage

Optional: `/public-modlog`, `/archive setup`, `/feed add`, `/meeting add`,
`/roster publish`.

---

## White-labelling

Set these in `.env` to rebrand a deployment without touching code:

```
PRODUCT_NAME=YourBot
ORG_NAME=Your Org
FOOTER_BRAND=YourBot · Your Org
BRAND_COLOR=0xD4A843
```

Dashboard colours live in `web/styles/tokens.css`.

---

## Requirements

Python 3.11+, a Discord application with all three privileged intents enabled,
and a machine that stays on. SQLite is the only datastore; there is nothing else
to provision.
