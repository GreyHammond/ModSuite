import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from collections import deque
import database as db


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
            await ch.send(embed=embed)


class Raid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> deque of join timestamps
        self._join_times: dict[int, deque] = {}
        self._locked_guilds: set[int] = set()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = db.get_config(member.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return

        # Auto-role
        auto_role_id = cfg.get("auto_role_id")
        if auto_role_id:
            role = member.guild.get_role(auto_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                except discord.Forbidden:
                    pass

        # Raid detection
        threshold_joins   = cfg.get("raid_join_count",   10)
        threshold_seconds = cfg.get("raid_join_seconds", 10)

        gid = member.guild.id
        if gid not in self._join_times:
            self._join_times[gid] = deque()

        now = datetime.now(timezone.utc).timestamp()
        self._join_times[gid].append(now)

        # Prune old entries
        cutoff = now - threshold_seconds
        while self._join_times[gid] and self._join_times[gid][0] < cutoff:
            self._join_times[gid].popleft()

        if len(self._join_times[gid]) >= threshold_joins and gid not in self._locked_guilds:
            await self._lockdown(member.guild, cfg, auto=True)

    async def _lockdown(self, guild: discord.Guild, cfg: dict, auto: bool = False):
        self._locked_guilds.add(guild.id)
        everyone = guild.default_role

        # Lock all non-staff text channels
        for ch in guild.text_channels:
            ow = ch.overwrites_for(everyone)
            if ow.send_messages is not False:
                try:
                    await ch.set_permissions(everyone, send_messages=False, reason="Raid lockdown")
                except discord.Forbidden:
                    pass

        embed = discord.Embed(
            title="🚨 RAID LOCKDOWN ACTIVATED",
            description="Suspicious join activity detected. All channels locked.\nUse `/unlock` to restore normal access.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Triggered", value="Automatically" if auto else "Manually", inline=True)
        await _post_modlog(guild, cfg, embed)

    async def _unlock(self, guild: discord.Guild, cfg: dict):
        self._locked_guilds.discard(guild.id)
        everyone = guild.default_role

        for ch in guild.text_channels:
            ow = ch.overwrites_for(everyone)
            if ow.send_messages is False:
                try:
                    await ch.set_permissions(everyone, send_messages=None, reason="Raid lockdown lifted")
                except discord.Forbidden:
                    pass

        embed = discord.Embed(
            title="✅ Lockdown Lifted",
            description="Server access has been restored.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await _post_modlog(guild, cfg, embed)

    @app_commands.command(name="lockdown", description="Manually lock all channels.")
    async def lockdown(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._lockdown(interaction.guild, cfg, auto=False)
        await interaction.edit_original_response(content="🔒 Server locked down.")

    @app_commands.command(name="unlock", description="Lift lockdown and restore channel access.")
    async def unlock(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._unlock(interaction.guild, cfg)
        await interaction.edit_original_response(content="✅ Lockdown lifted.")

    @app_commands.command(name="autorole", description="Set a role to auto-assign to new members.")
    @app_commands.describe(role="Role to assign, or leave blank to disable")
    async def autorole(self, interaction: discord.Interaction, role: discord.Role = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
        db.upsert_config(interaction.guild_id, auto_role_id=role.id if role else None)
        if role:
            await interaction.response.send_message(f"✅ Auto-role set to {role.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Auto-role disabled.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Raid(bot))
