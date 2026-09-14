"""
Public records request tracker.

Built for FOIA-style requests, where a body has N business days to respond and
may take one extension. Defaults match Michigan FOIA (MCL 15.235): 5 business
days, one 10-business-day extension. Both are configurable per guild, so other
jurisdictions work by changing two numbers rather than the code.

Weekends and holidays do not count as business days. The holiday set defaults
to US federal; `none` disables holidays entirely and counts weekdays only,
which is the right choice outside the US until a local set is added.

Deadline arithmetic matters more than it looks: in most FOIA regimes a missed
deadline is itself a denial the requester can appeal, so being off by a day
changes what the requester is entitled to do.
"""
import json
import logging
from datetime import date, datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from config import FOOTER_BRAND, BRAND_COLOR

log = logging.getLogger("ModSuite.foia")

# Defaults; overridden per guild by tracker_initial_days / tracker_extension_days
INITIAL_BUSINESS_DAYS = 5
EXTENSION_BUSINESS_DAYS = 10


def _holiday_set(guild_id) -> str:
    cfg = db.get_config(guild_id) or {}
    return cfg.get("tracker_holiday_set") or "us_federal"


def _days(guild_id, key: str, fallback: int) -> int:
    cfg = db.get_config(guild_id) or {}
    try:
        return int(cfg.get(key) or fallback)
    except (TypeError, ValueError):
        return fallback


def _observed(holiday: date) -> date:
    """Saturday holidays are observed Friday, Sunday holidays the next Monday."""
    if holiday.weekday() == 5:
        return holiday - timedelta(days=1)
    if holiday.weekday() == 6:
        return holiday + timedelta(days=1)
    return holiday


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """nth given weekday of a month; n = -1 for the last one."""
    if n > 0:
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        return d + timedelta(days=offset + 7 * (n - 1))
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    d = nxt - timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def michigan_holidays(year: int) -> set[date]:
    """
    Michigan state holidays under MCL 435.101. A superset of the US federal
    list: it adds the day after Thanksgiving, Christmas Eve, and New Year's
    Eve, which are the ones that most often catch people out.
    """
    days = {
        _observed(date(year, 1, 1)),                 # New Year's Day
        _nth_weekday(year, 1, 0, 3),                 # MLK Day
        _nth_weekday(year, 2, 0, 3),                 # Presidents Day
        _nth_weekday(year, 5, 0, -1),                # Memorial Day
        _observed(date(year, 6, 19)),                # Juneteenth
        _observed(date(year, 7, 4)),                 # Independence Day
        _nth_weekday(year, 9, 0, 1),                 # Labor Day
        _nth_weekday(year, 11, 3, 4),                # Thanksgiving
        _observed(date(year, 12, 25)),               # Christmas
    }
    # Michigan also observes the day after Thanksgiving and Christmas Eve
    days.add(_nth_weekday(year, 11, 3, 4) + timedelta(days=1))
    days.add(_observed(date(year, 12, 24)))
    days.add(_observed(date(year, 12, 31)))
    return days


def us_federal_holidays(year: int) -> set[date]:
    """Federal holidays, for jurisdictions that do not add state-specific days."""
    return {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _nth_weekday(year, 5, 0, -1),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 10, 0, 2),
        _observed(date(year, 11, 11)),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }


HOLIDAY_SETS = {
    "us_federal": us_federal_holidays,
    "michigan":   michigan_holidays,
    "none":       lambda year: set(),
}


def holidays_for(year: int, which: str = "us_federal") -> set[date]:
    return HOLIDAY_SETS.get(which, us_federal_holidays)(year)


def add_business_days(start: date, days: int,
                      holiday_set: str = "us_federal") -> date:
    """
    Add business days, skipping weekends and the configured holiday set.
    Counting begins the day AFTER receipt, which is how most FOIA statutes
    (including MCL 15.235(2)) define it.
    """
    current = start
    remaining = days
    holidays = holidays_for(start.year, holiday_set) | holidays_for(start.year + 1, holiday_set)
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() >= 5 or current in holidays:
            continue
        remaining -= 1
    return current


def business_days_between(a: date, b: date,
                          holiday_set: str = "us_federal") -> int:
    """Business days from a to b. Negative if b is in the past."""
    if b == a:
        return 0
    step = 1 if b > a else -1
    holidays = (holidays_for(min(a, b).year, holiday_set)
                | holidays_for(max(a, b).year, holiday_set))
    count = 0
    current = a
    while current != b:
        current += timedelta(days=step)
        if current.weekday() < 5 and current not in holidays:
            count += step
    return count


STATUS_LABELS = {
    "filed": "Filed", "acknowledged": "Acknowledged", "extended": "Extended",
    "fee_quoted": "Fee quoted", "granted": "Granted", "partial": "Partial",
    "denied": "Denied", "appealed": "Appealed", "closed": "Closed",
}
CLOSED_STATUSES = {"granted", "denied", "closed"}


def _effective_due(row: dict) -> date:
    raw = row.get("extended_due") or row.get("response_due")
    return date.fromisoformat(raw[:10])


class FOIA(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.deadline_loop.start()

    def cog_unload(self):
        self.deadline_loop.cancel()

    foia_group = app_commands.Group(name="foia", description="Track FOIA requests.")

    @foia_group.command(name="file", description="Log a FOIA request and compute its deadline.")
    @app_commands.describe(
        body="Public body the request went to",
        subject="What you asked for",
        filed_date="YYYY-MM-DD. Defaults to today.",
        notes="Optional notes",
    )
    async def foia_file(self, interaction: discord.Interaction, body: str,
                        subject: str, filed_date: str = "", notes: str = ""):
        try:
            filed = (date.fromisoformat(filed_date.strip())
                     if filed_date.strip() else date.today())
        except ValueError:
            return await interaction.response.send_message(
                "Date must be YYYY-MM-DD.", ephemeral=True)

        hs = _holiday_set(interaction.guild_id)
        due = add_business_days(
            filed, _days(interaction.guild_id, "tracker_initial_days",
                         INITIAL_BUSINESS_DAYS), hs)
        max_due = add_business_days(
            due, _days(interaction.guild_id, "tracker_extension_days",
                       EXTENSION_BUSINESS_DAYS), hs)

        foia_id = db.add_foia(
            str(interaction.guild_id), body.strip(), subject.strip(),
            filed.isoformat(), due.isoformat(),
            filed_by=interaction.user.display_name, notes=notes,
        )

        e = discord.Embed(title=f"FOIA #{foia_id} logged", colour=BRAND_COLOR)
        e.add_field(name="Body", value=body, inline=True)
        e.add_field(name="Filed", value=filed.isoformat(), inline=True)
        e.add_field(name="Response due", value=f"**{due.isoformat()}**", inline=True)
        e.add_field(name="Subject", value=subject[:1000], inline=False)
        e.add_field(
            name="If they extend",
            value=f"If an extension is granted, the deadline moves to "
                  f"{max_due.isoformat()}. Most statutes require written "
                  f"notice. Log it with `/foia extend id:{foia_id}`.",
            inline=False)
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e)

    @foia_group.command(name="list", description="Show tracked FOIA requests.")
    @app_commands.describe(show_all="Include closed requests")
    async def foia_list(self, interaction: discord.Interaction, show_all: bool = False):
        rows = db.get_foias(str(interaction.guild_id), open_only=not show_all)
        if not rows:
            return await interaction.response.send_message(
                "No FOIA requests tracked. Log one with `/foia file`.", ephemeral=True)

        today = date.today()
        e = discord.Embed(title="FOIA requests", colour=BRAND_COLOR)
        for r in rows[:20]:
            due = _effective_due(r)
            if r["status"] in CLOSED_STATUSES:
                timing = STATUS_LABELS.get(r["status"], r["status"])
            else:
                left = business_days_between(today, due, _holiday_set(r.get("guild_id")))
                if left < 0:
                    timing = f"**OVERDUE by {abs(left)} business day(s)**"
                elif left == 0:
                    timing = "**DUE TODAY**"
                else:
                    timing = f"{left} business day(s) left"
            e.add_field(
                name=f"#{r['id']} · {r['body']}",
                value=f"{r['subject'][:120]}\n"
                      f"Due {due.isoformat()} · {timing} · "
                      f"*{STATUS_LABELS.get(r['status'], r['status'])}*",
                inline=False)
        if len(rows) > 20:
            e.set_footer(text=f"Showing 20 of {len(rows)} · {FOOTER_BRAND}")
        else:
            e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e)

    @foia_group.command(name="extend", description="Log a 10-business-day extension.")
    @app_commands.describe(id="FOIA id", notice_date="Date of their written notice, YYYY-MM-DD")
    async def foia_extend(self, interaction: discord.Interaction, id: int,
                          notice_date: str = ""):
        row = db.get_foia(str(interaction.guild_id), id)
        if not row:
            return await interaction.response.send_message(
                f"No FOIA #{id}.", ephemeral=True)
        base = date.fromisoformat(row["response_due"][:10])
        new_due = add_business_days(
            base, _days(interaction.guild_id, "tracker_extension_days",
                        EXTENSION_BUSINESS_DAYS),
            _holiday_set(interaction.guild_id))
        db.update_foia(str(interaction.guild_id), id,
                       extended_due=new_due.isoformat(), status="extended",
                       warned_stages="[]")
        await interaction.response.send_message(
            f"Request #{id} extended. New deadline **{new_due.isoformat()}**.\n"
            f"Under most FOIA statutes only one extension is permitted and a "
            f"missed deadline counts as a denial. Check your jurisdiction.")

    @foia_group.command(name="status", description="Update a request's status.")
    @app_commands.describe(id="FOIA id", status="New status", note="Optional note",
                           fee="Fee quoted, if any")
    @app_commands.choices(status=[
        app_commands.Choice(name=v, value=k) for k, v in STATUS_LABELS.items()
    ])
    async def foia_status(self, interaction: discord.Interaction, id: int,
                          status: str, note: str = "", fee: float = None):
        row = db.get_foia(str(interaction.guild_id), id)
        if not row:
            return await interaction.response.send_message(
                f"No FOIA #{id}.", ephemeral=True)
        fields = {"status": status}
        if note:
            fields["notes"] = (row.get("notes", "") + f"\n[{date.today()}] {note}").strip()
        if fee is not None:
            fields["fee_quoted"] = fee
        db.update_foia(str(interaction.guild_id), id, **fields)

        msg = f"FOIA #{id} is now **{STATUS_LABELS.get(status, status)}**."
        if status == "denied":
            msg += ("\nMost jurisdictions set a deadline to appeal to the head of "
                    "the public body or to file suit. Michigan allows 180 days.")
        if fee is not None and fee > 0:
            msg += (f"\nFee quoted: ${fee:,.2f}. Many statutes cap the deposit a "
                    f"body may demand and allow a waiver where disclosure serves "
                    f"the public interest.")
        await interaction.response.send_message(msg)

    @foia_group.command(name="close", description="Close out a request.")
    @app_commands.describe(id="FOIA id")
    async def foia_close(self, interaction: discord.Interaction, id: int):
        if not db.update_foia(str(interaction.guild_id), id, status="closed"):
            return await interaction.response.send_message(f"No FOIA #{id}.", ephemeral=True)
        await interaction.response.send_message(f"FOIA #{id} closed.")

    @foia_group.command(name="delete", description="Delete a tracked request.")
    @app_commands.describe(id="FOIA id", confirm="Must be True")
    async def foia_delete(self, interaction: discord.Interaction, id: int,
                          confirm: bool = False):
        if not confirm:
            return await interaction.response.send_message(
                f"Re-run with `confirm:True` to delete FOIA #{id}.", ephemeral=True)
        ok = db.delete_foia(str(interaction.guild_id), id)
        await interaction.response.send_message(
            f"FOIA #{id} deleted." if ok else f"No FOIA #{id}.", ephemeral=True)

    # ── Deadline warnings ────────────────────────────────────────────────────
    @tasks.loop(hours=12)
    async def deadline_loop(self):
        today = date.today()
        for guild in self.bot.guilds:
            cfg = db.get_config(guild.id) or {}
            channel_id = cfg.get("modlog_ch_id")
            channel = self.bot.get_channel(int(channel_id)) if channel_id else None

            for row in db.get_foias(str(guild.id), open_only=True):
                if row["status"] in CLOSED_STATUSES:
                    continue
                due = _effective_due(row)
                left = business_days_between(today, due, _holiday_set(guild.id))

                stage = None
                if left < 0:
                    stage = f"overdue-{abs(left)}"
                elif left == 0:
                    stage = "due-today"
                elif left == 1:
                    stage = "due-tomorrow"
                if stage is None:
                    continue

                try:
                    warned = json.loads(row.get("warned_stages") or "[]")
                except json.JSONDecodeError:
                    warned = []
                if stage in warned:
                    continue

                if channel is not None:
                    if left < 0:
                        title = f"FOIA #{row['id']} is OVERDUE"
                        colour = 0xC0392B
                        body = (f"{abs(left)} business day(s) past the deadline. "
                                f"In most FOIA regimes a failure to respond is "
                                f"itself a denial, which opens an appeal.")
                    elif left == 0:
                        title = f"FOIA #{row['id']} is due TODAY"
                        colour = 0xD96C2C
                        body = "Response is due today. Nothing received yet."
                    else:
                        title = f"FOIA #{row['id']} is due tomorrow"
                        colour = 0xE6B422
                        body = "One business day left."

                    e = discord.Embed(title=title, description=body, colour=colour)
                    e.add_field(name="Body", value=row["body"], inline=True)
                    e.add_field(name="Filed", value=row["filed_date"][:10], inline=True)
                    e.add_field(name="Due", value=due.isoformat(), inline=True)
                    e.add_field(name="Subject", value=row["subject"][:500], inline=False)
                    e.set_footer(text=FOOTER_BRAND)
                    try:
                        await channel.send(embed=e)
                    except discord.HTTPException:
                        pass

                warned.append(stage)
                db.update_foia(str(guild.id), row["id"],
                               warned_stages=json.dumps(warned[-10:]))

    @deadline_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(FOIA(bot))
