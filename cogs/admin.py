"""
admin.py — Admin & Mod utility commands
/presence  — Change bot activity at runtime (Admin)
/say       — Post a message as the bot (Mod + Admin)
/setautojail — Set auto-jail duration for warn escalation (Admin)
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import timedelta
import re

import database as db


# ── Duration parser (shared with /setautojail) ────────────────────────────────

def parse_duration(raw: str) -> timedelta | None:
    """Parse strings like 10m, 2h, 1d, 2h30m into a timedelta."""
    pattern = re.compile(r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?')
    m = pattern.fullmatch(raw.strip().lower())
    if not m or not any(m.groups()):
        return None
    days, hours, mins, secs = (int(x) if x else 0 for x in m.groups())
    td = timedelta(days=days, hours=hours, minutes=mins, seconds=secs)
    return td if td.total_seconds() > 0 else None


def duration_to_str(td: timedelta) -> str:
    """Convert a timedelta back to a human-readable string."""
    total = int(td.total_seconds())
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m, s   = divmod(rem, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if s: parts.append(f"{s}s")
    return "".join(parts) or "0s"


# ── Activity type map ─────────────────────────────────────────────────────────

ACTIVITY_TYPES = {
    "playing":   discord.ActivityType.playing,
    "watching":  discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /presence ─────────────────────────────────────────────────────────────

    @app_commands.command(name="presence", description="Change the bot's Discord activity at runtime.")
    @app_commands.describe(
        type="Activity type",
        text="What the bot is doing",
    )
    @app_commands.choices(type=[
        app_commands.Choice(name="Playing",   value="playing"),
        app_commands.Choice(name="Watching",  value="watching"),
        app_commands.Choice(name="Listening", value="listening"),
        app_commands.Choice(name="Competing", value="competing"),
    ])
    async def presence(self, interaction: discord.Interaction, type: str, text: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "⛔ Administrator only.", ephemeral=True
            )

        activity = discord.Activity(type=ACTIVITY_TYPES[type], name=text)
        await self.bot.change_presence(activity=activity)

        db.upsert_config(
            interaction.guild_id,
            presence_type=type,
            presence_text=text,
        )

        embed = discord.Embed(
            title="✅ Presence Updated",
            description=f"**{type.capitalize()}** {text}",
            color=0xD4A843,
        )
        embed.set_footer(text="ModSuite · Hammond Digital Studios")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /say ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="say", description="Post a message as the bot.")
    @app_commands.describe(
        message="The message to send",
        channel="Channel to post in (defaults to current channel)",
    )
    async def say(
        self,
        interaction: discord.Interaction,
        message: str,
        channel: discord.TextChannel = None,
    ):
        cfg = db.get_config(str(interaction.guild_id))
        if cfg is None:
            return await interaction.response.send_message(
                "⚙️ Run `/setup` first.", ephemeral=True
            )

        mod_role_id = cfg.get("mod_role_id")
        is_mod = mod_role_id and any(
            str(r.id) == str(mod_role_id) for r in interaction.user.roles
        )
        is_admin = interaction.user.guild_permissions.administrator

        if not (is_mod or is_admin):
            return await interaction.response.send_message(
                "⛔ Moderator or Administrator only.", ephemeral=True
            )

        target = channel or interaction.channel
        await target.send(message)

        embed = discord.Embed(
            description=f"✅ Message sent to {target.mention}",
            color=0xD4A843,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /setautojail ──────────────────────────────────────────────────────────

    @app_commands.command(
        name="setautojail",
        description="Set the auto-jail duration when the warn threshold is reached.",
    )
    @app_commands.describe(duration="Duration format: 10m, 2h, 1d, 2h30m")
    async def setautojail(self, interaction: discord.Interaction, duration: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "⛔ Administrator only.", ephemeral=True
            )

        td = parse_duration(duration)
        if td is None:
            return await interaction.response.send_message(
                "❌ Invalid duration. Examples: `10m`, `2h`, `1d`, `2h30m`.",
                ephemeral=True,
            )

        db.upsert_config(interaction.guild_id, auto_jail_duration=duration_to_str(td))

        embed = discord.Embed(
            title="⚙️ Auto-Jail Duration Updated",
            description=(
                f"Members will be auto-jailed for **{duration_to_str(td)}** "
                f"when the warn threshold is reached."
            ),
            color=0xD4A843,
        )
        embed.set_footer(text="ModSuite · Hammond Digital Studios")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
