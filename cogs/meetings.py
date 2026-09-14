"""
Meeting reminders.

Recurring events rarely follow a plain interval. Boards sit on given weekdays
of the month, guilds raid on a numbered Tuesday, meetups take the last Friday.
An "every 14 days" timer drifts off the real schedule within a couple of
months, so the scheduler works in terms of "the 2nd and 4th Tuesday" directly.

Some bodies do not follow a rule at all and simply approve a calendar each
year, so an explicit list of dates is also supported.

Two pings per event: one the morning of, one an hour before. Both go to a role
rather than @everyone, because a server that pings everyone twice a week gets
muted, and a muted server reminds nobody of anything.
"""
import json
import logging
from datetime import date, datetime, time, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from config import FOOTER_BRAND, BRAND_COLOR

log = logging.getLogger("ModSuite.meetings")

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]

ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", -1: "last"}


def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date | None:
    """nth weekday of a month; n = -1 means the last one. None if it does not exist."""
    if n == -1:
        nxt = date(year + (month == 12), (month % 12) + 1, 1)
        d = nxt - timedelta(days=1)
        while d.weekday() != weekday:
            d -= timedelta(days=1)
        return d
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    d = first + timedelta(days=offset + 7 * (n - 1))
    return d if d.month == month else None


def apply_exceptions(dates: list[date], exceptions: dict,
                     year: int | None = None,
                     month: int | None = None) -> list[date]:
    """
    Fold cancellations and moves into a list of occurrences.

    Exceptions live apart from the schedule so cancelling one night never
    edits the approved calendar. Shape:
        {"2026-08-18": {"status": "cancelled"},
         "2026-09-08": {"status": "moved", "to": "2026-09-15"}}
    """
    if not exceptions:
        return dates
    # When a month is given, a date moved out of it must not linger there and
    # a date moved into it must appear. Without this a cross-month move shows
    # up in both months.
    if year is None and dates:
        year, month = dates[0].year, dates[0].month
    out = []
    for d in dates:
        rec = exceptions.get(d.isoformat())
        if not rec:
            out.append(d)
            continue
        if rec.get("status") == "cancelled":
            continue
        if rec.get("status") == "moved" and rec.get("to"):
            try:
                moved = date.fromisoformat(rec["to"][:10])
                # Only keep it here if it landed in the month being queried
                if month is None or (moved.year, moved.month) == (year, month):
                    out.append(moved)
                continue
            except ValueError:
                pass
        out.append(d)
    # A meeting moved INTO this month from another one still belongs here
    for src, rec in exceptions.items():
        if rec.get("status") != "moved" or not rec.get("to"):
            continue
        try:
            moved_to = date.fromisoformat(rec["to"][:10])
            moved_from = date.fromisoformat(src[:10])
        except ValueError:
            continue
        if (moved_to not in out and month is not None
                and (moved_to.year, moved_to.month) == (year, month)
                and (moved_from.year, moved_from.month) != (moved_to.year, moved_to.month)):
            out.append(moved_to)
    return sorted(set(out))


def occurrences_in_month(schedule: dict, year: int, month: int) -> list[date]:
    """
    Supported schedule shapes:
      {"type": "monthly_nth", "weekday": 1, "positions": [2, 4]}
      {"type": "weekly", "weekday": 1}
      {"type": "monthly_day", "day": 15}
    weekday is 0=Monday through 6=Sunday, matching date.weekday().
    """
    kind = schedule.get("type", "monthly_nth")
    out: list[date] = []

    if kind == "fixed":
        # An explicit list of ISO dates. Public bodies commonly approve a
        # calendar each year rather than following a rule; one real council's
        # published 2026 dates matched "2nd and 4th Tuesday" in only 4 of 12
        # months. Where that is true, the approved list IS the schedule.
        for raw in schedule.get("dates", []):
            try:
                d = date.fromisoformat(str(raw)[:10])
            except ValueError:
                continue
            if d.year == year and d.month == month:
                out.append(d)

    elif kind == "weekly":
        wd = int(schedule.get("weekday", 1))
        d = date(year, month, 1)
        d += timedelta(days=(wd - d.weekday()) % 7)
        while d.month == month:
            out.append(d)
            d += timedelta(days=7)

    elif kind == "monthly_day":
        day = int(schedule.get("day", 1))
        try:
            out.append(date(year, month, day))
        except ValueError:
            pass  # e.g. the 31st in a 30-day month

    else:  # monthly_nth
        wd = int(schedule.get("weekday", 1))
        for pos in schedule.get("positions", [1]):
            d = nth_weekday_of_month(year, month, wd, int(pos))
            if d:
                out.append(d)

    return sorted(out)


def next_occurrence(schedule: dict, meeting_time: str,
                    after: datetime, exceptions: dict | None = None) -> datetime | None:
    """Next meeting datetime strictly after `after`. Looks up to 3 months ahead."""
    try:
        hh, mm = [int(x) for x in meeting_time.split(":")[:2]]
    except (ValueError, AttributeError):
        hh, mm = 19, 0

    year, month = after.year, after.month
    # A fixed calendar can have gaps of several months, so look further ahead
    # than a recurring rule needs to.
    horizon = 14 if schedule.get("type") == "fixed" else 4
    for _ in range(horizon):
        occ = apply_exceptions(occurrences_in_month(schedule, year, month),
                               exceptions or {}, year, month)
        for d in occ:
            dt = datetime.combine(d, time(hh, mm), tzinfo=after.tzinfo)
            if dt > after:
                return dt
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return None


def describe(schedule: dict, meeting_time: str) -> str:
    kind = schedule.get("type", "monthly_nth")
    if kind == "fixed":
        dates = schedule.get("dates", [])
        upcoming = [d for d in sorted(dates) if d >= date.today().isoformat()]
        return (f"{len(dates)} approved date(s) at {meeting_time}"
                + (f", next {upcoming[0]}" if upcoming else ", none remaining"))
    if kind == "weekly":
        return f"Every {WEEKDAYS[int(schedule.get('weekday', 1))]} at {meeting_time}"
    if kind == "monthly_day":
        return f"Day {schedule.get('day', 1)} of each month at {meeting_time}"
    wd = WEEKDAYS[int(schedule.get("weekday", 1))]
    pos = schedule.get("positions", [1])
    words = " and ".join(ORDINALS.get(int(p), str(p)) for p in pos)
    return f"{words} {wd} of each month at {meeting_time}"


class Meetings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    meeting_group = app_commands.Group(name="meeting",
                                       description="Public meeting reminders.")

    @tasks.loop(minutes=20)
    async def reminder_loop(self):
        now = datetime.now(timezone.utc).astimezone()
        for m in db.get_meetings(enabled_only=True):
            try:
                await self._check(m, now)
            except Exception as e:
                log.warning(f"Meeting '{m['name']}' reminder failed: {e}")

    @reminder_loop.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def _check(self, m: dict, now: datetime):
        nxt = next_occurrence(m["schedule"], m["meeting_time"], now,
                              m.get("exceptions"))
        if nxt is None:
            return

        # Two stages. Keyed by occurrence date so a restart cannot re-send, and
        # so the next meeting starts with a clean slate.
        fired = set((m.get("last_fired") or "").split(","))
        delta = nxt - now
        stage = None
        if timedelta(0) < delta <= timedelta(hours=1, minutes=10):
            stage = f"{nxt.date()}:hour"
        elif nxt.date() == now.date() and now.hour >= 7 and delta > timedelta(hours=1):
            stage = f"{nxt.date()}:morning"
        if stage is None or stage in fired:
            return

        channel = self.bot.get_channel(int(m["channel_id"]))
        if channel is None:
            return

        soon = stage.endswith(":hour")
        e = discord.Embed(
            title=f"{'Starting soon: ' if soon else 'Today: '}{m['name']}",
            colour=0xD96C2C if soon else BRAND_COLOR,
        )
        e.add_field(name="When", value=f"<t:{int(nxt.timestamp())}:F>", inline=False)
        if m.get("location"):
            e.add_field(name="Where", value=m["location"], inline=False)
        if m.get("agenda_url"):
            e.add_field(name="Agenda", value=m["agenda_url"], inline=False)
        e.set_footer(text=FOOTER_BRAND)

        content = f"<@&{m['ping_role_id']}>" if m.get("ping_role_id") else None
        try:
            await channel.send(content=content, embed=e)
        except discord.HTTPException:
            return

        # Keep only stages for the current occurrence
        keep = [f for f in fired if f.startswith(str(nxt.date()))]
        keep.append(stage)
        db.update_meeting(m["guild_id"], m["id"], last_fired=",".join(keep))

    # ── Commands ─────────────────────────────────────────────────────────────
    @meeting_group.command(name="add", description="Add a recurring public meeting.")
    @app_commands.describe(
        name="e.g. Monthly Board Meeting",
        channel="Where reminders post",
        weekday="Day of the week it meets",
        positions="Which weeks, comma separated: 2,4 or -1 for last. Blank = weekly.",
        meeting_time="24h local time, e.g. 19:00",
        location="Optional address",
        agenda_url="Optional link to the agenda or packet",
        ping_role="Role to notify")
    @app_commands.choices(weekday=[
        app_commands.Choice(name=d, value=i) for i, d in enumerate(WEEKDAYS)
    ])
    async def meeting_add(self, interaction: discord.Interaction, name: str,
                          channel: discord.TextChannel, weekday: int,
                          positions: str = "", meeting_time: str = "19:00",
                          location: str = "", agenda_url: str = "",
                          ping_role: discord.Role = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)

        if positions.strip():
            try:
                pos = [int(p) for p in positions.split(",") if p.strip()]
            except ValueError:
                return await interaction.response.send_message(
                    "Positions must be numbers, e.g. `2,4` or `-1`.", ephemeral=True)
            schedule = {"type": "monthly_nth", "weekday": weekday, "positions": pos}
        else:
            schedule = {"type": "weekly", "weekday": weekday}

        mid = db.add_meeting(str(interaction.guild_id), name, str(channel.id),
                             schedule, meeting_time, location, agenda_url,
                             str(ping_role.id) if ping_role else "")

        nxt = next_occurrence(schedule, meeting_time,
                              datetime.now(timezone.utc).astimezone())
        e = discord.Embed(title=f"Meeting #{mid} added", colour=BRAND_COLOR)
        e.add_field(name="Schedule", value=describe(schedule, meeting_time), inline=False)
        if nxt:
            e.add_field(name="Next", value=f"<t:{int(nxt.timestamp())}:F>", inline=False)
        e.add_field(name="Reminders",
                    value="Morning of, and one hour before.", inline=False)
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e)

    @meeting_group.command(
        name="dates",
        description="Add a meeting from an approved list of dates.")
    @app_commands.describe(
        name="e.g. Monthly Board Meeting",
        channel="Where reminders post",
        dates="Comma-separated YYYY-MM-DD, e.g. 2026-08-18,2026-09-08",
        meeting_time="24h local time, e.g. 18:30",
        location="Optional address",
        agenda_url="Optional link to the agenda or packet",
        ping_role="Role to notify")
    async def meeting_dates(self, interaction: discord.Interaction, name: str,
                            channel: discord.TextChannel, dates: str,
                            meeting_time: str = "18:30", location: str = "",
                            agenda_url: str = "", ping_role: discord.Role = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)

        parsed, bad = [], []
        for raw in dates.replace(" ", "").split(","):
            if not raw:
                continue
            try:
                parsed.append(date.fromisoformat(raw).isoformat())
            except ValueError:
                bad.append(raw)
        if bad:
            return await interaction.response.send_message(
                f"Could not read these dates: {', '.join(bad[:5])}. "
                f"Use YYYY-MM-DD.", ephemeral=True)
        if not parsed:
            return await interaction.response.send_message(
                "No valid dates given.", ephemeral=True)

        schedule = {"type": "fixed", "dates": sorted(set(parsed))}
        mid = db.add_meeting(str(interaction.guild_id), name, str(channel.id),
                             schedule, meeting_time, location, agenda_url,
                             str(ping_role.id) if ping_role else "")

        nxt = next_occurrence(schedule, meeting_time,
                              datetime.now(timezone.utc).astimezone())
        e = discord.Embed(title=f"Meeting #{mid} added", colour=BRAND_COLOR)
        e.add_field(name="Dates", value=f"{len(schedule['dates'])} approved dates",
                    inline=True)
        e.add_field(name="Time", value=meeting_time, inline=True)
        if nxt:
            e.add_field(name="Next", value=f"<t:{int(nxt.timestamp())}:F>", inline=False)
        remaining = [d for d in schedule["dates"] if d >= date.today().isoformat()]
        if remaining:
            e.add_field(name="Upcoming",
                        value="\n".join(remaining[:8]) +
                              (f"\n…and {len(remaining) - 8} more" if len(remaining) > 8 else ""),
                        inline=False)
        e.add_field(name="Reminders", value="Morning of, and one hour before.",
                    inline=False)
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e)

    @meeting_group.command(name="cancel", description="Cancel one meeting date.")
    @app_commands.describe(id="Meeting id", meeting_date="YYYY-MM-DD to cancel",
                           reason="Optional, posted with the notice",
                           announce="Post a cancellation notice in the channel")
    async def meeting_cancel(self, interaction: discord.Interaction, id: int,
                             meeting_date: str, reason: str = "",
                             announce: bool = True):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        m = next((x for x in db.get_meetings(str(interaction.guild_id))
                  if x["id"] == id), None)
        if not m:
            return await interaction.response.send_message(f"No meeting #{id}.", ephemeral=True)
        try:
            d = date.fromisoformat(meeting_date.strip())
        except ValueError:
            return await interaction.response.send_message(
                "Date must be YYYY-MM-DD.", ephemeral=True)

        exc = dict(m.get("exceptions") or {})
        exc[d.isoformat()] = {"status": "cancelled", "reason": reason}
        db.update_meeting(str(interaction.guild_id), id, exceptions=exc)

        await interaction.response.send_message(
            f"**{m['name']}** on {d.isoformat()} marked cancelled. "
            f"The approved calendar is untouched; only this date is skipped.",
            ephemeral=True)

        if announce:
            ch = self.bot.get_channel(int(m["channel_id"]))
            if ch:
                e = discord.Embed(
                    title=f"Cancelled: {m['name']}",
                    description=f"The meeting scheduled for **{d.isoformat()}** "
                                f"has been cancelled.",
                    colour=0xC0392B)
                if reason:
                    e.add_field(name="Reason", value=reason, inline=False)
                nxt = next_occurrence(m["schedule"], m["meeting_time"],
                                      datetime.now(timezone.utc).astimezone(), exc)
                if nxt:
                    e.add_field(name="Next meeting",
                                value=f"<t:{int(nxt.timestamp())}:F>", inline=False)
                e.set_footer(text=FOOTER_BRAND)
                try:
                    await ch.send(embed=e)
                except discord.HTTPException:
                    pass

    @meeting_group.command(name="move", description="Reschedule one meeting date.")
    @app_commands.describe(id="Meeting id", from_date="Original YYYY-MM-DD",
                           to_date="New YYYY-MM-DD", reason="Optional",
                           announce="Post a notice in the channel")
    async def meeting_move(self, interaction: discord.Interaction, id: int,
                           from_date: str, to_date: str, reason: str = "",
                           announce: bool = True):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        m = next((x for x in db.get_meetings(str(interaction.guild_id))
                  if x["id"] == id), None)
        if not m:
            return await interaction.response.send_message(f"No meeting #{id}.", ephemeral=True)
        try:
            src = date.fromisoformat(from_date.strip())
            dst = date.fromisoformat(to_date.strip())
        except ValueError:
            return await interaction.response.send_message(
                "Dates must be YYYY-MM-DD.", ephemeral=True)

        exc = dict(m.get("exceptions") or {})
        exc[src.isoformat()] = {"status": "moved", "to": dst.isoformat(),
                                "reason": reason}
        db.update_meeting(str(interaction.guild_id), id, exceptions=exc)

        await interaction.response.send_message(
            f"**{m['name']}** moved from {src.isoformat()} to {dst.isoformat()}.",
            ephemeral=True)

        if announce:
            ch = self.bot.get_channel(int(m["channel_id"]))
            if ch:
                e = discord.Embed(
                    title=f"Rescheduled: {m['name']}",
                    description=f"Moved from **{src.isoformat()}** to "
                                f"**{dst.isoformat()}**.",
                    colour=0xD96C2C)
                if reason:
                    e.add_field(name="Reason", value=reason, inline=False)
                e.set_footer(text=FOOTER_BRAND)
                try:
                    await ch.send(embed=e)
                except discord.HTTPException:
                    pass

    @meeting_group.command(name="restore", description="Undo a cancellation or move.")
    @app_commands.describe(id="Meeting id", meeting_date="The original YYYY-MM-DD")
    async def meeting_restore(self, interaction: discord.Interaction, id: int,
                              meeting_date: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        m = next((x for x in db.get_meetings(str(interaction.guild_id))
                  if x["id"] == id), None)
        if not m:
            return await interaction.response.send_message(f"No meeting #{id}.", ephemeral=True)
        exc = dict(m.get("exceptions") or {})
        if meeting_date.strip() not in exc:
            return await interaction.response.send_message(
                f"No exception recorded for {meeting_date}.", ephemeral=True)
        exc.pop(meeting_date.strip())
        db.update_meeting(str(interaction.guild_id), id, exceptions=exc)
        await interaction.response.send_message(
            f"{meeting_date} restored to the normal schedule.", ephemeral=True)

    @meeting_group.command(name="edit", description="Change a meeting's details.")
    @app_commands.describe(id="Meeting id", name="New name",
                           channel="New reminder channel",
                           meeting_time="New time, 24h e.g. 18:30",
                           location="New location", agenda_url="New agenda link",
                           ping_role="New role to notify",
                           enabled="Turn reminders on or off")
    async def meeting_edit(self, interaction: discord.Interaction, id: int,
                           name: str = None, channel: discord.TextChannel = None,
                           meeting_time: str = None, location: str = None,
                           agenda_url: str = None, ping_role: discord.Role = None,
                           enabled: bool = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)

        fields = {}
        if name is not None:
            fields["name"] = name
        if channel is not None:
            fields["channel_id"] = str(channel.id)
        if meeting_time is not None:
            try:
                hh, mm = [int(x) for x in meeting_time.split(":")[:2]]
                assert 0 <= hh < 24 and 0 <= mm < 60
            except (ValueError, AssertionError):
                return await interaction.response.send_message(
                    "Time must be 24-hour, e.g. 18:30.", ephemeral=True)
            fields["meeting_time"] = meeting_time
        if location is not None:
            fields["location"] = location
        if agenda_url is not None:
            fields["agenda_url"] = agenda_url
        if ping_role is not None:
            fields["ping_role_id"] = str(ping_role.id)
        if enabled is not None:
            fields["enabled"] = int(enabled)

        if not fields:
            return await interaction.response.send_message(
                "Nothing to change. Give me at least one field.", ephemeral=True)
        if not db.update_meeting(str(interaction.guild_id), id, **fields):
            return await interaction.response.send_message(f"No meeting #{id}.", ephemeral=True)
        await interaction.response.send_message(
            f"Meeting #{id} updated: {', '.join(fields)}.", ephemeral=True)

    @meeting_group.command(name="adddates", description="Append dates to an existing meeting.")
    @app_commands.describe(id="Meeting id", dates="Comma-separated YYYY-MM-DD")
    async def meeting_adddates(self, interaction: discord.Interaction, id: int,
                               dates: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        m = next((x for x in db.get_meetings(str(interaction.guild_id))
                  if x["id"] == id), None)
        if not m:
            return await interaction.response.send_message(f"No meeting #{id}.", ephemeral=True)
        if m["schedule"].get("type") != "fixed":
            return await interaction.response.send_message(
                "That meeting follows a recurring rule, not a date list. Use "
                "`/meeting edit` or recreate it with `/meeting dates`.", ephemeral=True)

        parsed, bad = [], []
        for raw in dates.replace(" ", "").split(","):
            if not raw:
                continue
            try:
                parsed.append(date.fromisoformat(raw).isoformat())
            except ValueError:
                bad.append(raw)
        if bad:
            return await interaction.response.send_message(
                f"Could not read: {', '.join(bad[:5])}. Use YYYY-MM-DD.", ephemeral=True)

        sched = dict(m["schedule"])
        sched["dates"] = sorted(set(sched.get("dates", []) + parsed))
        db.update_meeting(str(interaction.guild_id), id, schedule=sched)
        await interaction.response.send_message(
            f"Added {len(parsed)} date(s). **{m['name']}** now has "
            f"{len(sched['dates'])} total.", ephemeral=True)

    @meeting_group.command(name="list", description="Show scheduled meetings.")
    async def meeting_list(self, interaction: discord.Interaction):
        meetings = db.get_meetings(str(interaction.guild_id))
        if not meetings:
            return await interaction.response.send_message(
                "No meetings scheduled. Add one with `/meeting add`.", ephemeral=True)
        now = datetime.now(timezone.utc).astimezone()
        e = discord.Embed(title="Public meetings", colour=BRAND_COLOR)
        for m in meetings:
            nxt = next_occurrence(m["schedule"], m["meeting_time"], now,
                                  m.get("exceptions"))
            val = describe(m["schedule"], m["meeting_time"])
            exc = m.get("exceptions") or {}
            upcoming_exc = {k: v for k, v in exc.items()
                            if k >= date.today().isoformat()}
            if upcoming_exc:
                bits = []
                for k, v in sorted(upcoming_exc.items())[:3]:
                    bits.append(f"{k} cancelled" if v.get("status") == "cancelled"
                                else f"{k} → {v.get('to', '?')}")
                val += "\n⚠ " + "; ".join(bits)
            if nxt:
                val += f"\nNext: <t:{int(nxt.timestamp())}:R>"
            if m.get("location"):
                val += f"\n{m['location']}"
            if not m["enabled"]:
                val += "\n*(disabled)*"
            e.add_field(name=f"#{m['id']} {m['name']}", value=val, inline=False)
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e)

    @meeting_group.command(name="agenda", description="Attach an agenda link to a meeting.")
    @app_commands.describe(id="Meeting id", url="Link to the agenda or packet")
    async def meeting_agenda(self, interaction: discord.Interaction, id: int, url: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        ok = db.update_meeting(str(interaction.guild_id), id, agenda_url=url)
        await interaction.response.send_message(
            f"Agenda set for meeting #{id}." if ok else f"No meeting #{id}.",
            ephemeral=True)

    @meeting_group.command(name="remove", description="Delete a meeting.")
    @app_commands.describe(id="Meeting id")
    async def meeting_remove(self, interaction: discord.Interaction, id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        ok = db.delete_meeting(str(interaction.guild_id), id)
        await interaction.response.send_message(
            f"Meeting #{id} deleted." if ok else f"No meeting #{id}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Meetings(bot))
