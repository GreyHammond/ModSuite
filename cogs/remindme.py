"""
cogs/remindme.py — Personal reminder system with timezone support.
Commands: /timezone, /remindme, /reminders
"""

import re
import io
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import database as db
from utils import parse_relative_time

# ── Timezone data ─────────────────────────────────────────────────────────────

TIMEZONE_REGIONS: dict[str, list[tuple[str, str]]] = {
    "🌎 Americas": [
        ("Honolulu",        "Pacific/Honolulu"),
        ("Anchorage",       "America/Anchorage"),
        ("Los Angeles",     "America/Los_Angeles"),
        ("Denver",          "America/Denver"),
        ("Mexico City",     "America/Mexico_City"),
        ("Chicago",         "America/Chicago"),
        ("New York",        "America/New_York"),
        ("Toronto",         "America/Toronto"),
        ("Halifax",         "America/Halifax"),
        ("Caracas",         "America/Caracas"),
        ("Bogotá",          "America/Bogota"),
        ("Lima",            "America/Lima"),
        ("Santiago",        "America/Santiago"),
        ("São Paulo",       "America/Sao_Paulo"),
        ("Buenos Aires",    "America/Argentina/Buenos_Aires"),
    ],
    "🌍 Europe & Africa": [
        ("London",          "Europe/London"),
        ("Dublin",          "Europe/Dublin"),
        ("Lisbon",          "Europe/Lisbon"),
        ("Paris",           "Europe/Paris"),
        ("Berlin",          "Europe/Berlin"),
        ("Amsterdam",       "Europe/Amsterdam"),
        ("Rome",            "Europe/Rome"),
        ("Madrid",          "Europe/Madrid"),
        ("Stockholm",       "Europe/Stockholm"),
        ("Warsaw",          "Europe/Warsaw"),
        ("Athens",          "Europe/Athens"),
        ("Helsinki",        "Europe/Helsinki"),
        ("Istanbul",        "Europe/Istanbul"),
        ("Cairo",           "Africa/Cairo"),
        ("Lagos",           "Africa/Lagos"),
        ("Nairobi",         "Africa/Nairobi"),
        ("Johannesburg",    "Africa/Johannesburg"),
    ],
    "🌏 Middle East & Asia": [
        ("Riyadh",          "Asia/Riyadh"),
        ("Dubai",           "Asia/Dubai"),
        ("Tehran",          "Asia/Tehran"),
        ("Karachi",         "Asia/Karachi"),
        ("Mumbai",          "Asia/Kolkata"),
        ("Kolkata",         "Asia/Kolkata"),
        ("Dhaka",           "Asia/Dhaka"),
        ("Bangkok",         "Asia/Bangkok"),
        ("Singapore",       "Asia/Singapore"),
        ("Hong Kong",       "Asia/Hong_Kong"),
        ("Shanghai",        "Asia/Shanghai"),
        ("Seoul",           "Asia/Seoul"),
        ("Tokyo",           "Asia/Tokyo"),
    ],
    "🌊 Pacific & Oceania": [
        ("Perth",           "Australia/Perth"),
        ("Sydney",          "Australia/Sydney"),
        ("Auckland",        "Pacific/Auckland"),
        ("Fiji",            "Pacific/Fiji"),
        ("Guam",            "Pacific/Guam"),
    ],
}

# Common timezone abbreviations → IANA
TZ_ABBREV: dict[str, str] = {
    "GMT":  "Etc/GMT",
    "UTC":  "UTC",
    "EST":  "America/New_York",
    "EDT":  "America/New_York",
    "CST":  "America/Chicago",
    "CDT":  "America/Chicago",
    "MST":  "America/Denver",
    "MDT":  "America/Denver",
    "PST":  "America/Los_Angeles",
    "PDT":  "America/Los_Angeles",
    "BST":  "Europe/London",
    "CET":  "Europe/Paris",
    "IST":  "Asia/Kolkata",
    "JST":  "Asia/Tokyo",
    "AEST": "Australia/Sydney",
    "NZST": "Pacific/Auckland",
}

# ── Time parsing helpers ──────────────────────────────────────────────────────

_TIME_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})",
)
_MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_absolute_time(text: str, iana_tz: str) -> "datetime | None":
    """
    Parse an absolute time string into a UTC-aware datetime.
    Handles: '9am', '9pm', '9am tomorrow', '9am 11/22/26', '12pm GMT', etc.
    Returns None if unparseable.
    """
    text = text.strip()

    # Extract inline timezone abbreviation if present
    inline_tz = None
    for abbr, iana in TZ_ABBREV.items():
        pattern = re.compile(r"\b" + abbr + r"\b", re.IGNORECASE)
        if pattern.search(text):
            inline_tz = iana
            text = pattern.sub("", text).strip()
            break

    tz = ZoneInfo(inline_tz or iana_tz)

    # Find time component
    tm = _TIME_RE.search(text)
    if not tm:
        return None

    hour   = int(tm.group(1))
    minute = int(tm.group(2) or 0)
    ampm   = tm.group(3).lower()
    if ampm == "pm" and hour != 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0

    remaining = (text[:tm.start()] + text[tm.end():]).strip().lower()

    now_local = datetime.now(tz)
    target_date = now_local.date()

    # Check for "tomorrow"
    if "tomorrow" in remaining:
        target_date = (now_local + timedelta(days=1)).date()
    else:
        # Check for numeric date  m/d/yy or m/d/yyyy
        dm = _DATE_RE.search(remaining)
        if dm:
            m, d, y = int(dm.group(1)), int(dm.group(2)), int(dm.group(3))
            if y < 100:
                y += 2000
            try:
                target_date = datetime(y, m, d).date()
            except ValueError:
                return None
        else:
            # Check for month-name date: "Nov 22 2026" or "22 Nov 2026"
            month_match = re.search(
                r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+(\d{1,2})(?:\s+(\d{2,4}))?",
                remaining, re.IGNORECASE
            )
            if not month_match:
                month_match = re.search(
                    r"(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*(?:\s+(\d{2,4}))?",
                    remaining, re.IGNORECASE
                )
                if month_match:
                    day_s, mon_s, yr_s = month_match.group(1), month_match.group(2), month_match.group(3)
                else:
                    day_s = mon_s = yr_s = None
            else:
                mon_s, day_s, yr_s = month_match.group(1), month_match.group(2), month_match.group(3)

            if mon_s and day_s:
                month = _MONTH_NAMES.get(mon_s[:3].lower())
                day   = int(day_s)
                year  = int(yr_s) if yr_s else now_local.year
                if year < 100:
                    year += 2000
                try:
                    target_date = datetime(year, month, day).date()
                except ValueError:
                    return None

    # Build local datetime and convert to UTC
    try:
        local_dt = datetime(
            target_date.year, target_date.month, target_date.day,
            hour, minute, 0,
            tzinfo=tz,
        )
    except Exception:
        return None

    # If the time is in the past and no explicit date was given, add 1 day
    now_utc = datetime.now(timezone.utc)
    if local_dt.astimezone(timezone.utc) <= now_utc:
        if "tomorrow" not in remaining and not _DATE_RE.search(remaining):
            local_dt = local_dt + timedelta(days=1)

    return local_dt.astimezone(timezone.utc).replace(tzinfo=None)  # store as naive UTC


def _fmt_delta(td: timedelta) -> str:
    """Format a timedelta as human-readable: '2d 3h 15m'"""
    total = int(td.total_seconds())
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m       = rem // 60
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    return " ".join(parts) or "< 1m"


def _fmt_fire_time(fire_at_utc_iso: str, iana_tz: str) -> str:
    """Format fire time in user's local timezone."""
    dt_utc = datetime.fromisoformat(fire_at_utc_iso).replace(tzinfo=timezone.utc)
    dt_local = dt_utc.astimezone(ZoneInfo(iana_tz))
    return dt_local.strftime("%A, %B %-d at %-I:%M %p %Z")


# ── Timezone views ────────────────────────────────────────────────────────────

class RegionSelectView(discord.ui.View):
    """Step 1: Pick a region."""

    def __init__(self, on_tz_set=None, pending_time: str = "", pending_msg: str = ""):
        super().__init__(timeout=120)
        self.on_tz_set   = on_tz_set    # optional callback(interaction, iana_str)
        self.pending_time = pending_time
        self.pending_msg  = pending_msg

        options = [
            discord.SelectOption(label=region, value=region)
            for region in TIMEZONE_REGIONS
        ]
        select = discord.ui.Select(
            placeholder="Pick your region…",
            options=options,
        )
        select.callback = self._region_chosen
        self.add_item(select)

    async def _region_chosen(self, interaction: discord.Interaction):
        region = interaction.data["values"][0]
        cities = TIMEZONE_REGIONS[region]
        view   = CitySelectView(
            region=region,
            cities=cities,
            on_tz_set=self.on_tz_set,
            pending_time=self.pending_time,
            pending_msg=self.pending_msg,
        )
        await interaction.response.edit_message(
            content=f"**{region}** — now pick your city:",
            view=view,
        )


class CitySelectView(discord.ui.View):
    """Step 2: Pick a city."""

    def __init__(self, region: str, cities: list, on_tz_set=None,
                 pending_time: str = "", pending_msg: str = ""):
        super().__init__(timeout=120)
        self.region       = region
        self.on_tz_set    = on_tz_set
        self.pending_time = pending_time
        self.pending_msg  = pending_msg

        options = [
            discord.SelectOption(label=city, value=iana)
            for city, iana in cities
        ]
        select = discord.ui.Select(
            placeholder="Pick your city…",
            options=options,
        )
        select.callback = self._city_chosen
        self.add_item(select)

    async def _city_chosen(self, interaction: discord.Interaction):
        iana = interaction.data["values"][0]
        db.upsert_user_prefs(str(interaction.user.id), timezone=iana)

        now_local = datetime.now(ZoneInfo(iana))
        time_str  = now_local.strftime("%-I:%M %p %Z")

        if self.on_tz_set:
            # Respond to the interaction immediately so it doesn't expire,
            # then let the callback send a followup with the reminder confirmation.
            await interaction.response.edit_message(
                content=f"✅ Timezone set to **{iana}** (current time: {time_str})\nSaving your reminder…",
                view=None,
            )
            try:
                await self.on_tz_set(interaction, iana)
            except Exception as e:
                print(f"[remindme] on_tz_set callback failed: {e}")
                await interaction.followup.send(
                    "❌ Timezone was saved but something went wrong setting the reminder. "
                    "Please try `/remindme` again.", ephemeral=True
                )
        else:
            await interaction.response.edit_message(
                content=(
                    f"✅ Timezone set to **{iana}**\n"
                    f"Your current local time: **{time_str}**"
                ),
                view=None,
            )


# ── Reminder cancel view ──────────────────────────────────────────────────────

class RemindersView(discord.ui.View):
    def __init__(self, reminders: list[dict], user_tz: str):
        super().__init__(timeout=180)
        self.reminders = reminders
        self.user_tz   = user_tz
        for r in reminders[:10]:  # Discord max 25 components; cap at 10 for safety
            btn = CancelButton(r["reminder_id"], r["message"][:30])
            self.add_item(btn)


class CancelButton(discord.ui.Button):
    def __init__(self, reminder_id: int, label_preview: str):
        super().__init__(
            label=f"Cancel #{reminder_id}",
            style=discord.ButtonStyle.danger,
            custom_id=f"cancel_reminder_{reminder_id}",
        )
        self.reminder_id = reminder_id

    async def callback(self, interaction: discord.Interaction):
        deleted = db.delete_reminder(self.reminder_id, str(interaction.user.id))
        if deleted:
            # Rebuild the view without this reminder
            remaining = db.get_user_reminders(str(interaction.user.id))
            prefs = db.get_user_prefs(str(interaction.user.id))
            tz    = prefs["timezone"] if prefs else "UTC"
            embed, view = _build_reminders_embed(remaining, tz)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.send_message(
                "❌ Could not cancel that reminder.", ephemeral=True
            )


def _build_reminders_embed(
    reminders: list[dict], user_tz: str
) -> "tuple[discord.Embed, RemindersView]":
    embed = discord.Embed(title="⏰ Your Upcoming Reminders", color=0xF0B429)
    if not reminders:
        embed.description = "ℹ️ You have no upcoming reminders."
        return embed, RemindersView([], user_tz)

    now = datetime.utcnow()
    lines = []
    for r in reminders[:10]:
        fire_dt = datetime.fromisoformat(r["fire_at"])
        delta   = fire_dt - now
        delta_s = _fmt_delta(delta) if delta.total_seconds() > 0 else "soon"
        msg_preview = r["message"][:40] + ("…" if len(r["message"]) > 40 else "")
        lines.append(f"**#{r['reminder_id']}** — in {delta_s} — \"{msg_preview}\"")

    embed.description = "\n".join(lines)
    embed.set_footer(text="Use the buttons below to cancel a reminder.")
    return embed, RemindersView(reminders, user_tz)


# ── Cog ───────────────────────────────────────────────────────────────────────

class RemindMe(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.check_reminders.start()

    def cog_unload(self):
        self.check_reminders.cancel()

    # ── Background loop ───────────────────────────────────────────────────────

    @tasks.loop(seconds=30)
    async def check_reminders(self):
        now = datetime.utcnow()
        pending = db.get_pending_reminders(now)
        for reminder in pending:
            try:
                await self._fire_reminder(reminder)
                db.mark_reminder_fired(reminder["reminder_id"])
            except Exception as e:
                print(f"[reminders] Failed to fire #{reminder['reminder_id']}: {e}")

    @check_reminders.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    async def _fire_reminder(self, reminder: dict):
        user = self.bot.get_user(int(reminder["user_id"]))
        if user is None:
            user = await self.bot.fetch_user(int(reminder["user_id"]))

        guild   = self.bot.get_guild(int(reminder["guild_id"]))
        channel = self.bot.get_channel(int(reminder["channel_id"]))
        guild_name   = guild.name if guild else "Discord"
        channel_name = f"#{channel.name}" if channel else "a channel"

        embed = discord.Embed(
            title="⏰ Reminder",
            description=f'"{reminder["message"]}"',
            color=0xF0B429,
        )
        embed.set_footer(text=f"Set in {channel_name} on {guild_name}")

        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            if channel:
                await channel.send(f"⏰ <@{reminder['user_id']}>", embed=embed)

    # ── /timezone ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name="timezone",
        description="Set your timezone for reminders.",
    )
    async def timezone_cmd(self, interaction: discord.Interaction):
        view = RegionSelectView()
        await interaction.response.send_message(
            "🌐 **Set Your Timezone**\nWhat region are you in?",
            view=view,
            ephemeral=True,
        )

    # ── /remindme ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name="remindme",
        description="Set a personal reminder. Examples: 2h, 30m, 9am, 9am tomorrow, 12pm GMT",
    )
    @app_commands.describe(
        time="When to remind you: 2h / 30m / 9am / 9am 11/22/26 / 12pm GMT",
        message="What to remind you about (max 300 chars)",
    )
    async def remindme(self, interaction: discord.Interaction, time: str, message: str):
        if len(message) > 300:
            await interaction.response.send_message(
                "❌ Message too long (max 300 characters).", ephemeral=True
            )
            return

        user_id  = str(interaction.user.id)
        guild_id = str(interaction.guild_id)
        chan_id  = str(interaction.channel_id)

        # Try relative time first
        td = parse_relative_time(time)
        if td is not None:
            # Validate bounds
            if td.total_seconds() < 60:
                await interaction.response.send_message(
                    "❌ Minimum reminder time is 1 minute.", ephemeral=True
                )
                return
            if td.total_seconds() > 365 * 86400:
                await interaction.response.send_message(
                    "❌ Maximum reminder time is 1 year.", ephemeral=True
                )
                return

            fire_at = (datetime.utcnow() + td).isoformat()
            rid     = db.add_reminder(user_id, guild_id, chan_id, message, fire_at)
            delta_s = _fmt_delta(td)
            await interaction.response.send_message(
                embed=self._confirm_embed(message, fire_at, delta_s, rid, "UTC"),
                ephemeral=True,
            )
            return

        # Absolute time — need timezone
        prefs = db.get_user_prefs(user_id)

        if prefs:
            # Timezone already set — parse and save
            await self._save_absolute_reminder(
                interaction, time, message, prefs["timezone"],
                guild_id, chan_id,
            )
        else:
            # Timezone not set — gate with picker, then auto-save
            async def _on_tz_set(itr: discord.Interaction, iana: str):
                now_local = datetime.now(ZoneInfo(iana))
                time_str  = now_local.strftime("%-I:%M %p %Z")
                await self._save_absolute_reminder(
                    itr, time, message, iana, guild_id, chan_id,
                    tz_confirm_line=f"✅ Timezone set to **{iana}** (current time: {time_str})\n",
                    edit=True,
                )

            view = RegionSelectView(
                on_tz_set=_on_tz_set,
                pending_time=time,
                pending_msg=message,
            )
            await interaction.response.send_message(
                "⏰ Before I can set that reminder, I need your timezone.\n"
                "Pick yours below and your reminder will be saved automatically.",
                view=view,
                ephemeral=True,
            )

    async def _save_absolute_reminder(
        self,
        interaction: discord.Interaction,
        time_str: str,
        message: str,
        iana_tz: str,
        guild_id: str,
        chan_id: str,
        tz_confirm_line: str = "",
        edit: bool = False,
    ):
        fire_dt = _parse_absolute_time(time_str, iana_tz)
        if fire_dt is None:
            content = (
                "❌ Couldn't parse that time. "
                "Try formats like: `2h`, `9am`, `9am tomorrow`, `9am 11/22/26`, `12pm GMT`"
            )
            if edit:
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
            return

        now_utc = datetime.utcnow()
        if fire_dt <= now_utc:
            content = "❌ That time is in the past."
            if edit:
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
            return

        if (fire_dt - now_utc).total_seconds() > 365 * 86400:
            content = "❌ Maximum reminder time is 1 year."
            if edit:
                await interaction.followup.send(content, ephemeral=True)
            else:
                await interaction.response.send_message(content, ephemeral=True)
            return

        fire_iso = fire_dt.isoformat()
        rid      = db.add_reminder(str(interaction.user.id), guild_id, chan_id, message, fire_iso)
        delta    = fire_dt - now_utc
        delta_s  = _fmt_delta(delta)
        embed    = self._confirm_embed(message, fire_iso, delta_s, rid, iana_tz)

        if edit:
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)

    def _confirm_embed(
        self, message: str, fire_iso: str, delta_s: str, rid: int, iana_tz: str
    ) -> discord.Embed:
        embed = discord.Embed(title="⏰ Reminder Set!", color=0x57F287)
        fire_friendly = _fmt_fire_time(fire_iso, iana_tz) if iana_tz != "UTC" else \
            datetime.fromisoformat(fire_iso).strftime("%A, %B %-d at %-I:%M %p UTC")
        embed.add_field(name="Message", value=f'"{message}"', inline=False)
        embed.add_field(name="Fires",   value=f"{fire_friendly}\n(in {delta_s})", inline=False)
        embed.set_footer(text=f"ID: #{rid}  —  use /reminders to view or cancel")
        return embed

    # ── /reminders ────────────────────────────────────────────────────────────

    @app_commands.command(
        name="reminders",
        description="View and cancel your upcoming reminders.",
    )
    async def reminders_cmd(self, interaction: discord.Interaction):
        user_id   = str(interaction.user.id)
        upcoming  = db.get_user_reminders(user_id)
        prefs     = db.get_user_prefs(user_id)
        tz        = prefs["timezone"] if prefs else "UTC"
        embed, view = _build_reminders_embed(upcoming, tz)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RemindMe(bot))
