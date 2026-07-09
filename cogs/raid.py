import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
from collections import deque
import asyncio
import database as db


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


class Raid(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> deque of join timestamps
        self._join_times: dict[int, deque] = {}
        # guilds currently in lockdown
        self._locked_guilds: set[int] = set()
        # remembered verification level per guild (restore on unlock)
        self._saved_verification: dict[int, discord.VerificationLevel] = {}
        # scheduled auto-unlock tasks per guild (so we can cancel on manual /unlock)
        self._unlock_tasks: dict[int, asyncio.Task] = {}

    # ── on_member_join: active-raid gate, account age, auto-role, detection ──
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = db.get_config(member.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return

        # ── Active raid mode: block new joiners immediately ─────────────────
        if member.guild.id in self._locked_guilds:
            action = (cfg.get("raid_active_action") or "ban").lower()
            try:
                if action == "ban":
                    await member.ban(reason="AutoMod raid: joined during active lockdown",
                                     delete_message_days=1)
                    outcome = "banned"
                else:
                    await member.kick(reason="AutoMod raid: joined during active lockdown")
                    outcome = "kicked"
                # Log to mod_logs DB so role persistence and /history see it
                db.add_mod_log(
                    guild_id=str(member.guild.id),
                    action="BAN" if action == "ban" else "KICK",
                    target_id=str(member.id),
                    target_username=str(member),
                    actor_id=str(self.bot.user.id) if self.bot.user else "",
                    actor_username="AutoMod (raid)",
                    reason=f"Raid: joined during active lockdown ({outcome})",
                )
                embed = discord.Embed(
                    title="🚨 Raid -- new joiner blocked",
                    description=f"{member} (`{member.id}`) was **{outcome}** on join.",
                    color=discord.Color.red(),
                    timestamp=datetime.utcnow(),
                )
                await _post_modlog(member.guild, cfg, embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
            return  # skip auto-role and further checks

        # ── Account age flag ────────────────────────────────────────────────
        min_age_days = cfg.get("raid_min_account_age_days") or 0
        if min_age_days > 0:
            account_age = (datetime.now(timezone.utc) - member.created_at).days
            if account_age < min_age_days:
                embed = discord.Embed(
                    title="⚠️ Suspicious join -- young account",
                    color=discord.Color.gold(),
                    timestamp=datetime.utcnow(),
                )
                embed.add_field(name="User",        value=f"{member.mention} (`{member.id}`)",              inline=True)
                embed.add_field(name="Account age", value=f"{account_age}d (min: {min_age_days}d)",         inline=True)
                embed.add_field(name="Created",     value=f"<t:{int(member.created_at.timestamp())}:R>",    inline=False)
                await _post_modlog(member.guild, cfg, embed)
                # Flag only -- don't auto-kick individual young accounts.
                # The raid detector below handles bulk-join scenarios where they matter most.

        # ── Auto-role ───────────────────────────────────────────────────────
        auto_role_id = cfg.get("auto_role_id")
        if auto_role_id:
            role = member.guild.get_role(auto_role_id)
            if role:
                try:
                    await member.add_roles(role, reason="Auto-role on join")
                except discord.Forbidden:
                    pass

        # ── Raid detection: join velocity ───────────────────────────────────
        threshold_joins   = cfg.get("raid_join_count",   10)
        threshold_seconds = cfg.get("raid_join_seconds", 10)

        gid = member.guild.id
        if gid not in self._join_times:
            self._join_times[gid] = deque()

        now = datetime.now(timezone.utc).timestamp()
        self._join_times[gid].append(now)

        cutoff = now - threshold_seconds
        while self._join_times[gid] and self._join_times[gid][0] < cutoff:
            self._join_times[gid].popleft()

        if len(self._join_times[gid]) >= threshold_joins and gid not in self._locked_guilds:
            await self._lockdown(member.guild, cfg, auto=True)

    # ── Lockdown ────────────────────────────────────────────────────────────
    async def _lockdown(self, guild: discord.Guild, cfg: dict, auto: bool = False):
        self._locked_guilds.add(guild.id)
        everyone = guild.default_role

        # Auto-switch to "raid" profile
        current_profile = cfg.get("active_profile") or "normal"
        if current_profile != "raid":
            db.upsert_config(guild.id, profile_before_raid=current_profile, active_profile="raid")
            db.seed_profiles(str(guild.id))  # ensure raid profile exists

        # Lock all non-staff text channels
        for ch in guild.text_channels:
            ow = ch.overwrites_for(everyone)
            if ow.send_messages is not False:
                try:
                    await ch.set_permissions(everyone, send_messages=False, reason="Raid lockdown")
                except discord.Forbidden:
                    pass

        # Auto-raise verification level
        verification_changed = False
        if cfg.get("raid_auto_verification"):
            try:
                self._saved_verification[guild.id] = guild.verification_level
                if guild.verification_level != discord.VerificationLevel.highest:
                    await guild.edit(
                        verification_level=discord.VerificationLevel.highest,
                        reason="Raid lockdown -- auto-verification bump",
                    )
                    verification_changed = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        embed = discord.Embed(
            title="🚨 RAID LOCKDOWN ACTIVATED",
            description="Suspicious join activity detected. All channels locked.\nUse `/unlock` to restore normal access.",
            color=discord.Color.red(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Triggered",           value="Automatically" if auto else "Manually",              inline=True)
        embed.add_field(name="Active-raid action",  value=(cfg.get("raid_active_action") or "ban").capitalize(), inline=True)
        if current_profile != "raid":
            embed.add_field(name="Profile", value=f"Switched from **{current_profile}** to **raid**", inline=False)
        if verification_changed:
            embed.add_field(name="Verification level", value="Raised to **highest**", inline=False)
        cooldown = cfg.get("raid_lockdown_cooldown_min") or 0
        if cooldown > 0:
            embed.add_field(name="Auto-unlock in", value=f"{cooldown} minute(s)", inline=False)
        await _post_modlog(guild, cfg, embed)

        # Schedule auto-unlock if configured
        if cooldown > 0:
            prior = self._unlock_tasks.get(guild.id)
            if prior and not prior.done():
                prior.cancel()
            self._unlock_tasks[guild.id] = asyncio.create_task(
                self._scheduled_unlock(guild, cfg, cooldown * 60)
            )

    async def _scheduled_unlock(self, guild: discord.Guild, cfg: dict, delay_seconds: int):
        try:
            await asyncio.sleep(delay_seconds)
        except asyncio.CancelledError:
            return
        fresh_cfg = db.get_config(guild.id) or cfg
        if guild.id in self._locked_guilds:
            await self._unlock(guild, fresh_cfg, auto=True)

    async def _unlock(self, guild: discord.Guild, cfg: dict, auto: bool = False):
        self._locked_guilds.discard(guild.id)
        everyone = guild.default_role

        for ch in guild.text_channels:
            ow = ch.overwrites_for(everyone)
            if ow.send_messages is False:
                try:
                    await ch.set_permissions(everyone, send_messages=None, reason="Raid lockdown lifted")
                except discord.Forbidden:
                    pass

        # Restore verification level
        saved = self._saved_verification.pop(guild.id, None)
        verification_restored = False
        if saved is not None:
            try:
                if guild.verification_level != saved:
                    await guild.edit(verification_level=saved, reason="Raid lockdown lifted")
                    verification_restored = True
            except (discord.Forbidden, discord.HTTPException):
                pass

        # Cancel any pending auto-unlock
        prior = self._unlock_tasks.pop(guild.id, None)
        if prior and not prior.done():
            prior.cancel()

        # Restore profile from before raid
        profile_restored = ""
        saved_profile = cfg.get("profile_before_raid") or ""
        if saved_profile and cfg.get("active_profile") == "raid":
            db.upsert_config(guild.id, active_profile=saved_profile, profile_before_raid="")
            profile_restored = saved_profile

        embed = discord.Embed(
            title="✅ Lockdown Lifted",
            description="Server access has been restored.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Lifted", value="Automatically (cooldown)" if auto else "Manually", inline=True)
        if verification_restored:
            embed.add_field(name="Verification level", value="Restored to previous", inline=True)
        if profile_restored:
            embed.add_field(name="Profile", value=f"Restored to **{profile_restored}**", inline=True)
        await _post_modlog(guild, cfg, embed)

    # ── Slash commands ──────────────────────────────────────────────────────
    @app_commands.command(name="lockdown", description="Manually lock all channels.")
    async def lockdown(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._lockdown(interaction.guild, cfg, auto=False)
        await interaction.edit_original_response(content="🔒 Server locked down.")

    @app_commands.command(name="unlock", description="Lift lockdown and restore channel access.")
    async def unlock(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self._unlock(interaction.guild, cfg, auto=False)
        await interaction.edit_original_response(content="✅ Lockdown lifted.")

    @app_commands.command(name="autorole", description="Set a role to auto-assign to new members.")
    @app_commands.describe(role="Role to assign, or leave blank to disable")
    async def autorole(self, interaction: discord.Interaction, role: discord.Role = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administrator only.", ephemeral=True)
        db.upsert_config(interaction.guild_id, auto_role_id=role.id if role else None)
        if role:
            await interaction.response.send_message(f"✅ Auto-role set to {role.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message("✅ Auto-role disabled.", ephemeral=True)

    # ── /raidcfg group ──────────────────────────────────────────────────────
    raidcfg_group = app_commands.Group(
        name="raidcfg",
        description="Configure raid detection & response thresholds.",
    )

    @raidcfg_group.command(name="threshold", description="Set raid detection: N joins in S seconds triggers lockdown.")
    @app_commands.describe(joins="Joins allowed in the window (min 3)", seconds="Window size in seconds (min 5)")
    async def raid_threshold(self, interaction: discord.Interaction, joins: int, seconds: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(
            interaction.guild_id,
            raid_join_count=max(3, joins),
            raid_join_seconds=max(5, seconds),
        )
        await interaction.response.send_message(
            f"✅ Raid threshold: **{max(3, joins)}** joins in **{max(5, seconds)}s**.", ephemeral=True
        )

    @raidcfg_group.command(name="account_age", description="Flag joins from accounts younger than N days. 0 = disabled.")
    @app_commands.describe(days="Minimum account age in days (0 to disable)")
    async def raid_account_age(self, interaction: discord.Interaction, days: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        days = max(0, days)
        db.upsert_config(interaction.guild_id, raid_min_account_age_days=days)
        await interaction.response.send_message(
            f"✅ Account age gate: **{days}d**" + (" (disabled)" if days == 0 else ""),
            ephemeral=True,
        )

    @raidcfg_group.command(name="action", description="What to do with joiners during an active raid lockdown.")
    @app_commands.choices(action=[
        app_commands.Choice(name="kick", value="kick"),
        app_commands.Choice(name="ban",  value="ban"),
    ])
    async def raid_action(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, raid_active_action=action.value)
        await interaction.response.send_message(
            f"✅ During active raid, new joiners will be **{action.value}ed**.", ephemeral=True
        )

    @raidcfg_group.command(name="auto_verification", description="Auto-raise server verification level during lockdown.")
    async def raid_auto_verification(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, raid_auto_verification=1 if enabled else 0)
        await interaction.response.send_message(
            f"✅ Auto-verification bump is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @raidcfg_group.command(name="cooldown", description="Auto-unlock lockdown after N minutes. 0 = manual only.")
    @app_commands.describe(minutes="Minutes until auto-unlock (0 to disable)")
    async def raid_cooldown(self, interaction: discord.Interaction, minutes: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        minutes = max(0, minutes)
        db.upsert_config(interaction.guild_id, raid_lockdown_cooldown_min=minutes)
        await interaction.response.send_message(
            f"✅ Lockdown cooldown: **{minutes}m**" + (" (auto-unlock disabled)" if minutes == 0 else ""),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Raid(bot))
