import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import database as db
import config


async def _post_modlog(guild: discord.Guild, cfg: dict, embed: discord.Embed):
    ch_id = cfg.get("modlog_ch_id") if cfg else None
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            await ch.send(embed=embed)


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


async def do_warn(guild: discord.Guild, user: discord.Member, mod: discord.Member,
                  reason: str, bot: commands.Bot) -> tuple[int, int, str]:
    """
    Add a warn, handle auto-escalation.
    Returns (warn_id, total_active_warns, escalation_action)
    escalation_action is one of: '', 'muted', 'banned'
    """
    cfg = db.get_config(guild.id)
    warn_id = db.add_warn(guild.id, user.id, mod.id, mod.display_name, reason)
    total   = db.get_active_warn_count(guild.id, user.id)
    action  = ""

    mute_at = cfg.get("warn_mute_threshold", config.DEFAULT_WARN_MUTE_AT) if cfg else config.DEFAULT_WARN_MUTE_AT
    ban_at  = cfg.get("warn_ban_threshold",  config.DEFAULT_WARN_BAN_AT)  if cfg else config.DEFAULT_WARN_BAN_AT

    if total >= ban_at:
        try:
            await user.ban(reason=f"Auto-ban: reached {total} warnings")
            action = "banned"
        except discord.Forbidden:
            pass
    elif total >= mute_at:
        try:
            until = datetime.now(timezone.utc) + timedelta(hours=1)
            await user.timeout(until, reason=f"Auto-mute: reached {total} warnings")
            action = "muted"
        except discord.Forbidden:
            pass

    return warn_id, total, action


class Warns(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.describe(member="Member to warn", reason="Reason for the warning")
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("❌ Cannot warn a bot.", ephemeral=True)

        await interaction.response.defer()
        warn_id, total, escalation = await do_warn(interaction.guild, member, interaction.user, reason, self.bot)

        embed = discord.Embed(title="⚠️ Member Warned", color=discord.Color.yellow(), timestamp=datetime.utcnow())
        embed.add_field(name="User",     value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Warned by", value=interaction.user.mention,  inline=True)
        embed.add_field(name="Reason",   value=reason,                     inline=False)
        embed.add_field(name="Total Warnings", value=str(total),           inline=True)
        if escalation:
            embed.add_field(name="Auto Action", value=f"🤖 User was **{escalation}** automatically", inline=False)
        embed.set_footer(text=f"Warn ID: {warn_id}")

        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.followup.send(embed=embed)

        try:
            dm_embed = discord.Embed(
                description=f"You have received a warning in **{interaction.guild.name}**.\n**Reason:** {reason}\n**Total warnings:** {total}",
                color=discord.Color.yellow(),
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    @app_commands.command(name="unwarn", description="Remove a specific warning by ID.")
    @app_commands.describe(warn_id="The warning ID to remove (shown in /history)")
    async def unwarn(self, interaction: discord.Interaction, warn_id: int):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        removed = db.remove_warn(warn_id)
        if removed:
            await interaction.response.send_message(f"✅ Warning `#{warn_id}` removed.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Warning `#{warn_id}` not found or already removed.", ephemeral=True)

    @app_commands.command(name="history", description="View moderation history for a user.")
    @app_commands.describe(member="Member to look up")
    async def history(self, interaction: discord.Interaction, member: discord.Member):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        warns = db.get_warns(interaction.guild_id, member.id, active_only=False)

        embed = discord.Embed(
            title=f"📋 Moderation History — {member.display_name}",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)

        if not warns:
            embed.description = "No warnings on record."
        else:
            active   = [w for w in warns if w["active"]]
            inactive = [w for w in warns if not w["active"]]
            embed.add_field(name="Active Warnings",   value=str(len(active)),   inline=True)
            embed.add_field(name="Removed Warnings",  value=str(len(inactive)), inline=True)
            embed.add_field(name="\u200b", value="\u200b", inline=True)

            for w in warns[-10:]:  # show last 10
                status = "✅" if w["active"] else "~~removed~~"
                embed.add_field(
                    name=f"#{w['id']} {status}",
                    value=f"**By:** {w['mod_name']}\n**Reason:** {w['reason']}\n**Date:** {w['timestamp'][:10]}",
                    inline=True,
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Warns(bot))
