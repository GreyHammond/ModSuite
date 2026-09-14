"""
Mute role and public moderation log.

Two problems this solves.

**Permanent mute.** Discord's native timeout is capped at 28 days. `/mute` was
clamping every duration with `min(td, timedelta(days=28))`, so a mute recorded
in the database as permanent silently expired at day 28 and the member started
talking again with nobody notified. A mute role has no such cap, so the role is
now the authority and the timeout is a supplement.

**Public log.** ModSuite writes to a private mod-log. For a public forum run
by a journalist, the accusation "he silences critics" is answered by a public
record, not a private one. Every mute, pull, and removal posts to a channel
residents can read.
"""
import logging
from datetime import datetime, timezone

import discord

import database as db
from config import FOOTER_BRAND, BRAND_COLOR

log = logging.getLogger("ModSuite.mute")

MUTED_ROLE_NAME = "Muted"

# Denied everywhere the role is applied. Voice permissions included, or a muted
# member simply moves to voice chat and keeps going.
MUTE_DENIALS = {
    "send_messages": False,
    "send_messages_in_threads": False,
    "create_public_threads": False,
    "create_private_threads": False,
    "add_reactions": False,
    "speak": False,
    "send_voice_messages": False,
    "send_tts_messages": False,
    "attach_files": False,
    "embed_links": False,
}


async def get_or_create_muted_role(guild: discord.Guild,
                                   cfg: dict | None = None) -> discord.Role | None:
    """Find the configured mute role, falling back to name, creating if absent."""
    cfg = cfg or db.get_config(guild.id) or {}

    role_id = cfg.get("muted_role")
    if role_id:
        role = guild.get_role(int(role_id))
        if role:
            return role

    role = discord.utils.get(guild.roles, name=MUTED_ROLE_NAME)
    if role is None:
        try:
            role = await guild.create_role(
                name=MUTED_ROLE_NAME,
                colour=discord.Colour(0x4A4A55),
                reason="ModSuite: mute role",
            )
        except discord.Forbidden:
            log.warning(f"[{guild.name}] Cannot create the Muted role.")
            return None

    db.upsert_config(guild.id, muted_role=role.id)
    return role


async def sync_mute_overwrites(guild: discord.Guild,
                               role: discord.Role) -> tuple[int, int]:
    """
    Apply the mute denials to every category and to any channel not synced to
    one. Returns (updated, failed).

    Pull Room channels are skipped deliberately: a muted member has to be able
    to answer you in the room where you talk it through.
    """
    updated = failed = 0
    overwrite = discord.PermissionOverwrite(**MUTE_DENIALS)

    targets = list(guild.categories)
    targets += [c for c in guild.channels
                if not isinstance(c, discord.CategoryChannel)
                and (c.category is None or not c.permissions_synced)]

    # Dedupe by id. guild.channels includes categories, and a channel could in
    # principle be reached twice; writing the same overwrite twice just burns
    # rate limit.
    seen: set = set()
    unique = []
    for t in targets:
        tid = getattr(t, "id", None)
        if tid in seen:
            continue
        seen.add(tid)
        unique.append(t)
    targets = unique

    for target in targets:
        name = getattr(target, "name", "").lower()
        category_name = getattr(getattr(target, "category", None), "name", "").lower()
        if "pull room" in (name, category_name) or name.startswith("pull-"):
            continue
        try:
            await target.set_permissions(role, overwrite=overwrite,
                                         reason="ModSuite: mute role sync")
            updated += 1
        except (discord.Forbidden, discord.HTTPException) as e:
            failed += 1
            log.warning(f"Mute overwrite failed on {target}: {e}")
    return updated, failed


async def apply_mute(member: discord.Member, reason: str = "") -> bool:
    """Add the mute role. True if the role was applied."""
    role = await get_or_create_muted_role(member.guild)
    if role is None:
        return False
    if role in member.roles:
        return True
    try:
        await member.add_roles(role, reason=f"ModSuite mute: {reason}"[:500])
        return True
    except (discord.Forbidden, discord.HTTPException) as e:
        log.warning(f"Could not apply mute role to {member}: {e}")
        return False


async def clear_mute(member: discord.Member, reason: str = "") -> bool:
    role = await get_or_create_muted_role(member.guild)
    if role is None or role not in member.roles:
        return False
    try:
        await member.remove_roles(role, reason=f"ModSuite unmute: {reason}"[:500])
        return True
    except (discord.Forbidden, discord.HTTPException) as e:
        log.warning(f"Could not remove mute role from {member}: {e}")
        return False


# ── Public moderation log ────────────────────────────────────────────────────

# Actions residents see. Warns stay private, since a public warning is a
# punishment in itself and the point is transparency about silencing, not
# pillorying people for a first misstep.
PUBLIC_ACTIONS = {
    "MUTE":     ("Muted", 0xD96C2C),
    "UNMUTE":   ("Unmuted", 0x2ECC71),
    "JAIL":     ("Pulled aside", 0xC58A3A),
    "UNJAIL":   ("Released", 0x2ECC71),
    "KICK":     ("Removed", 0xE67E22),
    "BAN":      ("Banned", 0xC0392B),
    "UNBAN":    ("Ban lifted", 0x2ECC71),
}


async def post_public_modlog(bot, guild_id: int, action: str, target_name: str,
                             actor_name: str, reason: str = "",
                             duration: str = "") -> bool:
    """
    Post a moderation action to the public log. Never raises; a failure here
    must not roll back the moderation action itself.
    """
    try:
        cfg = db.get_config(guild_id) or {}
        if not cfg.get("public_modlog_enabled"):
            return False
        channel_id = cfg.get("public_modlog_channel")
        if not channel_id:
            return False
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            return False

        label, colour = PUBLIC_ACTIONS.get(action.upper(), (action.title(), BRAND_COLOR))

        embed = discord.Embed(
            title=label,
            colour=colour,
            timestamp=datetime.now(timezone.utc),
        )
        # Display name only. The public log exists to show that moderation
        # happened and why, not to publish user IDs for anyone to harvest.
        embed.add_field(name="Member", value=target_name, inline=True)
        embed.add_field(name="By", value=actor_name, inline=True)
        if duration:
            embed.add_field(name="Duration", value=duration, inline=True)
        embed.add_field(name="Reason",
                        value=(reason or "No reason given.")[:1000], inline=False)
        embed.set_footer(text=FOOTER_BRAND)

        await channel.send(embed=embed)
        return True
    except Exception as e:
        log.warning(f"Public modlog post failed: {e}")
        return False
