# ModSuite v2.5 — Deploy Guide

## ⚠️ Read First

**Back up your database** before deploying anything:
```bash
cp /path/to/modsuite_v2/communitybot.db /path/to/modsuite_v2/communitybot.db.pre-v25.bak
```

The v2.5 package does **not** include a `.db` file or a `venv/` — those are yours and must not be overwritten.

---

## Deploy — Fresh install

If ModSuite isn't installed yet, extract the zip and follow the README:

```bash
unzip modsuite-v2.5.zip
cd modsuite_v2
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — paste DISCORD_TOKEN
python bot.py
```

## Deploy — Upgrading from any earlier version

The safest process, keeping your DB intact:

1. **Stop the running bot.** If you're using screen:
   ```bash
   screen -X -S MothMail quit
   # or whatever your session name is
   ```

2. **Back up.**
   ```bash
   cd /home/hammond/MothMail/modsuite_v2
   cp communitybot.db communitybot.db.pre-v25.bak
   ```

3. **Extract the v2.5 zip somewhere else**, then copy files into your install directory. From the extracted `modsuite_v2/` folder:

   ```bash
   # Copy everything EXCEPT venv, communitybot.db, and .env
   rsync -av \
     --exclude='venv/' \
     --exclude='communitybot.db*' \
     --exclude='.env' \
     ./ /home/hammond/MothMail/modsuite_v2/
   ```

   Or manually — copy `api.py`, `bot.py`, `database.py`, `config.py`, `utils.py`, `requirements.txt`, `README.md`, `CHANGELOG.md`, plus the whole `cogs/` and `web/` folders. Leave `.env`, `venv/`, and `communitybot.db*` alone.

4. **Install any new dependencies:**
   ```bash
   cd /home/hammond/MothMail/modsuite_v2
   source venv/bin/activate
   pip install -r requirements.txt
   ```
   This adds `psutil` if you don't already have it (used by `/health`).

5. **Start the bot back up:**
   ```bash
   screen -dmS MothMail bash -c 'cd /home/hammond/MothMail/modsuite_v2 && source venv/bin/activate && python3 bot.py'
   ```

6. **Verify:**
   - `screen -ls` should show MothMail attached.
   - `sudo ss -tlnp | grep 8000` should show Python listening.
   - Hard-refresh the dashboard: `Ctrl+Shift+R` at `http://127.0.0.1:8000/`.

The database schema migrates itself on first start after any code update — no manual SQL. Any new config columns added in v2.2 (AutoMod, raid upgrades) and v2.5 (schema unchanged, but you get the point) appear automatically.

---

## What changed in v2.5 vs your current install

Two files if you're on v2.2 and only want the additions: **`api.py`** and **`bot.py`** carry all backend changes. Every `web/pages/*.js` file except `setup.js` and `selfroles.js` was rewritten. **`web/api.js`** is important — this fixes the CORS issue where the dashboard couldn't talk to itself.

If you want the minimum change footprint instead of a full deploy, cherry-pick:
- `api.py`
- `bot.py`
- `web/api.js`
- `web/shell/sidebar.js`
- `web/pages/dashboard.js`
- `web/pages/configuration.js`
- `web/pages/warns.js`
- `web/pages/notes.js`
- `web/pages/modlogs.js`
- `web/pages/tickets.js`
- `requirements.txt` → `pip install psutil`

---

## Rollback

If anything goes wrong:

```bash
# Restore the DB
cp communitybot.db.pre-v25.bak communitybot.db

# If you kept your old files (recommended), copy them back over
# The bot is designed to run fine on the schema — older code + newer DB works.
```

---

## After deploy — try these

- Dashboard tab → look for the trend line, top offenders, and bot health card
- Configuration tab → 7 section tabs, edit anything, hit Save
- Warns tab → `+ Add warn` button, type a username
- Tickets tab → click any ticket to see the transcript
- Mod Logs tab → try Export CSV

If anything looks broken, the bot's startup log (`screen -r MothMail`) is your friend.
