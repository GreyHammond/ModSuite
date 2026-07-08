import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone
import zipfile, io
import database as db
import config
from utils import can_moderate, hierarchy_refusal_embed, get_bot_message, _fmt
from .moderation import parse_duration, _fmt_td


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


def _build_jail_transcript(jail: dict, messages: list) -> str:
    lines = [
        "Jail Transcript",
        f"User ID  : {jail['user_id']}",
        f"Jailed by: {jail['jailed_by_name']}",
        f"Reason   : {jail['reason']}",
        f"Opened   : {jail['jailed_at']}",
        "=" * 60, "",
    ]
    for msg in messages:
        lines.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {msg.author.display_name}: {msg.content}")
    return "\n".join(lines)


def _build_warning_history_embed(
    guild: discord.Guild,
    member: discord.Member,
    reason: str,
    mod: "discord.Member | None",
    jail_end_time: "datetime | None",
) -> discord.Embed:
    """Build the Warning History embed posted to #mod-log on every jail action."""
    active_warns = db.get_warns(guild.id, member.id, active_only=True)
    all_warns    = db.get_warns(guild.id, member.id, active_only=False)

    if jail_end_time:
        # Build a human-readable duration from the stored end time
        now = datetime.utcnow()
        delta = jail_end_time - now
        jail_type = f"Temp Jail ({_fmt_td(delta)})" if delta.total_seconds() > 0 else "Temp Jail (expired)"
    else:
        jail_type = "Permanent Jail"

    if mod is None:
        jailed_by_str = "ModSuite (Auto)"
    else:
        jailed_by_str = mod.mention

    embed = discord.Embed(
        title=f"📋 Jail — Warning History: {member.display_name}",
        color=0xE67E22,
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="Jail Type",    value=jail_type,       inline=True)
    embed.add_field(name="Reason",       value=reason,          inline=True)
    embed.add_field(name="Jailed by",    value=jailed_by_str,   inline=True)
    embed.add_field(name="Active Warns", value=str(len(active_warns)) if active_warns else "No prior warnings on record", inline=True)
    embed.add_field(name="Total Warns",  value=str(len(all_warns)),  inline=True)

    for w in active_warns:
        date_str = w["timestamp"][:10]
        embed.add_field(
            name=f"Warn #{w['id']}",
            value=f"{w['reason']} — issued by {w['mod_name']} on {date_str}",
            inline=False,
        )

    embed.set_footer(text="Review full history with /history @user")
    return embed


async def do_jail(
    guild: discord.Guild,
    member: discord.Member,
    mod: "discord.Member | None",
    reason: str,
    notify: bool,
    bot: commands.Bot,
    jail_end_time: "datetime | None" = None,
) -> discord.TextChannel:
    cfg = db.get_config(guild.id)

    # Derive display strings for mod (supports None = automated action)
    mod_display = str(mod) if mod else "ModSuite (Auto)"
    mod_id      = mod.id   if mod else bot.user.id
    mod_name    = mod.display_name if mod else "ModSuite (Auto)"

    # Save and strip all assignable roles
    saved_role_ids = [r.id for r in member.roles if r != guild.default_role and r.is_assignable()]
    roles_to_remove = [r for r in member.roles if r != guild.default_role and r.is_assignable()]
    if roles_to_remove:
        await member.remove_roles(*roles_to_remove, reason=f"Jailed by {mod_display}")

    # Get jail category
    jail_cat_id = cfg.get("jail_cat_id") if cfg else None
    jail_cat    = guild.get_channel(jail_cat_id) if jail_cat_id else None

    owner_role = guild.get_role(cfg["owner_role_id"]) if cfg and cfg.get("owner_role_id") else None
    mod_role   = guild.get_role(cfg["mod_role_id"])   if cfg and cfg.get("mod_role_id")   else None
    everyone   = guild.default_role

    overwrites = {
        everyone:  discord.PermissionOverwrite(read_messages=False),
        member:    discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me:  discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
    }
    if owner_role:
        overwrites[owner_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    if mod_role:
        overwrites[mod_role]   = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    safe_name = "".join(c for c in member.name if c.isalnum() or c in "-_").lower() or "user"
    jail_ch   = await guild.create_text_channel(
        f"jail-{safe_name}",
        category=jail_cat,
        overwrites=overwrites,
        reason=f"Jail: {member} by {mod_display}",
    )

    db.add_jail(guild.id, member.id, jail_ch.id, saved_role_ids, reason,
                mod_id, mod_name, jail_end_time=jail_end_time)

    # Persist to mod_logs so this appears on the user's record and in the dashboard
    db.add_mod_log(
        guild_id=str(guild.id),
        action="TEMPJAIL" if jail_end_time else "JAIL",
        target_id=str(member.id),
        target_username=str(member),
        actor_id=str(mod_id),
        actor_username=mod_name,
        reason=reason,
    )

    # Header embed in jail channel
    header_embed = discord.Embed(
        title=f"🔒 {member.display_name} has been jailed",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow(),
    )
    header_embed.add_field(name="User",      value=f"{member.mention} (`{member.id}`)", inline=True)
    header_embed.add_field(name="Jailed by", value=mod_display,                         inline=True)
    header_embed.add_field(name="Reason",    value=reason,                              inline=False)
    if jail_end_time:
        header_embed.add_field(name="Duration", value=_fmt_td(jail_end_time - datetime.utcnow()), inline=True)
        header_embed.add_field(name="Expires",  value=f"<t:{int(jail_end_time.replace(tzinfo=timezone.utc).timestamp())}:F>", inline=True)
    header_embed.set_footer(text="Use /unjail @user to release them and restore their roles.")
    await jail_ch.send(embed=header_embed)

    # Message to the user in the jail channel
    user_embed = discord.Embed(description=config.DEFAULT_JAIL_MSG, color=discord.Color.dark_red())
    await jail_ch.send(member.mention, embed=user_embed)

    # Optional DM
    if notify:
        try:
            duration_str = _fmt_td(jail_end_time - datetime.utcnow()) if jail_end_time else ""
            text = _fmt(
                get_bot_message(db, str(guild.id), "jail_dm"),
                user=member.mention, reason=reason, duration=duration_str,
            )
            dm_embed = discord.Embed(description=text, color=discord.Color.dark_red())
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    # Warning History embed to mod-log
    history_embed = _build_warning_history_embed(guild, member, reason, mod, jail_end_time)
    await _post_modlog(guild, cfg, history_embed)

    return jail_ch


async def do_unjail(
    guild: discord.Guild,
    member: discord.Member,
    mod: "discord.Member | None",
    bot: commands.Bot,
) -> tuple[bool, str]:
    cfg  = db.get_config(guild.id)
    jail = db.get_jail(guild.id, member.id)
    if jail is None:
        return False, "That user is not currently jailed."

    mod_display = mod.mention if mod else "ModSuite (Temp Jail Expired)"
    mod_str     = str(mod) if mod else "ModSuite (Auto)"

    # Restore roles
    roles_to_restore = []
    for rid in jail["saved_roles"]:
        role = guild.get_role(rid)
        if role and role.is_assignable():
            roles_to_restore.append(role)
    if roles_to_restore:
        await member.add_roles(*roles_to_restore, reason=f"Unjailed by {mod_str}")

    # Archive transcript
    jail_ch = guild.get_channel(jail["channel_id"])
    if jail_ch:
        messages = [m async for m in jail_ch.history(limit=500, oldest_first=True)]
        transcript = _build_jail_transcript(jail, messages)

        zip_buf  = io.BytesIO()
        stamp    = datetime.utcnow().strftime("%m%d%Y")
        zip_name = f"{stamp}-jail-{member.name}.zip"
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"{stamp}-jail-{member.name}.txt", transcript)
        zip_buf.seek(0)

        closed_ch_id = cfg.get("closed_ch_id") if cfg else None
        closed_ch    = guild.get_channel(closed_ch_id) if closed_ch_id else None
        if closed_ch:
            arch_embed = discord.Embed(
                title="🔓 Jail Closed",
                color=discord.Color.greyple(),
                timestamp=datetime.utcnow(),
            )
            arch_embed.add_field(name="User",       value=f"{member} (`{member.id}`)", inline=True)
            arch_embed.add_field(name="Released by", value=mod_display,               inline=True)
            await closed_ch.send(embed=arch_embed, file=discord.File(zip_buf, filename=zip_name))

        await jail_ch.delete(reason=f"Unjailed by {mod_str}")

    db.remove_jail(guild.id, member.id)

    # Persist to mod_logs so this appears on the user's record and in the dashboard
    db.add_mod_log(
        guild_id=str(guild.id),
        action="UNJAIL",
        target_id=str(member.id),
        target_username=str(member),
        actor_id=str(mod.id) if mod else str(bot.user.id),
        actor_username=str(mod) if mod else "ModSuite (auto)",
        reason="Jail duration expired" if mod is None else "Released by staff",
    )

    # Notify user
    try:
        text = _fmt(
            get_bot_message(db, str(guild.id), "unjail_dm"),
            user=member.mention,
        )
        dm_embed = discord.Embed(description=text, color=discord.Color.green())
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass

    # Log
    log_embed = discord.Embed(title="🔓 Member Unjailed", color=discord.Color.green(), timestamp=datetime.utcnow())
    log_embed.add_field(name="User",        value=f"{member} (`{member.id}`)", inline=True)
    log_embed.add_field(name="Released by", value=mod_display,                inline=True)
    await _post_modlog(guild, cfg, log_embed)

    return True, "ok"


class Jail(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_unjail_loop.start()

    def cog_unload(self):
        self.auto_unjail_loop.cancel()

    @app_commands.command(name="jail", description="Jail a member — strips roles and creates a private channel.")
    @app_commands.describe(member="Member to jail", reason="Reason", notify="DM the user that they've been jailed?")
    async def jail(self, interaction: discord.Interaction, member: discord.Member,
                   reason: str = "No reason provided.", notify: bool = True):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("❌ Cannot jail a bot.", ephemeral=True)
        if db.get_jail(interaction.guild_id, member.id):
            return await interaction.response.send_message("❌ That user is already jailed.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        jail_ch = await do_jail(interaction.guild, member, interaction.user, reason, notify, self.bot)

        log_embed = discord.Embed(title="🔒 Member Jailed", color=discord.Color.dark_red(), timestamp=datetime.utcnow())
        log_embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
        log_embed.add_field(name="Jailed by", value=interaction.user.mention,    inline=True)
        log_embed.add_field(name="Reason",    value=reason,                      inline=False)
        log_embed.add_field(name="Channel",   value=jail_ch.mention,             inline=True)
        await _post_modlog(interaction.guild, cfg, log_embed)

        await interaction.edit_original_response(
            content=f"✅ {member.mention} has been jailed in {jail_ch.mention}."
        )

    @app_commands.command(name="unjail", description="Release a jailed member and restore their roles.")
    @app_commands.describe(member="Member to unjail")
    async def unjail(self, interaction: discord.Interaction, member: discord.Member):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)

        ok_check = db.get_jail(interaction.guild_id, member.id)
        if not ok_check:
            return await interaction.response.send_message("❌ That user is not currently jailed.", ephemeral=True)

        # Respond first — the channel gets deleted during unjail which breaks edit_original_response
        await interaction.response.send_message(f"🔓 Releasing {member.mention}...", ephemeral=True)
        await do_unjail(interaction.guild, member, interaction.user, self.bot)

    @app_commands.command(name="tempjail", description="Temporarily jail a member for a fixed duration.")
    @app_commands.describe(
        member="Member to jail",
        duration="Duration: 10m, 2h, 1d, 2h30m",
        reason="Reason",
        notify="DM the user?",
    )
    async def tempjail(self, interaction: discord.Interaction, member: discord.Member,
                       duration: str, reason: str = "No reason provided.", notify: bool = True):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        if not can_moderate(interaction.user, member, cfg or {}):
            return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("❌ Cannot jail a bot.", ephemeral=True)
        if db.get_jail(interaction.guild_id, member.id):
            return await interaction.response.send_message("❌ That user is already jailed.", ephemeral=True)

        td = parse_duration(duration)
        if td is None:
            return await interaction.response.send_message(
                "❌ Invalid duration. Use formats like `10m`, `2h`, `1d`, `2h30m`.", ephemeral=True
            )

        jail_end_time = datetime.utcnow() + td

        await interaction.response.defer(ephemeral=True)
        jail_ch = await do_jail(
            interaction.guild, member, interaction.user, reason, notify, self.bot,
            jail_end_time=jail_end_time,
        )

        log_embed = discord.Embed(title="🔒 Member Temp-Jailed", color=discord.Color.dark_red(), timestamp=datetime.utcnow())
        log_embed.add_field(name="User",      value=f"{member} (`{member.id}`)", inline=True)
        log_embed.add_field(name="Jailed by", value=interaction.user.mention,    inline=True)
        log_embed.add_field(name="Duration",  value=_fmt_td(td),                 inline=True)
        log_embed.add_field(name="Reason",    value=reason,                      inline=False)
        log_embed.add_field(name="Channel",   value=jail_ch.mention,             inline=True)
        await _post_modlog(interaction.guild, cfg, log_embed)

        await interaction.edit_original_response(
            content=f"✅ {member.mention} has been temp-jailed for {_fmt_td(td)} in {jail_ch.mention}."
        )

    @tasks.loop(seconds=60)
    async def auto_unjail_loop(self):
        now     = datetime.utcnow()
        expired = db.get_expired_jails(now)
        for row in expired:
            guild = self.bot.get_guild(row["guild_id"])
            if guild is None:
                db.remove_jail(row["guild_id"], row["user_id"])
                continue
            member = guild.get_member(row["user_id"])
            if member is None:
                db.remove_jail(row["guild_id"], row["user_id"])
                continue
            try:
                # actor=None signals automated action — can_moderate allows everything except server owner
                await do_unjail(guild, member, None, self.bot)
            except Exception as e:
                import logging
                logging.getLogger("ModSuite.jail").warning(f"Auto-unjail failed for {row['user_id']}: {e}")
                db.remove_jail(row["guild_id"], row["user_id"])

    @auto_unjail_loop.before_loop
    async def before_auto_unjail_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Jail(bot))
