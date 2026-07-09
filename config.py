import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_TOKEN", "YOUR_TOKEN_HERE")

# ── Default messages ──────────────────────────────────────────────────────────
DEFAULT_SELFROLES_MSG = (
    "🎨 **Pick a color for your nickname!**\n"
    "React below to receive a color role. Remove your reaction to unassign it.\n\n"
    "{role_lines}"
)
DEFAULT_WELCOME_MSG = (
    "👋 Welcome to **{server}**, {user}!\n"
    "Feel free to grab a color role in <#{selfroles_ch}> and say hi!"
)
DEFAULT_MODMAIL_OPEN_MSG = (
    "📬 **Thanks for reaching out!**\n"
    "A staff member will be with you shortly. "
    "Please describe your issue and we'll get back to you as soon as possible."
)
DEFAULT_JAIL_MSG = (
    "🔒 You have been pulled into a private channel by a staff member.\n"
    "Please wait -- someone will be with you shortly."
)

# ── Color roles ───────────────────────────────────────────────────────────────
COLOR_ROLES = [
    ("Red",       0xE74C3C, "🔴"),
    ("Orange",    0xE67E22, "🟠"),
    ("Yellow",    0xF1C40F, "🟡"),
    ("Green",     0x2ECC71, "🟢"),
    ("Teal",      0x1ABC9C, "🩵"),
    ("Blue",      0x3498DB, "🔵"),
    ("Dark Blue", 0x2C3E8C, "🌀"),
    ("Purple",    0x9B59B6, "🟣"),
    ("Pink",      0xFF69B4, "🩷"),
    ("Magenta",   0xE91E8C, "💗"),
    ("White",     0xFFFFFF, "⬜"),
    ("Black",     0x010101, "⬛"),
    ("Gray",      0x95A5A6, "🔘"),
    ("Brown",     0x8B4513, "🟤"),
]

# ── Special roles ─────────────────────────────────────────────────────────────
OWNER_ROLE_NAME = "Owner"
OWNER_ROLE_COLOR = 0x2ECC71

MOD_ROLE_NAME = "Moderator"
MOD_ROLE_COLOR = 0xE74C3C

# ── Channel / category names ──────────────────────────────────────────────────
MODMAIL_CATEGORY_NAME  = "ModMail"
MODMAIL_CHANNEL_NAME   = "modmail"
MODLOG_CHANNEL_NAME    = "mod-log"
CLOSED_CHANNEL_NAME    = "closed-tickets"
SELFROLES_CHANNEL_NAME = "self-roles"
PANEL_CHANNEL_NAME     = "mod-panel"
REPORTS_CHANNEL_NAME   = "reports"
JAIL_CATEGORY_NAME     = "Jail"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_MUTE_DAYS      = 30
DEFAULT_WARN_MUTE_AT   = 3
DEFAULT_WARN_BAN_AT    = 5
DEFAULT_RAID_JOINS     = 10
DEFAULT_RAID_SECONDS   = 10
