import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import database as db


class Reports(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Register both context menu commands
        report_cmd = app_commands.ContextMenu(
            name="Report Message",
            callback=self.report_message,
        )
        emergency_cmd = app_commands.ContextMenu(
            name="Report Message (Emergency)",
            callback=self.emergency_report_message,
        )
        self.bot.tree.add_command(report_cmd)
        self.bot.tree.add_command(emergency_cmd)

    async def _get_reports_channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        cfg = db.get_config(guild.id)
        if cfg is None:
            return None
        ch_id = cfg.get("reports_ch_id")
        return guild.get_channel(ch_id) if ch_id else None

    async def report_message(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True)

        reports_ch = await self._get_reports_channel(interaction.guild)
        if reports_ch is None:
            return await interaction.edit_original_response(
                content="❌ Reports channel not set up. Ask an admin to run `/setup`."
            )

        cfg      = db.get_config(interaction.guild_id)
        mod_role = interaction.guild.get_role(cfg.get("mod_role_id")) if cfg else None

        embed = discord.Embed(
            title="🚩 Message Reported",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Reported User",    value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
        embed.add_field(name="Channel",          value=message.channel.mention,                             inline=True)
        embed.add_field(name="Jump to Message",  value=f"[Click here]({message.jump_url})",                 inline=True)

        content_preview = message.content[:1000] if message.content else "*[No text content]*"
        embed.add_field(name="Message Content",  value=content_preview, inline=False)
        embed.set_footer(text="Reporter is anonymous")

        ping = mod_role.mention if mod_role else "@Moderators"
        await reports_ch.send(content=ping, embed=embed)

        await interaction.edit_original_response(
            content="✅ Your report has been submitted anonymously. Staff have been notified."
        )

    async def emergency_report_message(self, interaction: discord.Interaction, message: discord.Message):
        await interaction.response.defer(ephemeral=True)

        reports_ch = await self._get_reports_channel(interaction.guild)
        if reports_ch is None:
            return await interaction.edit_original_response(
                content="❌ Reports channel not set up. Ask an admin to run `/setup`."
            )

        cfg        = db.get_config(interaction.guild_id)
        mod_role   = interaction.guild.get_role(cfg.get("mod_role_id"))   if cfg else None
        owner_role = interaction.guild.get_role(cfg.get("owner_role_id")) if cfg else None

        embed = discord.Embed(
            title="🚨 EMERGENCY REPORT -- ALL STAFF REQUIRED",
            description="⚠️ **This report has been flagged as an emergency. Immediate attention required.** ⚠️",
            color=discord.Color.red(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Reported User",   value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
        embed.add_field(name="Channel",         value=message.channel.mention,                             inline=True)
        embed.add_field(name="Jump to Message", value=f"[Click here]({message.jump_url})",                 inline=True)

        content_preview = message.content[:1000] if message.content else "*[No text content]*"
        embed.add_field(name="Message Content", value=content_preview, inline=False)
        embed.set_footer(text="Reporter is anonymous  •  EMERGENCY")

        pings = " ".join(r.mention for r in [owner_role, mod_role] if r)
        if not pings:
            pings = "@Owner @Moderators"

        await reports_ch.send(content=f"🚨 {pings} 🚨", embed=embed)

        await interaction.edit_original_response(
            content="✅ Your emergency report has been submitted anonymously. All staff have been alerted."
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Reports(bot))
