"""
verify.py -- Age verification commands
/verify @user   -- Grant the Verified 18+ role (Mod + Admin)
/unverify @user -- Remove the Verified 18+ role (Mod + Admin)

Logs both actions to #mod-log including who performed the action.
The Verified 18+ role is looked up by name on first use and cached
in guild_config as verified_role_id for all future calls.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone

import database as db
from config import FOOTER_BRAND

VERIFIED_ROLE_NAME = "Verified 18+"


async def _get_verified_role(guild: discord.Guild) -> discord.Role | None:
    """
    Return the Verified 18+ role. Looks up the ID from guild_config first.
    If not stored, searches the guild by name and caches the ID for next time.
    Returns None if the role cannot be found.
    """
    cfg = db.get_config(str(guild.id))
    stored_id = cfg.get("verified_role_id") if cfg else None

    if stored_id:
        role = guild.get_role(int(stored_id))
        if role:
            return role

    # Not cached -- search by name
    role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
    if role:
        db.upsert_config(guild.id, verified_role_id=str(role.id))
    return role


async def _post_modlog(
    guild: discord.Guild,
    action: str,
    target: discord.Member,
    actor: discord.Member,
):
    """Post a verification action embed to #mod-log."""
    cfg = db.get_config(str(guild.id))
    if not cfg:
        return

    log_ch_id = cfg.get("log_ch_id")
    if not log_ch_id:
        return

    channel = guild.get_channel(int(log_ch_id))
    if not channel:
        return

    color  = 0x3AB87A if action == "Verified" else 0xE83A5A
    symbol = "✅" if action == "Verified" else "❌"

    embed = discord.Embed(
        title=f"{symbol} {action}: {target.display_name}",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name="User",       value=f"{target.mention} (`{target.id}`)", inline=True)
    embed.add_field(name="Action by",  value=f"{actor.mention}",                  inline=True)
    embed.add_field(name="Role",       value=VERIFIED_ROLE_NAME,                  inline=False)
    embed.set_footer(text=FOOTER_BRAND)
    await channel.send(embed=embed)


class Verify(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_staff(self, interaction: discord.Interaction) -> bool:
        """Returns True if the user is a Moderator or Administrator."""
        if interaction.user.guild_permissions.administrator:
            return True
        cfg = db.get_config(str(interaction.guild_id))
        if not cfg:
            return False
        mod_role_id = cfg.get("mod_role_id")
        return mod_role_id and any(
            str(r.id) == str(mod_role_id) for r in interaction.user.roles
        )

    # ── /verify ───────────────────────────────────────────────────────────────

    @app_commands.command(
        name="verify",
        description=f"Grant the {VERIFIED_ROLE_NAME} role to a member.",
    )
    @app_commands.describe(user="Member mention, username, or numeric user ID")
    async def verify(self, interaction: discord.Interaction, user: str):
        if not self._is_staff(interaction):
            return await interaction.response.send_message(
                "⛔ Moderator or Administrator only.", ephemeral=True
            )

        from utils import resolve_user
        try:
            user, is_member = await resolve_user(self.bot, interaction.guild, user)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        if not is_member:
            return await interaction.response.send_message(
                f"❌ **{user}** is not in this server, so no role can be granted.",
                ephemeral=True,
            )

        role = await _get_verified_role(interaction.guild)
        if not role:
            return await interaction.response.send_message(
                f"❌ Could not find the **{VERIFIED_ROLE_NAME}** role. "
                f"Please ensure it exists in the server.",
                ephemeral=True,
            )

        if role in user.roles:
            return await interaction.response.send_message(
                f"ℹ️ {user.mention} already has the **{VERIFIED_ROLE_NAME}** role.",
                ephemeral=True,
            )

        await user.add_roles(role, reason=f"Verified by {interaction.user}")
        await _post_modlog(interaction.guild, "Verified", user, interaction.user)

        embed = discord.Embed(
            title="✅ Member Verified",
            description=f"{user.mention} has been granted **{VERIFIED_ROLE_NAME}**.",
            color=0x3AB87A,
        )
        embed.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /unverify ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name="unverify",
        description=f"Remove the {VERIFIED_ROLE_NAME} role from a member.",
    )
    @app_commands.describe(user="Member mention, username, or numeric user ID")
    async def unverify(self, interaction: discord.Interaction, user: str):
        if not self._is_staff(interaction):
            return await interaction.response.send_message(
                "⛔ Moderator or Administrator only.", ephemeral=True
            )

        from utils import resolve_user
        try:
            user, is_member = await resolve_user(self.bot, interaction.guild, user)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)
        if not is_member:
            return await interaction.response.send_message(
                f"❌ **{user}** is not in this server, so they hold no roles here.",
                ephemeral=True,
            )

        role = await _get_verified_role(interaction.guild)
        if not role:
            return await interaction.response.send_message(
                f"❌ Could not find the **{VERIFIED_ROLE_NAME}** role. "
                f"Please ensure it exists in the server.",
                ephemeral=True,
            )

        if role not in user.roles:
            return await interaction.response.send_message(
                f"ℹ️ {user.mention} does not have the **{VERIFIED_ROLE_NAME}** role.",
                ephemeral=True,
            )

        await user.remove_roles(role, reason=f"Unverified by {interaction.user}")
        await _post_modlog(interaction.guild, "Unverified", user, interaction.user)

        embed = discord.Embed(
            title="❌ Member Unverified",
            description=f"{user.mention}'s **{VERIFIED_ROLE_NAME}** role has been removed.",
            color=0xE83A5A,
        )
        embed.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Verify(bot))
