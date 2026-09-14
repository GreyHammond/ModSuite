# ModSuite v4.1 -- Start Here

This is the complete, working source tree. Every file the bot and dashboard
need is here. Nothing is a fragment or a diff you have to reconcile.

Two things you probably want to do with it: **run it on your server**, and
**push it to GitHub**. Both below.

---

## A. Put it on your web server

### If you already have ModSuite running

```bash
cd /path/to/your/ModSuite
cp communitybot.db communitybot.db.bak      # back up first
cp .env /tmp/modsuite-env.bak               # keep your secrets safe
```

Copy every file from this zip over the top of your existing install, then:

```bash
pip install -r requirements.txt
sudo systemctl restart modsuite              # or however you run it
```

**Your `.env` and `communitybot.db` are not in this zip**, so copying over the
top will not clobber them. The database migrates itself on startup. No manual
SQL.

Then read `UPGRADING-v3.5.md`. There are four behaviour changes worth knowing
about before you use it, particularly that auto-mute duration never previously
worked and that member-targeting commands now take text instead of a member
picker.

### If this is a fresh install

```bash
cd ModSuite
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env                                    # fill in your tokens
python bot.py
```

Then open `http://127.0.0.1:8000` and run `/setup` in Discord.

Full detail, including systemd and reverse proxy setup, is in `DEPLOY.md`.

### One thing to get right

The dashboard binds to `127.0.0.1:8000` and is **not** exposed to the internet
by default. Do not change that binding to `0.0.0.0` and call it done. Front it
with a reverse proxy, Cloudflare Tunnel, Tailscale, or an SSH tunnel. The OAuth
setup in `README.md` is what actually restricts access to your staff.

If you run without OAuth configured, dashboard actions are logged as
"Dashboard (unauthenticated)" rather than against a real person. Set it up.

---

## B. Push it to GitHub

### Into your existing repo, preserving history

```bash
cd /path/to/your/ModSuite-checkout
# copy every file from this zip over the top, then:
git add -A
git commit -m "v3.5.0: dashboard parity, user ID support across member commands"
git push
```

### Or apply the commits individually

The `patches/` folder holds each version as a separate commit with its full
message, so your history shows five meaningful changes rather than one blob:

```bash
cd /path/to/your/ModSuite-checkout
git am patches/*.patch
git push
```

Use `git apply --3way patches/0001-*.patch` as a fallback if `git am` complains
about context.

**Delete the `patches/` folder before committing** if you go the copy-over
route. It is packaging, not source.

### Starting a fresh repo

```bash
cd ModSuite
rm -rf patches START-HERE.md
git init && git add -A
git commit -m "ModSuite v3.5.0"
git remote add origin git@github.com:GreyHammond/ModSuite.git
git push -u origin main
```

`.gitignore` already excludes `.env`, `__pycache__/`, and `communitybot.db`, so
you will not commit your token or your live database.

---

## What changed since v3.1

| Version | What |
|---|---|
| 3.2.0 | User ID support across 17 member-targeting commands; Streamers page; config schema went from 45 to 65 fields |
| 3.3.0 | Moderation page; dashboard actions attributed to the logged-in staff member; permission hierarchy enforced on dashboard actions |
| 3.4.0 | AutoMod page: word lists with a match tester, severity profiles |
| 3.5.0 | Starboards, Reminders, and React Roles pages -- completes dashboard parity |
| 3.5.1 | ModMail attachment relay: media users send now actually reaches staff, and staff can send files back |
| 3.5.2 | `requirements.txt` was missing `httpx`, `pydantic`, and `starlette`, so a clean venv crashed on startup |
| 3.6.0 | Server blueprints: build roles, categories, and channels from a JSON file, with export |
| 3.7.0 | Message archive: edits, deletions, retention, and an authenticated attachment vault |
| 3.8.0 | Role-based mute that survives past 28 days, public moderation log, records request tracker |
| 3.9.0 | Multi-platform stream alerts, RSS feeds, recurring events, membership roster |
| 4.1.0 | Legacy booster rewards: a permanent role granted on first boost, so perks survive when someone stops boosting |
| 4.0.0 | Unified audit trail across dashboard and Discord, full dashboard config parity, configurable branding |

`CHANGELOG.md` has the full detail including every bug fixed along the way.

---

## Verifying it works before you trust it

```bash
python3 -c "
import database as db; db.init_db()
import api, bot, auth, utils
print('OK:', len(api.app.routes), 'routes')
"
```

Should print `OK: 81 routes`. If it does, everything imports and the database
schema is current.

Then in Discord, the fastest end-to-end check is the thing that was originally
broken: `/streamer remove` with the numeric user ID of a streamer who has left
your server. It should delete their channel, clear the record, and tell you it
skipped the role removal because they are gone.
