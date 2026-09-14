"""
Legacy booster rewards.

Discord's own booster role is removed the moment someone stops boosting, so
every perk tied to it evaporates. This grants a separate, permanent role on
first boost: boost once, keep the perks forever.

The database row is the source of truth, not the Discord role. Roles are lost
when a member leaves the server, so without a record the promise would quietly
break for anyone who left and came back. The row survives that, and the role is
re-applied on rejoin.

Three ways a grant happens:

1. Live, when `premium_since` goes from None to a datetime.
2. On join, re-applying to a returning member who earned it before.
3. By backfill, for anyone already boosting when this was switched on, or who
   boosted while the bot was offline.

Grants are one-way by design. `/booster revoke` exists for abuse cases and is
recorded with an actor and a reason rather than silently deleting the row.
"""
import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import FOOTER_BRAND, BRAND_COLOR

log = logging.getLogger("ModSuite.boosters")

DEFAULT_THANKS = (
    "Thank you for boosting. Your perks are now permanent — this role stays "
    "with you whether or not you keep boosting."
)


class Boosters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    booster_group = app_commands.Group(
        name="booster", description="Permanent rewards for server boosters.")

    # ── Core ─────────────────────────────────────────────────────────────────
    def _role(self, guild: discord.Guild, cfg: dict) -> discord.Role | None:
        rid = cfg.get("legacy_boost_role")
        return guild.get_role(int(rid)) if rid else None

    async def _apply(self, member: discord.Member, cfg: dict,
                     reason: str) -> bool:
        role = self._role(member.guild, cfg)
        if role is None:
            return False
        if role in member.roles:
            return True
        try:
            await member.add_roles(role, reason=f"Legacy booster: {reason}"[:500])
            return True
        except discord.Forbidden:
            log.warning(
                f"[{member.guild.name}] Cannot grant {role.name} to {member} -- "
                f"the bot's role must sit above it.")
        except discord.HTTPException as e:
            log.warning(f"Legacy booster grant failed for {member}: {e}")
        return False

    async def _announce(self, guild: discord.Guild, cfg: dict,
                        member: discord.Member):
        channel_id = cfg.get("legacy_boost_announce")
        if not channel_id:
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            return
        thanks = (cfg.get("legacy_boost_thanks") or "").strip() or DEFAULT_THANKS
        e = discord.Embed(
            title="Boost perks unlocked, permanently",
            description=f"{member.mention} — {thanks}",
            colour=0xF47FFF,
            timestamp=datetime.now(timezone.utc),
        )
        e.set_thumbnail(url=member.display_avatar.url)
        e.set_footer(text=FOOTER_BRAND)
        try:
            await channel.send(embed=e)
        except discord.HTTPException:
            pass

    async def _record_and_grant(self, member: discord.Member, cfg: dict,
                                granted_by: str, reason: str,
                                announce: bool = True) -> bool:
        """Returns True only when this is a NEW grant, so callers can count."""
        first = member.premium_since.isoformat() if member.premium_since else ""
        is_new = db.grant_legacy_boost(
            str(member.guild.id), str(member.id), str(member),
            first_boosted=first, granted_by=granted_by)
        await self._apply(member, cfg, reason)
        if is_new and announce:
            await self._announce(member.guild, cfg, member)
        return is_new

    # ── Listeners ────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member,
                               after: discord.Member):
        # premium_since flips from None to a datetime on the first boost
        if before.premium_since is not None or after.premium_since is None:
            return
        cfg = db.get_config(after.guild.id) or {}
        if not cfg.get("legacy_boost_enabled"):
            return
        if await self._record_and_grant(after, cfg, "auto", "started boosting"):
            log.info(f"[{after.guild.name}] Legacy booster granted to {after}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Roles do not survive leaving the server. Without this, someone who
        earned the reward and later rejoined would silently lose it, which
        would make the whole promise untrue.
        """
        cfg = db.get_config(member.guild.id) or {}
        if not cfg.get("legacy_boost_enabled"):
            return
        if not db.is_legacy_booster(str(member.guild.id), str(member.id)):
            return
        if await self._apply(member, cfg, "rejoined; previously earned"):
            log.info(f"[{member.guild.name}] Restored legacy booster role to {member}")

    # ── Commands ─────────────────────────────────────────────────────────────
    @booster_group.command(
        name="setup",
        description="Choose the permanent role granted on a member's first boost.")
    @app_commands.describe(
        role="Role granted forever, kept even after they stop boosting",
        announce_channel="Optional channel for a thank-you post",
        thanks="Optional custom thank-you line")
    async def booster_setup(self, interaction: discord.Interaction,
                            role: discord.Role,
                            announce_channel: discord.TextChannel = None,
                            thanks: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True)

        me = interaction.guild.me
        if role >= me.top_role:
            return await interaction.response.send_message(
                f"{role.mention} sits at or above my highest role, so I cannot "
                f"assign it. Move my role above it and run this again.",
                ephemeral=True)
        if role.is_premium_subscriber():
            return await interaction.response.send_message(
                "That is Discord's own booster role. It is removed automatically "
                "when someone stops boosting, which is the exact problem this "
                "feature exists to solve. Create a separate role and grant it "
                "the perks you want to make permanent.",
                ephemeral=True)

        db.upsert_config(
            interaction.guild_id,
            legacy_boost_enabled=1,
            legacy_boost_role=role.id,
            legacy_boost_announce=announce_channel.id if announce_channel else None,
            legacy_boost_thanks=thanks,
        )

        current = len(interaction.guild.premium_subscribers)
        e = discord.Embed(title="Legacy booster rewards enabled",
                          colour=BRAND_COLOR)
        e.add_field(name="Permanent role", value=role.mention, inline=True)
        e.add_field(name="Currently boosting", value=str(current), inline=True)
        if announce_channel:
            e.add_field(name="Announcements", value=announce_channel.mention,
                        inline=True)
        e.add_field(
            name="Next step",
            value=(f"Run `/booster sync` to grant it to the {current} member(s) "
                   f"already boosting. New boosts are picked up automatically."
                   if current else
                   "New boosts will be picked up automatically."),
            inline=False)
        e.add_field(
            name="Grant the perks to this role, not the boost role",
            value="Channel access, permissions, and anything else you want kept "
                  "should hang off this role. Discord strips its own booster "
                  "role the moment someone stops.",
            inline=False)
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @booster_group.command(
        name="sync",
        description="Grant the permanent role to everyone currently boosting.")
    async def booster_sync(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        if not cfg.get("legacy_boost_enabled"):
            return await interaction.response.send_message(
                "Not configured. Run `/booster setup` first.", ephemeral=True)
        role = self._role(interaction.guild, cfg)
        if role is None:
            return await interaction.response.send_message(
                "The configured role no longer exists. Run `/booster setup` again.",
                ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        new = existing = 0
        for member in interaction.guild.premium_subscribers:
            if await self._record_and_grant(member, cfg, str(interaction.user),
                                            "sync of current boosters",
                                            announce=False):
                new += 1
            else:
                existing += 1

        # Anyone with a record but missing the role, e.g. it was removed by hand
        restored = 0
        for row in db.get_legacy_boosters(str(interaction.guild_id)):
            m = interaction.guild.get_member(int(row["user_id"]))
            if m and role not in m.roles:
                if await self._apply(m, cfg, "restored by sync"):
                    restored += 1

        await interaction.followup.send(
            f"**{new}** new grant(s), **{existing}** already recorded, "
            f"**{restored}** role(s) restored to members who had it removed.",
            ephemeral=True)

    @booster_group.command(name="list", description="Everyone who has earned the permanent role.")
    @app_commands.describe(show_revoked="Include revoked grants")
    async def booster_list(self, interaction: discord.Interaction,
                           show_revoked: bool = False):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True)
        rows = db.get_legacy_boosters(str(interaction.guild_id),
                                      include_revoked=show_revoked)
        if not rows:
            return await interaction.response.send_message(
                "Nobody has earned it yet.", ephemeral=True)

        still = 0
        lines = []
        for r in rows[:25]:
            m = interaction.guild.get_member(int(r["user_id"]))
            boosting = m is not None and m.premium_since is not None
            if boosting:
                still += 1
            tag = " *(revoked)*" if r.get("revoked") else ""
            state = "boosting" if boosting else ("left" if m is None else "kept")
            lines.append(f"{m.mention if m else r['username'] or r['user_id']} "
                         f"— {state}, since {r['granted_at'][:10]}{tag}")

        e = discord.Embed(
            title="Legacy boosters",
            description="\n".join(lines) or "None",
            colour=BRAND_COLOR)
        e.add_field(name="Total", value=str(len(rows)), inline=True)
        e.add_field(name="Still boosting", value=str(still), inline=True)
        e.add_field(name="Keeping perks anyway", value=str(len(rows) - still),
                    inline=True)
        if len(rows) > 25:
            e.set_footer(text=f"Showing 25 of {len(rows)} · {FOOTER_BRAND}")
        else:
            e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @booster_group.command(
        name="grant",
        description="Manually give someone the permanent role without boosting.")
    @app_commands.describe(member="Member to grant it to", reason="Why")
    async def booster_grant(self, interaction: discord.Interaction,
                            member: discord.Member, reason: str = ""):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        if not cfg.get("legacy_boost_enabled"):
            return await interaction.response.send_message(
                "Not configured. Run `/booster setup` first.", ephemeral=True)

        db.grant_legacy_boost(str(interaction.guild_id), str(member.id),
                              str(member), granted_by=str(interaction.user),
                              note=reason)
        ok = await self._apply(member, cfg, f"manual grant: {reason}")
        await interaction.response.send_message(
            f"{member.mention} now has permanent booster perks."
            + ("" if ok else "\n⚠ Could not apply the role — check my role position."),
            ephemeral=True)

    @booster_group.command(
        name="revoke",
        description="Remove permanent perks. For abuse cases only.")
    @app_commands.describe(member="Member", reason="Recorded with the revocation")
    async def booster_revoke(self, interaction: discord.Interaction,
                             member: discord.Member, reason: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        ok = db.revoke_legacy_boost(str(interaction.guild_id), str(member.id),
                                    revoked_by=str(interaction.user), note=reason)
        if not ok:
            return await interaction.response.send_message(
                "That member has no active grant.", ephemeral=True)
        role = self._role(interaction.guild, cfg)
        if role and role in member.roles:
            try:
                await member.remove_roles(role, reason=f"Revoked: {reason}"[:500])
            except discord.HTTPException:
                pass
        db.add_mod_log(
            guild_id=str(interaction.guild_id), action="BOOSTER_REVOKE",
            target_id=str(member.id), target_username=str(member),
            actor_id=str(interaction.user.id),
            actor_username=str(interaction.user), reason=reason)
        await interaction.response.send_message(
            f"Revoked permanent booster perks from {member.mention}. "
            f"The record is kept, marked revoked.", ephemeral=True)

    @booster_group.command(name="off", description="Stop granting the permanent role.")
    async def booster_off(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True)
        db.upsert_config(interaction.guild_id, legacy_boost_enabled=0)
        await interaction.response.send_message(
            "Stopped. Nobody loses what they already earned — existing grants "
            "and roles are untouched.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Boosters(bot))
