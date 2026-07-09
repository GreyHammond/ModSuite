"""
namefilter.py -- ModSuite v3.0 Username/Nickname Filtering + Verification Gate

Username/nickname filtering:
- Checks display names on join and on nickname change
- Configurable word list for blocked name patterns
- Optional Unicode confusable normalization (e -> 3, a -> @, etc.)
- Actions: log (flag in modlog), kick, ban

Verification gate:
- New members must react to a verification message to gain a role
- Until verified, they only see the verify channel
- Configurable emoji and target role
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import unicodedata
import re
import json
import database as db


FOOTER = "ModSuite -- Hammond Digital Studios"

# ── Confusable character map ─────────────────────────────────────────────────
# Maps common Unicode lookalikes to their ASCII equivalents.
# This catches l33tspeak, Cyrillic lookalikes, and math/symbol substitutions.
CONFUSABLES = str.maketrans({
    '\u0430': 'a', '\u0410': 'a',  # Cyrillic a/A
    '\u0435': 'e', '\u0415': 'e',  # Cyrillic ie
    '\u043e': 'o', '\u041e': 'o',  # Cyrillic o
    '\u0440': 'p', '\u0420': 'p',  # Cyrillic er
    '\u0441': 'c', '\u0421': 'c',  # Cyrillic es
    '\u0443': 'y', '\u0423': 'y',  # Cyrillic u
    '\u0445': 'x', '\u0425': 'x',  # Cyrillic ha
    '\u0456': 'i', '\u0406': 'i',  # Ukrainian i
    '\u0455': 's', '\u0405': 's',  # Cyrillic dze
    '\u04bb': 'h',                  # Cyrillic shha
    '\u0501': 'd',                  # Cyrillic komi de
    '\uff41': 'a', '\uff42': 'b', '\uff43': 'c', '\uff44': 'd',  # fullwidth
    '\uff45': 'e', '\uff46': 'f', '\uff47': 'g', '\uff48': 'h',
    '\uff49': 'i', '\uff4a': 'j', '\uff4b': 'k', '\uff4c': 'l',
    '\uff4d': 'm', '\uff4e': 'n', '\uff4f': 'o', '\uff50': 'p',
    '\uff51': 'q', '\uff52': 'r', '\uff53': 's', '\uff54': 't',
    '\uff55': 'u', '\uff56': 'v', '\uff57': 'w', '\uff58': 'x',
    '\uff59': 'y', '\uff5a': 'z',
    '@': 'a', '0': 'o', '1': 'l', '3': 'e', '4': 'a', '5': 's',
    '7': 't', '8': 'b', '$': 's', '!': 'i', '|': 'l',
})


def normalize_name(name: str, use_confusables: bool = True) -> str:
    """Normalize a display name for matching against filters."""
    # NFKD decomposition strips accents and normalizes Unicode
    normalized = unicodedata.normalize('NFKD', name)
    # Remove combining characters (accents, diacritics)
    normalized = ''.join(c for c in normalized if not unicodedata.combining(c))
    if use_confusables:
        normalized = normalized.translate(CONFUSABLES)
    return normalized.lower().strip()


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


def _load_json_list(raw) -> list:
    if not raw:
        return []
    try:
        val = json.loads(raw) if isinstance(raw, str) else raw
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


class NameFilter(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Name check on join ───────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = db.get_config(member.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return
        if cfg.get("name_filter_enabled"):
            await self._check_name(member, member.display_name, cfg, event="join")

        # ── Verification gate: assign unverified state ───────────────────────
        if cfg.get("verify_gate_enabled"):
            # Don't gate bots or staff
            if member.bot:
                return
            gate_role_id = cfg.get("verify_gate_role_id")
            if not gate_role_id:
                return
            # The gate role is the role they GET after verifying.
            # Until they verify, they simply lack that role.
            # Log to modlog that they need to verify
            embed = discord.Embed(
                title="🚪 Verification pending",
                description=f"{member.mention} joined and needs to verify.",
                color=discord.Color.gold(),
                timestamp=datetime.utcnow(),
            )
            gate_ch = cfg.get("verify_gate_channel_id")
            if gate_ch:
                embed.add_field(name="Verify in", value=f"<#{gate_ch}>", inline=True)
            await _post_modlog(member.guild, cfg, embed)

    # ── Name check on nickname change ────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.display_name == after.display_name:
            return
        cfg = db.get_config(after.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return
        if not cfg.get("name_filter_enabled"):
            return
        if _is_staff(after, cfg):
            return
        await self._check_name(after, after.display_name, cfg, event="nickname change")

    # ── Verification gate: reaction listener ─────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        cfg = db.get_config(guild.id)
        if cfg is None or not cfg.get("verify_gate_enabled"):
            return

        gate_msg_id = cfg.get("verify_gate_message_id")
        if not gate_msg_id or payload.message_id != gate_msg_id:
            return

        gate_emoji = cfg.get("verify_gate_emoji") or "\u2705"
        if str(payload.emoji) != gate_emoji:
            return

        gate_role_id = cfg.get("verify_gate_role_id")
        if not gate_role_id:
            return

        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        role = guild.get_role(gate_role_id)
        if role is None:
            return

        if role in member.roles:
            return  # already verified

        try:
            await member.add_roles(role, reason="Verification gate: reacted to verify message")
        except discord.Forbidden:
            return

        db.add_mod_log(
            guild_id=str(guild.id),
            action="VERIFIED_GATE",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(self.bot.user.id),
            actor_username="ModSuite (auto)",
            reason="Passed verification gate (reaction)",
        )

        embed = discord.Embed(
            title="✅ Member Verified",
            description=f"{member.mention} passed the verification gate.",
            color=discord.Color.green(),
            timestamp=datetime.utcnow(),
        )
        await _post_modlog(guild, cfg, embed)

    # ── Core name checking logic ─────────────────────────────────────────────
    async def _check_name(self, member: discord.Member, name: str, cfg: dict, event: str = ""):
        if _is_staff(member, cfg):
            return

        blocked_words = _load_json_list(cfg.get("name_filter_words"))
        if not blocked_words:
            return

        use_confusables = bool(cfg.get("name_filter_confusables", 1))
        normalized = normalize_name(name, use_confusables)
        # Also check the raw lowercase name
        raw_lower = name.lower()

        matched_word = None
        for word in blocked_words:
            w = word.lower().strip()
            if not w:
                continue
            # Check both normalized and raw
            if w in normalized or w in raw_lower:
                matched_word = word
                break

        if matched_word is None:
            return

        action = (cfg.get("name_filter_action") or "log").lower()

        # Log to mod_logs
        db.add_mod_log(
            guild_id=str(member.guild.id),
            action="NAME_FILTER",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(self.bot.user.id) if self.bot.user else "",
            actor_username="AutoMod",
            reason=f"Blocked name pattern '{matched_word}' in '{name}' ({event})",
        )

        embed = discord.Embed(
            title="🚫 Name Filter Triggered",
            color=discord.Color.red(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Name", value=name, inline=True)
        embed.add_field(name="Matched", value=f"`{matched_word}`", inline=True)
        embed.add_field(name="Event", value=event, inline=True)
        if use_confusables:
            embed.add_field(name="Normalized", value=normalized, inline=True)
        embed.add_field(name="Action", value=action, inline=True)
        await _post_modlog(member.guild, cfg, embed)

        if action == "kick":
            try:
                await member.kick(reason=f"AutoMod name filter: matched '{matched_word}'")
            except discord.Forbidden:
                pass
        elif action == "ban":
            try:
                await member.ban(reason=f"AutoMod name filter: matched '{matched_word}'",
                                 delete_message_days=1)
            except discord.Forbidden:
                pass

    # ── Slash commands ────────────────────────────────────────────────────────

    namefilter_group = app_commands.Group(
        name="namefilter",
        description="Configure username/nickname filtering.",
    )

    @namefilter_group.command(name="toggle", description="Turn name filtering on or off.")
    @app_commands.describe(enabled="Enable or disable name filtering")
    async def toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, name_filter_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"Name filter is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @namefilter_group.command(name="action", description="Set what happens when a blocked name is detected.")
    @app_commands.choices(action=[
        app_commands.Choice(name="Log only (flag in mod-log)", value="log"),
        app_commands.Choice(name="Kick the member",            value="kick"),
        app_commands.Choice(name="Ban the member",             value="ban"),
    ])
    async def action(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, name_filter_action=action.value)
        await interaction.response.send_message(
            f"Name filter action set to **{action.name}**.", ephemeral=True
        )

    @namefilter_group.command(name="confusables", description="Toggle Unicode confusable character normalization.")
    @app_commands.describe(enabled="Normalize lookalike characters before checking")
    async def confusables(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, name_filter_confusables=1 if enabled else 0)
        await interaction.response.send_message(
            f"Confusable normalization is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @namefilter_group.command(name="add", description="Add a word to the blocked name list.")
    @app_commands.describe(words="Words to block, separated by commas")
    async def add_words(self, interaction: discord.Interaction, words: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        current = _load_json_list(cfg.get("name_filter_words"))
        new = [w.strip() for w in words.split(",") if w.strip()]
        added = [w for w in new if w.lower() not in [x.lower() for x in current]]
        current.extend(added)
        db.upsert_config(interaction.guild_id, name_filter_words=json.dumps(current))
        await interaction.response.send_message(
            f"Added **{len(added)}** word(s) to name filter. Total: **{len(current)}**.", ephemeral=True
        )

    @namefilter_group.command(name="remove", description="Remove a word from the blocked name list.")
    @app_commands.describe(words="Words to unblock, separated by commas")
    async def remove_words(self, interaction: discord.Interaction, words: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        current = _load_json_list(cfg.get("name_filter_words"))
        to_remove = {w.strip().lower() for w in words.split(",") if w.strip()}
        updated = [w for w in current if w.lower() not in to_remove]
        db.upsert_config(interaction.guild_id, name_filter_words=json.dumps(updated))
        await interaction.response.send_message(
            f"Removed. List now has **{len(updated)}** word(s).", ephemeral=True
        )

    @namefilter_group.command(name="list", description="View all blocked name words.")
    async def list_words(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id) or {}
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)
        words = _load_json_list(cfg.get("name_filter_words"))
        embed = discord.Embed(
            title="Name Filter -- Blocked Words",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(
            name=f"Status",
            value=(
                f"Filter: **{'on' if cfg.get('name_filter_enabled') else 'off'}**\n"
                f"Action: **{cfg.get('name_filter_action', 'log')}**\n"
                f"Confusables: **{'on' if cfg.get('name_filter_confusables', 1) else 'off'}**"
            ),
            inline=False,
        )
        embed.add_field(
            name=f"Blocked words ({len(words)})",
            value=", ".join(f"`{w}`" for w in words[:30]) or "*(empty)*",
            inline=False,
        )
        embed.set_footer(text=FOOTER)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Verification gate commands ────────────────────────────────────────────

    verify_gate_group = app_commands.Group(
        name="verifygate",
        description="Configure the verification gate for new members.",
    )

    @verify_gate_group.command(name="toggle", description="Turn the verification gate on or off.")
    @app_commands.describe(enabled="Enable or disable the verification gate")
    async def gate_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, verify_gate_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"Verification gate is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @verify_gate_group.command(name="role", description="Set the role granted when a member verifies.")
    @app_commands.describe(role="Role to grant on verification")
    async def gate_role(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, verify_gate_role_id=role.id)
        await interaction.response.send_message(
            f"Verification gate role set to {role.mention}.", ephemeral=True
        )

    @verify_gate_group.command(name="channel", description="Set the channel where the verification message lives.")
    @app_commands.describe(channel="Channel for the verify message")
    async def gate_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, verify_gate_channel_id=channel.id)
        await interaction.response.send_message(
            f"Verification channel set to {channel.mention}.", ephemeral=True
        )

    @verify_gate_group.command(name="post", description="Post the verification message in the configured channel.")
    async def gate_post(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        ch_id = cfg.get("verify_gate_channel_id")
        if not ch_id:
            return await interaction.response.send_message(
                "Set a verification channel first with `/verifygate channel`.", ephemeral=True
            )
        role_id = cfg.get("verify_gate_role_id")
        if not role_id:
            return await interaction.response.send_message(
                "Set a verification role first with `/verifygate role`.", ephemeral=True
            )

        channel = interaction.guild.get_channel(ch_id)
        if channel is None:
            return await interaction.response.send_message("Verification channel not found.", ephemeral=True)

        emoji = cfg.get("verify_gate_emoji") or "\u2705"

        embed = discord.Embed(
            title="Verification Required",
            description=(
                f"Welcome to **{interaction.guild.name}**!\n\n"
                f"React with {emoji} below to verify and gain access to the server."
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text=FOOTER)

        await interaction.response.defer(ephemeral=True)
        msg = await channel.send(embed=embed)
        try:
            await msg.add_reaction(emoji)
        except discord.HTTPException:
            pass

        db.upsert_config(interaction.guild_id, verify_gate_message_id=msg.id)
        await interaction.edit_original_response(
            content=f"Verification message posted in {channel.mention}."
        )

    @verify_gate_group.command(name="status", description="View verification gate settings.")
    async def gate_status(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id) or {}
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        def yn(v): return "on" if v else "off"
        def fmt_id(v, prefix="<@&"): return f"{prefix}{v}>" if v else "*(not set)*"

        embed = discord.Embed(
            title="Verification Gate",
            color=discord.Color.green() if cfg.get("verify_gate_enabled") else discord.Color.greyple(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Status", value=f"**{yn(cfg.get('verify_gate_enabled'))}**", inline=True)
        embed.add_field(name="Role", value=fmt_id(cfg.get("verify_gate_role_id")), inline=True)
        embed.add_field(name="Channel", value=fmt_id(cfg.get("verify_gate_channel_id"), "<#"), inline=True)
        embed.add_field(name="Emoji", value=cfg.get("verify_gate_emoji") or "\u2705", inline=True)
        embed.add_field(name="Message ID", value=str(cfg.get("verify_gate_message_id") or "*(not posted)*"), inline=True)
        embed.set_footer(text=FOOTER)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(NameFilter(bot))
