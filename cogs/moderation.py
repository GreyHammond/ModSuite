import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import re
import database as db
import config
from utils import can_moderate, hierarchy_refusal_embed, get_bot_message, _fmt

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
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
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

    @app_commands.command(name="ban", description="Ban a member or user ID from the server.")
    @app_commands.describe(member="Member mention or user ID", reason="Optional reason", delete_days="Days of messages to delete (0-7)")
    async def ban(self, interaction: discord.Interaction, member: str,
                  reason: str = "No reason provided.", delete_days: int = 0):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        from utils import resolve_user
        try:
            user, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        if is_member:
            if not can_moderate(interaction.user, user, cfg or {}):
                return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
            # DM the user before banning
            try:
                text = _fmt(
                    get_bot_message(db, str(interaction.guild_id), "ban_dm"),
                    user=user.mention, reason=reason,
                )
                await user.send(embed=discord.Embed(description=text, color=discord.Color.red()))
            except (discord.Forbidden, discord.HTTPException):
                pass
            try:
                await user.ban(reason=f"{interaction.user} — {reason}", delete_message_days=max(0, min(7, delete_days)))
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Cannot ban that member.", ephemeral=True)
        else:
            # Pre-emptive ban by user ID
            try:
                await interaction.guild.ban(user, reason=f"{interaction.user} — {reason}", delete_message_days=max(0, min(7, delete_days)))
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Cannot ban that user.", ephemeral=True)
            except discord.NotFound:
                return await interaction.response.send_message("❌ User not found.", ephemeral=True)

        embed = discord.Embed(title="🔨 Member Banned", color=discord.Color.red(), timestamp=datetime.utcnow())
        name_display = f"{user} (`{user.id}`)"
        if not is_member:
            name_display += " *(pre-emptive ban)*"
        embed.add_field(name="User",      value=name_display,             inline=True)
        embed.add_field(name="Banned by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason",    value=reason,                   inline=False)
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
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
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
        # DM the muted user
        try:
            text = _fmt(
                get_bot_message(db, str(interaction.guild_id), "mute_dm"),
                user=member.mention, reason=reason, duration=_fmt_td(td),
            )
            await member.send(embed=discord.Embed(description=text, color=discord.Color.dark_orange()))
        except (discord.Forbidden, discord.HTTPException):
            pass
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
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
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

    @app_commands.command(name="softban", description="[Mod] Softban a member: saves roles, bans to wipe messages, unbans, restores roles on rejoin.")
    @app_commands.describe(member="Member to softban", reason="Reason for the softban")
    async def softban(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ You need to be a moderator to use this command.", ephemeral=True)
            return
        if not can_moderate(interaction.user, member, cfg or {}):
            await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
            return
        if not interaction.guild.me.guild_permissions.ban_members:
            await interaction.response.send_message("❌ I need the **Ban Members** permission.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Save roles (skip @everyone and managed/bot roles)
        roles_to_save = [
            r.id for r in member.roles
            if r.id != interaction.guild.default_role.id and not r.managed
        ]
        db.save_softban_roles(str(interaction.guild_id), str(member.id), roles_to_save)

        # Ban (deletes last 7 days of messages) then immediately unban
        try:
            await member.ban(delete_message_days=7, reason=f"Softban by {interaction.user}: {reason}")
            await interaction.guild.unban(member, reason="Softban: immediate unban")
        except discord.Forbidden:
            await interaction.followup.send("❌ I don't have permission to ban that member.", ephemeral=True)
            db.clear_softban_roles(str(interaction.guild_id), str(member.id))
            return
        except Exception as e:
            await interaction.followup.send(f"❌ Something went wrong: {e}", ephemeral=True)
            db.clear_softban_roles(str(interaction.guild_id), str(member.id))
            return

        # Log
        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="SOFTBAN",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=reason,
        )
        embed = discord.Embed(title="🔨 Member Softbanned", color=0xE67E22, timestamp=datetime.utcnow())
        embed.add_field(name="User",   value=f"{member} (`{member.id}`)", inline=False)
        embed.add_field(name="Mod",    value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.set_footer(text="Roles will be restored automatically when they rejoin.")
        await _post_modlog(interaction.guild, cfg or {}, embed)

        await interaction.followup.send(
            f"✅ **{member}** has been softbanned. Their messages have been wiped and roles saved for when they rejoin.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = db.get_config(member.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return

        # ── Softban role restore ──────────────────────────────────────────────
        saved_role_ids = db.get_softban_roles(str(member.guild.id), str(member.id))
        if saved_role_ids:
            roles_to_restore = [
                member.guild.get_role(rid)
                for rid in saved_role_ids
                if member.guild.get_role(rid) is not None
            ]
            if roles_to_restore:
                try:
                    await member.add_roles(*roles_to_restore, reason="Softban role restore on rejoin")
                except Exception as e:
                    print(f"[softban] Failed to restore roles for {member.id}: {e}")

            db.clear_softban_roles(str(member.guild.id), str(member.id))

            # Notify mod-log
            restored_mentions = " ".join(f"<@&{r.id}>" for r in roles_to_restore)
            log_embed = discord.Embed(
                title="🔄 Softbanned Member Rejoined",
                color=0x57F287,
                timestamp=datetime.utcnow(),
            )
            log_embed.add_field(name="User",           value=f"{member} (`{member.id}`)", inline=False)
            log_embed.add_field(name="Roles Restored", value=restored_mentions or "None", inline=False)
            log_embed.set_footer(text="ModSuite · Hammond Digital Studios")
            await _post_modlog(member.guild, cfg, log_embed)

        # ── Welcome message ───────────────────────────────────────────────────
        text = _fmt(
            get_bot_message(db, str(member.guild.id), "welcome_message"),
            user=member.mention,
        )
        system_ch = member.guild.system_channel
        if system_ch and system_ch.permissions_for(member.guild.me).send_messages:
            await system_ch.send(text)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
