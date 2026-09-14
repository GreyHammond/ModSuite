"""
Discord-side audit capture.

The dashboard writes to the audit trail through middleware. This does the same
job for the other half of the surface: every slash command run in Discord.

It hooks the tree globally rather than touching each cog, for the same reason
the API side is middleware -- a command added later cannot forget to log, and
there is no per-cog boilerplate to keep in sync. Together the two sources make
one timeline that answers "who did what", regardless of where they did it.

Both successes and failures are recorded. A refused `/ban` is often more
interesting than a successful one.
"""
import json
import logging

import discord
from discord import app_commands
from discord.ext import commands

import database as db

log = logging.getLogger("ModSuite.audit")

# Read-only commands. Still logged, but flagged non-mutating so the audit page
# can hide them by default without losing the record that someone looked.
READ_ONLY = {
    "userinfo", "serverinfo", "avatar", "roleinfo", "ping", "help",
    "warns list", "notes list", "modlogs", "violations", "foia list",
    "archive status", "blueprint list", "blueprint preview", "streamer list",
    "reminders list", "profiles list", "config view", "whois", "membercount",
}

# Option names never written into the audit payload.
REDACT = {"token", "secret", "password", "client_secret", "api_key", "webhook"}

# Options that identify the person an action was taken against.
TARGET_KEYS = ("member", "user", "target", "streamer", "channel")


def _full_name(command) -> str:
    """Qualified command name, including group, e.g. 'blueprint apply'."""
    if command is None:
        return "unknown"
    name = getattr(command, "qualified_name", None)
    return name or getattr(command, "name", "unknown")


def _extract_options(interaction: discord.Interaction) -> tuple[dict, str]:
    """
    Pull the supplied options and a best-guess target out of an interaction.

    interaction.namespace holds resolved values (a Member object rather than a
    snowflake), which is what makes the audit line readable.
    """
    payload: dict = {}
    target = ""
    namespace = getattr(interaction, "namespace", None)
    if namespace is None:
        return payload, target

    for key, value in vars(namespace).items():
        if key.startswith("_"):
            continue
        if key.lower() in REDACT:
            payload[key] = "[redacted]"
            continue
        if isinstance(value, (discord.Member, discord.User)):
            rendered = f"{value} ({value.id})"
            if not target and key.lower() in TARGET_KEYS:
                target = str(value)
        elif isinstance(value, (discord.TextChannel, discord.VoiceChannel,
                                discord.CategoryChannel, discord.Role)):
            rendered = f"{value.name} ({value.id})"
            if not target and key.lower() in TARGET_KEYS:
                target = f"#{value.name}"
        else:
            rendered = value
        if rendered is not None and rendered != "":
            payload[key] = rendered
    return payload, target


def _summarise(name: str, payload: dict, target: str, ok: bool) -> str:
    bits = f"/{name}"
    if target:
        bits += f" on {target}"
    reason = payload.get("reason")
    if reason:
        bits += f" -- {str(reason)[:80]}"
    if not ok:
        bits += " [FAILED]"
    return bits


def record_command(interaction: discord.Interaction, command,
                   status: int = 200, error: str = ""):
    """Write one slash-command invocation to the audit trail."""
    try:
        name = _full_name(command)
        payload, target = _extract_options(interaction)
        if error:
            payload["_error"] = error[:300]

        db.add_audit(
            guild_id=str(interaction.guild_id or ""),
            actor_id=str(interaction.user.id),
            actor_name=getattr(interaction.user, "display_name",
                               str(interaction.user)),
            method="CMD",
            path=f"/{name.replace(' ', '/')}",
            summary=_summarise(name, payload, target, status < 400),
            payload=json.dumps(payload, default=str) if payload else "",
            status=status,
            ip="",
            source="discord",
            target=target,
            mutating=name not in READ_ONLY,
        )
    except Exception as e:
        # Auditing must never interfere with the command the user ran.
        log.warning(f"Command audit failed: {e}")


class AuditCapture(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Chain onto any existing tree error handler rather than replacing it,
        # so whatever the bot already does with errors still happens.
        self._prev_error = bot.tree.on_error
        bot.tree.on_error = self._on_tree_error

    def cog_unload(self):
        if self._prev_error is not None:
            self.bot.tree.on_error = self._prev_error

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction,
                                        command):
        record_command(interaction, command, status=200)

    async def _on_tree_error(self, interaction: discord.Interaction,
                             error: app_commands.AppCommandError):
        status = 403 if isinstance(
            error, (app_commands.MissingPermissions,
                    app_commands.CheckFailure)) else 500
        record_command(interaction, interaction.command, status=status,
                       error=str(error))
        if self._prev_error is not None:
            await self._prev_error(interaction, error)


async def setup(bot: commands.Bot):
    await bot.add_cog(AuditCapture(bot))
