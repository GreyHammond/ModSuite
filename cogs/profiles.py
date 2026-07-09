"""
profiles.py -- ModSuite v2.9 Severity Profiles

Named sets of automod thresholds that can be switched on the fly.
Three built-in profiles ship with every guild:

  normal  -- baseline thresholds (default)
  strict  -- lower thresholds, faster escalation
  raid    -- aggressive; auto-activated during lockdown, restored on unlock

Admins can also create custom profiles.

The active profile's overrides are merged onto guild_config at read time
via db.get_effective_config(). The automod pipeline uses that merged config
so switching profiles changes behavior instantly with zero restart.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import json
import database as db


FOOTER = "ModSuite -- Hammond Digital Studios"

# Keys that profiles can override
OVERRIDABLE_KEYS = [
    "spam_msg_limit", "spam_window_sec", "spam_dup_limit",
    "spam_mention_limit", "spam_emoji_limit", "spam_action",
    "spam_mute_minutes", "spam_enabled",
    "link_filter_enabled", "link_action",
    "invite_filter_enabled", "invite_action",
    "wordlist_enabled",
    "antiphish_enabled",
    "max_message_length", "min_message_length",
    "slowmode_enabled", "slowmode_seconds",
    "violation_jail_threshold", "violation_window_minutes",
    "violation_jail_duration",
]


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


async def _post_modlog(guild: discord.Guild, cfg: dict, embed: discord.Embed):
    ch_id = cfg.get("modlog_ch_id") if cfg else None
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except discord.HTTPException:
                pass


class Profiles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    profile_group = app_commands.Group(
        name="profile",
        description="Switch or manage automod severity profiles.",
    )

    @profile_group.command(name="switch", description="Switch the active automod profile.")
    @app_commands.describe(name="Profile name (normal, strict, raid, or a custom name)")
    async def switch(self, interaction: discord.Interaction, name: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        name = name.strip().lower()
        db.seed_profiles(str(interaction.guild_id))
        profile = db.get_profile(str(interaction.guild_id), name)
        if profile is None:
            available = db.get_all_profiles(str(interaction.guild_id))
            names = ", ".join(f"`{p['name']}`" for p in available)
            return await interaction.response.send_message(
                f"Profile `{name}` not found. Available: {names}", ephemeral=True
            )

        old_name = (cfg or {}).get("active_profile") or "normal"
        db.upsert_config(interaction.guild_id, active_profile=name)

        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="PROFILE_SWITCH",
            target_id="",
            target_username="",
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=f"Profile switched from {old_name} to {name}",
        )

        embed = discord.Embed(
            title="AutoMod Profile Switched",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Previous", value=f"**{old_name}**", inline=True)
        embed.add_field(name="Active", value=f"**{name}**", inline=True)
        overrides = profile.get("overrides", {})
        if overrides:
            preview = "\n".join(f"`{k}`: **{v}**" for k, v in list(overrides.items())[:8])
            if len(overrides) > 8:
                preview += f"\n...+{len(overrides) - 8} more"
            embed.add_field(name="Overrides", value=preview, inline=False)
        embed.set_footer(text=FOOTER)
        await _post_modlog(interaction.guild, cfg or {}, embed)
        await interaction.response.send_message(
            f"Switched to profile **{name}**.", ephemeral=True
        )

    @profile_group.command(name="list", description="View all available profiles.")
    async def list_profiles(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        db.seed_profiles(str(interaction.guild_id))
        profiles = db.get_all_profiles(str(interaction.guild_id))
        active = (cfg or {}).get("active_profile") or "normal"

        embed = discord.Embed(
            title="AutoMod Profiles",
            description=f"Active: **{active}**",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        for p in profiles:
            tag = " (active)" if p["name"] == active else ""
            built = " [built-in]" if p.get("built_in") else ""
            overrides = p.get("overrides", {})
            preview = ", ".join(f"{k}={v}" for k, v in list(overrides.items())[:5])
            if len(overrides) > 5:
                preview += f" ...+{len(overrides) - 5} more"
            embed.add_field(
                name=f"{p['name']}{tag}{built}",
                value=preview or "No overrides",
                inline=False,
            )
        embed.set_footer(text=FOOTER)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @profile_group.command(name="view", description="View details of a specific profile.")
    @app_commands.describe(name="Profile name")
    async def view_profile(self, interaction: discord.Interaction, name: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        db.seed_profiles(str(interaction.guild_id))
        profile = db.get_profile(str(interaction.guild_id), name.strip().lower())
        if profile is None:
            return await interaction.response.send_message(f"Profile `{name}` not found.", ephemeral=True)

        active = (cfg or {}).get("active_profile") or "normal"
        embed = discord.Embed(
            title=f"Profile: {profile['name']}",
            color=discord.Color.gold() if profile["name"] == active else discord.Color.greyple(),
            timestamp=datetime.utcnow(),
        )
        if profile["name"] == active:
            embed.description = "Currently active"
        if profile.get("built_in"):
            embed.description = (embed.description or "") + " [built-in]"
        overrides = profile.get("overrides", {})
        if overrides:
            lines = [f"`{k}`: **{v}**" for k, v in overrides.items()]
            embed.add_field(name=f"Overrides ({len(overrides)})", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Overrides", value="None (uses guild defaults)", inline=False)
        embed.set_footer(text=FOOTER)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @profile_group.command(name="create", description="Create a custom profile by copying the current config values.")
    @app_commands.describe(name="Name for the new profile")
    async def create_profile(self, interaction: discord.Interaction, name: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)

        name = name.strip().lower()
        if not name or len(name) > 32:
            return await interaction.response.send_message("Name must be 1-32 characters.", ephemeral=True)

        existing = db.get_profile(str(interaction.guild_id), name)
        if existing:
            return await interaction.response.send_message(f"Profile `{name}` already exists.", ephemeral=True)

        # Snapshot current effective config as the overrides
        cfg = db.get_config(interaction.guild_id) or {}
        overrides = {k: cfg.get(k) for k in OVERRIDABLE_KEYS if cfg.get(k) is not None}
        db.upsert_profile(str(interaction.guild_id), name, overrides, built_in=False)

        await interaction.response.send_message(
            f"Created profile `{name}` with {len(overrides)} setting(s) from current config. "
            f"Switch to it with `/profile switch {name}`.",
            ephemeral=True,
        )

    @profile_group.command(name="delete", description="Delete a custom profile (built-in profiles cannot be deleted).")
    @app_commands.describe(name="Profile name to delete")
    async def delete_profile(self, interaction: discord.Interaction, name: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)

        name = name.strip().lower()
        cfg = db.get_config(interaction.guild_id) or {}
        if cfg.get("active_profile") == name:
            return await interaction.response.send_message(
                "Cannot delete the active profile. Switch to another one first.", ephemeral=True
            )
        deleted = db.delete_profile(str(interaction.guild_id), name)
        if deleted:
            await interaction.response.send_message(f"Deleted profile `{name}`.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"Profile `{name}` not found or is a built-in profile.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Profiles(bot))
