import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import database as db


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


class UserInfo(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="userinfo", description="View information about a user.")
    @app_commands.describe(member="Member to look up (defaults to yourself)")
    async def userinfo(self, interaction: discord.Interaction, member: discord.Member = None):
        member = member or interaction.user
        cfg    = db.get_config(interaction.guild_id)

        is_staff = _is_staff(interaction.user, cfg)
        warns    = db.get_active_warn_count(interaction.guild_id, member.id) if is_staff else None
        jailed   = db.get_jail(interaction.guild_id, member.id) is not None if is_staff else None

        embed = discord.Embed(
            title=f"👤 {member.display_name}",
            color=member.color if member.color.value else discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Username",   value=str(member),                                             inline=True)
        embed.add_field(name="ID",         value=str(member.id),                                          inline=True)
        embed.add_field(name="Bot?",       value="Yes" if member.bot else "No",                           inline=True)
        embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>",      inline=True)
        embed.add_field(name="Joined Server",   value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown", inline=True)

        roles = [r.mention for r in reversed(member.roles) if r != interaction.guild.default_role]
        embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:10]) or "None", inline=False)

        if is_staff:
            embed.add_field(name="Active Warns", value=str(warns), inline=True)
            embed.add_field(name="Jailed",       value="🔒 Yes" if jailed else "No", inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="serverinfo", description="View information about this server.")
    async def serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(
            title=f"🏠 {guild.name}",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)

        embed.add_field(name="Owner",         value=f"<@{guild.owner_id}>",                         inline=True)
        embed.add_field(name="Members",       value=str(guild.member_count),                         inline=True)
        embed.add_field(name="Boost Level",   value=str(guild.premium_tier),                         inline=True)
        embed.add_field(name="Boosts",        value=str(guild.premium_subscription_count),            inline=True)
        embed.add_field(name="Roles",         value=str(len(guild.roles)),                            inline=True)
        embed.add_field(name="Channels",      value=str(len(guild.channels)),                         inline=True)
        embed.add_field(name="Created",       value=f"<t:{int(guild.created_at.timestamp())}:R>",     inline=True)
        embed.add_field(name="Verification",  value=str(guild.verification_level).title(),            inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="purge", description="Delete messages in this channel.")
    @app_commands.describe(amount="Number of messages to delete (max 100)")
    async def purge(self, interaction: discord.Interaction, amount: int):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        amount = max(1, min(100, amount))
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.edit_original_response(content=f"✅ Deleted {len(deleted)} messages.")


async def setup(bot: commands.Bot):
    await bot.add_cog(UserInfo(bot))
