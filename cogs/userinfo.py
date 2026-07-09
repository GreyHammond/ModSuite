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
    @app_commands.describe(member="Member mention or user ID (defaults to yourself)")
    async def userinfo(self, interaction: discord.Interaction, member: str = None):
        from utils import resolve_user
        cfg = db.get_config(interaction.guild_id)
        is_staff = _is_staff(interaction.user, cfg)

        if member is None:
            user = interaction.user
            is_member = True
        else:
            try:
                user, is_member = await resolve_user(self.bot, interaction.guild, member)
            except ValueError as e:
                return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        warns  = db.get_active_warn_count(interaction.guild_id, user.id) if is_staff else None
        jailed = db.get_jail(interaction.guild_id, user.id) is not None if is_staff else None

        embed = discord.Embed(
            title=f"👤 {user.display_name if is_member else user.name}",
            color=user.color if is_member and user.color.value else discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if hasattr(user, 'display_avatar'):
            embed.set_thumbnail(url=user.display_avatar.url)

        embed.add_field(name="Username", value=str(user), inline=True)
        embed.add_field(name="ID",       value=str(user.id), inline=True)
        embed.add_field(name="Bot?",     value="Yes" if user.bot else "No", inline=True)
        embed.add_field(name="Account Created", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)

        if is_member:
            embed.add_field(name="Joined Server", value=f"<t:{int(user.joined_at.timestamp())}:R>" if user.joined_at else "Unknown", inline=True)
            roles = [r.mention for r in reversed(user.roles) if r != interaction.guild.default_role]
            embed.add_field(name=f"Roles ({len(roles)})", value=" ".join(roles[:10]) or "None", inline=False)
        else:
            embed.add_field(name="Server Status", value="*Not in server*", inline=True)

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

    @app_commands.command(name="purge", description="Delete messages in this channel with optional filters.")
    @app_commands.describe(
        amount="Number of messages to scan (max 200)",
        user="Only delete messages from this user",
        contains="Only delete messages containing this text",
        bots_only="Only delete messages from bots",
        max_age="Only delete messages newer than this (e.g. 1h, 30m, 2d)",
    )
    async def purge(self, interaction: discord.Interaction, amount: int,
                    user: discord.Member = None, contains: str = None,
                    bots_only: bool = False, max_age: str = None):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        amount = max(1, min(200, amount))
        await interaction.response.defer(ephemeral=True)

        # Parse max_age if provided
        from datetime import timedelta, datetime, timezone
        age_cutoff = None
        if max_age:
            from cogs.moderation import parse_duration
            td = parse_duration(max_age)
            if td:
                age_cutoff = datetime.now(timezone.utc) - td

        contains_lower = contains.lower() if contains else None

        def check(msg):
            if user and msg.author.id != user.id:
                return False
            if bots_only and not msg.author.bot:
                return False
            if contains_lower and contains_lower not in msg.content.lower():
                return False
            if age_cutoff and msg.created_at < age_cutoff:
                return False
            return True

        deleted = await interaction.channel.purge(limit=amount, check=check)
        filters_used = []
        if user:
            filters_used.append(f"user: {user}")
        if contains:
            filters_used.append(f"contains: '{contains}'")
        if bots_only:
            filters_used.append("bots only")
        if max_age:
            filters_used.append(f"max age: {max_age}")

        summary = f"Deleted {len(deleted)} messages."
        if filters_used:
            summary += f" Filters: {', '.join(filters_used)}"
        await interaction.edit_original_response(content=summary)


async def setup(bot: commands.Bot):
    await bot.add_cog(UserInfo(bot))
