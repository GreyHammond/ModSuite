import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import database as db
import config
from utils import can_moderate, hierarchy_refusal_embed, get_bot_message, _fmt


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


async def do_warn(
    guild: discord.Guild,
    user: discord.Member,
    mod: "discord.Member | None",
    reason: str,
    bot: commands.Bot,
) -> tuple[int, int, str]:
    """
    Add a warn and handle auto-escalation.
    Returns (warn_id, total_active_warns, escalation_action).
    escalation_action is one of: '', 'jailed', 'banned'.
    mod=None means automated action.
    """
    cfg = db.get_config(guild.id)
    mod_id   = mod.id           if mod else bot.user.id
    mod_name = mod.display_name if mod else "ModSuite (Auto)"

    warn_id = db.add_warn(guild.id, user.id, mod_id, mod_name, reason)
    total   = db.get_active_warn_count(guild.id, user.id)
    action  = ""

    # Log the warn itself to mod_logs
    db.add_mod_log(
        guild_id=str(guild.id),
        action="WARN",
        target_id=str(user.id),
        target_username=str(user),
        actor_id=str(mod_id),
        actor_username=mod_name,
        reason=reason,
    )

    mute_at = cfg.get("warn_mute_threshold", config.DEFAULT_WARN_MUTE_AT) if cfg else config.DEFAULT_WARN_MUTE_AT
    ban_at  = cfg.get("warn_ban_threshold",  config.DEFAULT_WARN_BAN_AT)  if cfg else config.DEFAULT_WARN_BAN_AT

    if total >= ban_at:
        try:
            await user.ban(reason=f"Auto-ban: reached {total} warnings")
            action = "banned"
            db.add_mod_log(
                guild_id=str(guild.id),
                action="BAN",
                target_id=str(user.id),
                target_username=str(user),
                actor_id=str(bot.user.id),
                actor_username="ModSuite (auto)",
                reason=f"Auto-ban: reached {total} warnings",
            )
        except discord.Forbidden:
            pass
    elif total >= mute_at:
        # Replace auto-mute with auto-tempjail
        if not db.get_jail(guild.id, user.id):
            try:
                from .jail import do_jail
                from .moderation import parse_duration
                raw_duration = (cfg.get("auto_jail_duration") if cfg else None) or "1d"
                td = parse_duration(raw_duration) or __import__("datetime").timedelta(days=1)
                jail_end_time = datetime.utcnow() + td
                await do_jail(
                    guild, user, None,
                    f"Auto-jailed: warn threshold reached (warn #{warn_id})",
                    True, bot,
                    jail_end_time=jail_end_time,
                )
                action = "jailed"
            except Exception:
                pass

    return warn_id, total, action


class Warns(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="warn", description="Warn a member.")
    @app_commands.describe(member="Member mention or user ID", reason="Reason for the warning")
    async def warn(self, interaction: discord.Interaction, member: str, reason: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        from utils import resolve_user
        try:
            user, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        if user.bot:
            return await interaction.response.send_message("❌ Cannot warn a bot.", ephemeral=True)

        if is_member:
            if not can_moderate(interaction.user, user, cfg or {}):
                return await interaction.response.send_message(embed=hierarchy_refusal_embed(), ephemeral=True)

        await interaction.response.defer()

        if is_member:
            warn_id, total, escalation = await do_warn(interaction.guild, user, interaction.user, reason, self.bot)
        else:
            # User not in server -- just record the warn, no escalation
            mod_id = interaction.user.id
            mod_name = interaction.user.display_name
            warn_id = db.add_warn(interaction.guild_id, user.id, mod_id, mod_name, reason)
            total = db.get_active_warn_count(interaction.guild_id, user.id)
            escalation = ""

        embed = discord.Embed(title="⚠️ Member Warned", color=discord.Color.yellow(), timestamp=datetime.utcnow())
        name_display = f"{user} (`{user.id}`)"
        if not is_member:
            name_display += " *(not in server)*"
        embed.add_field(name="User",          value=name_display,             inline=True)
        embed.add_field(name="Warned by",     value=interaction.user.mention, inline=True)
        embed.add_field(name="Reason",        value=reason,                   inline=False)
        embed.add_field(name="Total Warnings",value=str(total),               inline=True)
        if escalation:
            embed.add_field(name="Auto Action", value=f"🤖 User was **{escalation}** automatically", inline=False)
        embed.set_footer(text=f"Warn ID: {warn_id}")

        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="WARN",
            target_id=str(user.id),
            target_username=str(user),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=f"{reason}" + (f" (auto: {escalation})" if escalation else ""),
        )
        await _post_modlog(interaction.guild, cfg, embed)
        await interaction.followup.send(embed=embed)

        if is_member:
            try:
                text = _fmt(
                    get_bot_message(db, str(interaction.guild_id), "warn_dm"),
                    user=user.mention, reason=reason,
                )
                dm_embed = discord.Embed(description=text, color=discord.Color.yellow())
                await user.send(embed=dm_embed)
            except discord.Forbidden:
                pass

    @app_commands.command(name="unwarn", description="Remove a specific warning by ID.")
    @app_commands.describe(warn_id="The warning ID to remove (shown in /history)")
    async def unwarn(self, interaction: discord.Interaction, warn_id: int):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        # Fetch the warn first so we can log the target user in mod_logs
        target_user_id = ""
        with db.get_conn() as conn:
            row = conn.execute("SELECT user_id FROM warns WHERE id = ?", (warn_id,)).fetchone()
            if row:
                target_user_id = str(row["user_id"])

        removed = db.remove_warn(warn_id)
        if removed:
            db.add_mod_log(
                guild_id=str(interaction.guild_id),
                action="UNWARN",
                target_id=target_user_id,
                target_username="",
                actor_id=str(interaction.user.id),
                actor_username=interaction.user.display_name,
                reason=f"Removed warn #{warn_id}",
            )
            await interaction.response.send_message(f"✅ Warning `#{warn_id}` removed.", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ Warning `#{warn_id}` not found or already removed.", ephemeral=True)

    @app_commands.command(name="history", description="View moderation history for a user.")
    @app_commands.describe(member="Member mention or user ID")
    async def history(self, interaction: discord.Interaction, member: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        from utils import resolve_user
        try:
            user, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        warns = db.get_warns(interaction.guild_id, user.id, active_only=False)
        notes = db.get_notes(str(interaction.guild_id), str(user.id), active_only=True)

        # Pull all mod_logs entries for this user (kicks, bans, mutes, etc.)
        # Filter client-side because get_mod_logs doesn't take a target filter.
        with db.get_conn() as conn:
            log_rows = conn.execute(
                """SELECT * FROM mod_logs
                   WHERE guild_id = ? AND target_id = ?
                   ORDER BY id DESC
                   LIMIT 25""",
                (str(interaction.guild_id), str(user.id)),
            ).fetchall()
        mod_log_entries = [dict(r) for r in log_rows]

        name_display = user.display_name if is_member else str(user)
        embed = discord.Embed(
            title=f"📋 Moderation History -- {name_display}",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if is_member:
            embed.set_thumbnail(url=user.display_avatar.url)
        if not is_member:
            embed.description = f"*User is not in the server* (`{user.id}`)\n"

        # ── Warnings section ───────────────────────────────────────────────────
        if not warns:
            embed.description = "No warnings on record."
        else:
            active   = [w for w in warns if w["active"]]
            inactive = [w for w in warns if not w["active"]]
            embed.add_field(name="Active Warnings",  value=str(len(active)),   inline=True)
            embed.add_field(name="Removed Warnings", value=str(len(inactive)), inline=True)
            embed.add_field(name="\u200b",           value="\u200b",           inline=True)

            for w in warns[-10:]:  # show last 10
                status = "✅" if w["active"] else "~~removed~~"
                embed.add_field(
                    name=f"#{w['id']} {status}",
                    value=f"**By:** {w['mod_name']}\n**Reason:** {w['reason']}\n**Date:** {w['timestamp'][:10]}",
                    inline=True,
                )

        # ── Kicks / Bans / Mutes / etc. from mod_logs ─────────────────────────
        # Warns are already displayed above; skip them here to avoid duplication.
        NON_WARN_ACTIONS = {"KICK", "BAN", "UNBAN", "MUTE", "UNMUTE", "JAIL",
                            "UNJAIL", "TEMPJAIL", "SOFTBAN", "UNWARN",
                            "TEMPBAN", "VIOLATION", "VIOLATIONS_CLEARED",
                            "PROFILE_SWITCH", "NAME_FILTER", "VERIFIED_GATE"}
        enforcement = [l for l in mod_log_entries if (l.get("action") or "").upper() in NON_WARN_ACTIONS]
        if enforcement:
            action_icons = {
                "KICK": "👢", "BAN": "🔨", "UNBAN": "✅",
                "MUTE": "🔇", "UNMUTE": "🔊",
                "JAIL": "🔒", "UNJAIL": "🔓", "TEMPJAIL": "⏱",
                "SOFTBAN": "🧼", "UNWARN": "↩",
                "TEMPBAN": "⏳", "VIOLATION": "🔶", "VIOLATIONS_CLEARED": "🧹",
                "PROFILE_SWITCH": "🎚️",
                "NAME_FILTER": "🚫", "VERIFIED_GATE": "🚪",
            }
            embed.add_field(name="\u200b", value=f"⚖️ **Enforcement History ({len(enforcement)} entries)**", inline=False)
            for l in enforcement[:10]:  # show last 10
                act = (l.get("action") or "").upper()
                icon = action_icons.get(act, "•")
                date_str = (l.get("timestamp") or "")[:10]
                by = l.get("actor_username") or "?"
                reason = l.get("reason") or "--"
                embed.add_field(
                    name=f"{icon} {act} #{l.get('id')} · {date_str}",
                    value=f"**By:** {by}\n**Reason:** {reason}",
                    inline=True,
                )

        # ── Notes section (staff-only; never shown in /userinfo) ──────────────
        if notes:
            embed.add_field(name="\u200b", value=f"📝 **Staff Notes ({len(notes)} active)**", inline=False)
            for n in notes:
                date_str = n["created_at"][:10]
                embed.add_field(
                    name=f"Note #{n['note_id']} | {date_str} | by <@{n['author_id']}>",
                    value=n["content"],
                    inline=False,
                )

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Warns(bot))
