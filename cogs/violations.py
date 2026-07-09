"""
violations.py -- ModSuite v3.0 Violation Counter Engine

The central escalation pipeline. Every automod trigger calls
`record_violation()` instead of punishing directly. This module:

  1. Records the violation to the DB with a named category
  2. Counts total violations for the user within the configured window
  3. If the threshold is met, auto-jails the user
  4. Logs everything to #mod-log

Raids bypass this entirely and go straight to ban (see raid.py).
Manual staff warns use the existing warn system (warns.py).
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta
import database as db
from utils import get_bot_message, _fmt


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


async def _post_modlog(guild: discord.Guild, cfg: dict, embed: discord.Embed):
    ch_id = cfg.get("modlog_ch_id") if cfg else None
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except discord.HTTPException:
                pass


# ── Core: record + escalate ───────────────────────────────────────────────────

async def record_violation(
    guild: discord.Guild,
    member: discord.Member,
    violation_name: str,
    trigger_detail: str,
    bot: commands.Bot,
    message: discord.Message | None = None,
) -> tuple[int, int, str]:
    """
    Record a violation and check for escalation.

    Returns (violation_id, total_count, escalation_action).
    escalation_action is '' or 'jailed'.
    """
    cfg = db.get_config(guild.id) or {}

    # Record the violation
    violation_id = db.add_violation(
        guild.id, member.id, violation_name, trigger_detail,
    )

    # Count within window
    window = cfg.get("violation_window_minutes") or 60
    total = db.get_all_violation_count(guild.id, member.id, window_minutes=window)
    threshold = cfg.get("violation_jail_threshold") or 5
    escalation = ""

    # Log violation to mod_logs
    db.add_mod_log(
        guild_id=str(guild.id),
        action="VIOLATION",
        target_id=str(member.id),
        target_username=str(member),
        actor_id=str(bot.user.id) if bot.user else "",
        actor_username="AutoMod",
        reason=f"[{violation_name}] {trigger_detail} (#{total} in {window}m)",
    )

    # Log to mod-log channel
    embed = discord.Embed(
        title=f"🔶 Violation -- {violation_name}",
        color=discord.Color.orange(),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
    embed.add_field(name="Count", value=f"**{total}** / {threshold} in {window}m", inline=True)
    embed.add_field(name="Trigger", value=trigger_detail, inline=False)
    if message and message.content:
        snippet = message.content[:400] + "..." if len(message.content) > 400 else message.content
        embed.add_field(name="Content", value=f"```{snippet}```", inline=False)
    await _post_modlog(guild, cfg, embed)

    # Check for escalation: violations -> jail
    if total >= threshold:
        if not db.get_jail(guild.id, member.id):
            try:
                from .jail import do_jail
                from .moderation import parse_duration

                raw_duration = cfg.get("violation_jail_duration") or "1d"
                td = parse_duration(raw_duration) or timedelta(days=1)
                jail_end_time = datetime.utcnow() + td

                await do_jail(
                    guild, member, None,
                    f"Auto-jailed: {total} violations in {window}m (last: {violation_name})",
                    True, bot,
                    jail_end_time=jail_end_time,
                )
                escalation = "jailed"

                # Log the escalation
                esc_embed = discord.Embed(
                    title="🔒 Auto-Jail -- violation threshold reached",
                    color=discord.Color.dark_red(),
                    timestamp=datetime.utcnow(),
                )
                esc_embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
                esc_embed.add_field(name="Violations", value=f"{total} in {window}m", inline=True)
                esc_embed.add_field(name="Duration", value=raw_duration, inline=True)
                await _post_modlog(guild, cfg, esc_embed)

            except Exception as e:
                import logging
                logging.getLogger("ModSuite.violations").warning(
                    f"Auto-jail failed for {member.id}: {e}"
                )

    return violation_id, total, escalation


# ── Cog ────────────────────────────────────────────────────────────────────────

class Violations(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cleanup_loop.start()

    def cog_unload(self):
        self.cleanup_loop.cancel()

    # Clean up old violation records once a day
    @tasks.loop(hours=24)
    async def cleanup_loop(self):
        cleaned = db.cleanup_old_violations(days=30)
        if cleaned > 0:
            import logging
            logging.getLogger("ModSuite.violations").info(
                f"Cleaned {cleaned} violation records older than 30 days."
            )

    @cleanup_loop.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    # ── /violations command group ────────────────────────────────────────────

    violations_group = app_commands.Group(
        name="violations",
        description="View and manage the violation counter system.",
    )

    @violations_group.command(name="check", description="Check a user's active violation count.")
    @app_commands.describe(member="Member to check")
    async def check(self, interaction: discord.Interaction, member: discord.Member):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        window = (cfg or {}).get("violation_window_minutes") or 60
        threshold = (cfg or {}).get("violation_jail_threshold") or 5
        total = db.get_all_violation_count(interaction.guild_id, member.id, window_minutes=window)
        recent = db.get_recent_violations(interaction.guild_id, member.id, limit=10)

        embed = discord.Embed(
            title=f"Violations -- {member.display_name}",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(
            name="Active count",
            value=f"**{total}** / {threshold} threshold (window: {window}m)",
            inline=False,
        )

        if recent:
            lines = []
            for v in recent[:10]:
                ts = v["created_at"][:16]
                lines.append(f"`{ts}` **{v['name']}** -- {v['trigger'][:60]}")
            embed.add_field(
                name=f"Recent ({len(recent)})",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(name="Recent", value="No violations on record.", inline=False)

        embed.set_footer(text="ModSuite v3.0 -- Hammond Digital Studios")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @violations_group.command(name="clear", description="Clear all violations for a user.")
    @app_commands.describe(member="Member to clear violations for")
    async def clear(self, interaction: discord.Interaction, member: discord.Member):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        with db.get_conn() as conn:
            cur = conn.execute(
                "DELETE FROM violations WHERE guild_id = ? AND user_id = ?",
                (interaction.guild_id, member.id),
            )
            count = cur.rowcount

        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="VIOLATIONS_CLEARED",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=f"Cleared {count} violation(s)",
        )

        await interaction.response.send_message(
            f"Cleared **{count}** violation(s) for {member.mention}.", ephemeral=True
        )

    @violations_group.command(name="threshold", description="Set violation-to-jail threshold.")
    @app_commands.describe(
        count="Violations before auto-jail (min 2)",
        window="Window in minutes (min 5)",
    )
    async def threshold(self, interaction: discord.Interaction, count: int, window: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(
            interaction.guild_id,
            violation_jail_threshold=max(2, count),
            violation_window_minutes=max(5, window),
        )
        await interaction.response.send_message(
            f"Violation threshold: **{max(2, count)}** in **{max(5, window)}m** before auto-jail.",
            ephemeral=True,
        )

    @violations_group.command(name="duration", description="Set auto-jail duration from violations.")
    @app_commands.describe(duration="Duration (e.g. 1d, 6h, 2h30m)")
    async def duration(self, interaction: discord.Interaction, duration: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        from .moderation import parse_duration
        td = parse_duration(duration)
        if td is None:
            return await interaction.response.send_message(
                "Invalid duration. Use formats like 10m, 2h, 1d, 2h30m.", ephemeral=True
            )
        db.upsert_config(interaction.guild_id, violation_jail_duration=duration)
        await interaction.response.send_message(
            f"Violation auto-jail duration set to **{duration}**.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Violations(bot))
