import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import zipfile, io
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


async def do_jail(guild: discord.Guild, member: discord.Member, mod: discord.Member,
                  reason: str, notify: bool, bot: commands.Bot) -> discord.TextChannel:
    cfg = db.get_config(guild.id)

    # Save and strip all assignable roles
    saved_role_ids = [r.id for r in member.roles if r != guild.default_role and r.is_assignable()]
    roles_to_remove = [r for r in member.roles if r != guild.default_role and r.is_assignable()]
    if roles_to_remove:
        await member.remove_roles(*roles_to_remove, reason=f"Jailed by {mod}")

    # Get jail category
    jail_cat_id = cfg.get("jail_cat_id") if cfg else None
    jail_cat    = guild.get_channel(jail_cat_id) if jail_cat_id else None

    owner_role = guild.get_role(cfg["owner_role_id"]) if cfg else None
    mod_role   = guild.get_role(cfg["mod_role_id"])   if cfg else None
    everyone   = guild.default_role

    overwrites = {
        everyone:     discord.PermissionOverwrite(read_messages=False),
        member:       discord.PermissionOverwrite(read_messages=True, send_messages=True),
        guild.me:     discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
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
        reason=f"Jail: {member} by {mod}",
    )

    db.add_jail(guild.id, member.id, jail_ch.id, saved_role_ids, reason, mod.id, mod.display_name)

    # Header embed in jail channel
    embed = discord.Embed(
        title=f"🔒 {member.display_name} has been jailed",
        color=discord.Color.dark_red(),
        timestamp=datetime.utcnow(),
    )
    embed.add_field(name="User",      value=f"{member.mention} (`{member.id}`)", inline=True)
    embed.add_field(name="Jailed by", value=mod.mention,                         inline=True)
    embed.add_field(name="Reason",    value=reason,                              inline=False)
    embed.set_footer(text="Use /unjail @user to release them and restore their roles.")
    await jail_ch.send(embed=embed)

    # Message to the user in the jail channel
    user_embed = discord.Embed(description=config.DEFAULT_JAIL_MSG, color=discord.Color.dark_red())
    await jail_ch.send(member.mention, embed=user_embed)

    # Optional DM
    if notify:
        try:
            dm_embed = discord.Embed(
                description=f"You have been pulled into a private channel in **{guild.name}**.\n**Reason:** {reason}\nPlease check the server.",
                color=discord.Color.dark_red(),
            )
            await member.send(embed=dm_embed)
        except discord.Forbidden:
            pass

    return jail_ch


async def do_unjail(guild: discord.Guild, member: discord.Member, mod: discord.Member, bot: commands.Bot):
    cfg  = db.get_config(guild.id)
    jail = db.get_jail(guild.id, member.id)
    if jail is None:
        return False, "That user is not currently jailed."

    # Restore roles
    roles_to_restore = []
    for rid in jail["saved_roles"]:
        role = guild.get_role(rid)
        if role and role.is_assignable():
            roles_to_restore.append(role)
    if roles_to_restore:
        await member.add_roles(*roles_to_restore, reason=f"Unjailed by {mod}")

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
            arch_embed.add_field(name="Released by", value=mod.mention,               inline=True)
            await closed_ch.send(embed=arch_embed, file=discord.File(zip_buf, filename=zip_name))

        await jail_ch.delete(reason=f"Unjailed by {mod}")

    db.remove_jail(guild.id, member.id)

    # Notify user
    try:
        dm_embed = discord.Embed(
            description=f"You have been released from jail in **{guild.name}**. Your roles have been restored.",
            color=discord.Color.green(),
        )
        await member.send(embed=dm_embed)
    except discord.Forbidden:
        pass

    # Log
    log_embed = discord.Embed(title="🔓 Member Unjailed", color=discord.Color.green(), timestamp=datetime.utcnow())
    log_embed.add_field(name="User",        value=f"{member} (`{member.id}`)", inline=True)
    log_embed.add_field(name="Released by", value=mod.mention,                inline=True)
    await _post_modlog(guild, cfg, log_embed)

    return True, "ok"


class Jail(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="jail", description="Jail a member — strips roles and creates a private channel.")
    @app_commands.describe(member="Member to jail", reason="Reason", notify="DM the user that they've been jailed?")
    async def jail(self, interaction: discord.Interaction, member: discord.Member,
                   reason: str = "No reason provided.", notify: bool = True):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
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

        # Respond first — the channel gets deleted during unjail which breaks edit_original_response
        ok_check = db.get_jail(interaction.guild_id, member.id)
        if not ok_check:
            return await interaction.response.send_message("❌ That user is not currently jailed.", ephemeral=True)

        await interaction.response.send_message(f"🔓 Releasing {member.mention}...", ephemeral=True)
        ok, msg = await do_unjail(interaction.guild, member, interaction.user, self.bot)


async def setup(bot: commands.Bot):
    await bot.add_cog(Jail(bot))
