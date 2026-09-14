import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
import re
import database as db
import mutes as mutelib
from config import FOOTER_BRAND
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
        self.unban_loop.start()

    def cog_unload(self):
        self.unmute_loop.cancel()
        self.unban_loop.cancel()

    @app_commands.command(name="kick", description="Kick a member from the server.")
    @app_commands.describe(member="Member mention, username, or numeric user ID", reason="Optional reason")
    async def kick(self, interaction: discord.Interaction, member: str, reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        from utils import resolve_user
        try:
            member, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        if not is_member:
            return await interaction.response.send_message(
                f"❌ **{member}** is not in this server, so there is nothing to kick. "
                f"Use `/ban` if you want to keep them out.",
                ephemeral=True,
            )
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
        try:
            await member.kick(reason=f"{interaction.user} -- {reason}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot kick that member.", ephemeral=True)
        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="KICK",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=reason,
        )
        await mutelib.post_public_modlog(
            self.bot, interaction.guild_id, "KICK",
            target_name=getattr(member, 'display_name', str(member)),
            actor_name=interaction.user.display_name,
            reason=reason, duration="")
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
                await user.ban(reason=f"{interaction.user} -- {reason}", delete_message_days=max(0, min(7, delete_days)))
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Cannot ban that member.", ephemeral=True)
        else:
            # Pre-emptive ban by user ID
            try:
                await interaction.guild.ban(user, reason=f"{interaction.user} -- {reason}", delete_message_days=max(0, min(7, delete_days)))
            except discord.Forbidden:
                return await interaction.response.send_message("❌ Cannot ban that user.", ephemeral=True)
            except discord.NotFound:
                return await interaction.response.send_message("❌ User not found.", ephemeral=True)

        embed = discord.Embed(title="🔨 Member Banned", color=discord.Color.red(), timestamp=datetime.utcnow())
        name_display = f"{user} (`{user.id}`)"
        if not is_member:
            name_display += " *(pre-emptive ban)*"
        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="BAN",
            target_id=str(user.id),
            target_username=str(user),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=reason,
        )
        await mutelib.post_public_modlog(
            self.bot, interaction.guild_id, "BAN",
            target_name=getattr(user, 'display_name', str(user)),
            actor_name=interaction.user.display_name,
            reason=reason, duration="")
        embed.add_field(name="User",      value=name_display,             inline=True)
        embed.add_field(name="Banned by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason",    value=reason,                   inline=False)
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="unban", description="Unban a user by ID.")
    @app_commands.describe(user_id="The user's Discord ID (a mention also works)", reason="Optional reason")
    async def unban(self, interaction: discord.Interaction, user_id: str, reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        from utils import parse_user_id, UnknownUser
        uid = parse_user_id(user_id)
        if uid is None:
            return await interaction.response.send_message(
                "❌ That is not a valid user ID. A banned user is not in the server, "
                "so their username cannot be looked up -- use the numeric ID.",
                ephemeral=True,
            )

        try:
            user = await self.bot.fetch_user(uid)
        except Exception:
            # Deleted account: the ban entry still exists and is liftable by ID.
            user = UnknownUser(uid)

        try:
            await interaction.guild.unban(discord.Object(id=uid), reason=f"{interaction.user} -- {reason}")
        except discord.NotFound:
            return await interaction.response.send_message(
                f"❌ `{uid}` is not on the ban list.", ephemeral=True
            )
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ I do not have permission to unban.", ephemeral=True
            )

        # Clear any pending auto-unban so the loop does not retry a lifted ban.
        db.remove_timed_ban(interaction.guild_id, uid)
        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="UNBAN",
            target_id=str(user.id),
            target_username=str(user),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=reason,
        )
        await mutelib.post_public_modlog(
            self.bot, interaction.guild_id, "UNBAN",
            target_name=getattr(user, 'display_name', str(user)),
            actor_name=interaction.user.display_name,
            reason=reason, duration="")
        embed = discord.Embed(title="✅ Member Unbanned", color=discord.Color.green(), timestamp=datetime.utcnow())
        embed.add_field(name="User",        value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Unbanned by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason",      value=reason,                   inline=False)
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="tempban", description="Temporarily ban a member. Auto-unbans after the duration.")
    @app_commands.describe(
        member="Member to ban", duration="Duration: 1h, 1d, 7d, 30d",
        reason="Reason for the ban", delete_days="Days of messages to delete (0-7)",
    )
    async def tempban(self, interaction: discord.Interaction, member: str,
                      duration: str, reason: str = "No reason provided.", delete_days: int = 0):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        td = parse_duration(duration)
        if td is None:
            return await interaction.response.send_message(
                "Invalid duration. Use formats like 1h, 1d, 7d, 30d.", ephemeral=True
            )

        from utils import resolve_user
        try:
            user, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            return await interaction.response.send_message(f"{e}", ephemeral=True)

        if is_member:
            if not can_moderate(interaction.user, user, cfg or {}):
                return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
            try:
                text = _fmt(
                    get_bot_message(db, str(interaction.guild_id), "ban_dm"),
                    user=user.mention, reason=f"{reason} (temp: {_fmt_td(td)})",
                )
                await user.send(embed=discord.Embed(description=text, color=discord.Color.red()))
            except (discord.Forbidden, discord.HTTPException):
                pass
            try:
                await user.ban(reason=f"{interaction.user} -- tempban {_fmt_td(td)}: {reason}",
                               delete_message_days=max(0, min(7, delete_days)))
            except discord.Forbidden:
                return await interaction.response.send_message("Cannot ban that member.", ephemeral=True)
        else:
            try:
                await interaction.guild.ban(user, reason=f"{interaction.user} -- tempban {_fmt_td(td)}: {reason}",
                                            delete_message_days=max(0, min(7, delete_days)))
            except discord.Forbidden:
                return await interaction.response.send_message("Cannot ban that user.", ephemeral=True)
            except discord.NotFound:
                return await interaction.response.send_message("User not found.", ephemeral=True)

        unban_at = datetime.now(timezone.utc) + td
        db.add_timed_ban(interaction.guild_id, user.id, unban_at, reason, interaction.user.display_name)

        # Clear saved roles so unbanned user gets a fresh start
        db.clear_member_roles(str(interaction.guild_id), str(user.id))

        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="TEMPBAN",
            target_id=str(user.id),
            target_username=str(user),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=f"{reason} (duration: {_fmt_td(td)})",
        )

        embed = discord.Embed(title="🔨 Member Temp-Banned", color=discord.Color.red(), timestamp=datetime.utcnow())
        embed.add_field(name="User",      value=f"{user} (`{user.id}`)", inline=True)
        embed.add_field(name="Banned by", value=interaction.user.mention, inline=True)
        embed.add_field(name="Duration",  value=_fmt_td(td),              inline=True)
        embed.add_field(name="Reason",    value=reason,                   inline=False)
        embed.add_field(name="Auto-unban", value=f"<t:{int(unban_at.timestamp())}:F>", inline=False)
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mute", description="Timeout a member. Duration: 10m, 2h, 1d (default: 30 days).")
    @app_commands.describe(member="Member mention, username, or numeric user ID", duration="e.g. 10m, 2h30m, 1d", reason="Optional reason")
    async def mute(self, interaction: discord.Interaction, member: str,
                   duration: str = "", reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        from utils import resolve_user
        try:
            member, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        if not is_member:
            return await interaction.response.send_message(
                f"❌ **{member}** is not in this server. Discord timeouts only "
                f"apply to current members.",
                ephemeral=True,
            )
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
        # "permanent" / "perm" / "0" mean no expiry at all.
        raw = duration.strip().lower()
        permanent = raw in ("permanent", "perm", "forever", "0", "inf")
        if permanent:
            td = None
            # Far-future sentinel so the expiry sweep never picks it up.
            until = datetime(2099, 1, 1, tzinfo=timezone.utc)
        else:
            td = parse_duration(duration) if raw else timedelta(days=config.DEFAULT_MUTE_DAYS)
            if td is None:
                td = timedelta(days=config.DEFAULT_MUTE_DAYS)
            until = datetime.now(timezone.utc) + td

        # The mute ROLE is what actually enforces this. Discord's native
        # timeout caps at 28 days, so relying on it meant a permanent mute
        # quietly lapsed at day 28 with nobody told.
        role_ok = await mutelib.apply_mute(member, reason)

        # Timeout as well when the duration fits inside the cap: it takes
        # effect instantly and survives the member re-joining.
        if td is not None and td <= timedelta(days=28):
            try:
                await member.timeout(datetime.now(timezone.utc) + td,
                                     reason=f"{interaction.user} -- {reason}")
            except (discord.Forbidden, discord.HTTPException):
                pass

        if not role_ok:
            return await interaction.response.send_message(
                "❌ Could not apply the Muted role. Check that I have Manage Roles "
                "and that my role sits above the member's highest role.",
                ephemeral=True)

        db.add_mute(interaction.guild_id, member.id, until, reason)
        # DM the muted user
        try:
            text = _fmt(
                get_bot_message(db, str(interaction.guild_id), "mute_dm"),
                user=member.mention, reason=reason,
                duration="permanently" if td is None else _fmt_td(td),
            )
            await member.send(embed=discord.Embed(description=text, color=discord.Color.dark_orange()))
        except (discord.Forbidden, discord.HTTPException):
            pass
        embed = discord.Embed(title="🔇 Member Muted", color=discord.Color.dark_orange(), timestamp=datetime.utcnow())
        embed.add_field(name="User",     value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Muted by", value=interaction.user.mention,    inline=True)
        embed.add_field(name="Duration",
                        value="Permanent" if td is None else _fmt_td(td), inline=True)
        embed.add_field(name="Expires",
                        value="Never (manual unmute)" if td is None
                              else f"<t:{int(until.timestamp())}:F>", inline=True)
        embed.add_field(name="Reason",   value=reason,                      inline=False)
        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="MUTE",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=f"{reason} (duration: {'permanent' if td is None else _fmt_td(td)})",
        )
        await mutelib.post_public_modlog(
            self.bot, interaction.guild_id, "MUTE",
            target_name=member.display_name,
            actor_name=interaction.user.display_name,
            reason=reason, duration="Permanent" if td is None else _fmt_td(td))
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="mute-setup",
        description="Create the Muted role and lock it out of every channel.")
    async def mute_setup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ Administrator only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        role = await mutelib.get_or_create_muted_role(interaction.guild)
        if role is None:
            return await interaction.followup.send(
                "❌ Could not create the Muted role. I need Manage Roles.",
                ephemeral=True)

        updated, failed = await mutelib.sync_mute_overwrites(interaction.guild, role)
        e = discord.Embed(title="Mute role ready", colour=0xD73739)
        e.add_field(name="Role", value=role.mention, inline=True)
        e.add_field(name="Channels locked", value=str(updated), inline=True)
        if failed:
            e.add_field(name="Failed", value=str(failed), inline=True)
        e.add_field(
            name="Position matters",
            value="Drag this role above every member role, but below "
                  "ModSuite. The bot can only assign roles beneath its own.",
            inline=False)
        e.add_field(
            name="Pull Room excluded",
            value="Muted members can still speak there, which is the point of it.",
            inline=False)
        e.set_footer(text=FOOTER_BRAND)
        await interaction.followup.send(embed=e, ephemeral=True)

    @app_commands.command(
        name="public-modlog",
        description="Post every mute, pull, and removal to a public channel.")
    @app_commands.describe(channel="Channel residents can read. Omit to turn off.")
    async def public_modlog(self, interaction: discord.Interaction,
                            channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "❌ Administrator only.", ephemeral=True)
        if channel is None:
            db.upsert_config(interaction.guild_id, public_modlog_enabled=0)
            return await interaction.response.send_message(
                "Public moderation log turned off.", ephemeral=True)

        db.upsert_config(interaction.guild_id,
                         public_modlog_channel=channel.id,
                         public_modlog_enabled=1)
        await interaction.response.send_message(
            f"Public moderation log set to {channel.mention}. Mutes, pulls, "
            f"kicks, and bans will post there with a reason. Warnings stay "
            f"private.\n\nMake sure @everyone can read it but not post in it.",
            ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Re-apply the mute role to someone who left and rejoined while muted.
        Without this, leaving and rejoining is a one-click mute bypass.
        """
        try:
            row = db.get_mute(member.guild.id, member.id)
        except AttributeError:
            row = next((m for m in db.get_all_mutes()
                        if str(m["guild_id"]) == str(member.guild.id)
                        and str(m["user_id"]) == str(member.id)), None)
        if not row:
            return
        await mutelib.apply_mute(member, "rejoined while muted")
        log_ch = (db.get_config(member.guild.id) or {}).get("modlog_ch_id")
        if log_ch and (ch := self.bot.get_channel(int(log_ch))):
            try:
                await ch.send(embed=discord.Embed(
                    description=f"🔇 {member.mention} rejoined while muted. "
                                f"Mute role re-applied.",
                    colour=0xD96C2C))
            except discord.HTTPException:
                pass

    @app_commands.command(name="unmute", description="Remove a timeout from a member.")
    @app_commands.describe(member="Member mention, username, or numeric user ID", reason="Optional reason")
    async def unmute(self, interaction: discord.Interaction, member: str, reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        from utils import resolve_user
        try:
            member, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        if is_member:
            if not can_moderate(interaction.user, member, cfg or {}):
                return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
            try:
                await member.timeout(None, reason=f"{interaction.user} -- {reason}")
            except (discord.Forbidden, discord.HTTPException):
                pass
            await mutelib.clear_mute(member, reason)
        # If they left while muted there is no timeout left to lift, but the
        # mute row still needs clearing so it does not linger in the dashboard.
        db.remove_mute(interaction.guild_id, member.id)
        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="UNMUTE",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=reason,
        )
        await mutelib.post_public_modlog(
            self.bot, interaction.guild_id, "UNMUTE",
            target_name=getattr(member, 'display_name', str(member)),
            actor_name=interaction.user.display_name,
            reason=reason, duration="")
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
                        await mutelib.clear_mute(member, "duration expired")
                except Exception:
                    pass
            db.remove_mute(row["guild_id"], row["user_id"])
            db.add_mod_log(
                guild_id=str(row["guild_id"]),
                action="UNMUTE",
                target_id=str(row["user_id"]),
                target_username=str(member) if member else "",
                actor_id=str(self.bot.user.id),
                actor_username="ModSuite (auto)",
                reason="Mute duration expired",
            )
            cfg = db.get_config(row["guild_id"])
            if cfg:
                embed = discord.Embed(title="🔊 Auto-Unmuted", color=discord.Color.green(), timestamp=now)
                embed.add_field(name="User", value=f"<@{row['user_id']}>", inline=True)
                await _post_modlog(guild, cfg, embed)

    @tasks.loop(minutes=1)
    async def unban_loop(self):
        now = datetime.now(timezone.utc)
        expired = db.get_expired_bans(now)
        for row in expired:
            guild = self.bot.get_guild(row["guild_id"])
            if guild is None:
                db.remove_timed_ban(row["guild_id"], row["user_id"])
                continue
            try:
                user = await self.bot.fetch_user(row["user_id"])
                await guild.unban(user, reason="Auto-unban: tempban duration expired")
            except Exception:
                pass
            db.remove_timed_ban(row["guild_id"], row["user_id"])
            db.add_mod_log(
                guild_id=str(row["guild_id"]),
                action="UNBAN",
                target_id=str(row["user_id"]),
                target_username="",
                actor_id=str(self.bot.user.id),
                actor_username="ModSuite (auto)",
                reason="Tempban duration expired",
            )
            cfg = db.get_config(row["guild_id"])
            if cfg:
                embed = discord.Embed(title="✅ Auto-Unbanned", color=discord.Color.green(), timestamp=now)
                embed.add_field(name="User", value=f"<@{row['user_id']}>", inline=True)
                embed.add_field(name="Reason", value="Tempban expired", inline=True)
                await _post_modlog(guild, cfg, embed)

    @unban_loop.before_loop
    async def before_unban_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="softban", description="[Mod] Softban a member: saves roles, bans to wipe messages, unbans, restores roles on rejoin.")
    @app_commands.describe(member="Member mention, username, or numeric user ID", reason="Reason for the softban")
    async def softban(self, interaction: discord.Interaction, member: str, reason: str = "No reason provided."):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ You need to be a moderator to use this command.", ephemeral=True)
            return
        from utils import resolve_user
        try:
            member, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return
        if not is_member:
            await interaction.response.send_message(
                f"❌ **{member}** is not in this server, so there are no roles to save. "
                f"Use `/ban` followed by `/unban` to wipe their messages.",
                ephemeral=True,
            )
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

    # ── Role persistence: save on leave ─────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        cfg = db.get_config(member.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return
        if not cfg.get("role_persist_enabled", 1):
            return

        # Save roles (skip @everyone and managed/bot roles)
        role_ids = [
            r.id for r in member.roles
            if r.id != member.guild.default_role.id and not r.managed
        ]
        if role_ids:
            db.save_member_roles(str(member.guild.id), str(member.id), role_ids)

    # ── Role persistence: restore on rejoin ──────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = db.get_config(member.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return

        # ── Softban role restore (legacy, takes priority) ─────────────────────
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
            db.clear_member_roles(str(member.guild.id), str(member.id))

            restored_mentions = " ".join(f"<@&{r.id}>" for r in roles_to_restore)
            log_embed = discord.Embed(
                title="🔄 Softbanned Member Rejoined",
                color=0x57F287,
                timestamp=datetime.utcnow(),
            )
            log_embed.add_field(name="User",           value=f"{member} (`{member.id}`)", inline=False)
            log_embed.add_field(name="Roles Restored", value=restored_mentions or "None", inline=False)
            log_embed.set_footer(text=FOOTER_BRAND)
            await _post_modlog(member.guild, cfg, log_embed)

        # ── General role persistence restore ──────────────────────────────────
        elif cfg.get("role_persist_enabled", 1):
            # Check if user was banned (ban = fresh start, no restore)
            # Look for a recent BAN entry in mod_logs with no subsequent UNBAN
            with db.get_conn() as conn:
                last_ban = conn.execute(
                    """SELECT id FROM mod_logs
                       WHERE guild_id = ? AND target_id = ? AND action = 'BAN'
                       ORDER BY id DESC LIMIT 1""",
                    (str(member.guild.id), str(member.id)),
                ).fetchone()
                last_unban = conn.execute(
                    """SELECT id FROM mod_logs
                       WHERE guild_id = ? AND target_id = ? AND action = 'UNBAN'
                       ORDER BY id DESC LIMIT 1""",
                    (str(member.guild.id), str(member.id)),
                ).fetchone()

            was_banned = (
                last_ban is not None
                and (last_unban is None or last_unban["id"] < last_ban["id"])
            )

            if was_banned:
                # Banned users get a fresh start -- clear saved roles, don't restore
                db.clear_member_roles(str(member.guild.id), str(member.id))
            else:
                # Restore roles for kicks, voluntary leaves, etc.
                saved = db.get_member_roles(str(member.guild.id), str(member.id))
                if saved:
                    roles_to_restore = [
                        member.guild.get_role(rid)
                        for rid in saved
                        if member.guild.get_role(rid) is not None
                    ]
                    if roles_to_restore:
                        try:
                            await member.add_roles(
                                *roles_to_restore,
                                reason="Role persistence: restored on rejoin",
                            )
                        except Exception as e:
                            print(f"[role_persist] Failed to restore roles for {member.id}: {e}")

                        log_embed = discord.Embed(
                            title="🔄 Roles Restored on Rejoin",
                            color=0x57F287,
                            timestamp=datetime.utcnow(),
                        )
                        log_embed.add_field(
                            name="User",
                            value=f"{member} (`{member.id}`)",
                            inline=False,
                        )
                        log_embed.add_field(
                            name="Roles Restored",
                            value=" ".join(f"<@&{r.id}>" for r in roles_to_restore) or "None",
                            inline=False,
                        )
                        log_embed.set_footer(text=FOOTER_BRAND)
                        await _post_modlog(member.guild, cfg, log_embed)

                    db.clear_member_roles(str(member.guild.id), str(member.id))

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
