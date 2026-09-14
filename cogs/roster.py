"""
Published membership roster.

Generates a public list of everyone holding a given role, grouped by the
organization they represent, and republishes it whenever the role is granted or
removed. Hand-maintained lists drift out of date within weeks; this one cannot.

Discord has no concept of an organization, so that is stored here and joined
against role membership at render time.

The published message is edited in place rather than reposted, so it keeps a
permanent link that can be cited elsewhere.

Role name, channel name, and intro text are all configurable per guild under
Configuration → Roster.
"""
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import FOOTER_BRAND, BRAND_COLOR

log = logging.getLogger("ModSuite.roster")

# Defaults. Both are overridable per guild in Configuration, so a server can
# point this at whatever its own membership role happens to be called.
DEFAULT_ROLE_NAME = "Roster"
DEFAULT_CHANNEL_NAME = "roster"

DEFAULT_INTRO = (
    "Current members, grouped by organization. This list is generated from "
    "role membership and updates automatically."
)


class Roster(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    roster_group = app_commands.Group(name="roster",
                                      description="Published membership roster.")

    # ── Building ─────────────────────────────────────────────────────────────
    @staticmethod
    def _cfg(guild) -> dict:
        return db.get_config(guild.id) or {}

    def _role_name(self, guild) -> str:
        return self._cfg(guild).get("roster_role_name") or DEFAULT_ROLE_NAME

    def _channel_name(self, guild) -> str:
        return self._cfg(guild).get("roster_channel_name") or DEFAULT_CHANNEL_NAME

    def _intro(self, guild) -> str:
        return (self._cfg(guild).get("roster_intro") or "").strip() or DEFAULT_INTRO

    def _role(self, guild: discord.Guild) -> discord.Role | None:
        return discord.utils.get(guild.roles, name=self._role_name(guild))

    def _channel(self, guild: discord.Guild) -> discord.TextChannel | None:
        return discord.utils.get(guild.text_channels, name=self._channel_name(guild))

    def build_embed(self, guild: discord.Guild) -> tuple[discord.Embed, int, list]:
        """Returns the embed, the member count, and members missing an org."""
        role = self._role(guild)
        members = sorted(role.members, key=lambda m: m.display_name.lower()) if role else []

        stored = {r["user_id"]: r for r in db.get_roster(str(guild.id))}
        by_org: dict[str, list[str]] = {}
        missing = []

        for m in members:
            rec = stored.get(str(m.id), {})
            org = (rec.get("organization") or "").strip()
            title = (rec.get("role_title") or "").strip()
            if not org:
                org = "Organization not listed"
                missing.append(m)
            label = m.display_name
            if title:
                label += f" -- {title}"
            by_org.setdefault(org, []).append(label)

        embed = discord.Embed(
            title=f"{self._role_name(guild)} -- Membership",
            description=self._intro(guild),
            colour=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        if not members:
            embed.add_field(name="Members", value="No members yet.", inline=False)
        else:
            # "Organization not listed" sorts last, so gaps are visible but not first
            for org in sorted(by_org, key=lambda o: (o == "Organization not listed", o.lower())):
                embed.add_field(name=org, value="\n".join(by_org[org])[:1000],
                                inline=False)
        embed.set_footer(text=f"{len(members)} member(s) · updated · {FOOTER_BRAND}")
        return embed, len(members), missing

    async def publish(self, guild: discord.Guild) -> bool:
        """Edit the existing roster post, or create it if there is none."""
        channel = self._channel(guild)
        if channel is None:
            return False
        embed, _, _ = self.build_embed(guild)

        try:
            async for msg in channel.history(limit=30):
                if msg.author.id == self.bot.user.id and msg.embeds:
                    await msg.edit(embed=embed)
                    return True
            await channel.send(embed=embed)
            return True
        except discord.HTTPException as e:
            log.warning(f"Roster publish failed: {e}")
            return False

    # ── Auto-republish when the role changes ─────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if {r.name for r in before.roles} == {r.name for r in after.roles}:
            return
        name = self._role_name(after.guild)
        had = any(r.name == name for r in before.roles)
        has = any(r.name == name for r in after.roles)
        if had == has:
            return
        if has:
            db.upsert_roster_member(str(after.guild.id), str(after.id),
                                    display_name=after.display_name)
        await self.publish(after.guild)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if db.get_roster_member(str(member.guild.id), str(member.id)):
            await self.publish(member.guild)

    # ── Commands ─────────────────────────────────────────────────────────────
    @roster_group.command(name="set", description="Record a member's organization.")
    @app_commands.describe(member="Roster member",
                           organization="Which organization they represent",
                           title="Their role there, e.g. Executive Director")
    async def roster_set(self, interaction: discord.Interaction,
                         member: discord.Member, organization: str, title: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        db.upsert_roster_member(str(interaction.guild_id), str(member.id),
                                display_name=member.display_name,
                                organization=organization, role_title=title)
        await self.publish(interaction.guild)
        await interaction.response.send_message(
            f"{member.display_name} recorded as **{organization}**"
            + (f", {title}" if title else "") + ". Roster republished.",
            ephemeral=True)

    @roster_group.command(name="publish", description="Rebuild the public roster now.")
    async def roster_publish(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        embed, count, missing = self.build_embed(interaction.guild)
        ok = await self.publish(interaction.guild)
        if not ok:
            return await interaction.followup.send(
                f"No `#{self._channel_name(interaction.guild)}` channel found. "
                f"Create it, or change the channel name under Configuration → "
                f"Roster.", ephemeral=True)

        msg = f"Roster published: {count} member(s)."
        if missing:
            names = ", ".join(m.display_name for m in missing[:8])
            msg += (f"\n\n{len(missing)} member(s) have no organization recorded "
                    f"and appear as unlisted: {names}. Fix with `/roster set`.")
        await interaction.followup.send(msg, ephemeral=True)

    @roster_group.command(name="preview", description="See the roster without publishing.")
    async def roster_preview(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        embed, count, missing = self.build_embed(interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @roster_group.command(name="remove", description="Clear a member's roster record.")
    @app_commands.describe(member="Member to remove from the roster table")
    async def roster_remove(self, interaction: discord.Interaction,
                            member: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        ok = db.remove_roster_member(str(interaction.guild_id), str(member.id))
        if ok:
            await self.publish(interaction.guild)
        await interaction.response.send_message(
            "Record cleared and roster republished." if ok else "No record for that member.",
            ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Roster(bot))
