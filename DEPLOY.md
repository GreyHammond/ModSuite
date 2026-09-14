# ModSuite — Deployment

Everything you have to edit lives in one file: `.env`.

```bash
cp .env.example .env
nano .env
```

---

## 1. The four values you actually have to set

| Key | Where to get it |
|---|---|
| `DISCORD_TOKEN` | discord.com/developers → your app → Bot → Reset Token |
| `DISCORD_CLIENT_ID` | same app → OAuth2 → Client ID |
| `DISCORD_CLIENT_SECRET` | same app → OAuth2 → Reset Secret |
| `MODSUITE_GUILD_ID` | right-click your server → Copy Server ID |

Everything else has a working default or is optional.

### Bot setup in the developer portal

Under **Bot**, enable all three Privileged Gateway Intents:

- Presence Intent
- Server Members Intent
- Message Content Intent

Without Message Content the archive and automod see empty messages. Without
Server Members the roster cannot read who holds a role.

Invite with the `bot` and `applications.commands` scopes and Administrator.
**Then drag the bot's role near the top of the list.** The bot can only manage
roles below its own, so anything above it is untouchable by mute, automod, and
the blueprint.

---

## 2. Oracle Cloud

### Networking, once

OCI console: **Networking → Virtual Cloud Networks → your VCN → Security Lists
→ Default Security List → Add Ingress Rule**

- Source CIDR `0.0.0.0/0`
- Destination port `8000`

Then on the instance itself, because Oracle images ship with iptables closed no
matter what the VCN says:

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
```

That second step is the one people miss. The VCN rule alone will not open it.

### .env for a remote dashboard

Replace `YOUR_IP` with the instance's public IP:

```
DISCORD_REDIRECT_URI=http://YOUR_IP:8000/auth/callback
CORS_ORIGINS=http://YOUR_IP:8000
API_HOST=0.0.0.0
API_PORT=8000
```

The redirect URI must **also** be added in the developer portal under OAuth2 →
Redirects, character for character. A trailing-slash mismatch is the most
common reason login fails.

### Restrict who can log in

```
DASHBOARD_ALLOWED_ROLES=<Editor role ID>,<Moderator role ID>
```

Leave it blank and any member of the guild can reach the dashboard. Set it
before you go live, not after.

### Running it

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python bot.py
```

Keep it alive across reboots with `/etc/systemd/system/modsuite.service`:

```ini
[Unit]
Description=ModSuite
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/ModSuite
ExecStart=/home/ubuntu/ModSuite/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now modsuite
sudo journalctl -u modsuite -f
```

---

## 3. First run, in order

Several of these depend on the one before, so do them in sequence.

1. `/blueprint preview name:starter` — read the plan, nothing changes
2. `/blueprint apply name:starter confirm:True`
3. Verify role order: the bot's role above Muted, and Muted above members
4. `/mute-setup` — locks Muted out of every category except the Jail
5. `/setup` — mod-log, ModMail, roles. **Set both the ModMail owner and mod
   roles**, or tickets are invisible to you as well as everyone else
6. `/public-modlog channel:#mod-log`
7. `/archive setup restore_channel:#deleted-messages retention_days:30 scope:public`
8. `/feed add name:Blog url:https://example.com/feed channel:#announcements`
9. `/meeting add` for any recurring event
10. `/roster set` for each member, then `/roster publish`

### Verify before inviting anyone

- Log in from a second account with no roles. Private categories should be
  **invisible**, not merely locked.
- Mute a test account and confirm it cannot post anywhere, including in
  channels where it holds another role that grants access.
- Delete a message in `#general` and confirm it reappears in
  `#deleted-messages`.

---

## 4. Backups

Two things hold everything:

- `communitybot.db` — config, logs, tickets, archive, audit trail, FOIA
- `vault/` — archived attachments

```bash
sqlite3 communitybot.db ".backup /home/ubuntu/backups/modsuite-$(date +%F).db"
```

Neither is in git, by design. Back them up somewhere else.
