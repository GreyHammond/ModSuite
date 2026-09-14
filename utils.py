"""
utils.py -- ModSuite shared helpers.

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
    # Nobody -- including the bot -- acts on the server owner
    if target.id == target.guild.owner_id:
        return False

    # Automated bot action -- allow everything except server owner (handled above)
    if actor is None:
        return True

    # The server owner outranks everyone. The docstring table has always said
    # so, but the admin-versus-admin rule below caught the owner too, because
    # the owner also holds administrator permissions. Acting on themselves is
    # already blocked above.
    if actor.id == target.guild.owner_id:
        return True

    # Target is a protected member -- apply role-level restrictions
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

# ── User resolution ───────────────────────────────────────────────────────────
#
# Every staff-facing command that targets a person accepts the same three
# forms: a mention (<@123>), a raw numeric user ID (123), or a username /
# display name. The numeric ID is the only form that keeps working after the
# person leaves the guild, so it is the form the rest of the codebase relies on
# for cleanup work (removing a departed streamer, releasing a stale jail row,
# clearing violations, lifting a ban).

# A Discord snowflake is 17-20 digits. Anything shorter is almost certainly a
# username made of digits, so we do not treat it as an ID.
_SNOWFLAKE_RE = _re.compile(r"^\d{15,20}$")
_MENTION_RE = _re.compile(r"^<@!?(\d+)>$")


class UnknownUser:
    """
    Stand-in for a user ID that Discord will not resolve -- a deleted account,
    or an account the bot shares no mutual context with.

    Exposes the same surface the cogs read off a real user object so that
    embeds, mod-log rows, and DM attempts do not need special-casing. Anything
    that would perform a Discord action against this object should be guarded
    by the ``is_member`` flag returned from ``resolve_user``.
    """

    __slots__ = ("id",)

    def __init__(self, user_id: int):
        self.id = int(user_id)

    def __str__(self) -> str:
        return f"Unknown User ({self.id})"

    def __int__(self) -> int:
        return self.id

    def __repr__(self) -> str:
        return f"<UnknownUser id={self.id}>"

    @property
    def name(self) -> str:
        return "Unknown User"

    @property
    def display_name(self) -> str:
        return "Unknown User"

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    @property
    def bot(self) -> bool:
        return False

    @property
    def display_avatar(self):
        return None

    async def send(self, *args, **kwargs):
        """
        No-op. Callers wrap DM attempts in try/except for discord exceptions
        only, so raising here would escape those handlers. There is genuinely
        nothing to deliver to an unresolvable account.
        """
        return None


def parse_user_id(target: str) -> "int | None":
    """
    Pull a numeric user ID out of a mention or a bare ID string.
    Returns None when the input is not ID-shaped (i.e. it is a username).
    """
    if target is None:
        return None
    text = str(target).strip()
    m = _MENTION_RE.match(text)
    if m:
        return int(m.group(1))
    if _SNOWFLAKE_RE.match(text):
        return int(text)
    return None


async def resolve_user(bot, guild, target: str, *, allow_unknown: bool = True):
    """
    Resolve a user from a mention, a raw numeric user ID, or a username.

    Returns (user, is_member):
      user      -- discord.Member if they are in the guild,
                   discord.User if Discord knows them but they are not,
                   utils.UnknownUser if only the ID is knowable.
      is_member -- True only when the target is currently in the guild. Guard
                   every Discord-side action (kick, role edit, timeout, DM) on
                   this flag.

    Raises ValueError when the target cannot be resolved at all. Pass
    allow_unknown=False to also raise when the ID is valid but unfetchable --
    use that for commands that genuinely need a real account.
    """
    if target is None or not str(target).strip():
        raise ValueError("No user was supplied.")

    text = str(target).strip()
    user_id = parse_user_id(text)

    if user_id is not None:
        # In the guild -- full member object, everything is available.
        member = guild.get_member(user_id) if guild else None
        if member:
            return member, True

        # Not cached but possibly still present. Only worth a round trip when
        # the guild is available and the member intent may have missed them.
        if guild is not None:
            try:
                member = await guild.fetch_member(user_id)
                if member:
                    return member, True
            except Exception:
                pass

        # Outside the guild -- Discord may still know the account.
        try:
            user = await bot.fetch_user(user_id)
            return user, False
        except Exception:
            pass

        if allow_unknown:
            # Deleted or unreachable account. The ID is still valid for every
            # database-side operation, which is the whole point of this branch.
            return UnknownUser(user_id), False

        raise ValueError(
            f"Could not find a user with ID `{user_id}`. "
            f"The account may have been deleted."
        )

    # Not ID-shaped -- fall back to a name match inside the guild.
    lowered = text.lower().lstrip("@")
    if guild is not None:
        for member in guild.members:
            if (
                member.name.lower() == lowered
                or member.display_name.lower() == lowered
                or str(member).lower() == lowered
            ):
                return member, True
        # Second pass: prefix match, so partial names still work.
        prefix_hits = [
            m for m in guild.members
            if m.name.lower().startswith(lowered)
            or m.display_name.lower().startswith(lowered)
        ]
        if len(prefix_hits) == 1:
            return prefix_hits[0], True
        if len(prefix_hits) > 1:
            names = ", ".join(f"`{m}`" for m in prefix_hits[:5])
            raise ValueError(
                f"`{text}` matches multiple members ({names}). "
                f"Use their numeric user ID instead."
            )

    raise ValueError(
        f"Could not find user `{text}`. If they have left the server, "
        f"use their numeric user ID instead."
    )


def describe_user(user, is_member: bool = True) -> str:
    """Consistent '<name> (`<id>`)' rendering, with a note when they are gone."""
    base = f"{user} (`{user.id}`)"
    if not is_member:
        base += " *(not in server)*"
    return base
