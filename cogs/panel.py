"""
Mod Panel -- persistent + ephemeral context-aware UI.
All actions call the same underlying functions as slash commands.
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone, timedelta
import database as db
import config
from utils import can_moderate, hierarchy_refusal_embed
from .moderation import parse_duration, _fmt_td, _post_modlog as mod_log
from .warns import do_warn
from .jail import do_jail, do_unjail
from .modmail import _close_ticket


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


# ── Context detection ─────────────────────────────────────────────────────────

def _detect_context(channel_id: int) -> str:
    """Returns 'modmail', 'jail', or 'general'"""
    if db.get_open_ticket_by_channel(channel_id):
        return "modmail"
    if db.get_jail_by_channel(channel_id):
        return "jail"
    return "general"


# ══════════════════════════════════════════════════════════════════════════════
# Modals
# ══════════════════════════════════════════════════════════════════════════════

class MuteModal(discord.ui.Modal, title="Mute Member"):
    username = discord.ui.TextInput(label="Username or ID", placeholder="hammond")
    duration = discord.ui.TextInput(label="Duration (10m / 2h / 1d -- blank = 30 days)", required=False)
    reason   = discord.ui.TextInput(label="Reason", required=False, style=discord.TextStyle.short)

    def __init__(self, bot, guild):
        super().__init__()
        self.bot   = bot
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        cfg    = db.get_config(self.guild.id)
        member = self.guild.get_member_named(self.username.value.strip())
        if member is None:
            try:
                member = await self.guild.fetch_member(int(self.username.value.strip()))
            except Exception:
                return await interaction.response.send_message("❌ Member not found.", ephemeral=True)

        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)

        td = parse_duration(self.duration.value.strip()) if self.duration.value.strip() else None
        if td is None:
            td = timedelta(days=config.DEFAULT_MUTE_DAYS)

        MAX_DISCORD = timedelta(days=28)
        discord_td  = min(td, MAX_DISCORD)
        until       = datetime.now(timezone.utc) + td

        try:
            await member.timeout(datetime.now(timezone.utc) + discord_td,
                                 reason=f"{interaction.user} -- {self.reason.value or 'No reason'}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot mute that member.", ephemeral=True)

        db.add_mute(self.guild.id, member.id, until, self.reason.value or "No reason")

        embed = discord.Embed(title="🔇 Member Muted", color=discord.Color.dark_orange(), timestamp=datetime.utcnow())
        embed.add_field(name="User",     value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Muted by", value=interaction.user.mention,    inline=True)
        embed.add_field(name="Duration", value=_fmt_td(td),                 inline=True)
        embed.add_field(name="Reason",   value=self.reason.value or "No reason", inline=False)
        await mod_log(self.guild, cfg, embed)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class KickModal(discord.ui.Modal, title="Kick Member"):
    username = discord.ui.TextInput(label="Username or ID")
    reason   = discord.ui.TextInput(label="Reason", required=False)

    def __init__(self, bot, guild):
        super().__init__()
        self.bot   = bot
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        cfg    = db.get_config(self.guild.id)
        member = self.guild.get_member_named(self.username.value.strip())
        if member is None:
            try:
                member = await self.guild.fetch_member(int(self.username.value.strip()))
            except Exception:
                return await interaction.response.send_message("❌ Member not found.", ephemeral=True)
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
        try:
            await member.kick(reason=f"{interaction.user} -- {self.reason.value or 'No reason'}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot kick that member.", ephemeral=True)

        embed = discord.Embed(title="👢 Member Kicked", color=discord.Color.orange(), timestamp=datetime.utcnow())
        embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Kicked by", value=interaction.user.mention,    inline=True)
        embed.add_field(name="Reason",    value=self.reason.value or "No reason", inline=False)
        await mod_log(self.guild, cfg, embed)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class BanModal(discord.ui.Modal, title="Ban Member"):
    username = discord.ui.TextInput(label="Username or ID")
    reason   = discord.ui.TextInput(label="Reason", required=False)

    def __init__(self, bot, guild):
        super().__init__()
        self.bot   = bot
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        cfg    = db.get_config(self.guild.id)
        member = self.guild.get_member_named(self.username.value.strip())
        if member is None:
            try:
                member = await self.guild.fetch_member(int(self.username.value.strip()))
            except Exception:
                return await interaction.response.send_message("❌ Member not found.", ephemeral=True)
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
        try:
            await member.ban(reason=f"{interaction.user} -- {self.reason.value or 'No reason'}")
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot ban that member.", ephemeral=True)

        embed = discord.Embed(title="🔨 Member Banned", color=discord.Color.red(), timestamp=datetime.utcnow())
        embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Banned by", value=interaction.user.mention,    inline=True)
        embed.add_field(name="Reason",    value=self.reason.value or "No reason", inline=False)
        await mod_log(self.guild, cfg, embed)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class WarnModal(discord.ui.Modal, title="Warn Member"):
    username = discord.ui.TextInput(label="Username or ID")
    reason   = discord.ui.TextInput(label="Reason")

    def __init__(self, bot, guild):
        super().__init__()
        self.bot   = bot
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        member = self.guild.get_member_named(self.username.value.strip())
        if member is None:
            try:
                member = await self.guild.fetch_member(int(self.username.value.strip()))
            except Exception:
                return await interaction.response.send_message("❌ Member not found.", ephemeral=True)

        cfg = db.get_config(self.guild.id)
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)

        warn_id, total, escalation = await do_warn(
            self.guild, member, interaction.user, self.reason.value, self.bot
        )
        embed = discord.Embed(title="⚠️ Member Warned", color=discord.Color.yellow(), timestamp=datetime.utcnow())
        embed.add_field(name="User",           value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Total Warnings", value=str(total),                  inline=True)
        embed.add_field(name="Reason",         value=self.reason.value,           inline=False)
        if escalation:
            embed.add_field(name="Auto Action", value=f"User was **{escalation}** automatically", inline=False)
        embed.set_footer(text=f"Warn ID: {warn_id}")
        await mod_log(self.guild, cfg, embed)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TempBanModal(discord.ui.Modal, title="Temp-Ban Member"):
    username = discord.ui.TextInput(label="Username or ID")
    duration = discord.ui.TextInput(label="Duration (e.g. 1d, 7d, 30d)", placeholder="7d")
    reason   = discord.ui.TextInput(label="Reason", required=False)

    def __init__(self, bot, guild):
        super().__init__()
        self.bot   = bot
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        from .moderation import parse_duration, _fmt_td
        cfg    = db.get_config(self.guild.id)
        member = self.guild.get_member_named(self.username.value.strip())
        if member is None:
            try:
                member = await self.guild.fetch_member(int(self.username.value.strip()))
            except Exception:
                return await interaction.response.send_message("Member not found.", ephemeral=True)
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)

        td = parse_duration(self.duration.value.strip())
        if td is None:
            return await interaction.response.send_message(
                "Invalid duration. Use formats like 1d, 7d, 30d.", ephemeral=True
            )

        reason = self.reason.value or "No reason"
        unban_at = datetime.now(timezone.utc) + td

        try:
            await member.ban(reason=f"{interaction.user} -- tempban {_fmt_td(td)}: {reason}")
        except discord.Forbidden:
            return await interaction.response.send_message("Cannot ban that member.", ephemeral=True)

        db.add_timed_ban(self.guild.id, member.id, unban_at, reason, interaction.user.display_name)
        db.clear_member_roles(str(self.guild.id), str(member.id))
        db.add_mod_log(
            guild_id=str(self.guild.id),
            action="TEMPBAN",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=f"{reason} (duration: {_fmt_td(td)})",
        )

        embed = discord.Embed(title="🔨 Member Temp-Banned", color=discord.Color.red(), timestamp=datetime.utcnow())
        embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
        embed.add_field(name="Banned by", value=interaction.user.mention,    inline=True)
        embed.add_field(name="Duration",  value=_fmt_td(td),                 inline=True)
        embed.add_field(name="Reason",    value=reason,                      inline=False)
        await mod_log(self.guild, cfg, embed)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class JailModal(discord.ui.Modal, title="Jail Member"):
    username = discord.ui.TextInput(label="Username or ID")
    reason   = discord.ui.TextInput(label="Reason", required=False)
    notify   = discord.ui.TextInput(label="DM the user? (yes/no)", default="yes", max_length=3)

    def __init__(self, bot, guild):
        super().__init__()
        self.bot   = bot
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        member = self.guild.get_member_named(self.username.value.strip())
        if member is None:
            try:
                member = await self.guild.fetch_member(int(self.username.value.strip()))
            except Exception:
                return await interaction.response.send_message("❌ Member not found.", ephemeral=True)

        cfg = db.get_config(self.guild.id)
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)

        if db.get_jail(self.guild.id, member.id):
            return await interaction.response.send_message("❌ Already jailed.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        notify  = self.notify.value.strip().lower() in ("yes", "y", "true")
        jail_ch = await do_jail(self.guild, member, interaction.user,
                                self.reason.value or "No reason provided.", notify, self.bot)
        cfg = db.get_config(self.guild.id)
        log_embed = discord.Embed(title="🔒 Member Jailed", color=discord.Color.dark_red(), timestamp=datetime.utcnow())
        log_embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
        log_embed.add_field(name="Jailed by", value=interaction.user.mention,    inline=True)
        log_embed.add_field(name="Channel",   value=jail_ch.mention,             inline=True)
        await mod_log(self.guild, cfg, log_embed)
        await interaction.edit_original_response(content=f"✅ {member.mention} jailed in {jail_ch.mention}.")


class PurgeModal(discord.ui.Modal, title="Purge Messages"):
    amount = discord.ui.TextInput(label="Number of messages to delete (max 100)", default="10")

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            n = max(1, min(100, int(self.amount.value.strip())))
        except ValueError:
            return await interaction.response.send_message("❌ Enter a number.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        deleted = await self.channel.purge(limit=n)
        await interaction.edit_original_response(content=f"✅ Deleted {len(deleted)} messages.")


class ModMailReplyModal(discord.ui.Modal, title="Reply to ModMail User"):
    message   = discord.ui.TextInput(label="Your message", style=discord.TextStyle.long, max_length=1800)
    anonymous = discord.ui.TextInput(label="Send anonymously? (yes/no)", default="no", max_length=3)

    def __init__(self, bot, ticket, user):
        super().__init__()
        self.bot    = bot
        self.ticket = ticket
        self._user  = user

    async def on_submit(self, interaction: discord.Interaction):
        anon    = self.anonymous.value.strip().lower() in ("yes", "y")
        content = self.message.value.strip()
        display = "Staff" if anon else interaction.user.display_name

        embed = discord.Embed(description=content, color=discord.Color.blurple(), timestamp=datetime.utcnow())
        embed.set_author(name=f"💬 {display}")
        try:
            await self._user.send(embed=embed)
        except discord.Forbidden:
            return await interaction.response.send_message("❌ Cannot DM that user.", ephemeral=True)

        echo = discord.Embed(description=content, color=discord.Color.blurple(), timestamp=datetime.utcnow())
        echo.set_author(name=f"📤 Sent by {display}")
        if anon:
            echo.set_footer(text="Sent anonymously")
        await interaction.channel.send(embed=echo)

        db.log_message(self.ticket["id"], interaction.user.id, interaction.user.display_name,
                       content, "to_user", anonymous=anon)
        await interaction.response.send_message("✅ Reply sent.", ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Panel Views
# ══════════════════════════════════════════════════════════════════════════════

class GeneralPanelView(discord.ui.View):
    """General context -- full mod toolkit."""

    def __init__(self, bot, persistent: bool = False):
        super().__init__(timeout=None if persistent else 300)
        self.bot = bot

    async def _check_staff(self, interaction: discord.Interaction) -> bool:
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="⚠️ Warn", style=discord.ButtonStyle.secondary, row=0, custom_id="panel_warn")
    async def btn_warn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(WarnModal(self.bot, interaction.guild))

    @discord.ui.button(label="🔇 Mute", style=discord.ButtonStyle.secondary, row=0, custom_id="panel_mute")
    async def btn_mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(MuteModal(self.bot, interaction.guild))

    @discord.ui.button(label="👢 Kick", style=discord.ButtonStyle.danger, row=0, custom_id="panel_kick")
    async def btn_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(KickModal(self.bot, interaction.guild))

    @discord.ui.button(label="🔨 Ban", style=discord.ButtonStyle.danger, row=0, custom_id="panel_ban")
    async def btn_ban(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(BanModal(self.bot, interaction.guild))

    @discord.ui.button(label="🔒 Jail", style=discord.ButtonStyle.danger, row=1, custom_id="panel_jail")
    async def btn_jail(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(JailModal(self.bot, interaction.guild))

    @discord.ui.button(label="⏳ TempBan", style=discord.ButtonStyle.danger, row=1, custom_id="panel_tempban")
    async def btn_tempban(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(TempBanModal(self.bot, interaction.guild))

    @discord.ui.button(label="📋 History", style=discord.ButtonStyle.secondary, row=2, custom_id="panel_history")
    async def btn_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_message(
            "Use `/history @user` to view their moderation history.", ephemeral=True
        )

    @discord.ui.button(label="🗑️ Purge", style=discord.ButtonStyle.secondary, row=2, custom_id="panel_purge")
    async def btn_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(PurgeModal(interaction.channel))

    @discord.ui.button(label="🚨 Lockdown", style=discord.ButtonStyle.danger, row=3, custom_id="panel_lockdown")
    async def btn_lockdown(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        raid_cog = interaction.client.cogs.get("Raid")
        if raid_cog:
            cfg = db.get_config(interaction.guild_id)
            await raid_cog._lockdown(interaction.guild, cfg, auto=False)
        await interaction.response.send_message("🔒 Server locked down.", ephemeral=True)

    @discord.ui.button(label="✅ Unlock", style=discord.ButtonStyle.success, row=3, custom_id="panel_unlock")
    async def btn_unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        raid_cog = interaction.client.cogs.get("Raid")
        if raid_cog:
            cfg = db.get_config(interaction.guild_id)
            await raid_cog._unlock(interaction.guild, cfg)
        await interaction.response.send_message("✅ Lockdown lifted.", ephemeral=True)


class ModMailPanelView(discord.ui.View):
    """ModMail ticket context -- reply, close."""

    def __init__(self, bot, ticket, user):
        super().__init__(timeout=300)
        self.bot    = bot
        self.ticket = ticket
        self._user  = user

    async def _check_staff(self, interaction: discord.Interaction) -> bool:
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="💬 Reply", style=discord.ButtonStyle.primary, row=0)
    async def btn_reply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(ModMailReplyModal(self.bot, self.ticket, self._user))

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, row=0)
    async def btn_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.defer(ephemeral=True)
        await _close_ticket(self.bot, interaction.guild, self.ticket, interaction.channel, interaction.user)

    @discord.ui.button(label="🗑️ Purge", style=discord.ButtonStyle.secondary, row=0)
    async def btn_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(PurgeModal(interaction.channel))


class JailPanelView(discord.ui.View):
    """Jail channel context -- unjail, message controls."""

    def __init__(self, bot, jail_record, member):
        super().__init__(timeout=300)
        self.bot         = bot
        self.jail_record = jail_record
        self.member      = member

    async def _check_staff(self, interaction: discord.Interaction) -> bool:
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message("❌ Staff only.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔓 Unjail", style=discord.ButtonStyle.success, row=0)
    async def btn_unjail(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        cfg = db.get_config(interaction.guild_id)
        if self.member and not can_moderate(interaction.user, self.member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        ok, msg = await do_unjail(interaction.guild, self.member, interaction.user, self.bot)
        if ok:
            await interaction.edit_original_response(content=f"✅ {self.member.mention} released.")
        else:
            await interaction.edit_original_response(content=f"❌ {msg}")

    @discord.ui.button(label="⚠️ Warn", style=discord.ButtonStyle.secondary, row=0)
    async def btn_warn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(WarnModal(self.bot, interaction.guild))

    @discord.ui.button(label="🗑️ Purge", style=discord.ButtonStyle.secondary, row=0)
    async def btn_purge(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        await interaction.response.send_modal(PurgeModal(interaction.channel))

    @discord.ui.button(label="📋 User Info", style=discord.ButtonStyle.secondary, row=1)
    async def btn_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_staff(interaction): return
        member = self.member
        cfg    = db.get_config(interaction.guild_id)
        warns  = db.get_active_warn_count(interaction.guild_id, member.id)
        embed  = discord.Embed(title=f"👤 {member.display_name}", color=discord.Color.blurple())
        embed.add_field(name="ID",           value=str(member.id),                                 inline=True)
        embed.add_field(name="Active Warns", value=str(warns),                                     inline=True)
        embed.add_field(name="Joined",       value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "?", inline=True)
        embed.add_field(name="Jail Reason",  value=self.jail_record.get("reason", "?"),            inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ══════════════════════════════════════════════════════════════════════════════
# Cog
# ══════════════════════════════════════════════════════════════════════════════

class Panel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="panel", description="Post the persistent Mod Panel in this channel.")
    async def panel(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        embed = discord.Embed(
            title="🛡️ CommunityBot Mod Panel",
            description=(
                "Use the buttons below to take moderation actions.\n"
                "All actions are logged to **#mod-log**.\n\n"
                "You can also use slash commands -- type `/` to see the full list."
            ),
            color=discord.Color.dark_blue(),
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text="Panel last updated")

        view = GeneralPanelView(self.bot, persistent=True)
        await interaction.response.send_message(embed=embed, view=view)

        msg = await interaction.original_response()
        db.upsert_config(interaction.guild_id, panel_msg_id=msg.id, panel_ch_id=interaction.channel_id)

    @app_commands.command(name="mod", description="Open the ephemeral Mod Panel here.")
    async def mod(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        context = _detect_context(interaction.channel_id)

        if context == "modmail":
            ticket = db.get_open_ticket_by_channel(interaction.channel_id)
            try:
                user = await self.bot.fetch_user(ticket["user_id"])
            except Exception:
                user = None
            view  = ModMailPanelView(self.bot, ticket, user)
            embed = discord.Embed(
                title="📬 ModMail Panel",
                description=f"Ticket #{ticket['id']} -- <@{ticket['user_id']}>",
                color=discord.Color.gold(),
            )
            embed.add_field(name="Opened", value=ticket["opened_at"][:19], inline=True)

        elif context == "jail":
            jail_record = db.get_jail_by_channel(interaction.channel_id)
            member      = interaction.guild.get_member(jail_record["user_id"])
            view  = JailPanelView(self.bot, jail_record, member)
            embed = discord.Embed(
                title="🔒 Jail Panel",
                description=f"<@{jail_record['user_id']}> • Jailed by {jail_record['jailed_by_name']}",
                color=discord.Color.dark_red(),
            )
            embed.add_field(name="Reason", value=jail_record.get("reason", "?"), inline=False)
            embed.add_field(name="Since",  value=jail_record["jailed_at"][:19],  inline=True)
            active_warns = db.get_active_warn_count(interaction.guild_id, jail_record["user_id"])
            embed.add_field(name="Active Warns", value=str(active_warns), inline=True)

        else:
            view  = GeneralPanelView(self.bot, persistent=False)
            embed = discord.Embed(
                title="🛡️ Mod Panel",
                description="Choose an action below.",
                color=discord.Color.dark_blue(),
            )

        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Panel(bot))
