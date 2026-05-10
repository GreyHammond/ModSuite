import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import re
import database as db
import config

DURATION_RE = re.compile(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", re.IGNORECASE)


def parse_duration(raw: str) -> timedelta | None:
    m = DURATION_RE.fullmatch(raw.strip())
    if not m or not any(m.groups()):
        return None
    td = timedelta(
        days=int(m.group(1) or 0), hours=int(m.group(2) or 0),
        minutes=int(m.group(3) or 0), seconds=int(m.group(4) or 0),
    )
    return td if td.total_seconds() > 0 else None


def _fmt_td(td: timedelta) -> str:
    total = int(td.total_seconds())
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    parts  = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s: parts.append(f"{s}s")
    return " ".join(parts) or "0s"


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


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.unmute_loop.start()

    def cog_unload(self):
        self.unmute_loop.cancel()

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="Member to kick", reason="Optional reason")
    async def kick(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        try:
            await member.kick(reason=f"{interaction.user} — {reason}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot kick that member.", ephemeral=True)
        embed = discord.Embed(title="👢 Member Kicked", color=discord.Color.orange(), timestamp=datetime.utcnow())
        embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Kicked by", value=interaction.user.mention,    inline=True)
        embed.add_field(name="Reason",    value=reason,                      inline=False)
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="ban", description="Ban a member from the server.")
    @app_commands.describe(member="Member to ban", reason="Optional reason", delete_days="Days of messages to delete (0-7)")
    async def ban(self, interaction: discord.Interaction, member: discord.Member,
                  reason: str = "No reason provided.", delete_days: int = 0):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        try:
            await member.ban(reason=f"{interaction.user} — {reason}", delete_message_days=max(0, min(7, delete_days)))
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot ban that member.", ephemeral=True)
        embed = discord.Embed(title="🔨 Member Banned", color=discord.Color.red(), timestamp=datetime.utcnow())
        embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Banned by", value=interaction.user.mention,    inline=True)
        embed.add_field(name="Reason",    value=reason,                      inline=False)
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unban", description="Unban a user by ID.")
    @app_commands.describe(user_id="The user's Discord ID", reason="Optional reason")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        try:
            uid  = int(user_id)
            user = await self.bot.fetch_user(uid)
            await interaction.guild.unban(user, reason=f"{interaction.user} — {reason}")
        except Exception:
            return await interaction.response.send_message("❌ User not found or not banned.", ephemeral=True)
        embed = discord.Embed(title="✅ Member Unbanned", color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="User",        value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Unbanned by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason",      value=reason,                   inline=False)
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mute", description="Timeout a member. Duration: 10m, 2h, 1d (default: 30 days).")
    @app_commands.describe(member="Member to mute", duration="e.g. 10m, 2h30m, 1d", reason="Optional reason")
    async def mute(self, interaction: discord.Interaction, member: discord.Member,
                   duration: str = "", reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        td = parse_duration(duration) if duration.strip() else timedelta(days=config.DEFAULT_MUTE_DAYS)
        if td is None:
            td = timedelta(days=config.DEFAULT_MUTE_DAYS)
        discord_td = min(td, timedelta(days=28))
        until = datetime.now(timezone.utc) + td
        try:
            await member.timeout(datetime.now(timezone.utc) + discord_td, reason=f"{interaction.user} — {reason}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot mute that member.", ephemeral=True)
        db.add_mute(interaction.guild_id, member.id, until, reason)
        embed = discord.Embed(title="🔇 Member Muted", color=discord.Color.dark_orange(), timestamp=datetime.utcnow())
        embed.add_field(name="User",     value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Muted by", value=interaction.user.mention,    inline=True)
        embed.add_field(name="Duration", value=_fmt_td(td),                 inline=True)
        embed.add_field(name="Expires",  value=f"<t:{int(until.timestamp())}:F>", inline=True)
        embed.add_field(name="Reason",   value=reason,                      inline=False)
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unmute", description="Remove a timeout from a member.")
    @app_commands.describe(member="Member to unmute", reason="Optional reason")
    async def unmute(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        try:
            await member.timeout(None, reason=f"{interaction.user} — {reason}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot unmute that member.", ephemeral=True)
        db.remove_mute(interaction.guild_id, member.id)
        embed = discord.Embed(title="🔊 Member Unmuted", color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="User",        value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Unmuted by",  value=interaction.user.mention,    inline=True)
        embed.add_field(name="Reason",      value=reason,                      inline=False)
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @tasks.loop(minutes=1)
    async def unmute_loop(self):
        now     = datetime.now(timezone.utc)
        expired = db.get_expired_mutes(now)
        for row in expired:
            guild  = self.bot.get_guild(row["guild_id"])
            if guild is None:
                db.remove_mute(row["guild_id"], row["user_id"])
                continue
            member = guild.get_member(row["user_id"])
            if member:
                try:
                    if member.is_timed_out():
                        await member.timeout(None, reason="Auto-unmute: duration expired")
                except Exception:
                    pass
            db.remove_mute(row["guild_id"], row["user_id"])
            cfg = db.get_config(row["guild_id"])
            if cfg:
                embed = discord.Embed(title="🔊 Auto-Unmuted", color=discord.Color.green(), timestamp=now)
                embed.add_field(name="User", value=f"<@{row['user_id']}>", inline=True)
                await _post_modlog(guild, cfg, embed)

    @unmute_loop.before_loop
    async def before_unmute_loop(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = db.get_config(member.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return
        welcome_msg = cfg.get("welcome_msg") or config.DEFAULT_WELCOME_MSG
        sr_ch_id    = cfg.get("selfroles_ch_id")
        text = welcome_msg.format(
            user=member.mention, server=member.guild.name,
            selfroles_ch=sr_ch_id or "self-roles",
        )
        system_ch = member.guild.system_channel
        if system_ch and system_ch.permissions_for(member.guild.me).send_messages:
            await system_ch.send(text)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
