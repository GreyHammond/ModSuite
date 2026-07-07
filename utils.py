"""
utils.py — ModSuite shared helpers.

Permission hierarchy (highest → lowest):
  Server Owner  >  Administrator  >  Owner Role  >  Mod Role  >  Regular Member

Only bot-created role IDs and Discord-native owner/admin signals are checked.
All other custom roles are invisible to this logic.
"""
import discord


# ── Permission Helpers ────────────────────────────────────────────────────────

def is_protected(target: discord.Member, guild_config: dict) -> bool:
    """
    Returns True if target is a protected member who should not be moderated.
    Only checks bot-created role IDs and Discord-native owner/admin signals.
    All other roles are ignored entirely.
    """
    if target.id == target.guild.owner_id:
        return True
    if target.guild_permissions.administrator:
        return True
    owner_role_id = guild_config.get("owner_role_id")
    if owner_role_id and any(role.id == owner_role_id for role in target.roles):
        return True
    mod_role_id = guild_config.get("mod_role_id")
    if mod_role_id and any(role.id == mod_role_id for role in target.roles):
        return True
    return False


def can_moderate(actor: discord.Member | None, target: discord.Member, guild_config: dict) -> bool:
    """
    Returns True only if actor is permitted to take a moderation action on target.
    Pass actor=None for automated bot actions to bypass actor checks.
    The server owner can never be acted on under any circumstance.

    Behavioral contract:
      Actor               Regular  Mod Role  Admin  Server Owner
      Moderator           ✅       ❌        ❌     ❌
      Administrator       ✅       ✅        ❌     ❌
      Server Owner        ✅       ✅        ✅     ❌
      Bot (actor=None)    ✅       ✅        ✅     ❌
    """
    # Nobody — including the bot — acts on the server owner
    if target.id == target.guild.owner_id:
        return False

    # Automated bot action — allow everything except server owner (handled above)
    if actor is None:
        return True

    # Target is a protected member — apply role-level restrictions
    if is_protected(target, guild_config):
        mod_role_id = guild_config.get("mod_role_id")
        actor_is_only_mod = (
            mod_role_id is not None
            and any(role.id == mod_role_id for role in actor.roles)
            and not actor.guild_permissions.administrator
        )
        if actor_is_only_mod:
            # Pure moderators cannot act on any protected target
            return False
        # Admin-level actors cannot act on other admins (or owner, already handled)
        if target.guild_permissions.administrator:
            return False
        target_owner_role_id = guild_config.get("owner_role_id")
        if target_owner_role_id and any(role.id == target_owner_role_id for role in target.roles):
            return False

    return True


def hierarchy_refusal_embed() -> discord.Embed:
    embed = discord.Embed(
        title="⛔ Action Not Permitted",
        description="You cannot perform moderation actions on a member with equal or higher standing.",
        color=0xE74C3C,
    )
    embed.set_footer(text="ModSuite Permission Hierarchy")
    return embed


# ── Bot Message Templates ─────────────────────────────────────────────────────

import re as _re  # local import to keep the top of the file clean

DEFAULTS: dict[str, str] = {
    "warn_dm":        "Hey {user}, you've received a warning: {reason}. Please review the server rules.",
    "jail_dm":        "You have been jailed for: {reason}. Duration: {duration}. A moderator will be with you shortly.",
    "unjail_dm":      "You have been released from jail. Please review the server rules and conduct yourself accordingly.",
    "mute_dm":        "You have been muted for: {reason}. Duration: {duration}.",
    "ban_dm":         "You have been banned from the server for: {reason}.",
    "join_message":   "Welcome to the server, {user}! Please read the rules and grab your roles.",
    "welcome_message": "Welcome, {user}! We're glad to have you here.",
}


def get_bot_message(db, guild_id: str, slot: str) -> str:
    """
    Returns the configured message for a slot.
    Falls back to the hardcoded default if no custom value is set.
    """
    try:
        content = db.get_bot_message_content(guild_id, slot)
        if content is not None:
            return content
    except Exception:
        pass
    return DEFAULTS.get(slot, "")


def parse_relative_time(text: str) -> "timedelta | None":
    """
    Parse relative time strings like: 10m, 1h, 2h 30m, 1d, 1d 6h, 1w
    Used by both /move and /remindme.
    Returns a timedelta or None if unrecognised.
    """
    from datetime import timedelta
    import re
    pattern = re.compile(
        r"^\s*(?:(\d+)\s*w(?:eeks?)?)?\s*"
        r"(?:(\d+)\s*d(?:ays?)?)?\s*"
        r"(?:(\d+)\s*h(?:ours?|rs?)?)?\s*"
        r"(?:(\d+)\s*m(?:ins?|inutes?)?)?\s*$",
        re.IGNORECASE,
    )
    m = pattern.match(text.strip())
    if not m or not any(m.groups()):
        return None
    weeks   = int(m.group(1) or 0)
    days    = int(m.group(2) or 0)
    hours   = int(m.group(3) or 0)
    minutes = int(m.group(4) or 0)
    td = timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes)
    return td if td.total_seconds() > 0 else None


def _fmt(template: str, **kwargs) -> str:
    """
    Format a bot-message template, replacing any placeholder that has no
    supplied value with an empty string rather than leaving {placeholder}
    visible in the output.
    """
    class _SafeDict(dict):
        def __missing__(self, key: str) -> str:
            return ""

    return template.format_map(_SafeDict(**kwargs))


import re as _re

async def resolve_user(bot, guild, target: str):
    """
    Resolve a user from a mention, username, or raw user ID string.
    Returns (discord.Member or discord.User, is_member: bool).
    Raises ValueError if the user cannot be found.
    """
    # Strip mention syntax: <@123> or <@!123>
    mention_match = _re.match(r"<@!?(\d+)>", target.strip())
    if mention_match:
        target = mention_match.group(1)

    # Try as an ID
    user_id = None
    try:
        user_id = int(target.strip())
    except ValueError:
        pass

    if user_id:
        # Try guild member first
        member = guild.get_member(user_id)
        if member:
            return member, True
        # Try fetching as a user (not in server)
        try:
            user = await bot.fetch_user(user_id)
            return user, False
        except Exception:
            raise ValueError(f"Could not find a user with ID `{user_id}`.")

    # Try as a username match in guild
    target_lower = target.strip().lower()
    for member in guild.members:
        if (member.name.lower() == target_lower or
                member.display_name.lower() == target_lower or
                str(member).lower() == target_lower):
            return member, True

    raise ValueError(f"Could not find user `{target}`. Try using their user ID instead.")
