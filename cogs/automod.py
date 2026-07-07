import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlparse
import json
import re
import database as db


# ── Helpers ────────────────────────────────────────────────────────────────────

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


def _load_json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _dump_json_list(items: list) -> str:
    return json.dumps(items)


# ── Regex patterns ─────────────────────────────────────────────────────────────

URL_PATTERN = re.compile(
    r"https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[^\s]*",
    re.IGNORECASE,
)

INVITE_PATTERN = re.compile(
    r"(?:https?://)?(?:www\.)?(?:discord\.gg|discord\.com/invite|discordapp\.com/invite)/[\w-]+",
    re.IGNORECASE,
)

# Matches custom Discord emoji <:name:id> / <a:name:id> and common Unicode emoji ranges
EMOJI_PATTERN = re.compile(
    r"<a?:\w+:\d+>|["
    r"\U0001F600-\U0001F64F"
    r"\U0001F300-\U0001F5FF"
    r"\U0001F680-\U0001F6FF"
    r"\U0001F1E0-\U0001F1FF"
    r"\U00002702-\U000027B0"
    r"\U0001F900-\U0001F9FF"
    r"\U0001FA00-\U0001FA6F"
    r"\U0001FA70-\U0001FAFF"
    r"\U00002600-\U000026FF"
    r"]",
    re.UNICODE,
)


# ── Per-user tracker ───────────────────────────────────────────────────────────

@dataclass
class UserTracker:
    """Tracks recent message history for spam heuristics."""
    timestamps: deque = field(default_factory=deque)   # deque[float]
    contents:   deque = field(default_factory=deque)   # deque[str]


# ── Cog ────────────────────────────────────────────────────────────────────────

class AutoMod(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # guild_id -> user_id -> UserTracker
        self._trackers: dict[int, dict[int, UserTracker]] = {}

    # ── Main message listener ────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Bail early on obvious non-targets
        if message.author.bot or message.guild is None:
            return
        if not isinstance(message.author, discord.Member):
            return

        cfg = db.get_config(message.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return

        # Staff and immune roles bypass all automod
        if _is_staff(message.author, cfg):
            return
        immune_roles = set(_load_json_list(cfg.get("automod_immune_roles")))
        if any(str(r.id) in {str(i) for i in immune_roles} for r in message.author.roles):
            return

        # Run each filter — first one to act stops the chain to avoid double-punishing
        if cfg.get("invite_filter_enabled") and await self._check_invites(message, cfg):
            return
        if cfg.get("link_filter_enabled") and await self._check_links(message, cfg):
            return
        if cfg.get("spam_enabled") and await self._check_spam(message, cfg):
            return

    # ── Invite filter ────────────────────────────────────────────────────────
    async def _check_invites(self, message: discord.Message, cfg: dict) -> bool:
        if not INVITE_PATTERN.search(message.content):
            return False
        action = (cfg.get("invite_action") or "delete").lower()
        await self._apply_action(
            message, cfg, action,
            reason="Posted a Discord invite link",
            trigger="Invite link",
            mute_minutes=cfg.get("spam_mute_minutes") or 10,
        )
        return True

    # ── Link filter ──────────────────────────────────────────────────────────
    async def _check_links(self, message: discord.Message, cfg: dict) -> bool:
        urls = URL_PATTERN.findall(message.content)
        if not urls:
            return False

        # Channel bypass
        bypass_channels = {int(x) for x in _load_json_list(cfg.get("link_bypass_channels")) if str(x).isdigit()}
        if message.channel.id in bypass_channels:
            return False

        # Role bypass
        bypass_roles = {int(x) for x in _load_json_list(cfg.get("link_bypass_roles")) if str(x).isdigit()}
        if any(r.id in bypass_roles for r in message.author.roles):
            return False

        mode = (cfg.get("link_mode") or "whitelist").lower()
        whitelist = {d.lower().strip() for d in _load_json_list(cfg.get("link_whitelist"))}
        blacklist = {d.lower().strip() for d in _load_json_list(cfg.get("link_blacklist"))}

        offender = None
        for url in urls:
            try:
                host = urlparse(url).netloc.lower()
            except ValueError:
                continue
            if not host:
                continue
            # Strip leading www.
            if host.startswith("www."):
                host = host[4:]

            if mode == "whitelist":
                if not self._domain_in_set(host, whitelist):
                    offender = host
                    break
            else:  # blacklist
                if self._domain_in_set(host, blacklist):
                    offender = host
                    break

        if offender is None:
            return False

        action = (cfg.get("link_action") or "delete").lower()
        await self._apply_action(
            message, cfg, action,
            reason=f"Posted disallowed link ({offender})",
            trigger=f"Link filter ({mode}) — {offender}",
            mute_minutes=cfg.get("spam_mute_minutes") or 10,
        )
        return True

    @staticmethod
    def _domain_in_set(host: str, domain_set: set[str]) -> bool:
        """Match host against a domain set, including subdomains."""
        if host in domain_set:
            return True
        # Subdomain match: 'foo.example.com' matches 'example.com'
        parts = host.split(".")
        for i in range(1, len(parts)):
            if ".".join(parts[i:]) in domain_set:
                return True
        return False

    # ── Spam detection ───────────────────────────────────────────────────────
    async def _check_spam(self, message: discord.Message, cfg: dict) -> bool:
        # Per-message checks first (mentions, emojis) — cheap
        mention_limit = cfg.get("spam_mention_limit") or 5
        emoji_limit   = cfg.get("spam_emoji_limit")   or 15

        mention_count = len(message.mentions) + len(message.role_mentions)
        if mention_count >= mention_limit:
            await self._apply_spam_action(
                message, cfg, f"Mass mentions ({mention_count})", "Mention spam"
            )
            return True

        emoji_count = len(EMOJI_PATTERN.findall(message.content))
        if emoji_count >= emoji_limit:
            await self._apply_spam_action(
                message, cfg, f"Emoji flood ({emoji_count})", "Emoji spam"
            )
            return True

        # Velocity + duplicate check — needs the tracker
        gid = message.guild.id
        uid = message.author.id
        tracker = self._trackers.setdefault(gid, {}).setdefault(uid, UserTracker())

        now       = datetime.now(timezone.utc).timestamp()
        window    = cfg.get("spam_window_sec") or 8
        msg_limit = cfg.get("spam_msg_limit")  or 5
        dup_limit = cfg.get("spam_dup_limit")  or 3

        tracker.timestamps.append(now)
        tracker.contents.append(message.content.strip().lower())

        # Prune anything outside the window
        cutoff = now - window
        while tracker.timestamps and tracker.timestamps[0] < cutoff:
            tracker.timestamps.popleft()
            tracker.contents.popleft()

        # Velocity
        if len(tracker.timestamps) >= msg_limit:
            await self._apply_spam_action(
                message, cfg,
                f"Sent {len(tracker.timestamps)} messages in {window}s",
                "Message velocity",
            )
            tracker.timestamps.clear()
            tracker.contents.clear()
            return True

        # Duplicate messages
        current = message.content.strip().lower()
        if current and tracker.contents.count(current) >= dup_limit:
            await self._apply_spam_action(
                message, cfg,
                f"Duplicate message ×{tracker.contents.count(current)}",
                "Duplicate spam",
            )
            tracker.timestamps.clear()
            tracker.contents.clear()
            return True

        return False

    async def _apply_spam_action(self, message: discord.Message, cfg: dict, reason: str, trigger: str):
        action = (cfg.get("spam_action") or "mute").lower()
        await self._apply_action(
            message, cfg, action,
            reason=reason,
            trigger=f"Spam — {trigger}",
            mute_minutes=cfg.get("spam_mute_minutes") or 10,
        )

    # ── Shared action executor ───────────────────────────────────────────────
    async def _apply_action(
        self,
        message: discord.Message,
        cfg: dict,
        action: str,
        reason: str,
        trigger: str,
        mute_minutes: int,
    ):
        member = message.author
        guild  = message.guild

        # Always try to delete the offending message
        try:
            await message.delete()
            deleted = True
        except (discord.NotFound, discord.Forbidden):
            deleted = False

        acted = "Deleted message"

        if action == "mute":
            until = datetime.now(timezone.utc) + timedelta(minutes=mute_minutes)
            try:
                await member.timeout(until, reason=f"AutoMod: {reason}")
                acted = f"Deleted + muted {mute_minutes}m"
            except discord.Forbidden:
                acted = "Deleted message (mute failed: bot lacks Moderate Members)"
            except discord.HTTPException:
                acted = "Deleted message (mute failed)"

        elif action == "kick":
            try:
                await member.kick(reason=f"AutoMod: {reason}")
                acted = "Deleted + kicked"
            except discord.Forbidden:
                acted = "Deleted message (kick failed: bot lacks Kick Members)"
            except discord.HTTPException:
                acted = "Deleted message (kick failed)"

        elif action == "ban":
            try:
                await member.ban(reason=f"AutoMod: {reason}", delete_message_days=1)
                acted = "Deleted + banned"
            except discord.Forbidden:
                acted = "Deleted message (ban failed: bot lacks Ban Members)"
            except discord.HTTPException:
                acted = "Deleted message (ban failed)"

        # else: action == "delete" — nothing else to do

        # Modlog embed
        embed = discord.Embed(
            title=f"🛡️ AutoMod — {trigger}",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="User",    value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention,             inline=True)
        embed.add_field(name="Action",  value=acted,                               inline=False)
        embed.add_field(name="Reason",  value=reason,                              inline=False)
        if message.content:
            snippet = message.content if len(message.content) <= 500 else message.content[:497] + "…"
            embed.add_field(name="Content", value=f"```{snippet}```", inline=False)
        if not deleted:
            embed.set_footer(text="⚠️ Message could not be deleted (missing Manage Messages?)")

        await _post_modlog(guild, cfg, embed)

    # ── /automod command group ───────────────────────────────────────────────
    automod_group = app_commands.Group(
        name="automod",
        description="Configure AutoMod filters and thresholds",
    )

    # ── Status ───────────────────────────────────────────────────────────────
    @automod_group.command(name="status", description="Show current AutoMod settings.")
    async def status(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id) or {}
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        def yn(v): return "🟢 On" if v else "🔴 Off"

        embed = discord.Embed(
            title="🛡️ AutoMod Status",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        # Spam
        embed.add_field(
            name=f"Spam {yn(cfg.get('spam_enabled'))}",
            value=(
                f"Threshold: **{cfg.get('spam_msg_limit', 5)}** msgs / **{cfg.get('spam_window_sec', 8)}s**\n"
                f"Duplicates: **{cfg.get('spam_dup_limit', 3)}**\n"
                f"Mentions: **{cfg.get('spam_mention_limit', 5)}**  ·  Emojis: **{cfg.get('spam_emoji_limit', 15)}**\n"
                f"Action: **{cfg.get('spam_action', 'mute')}**  ·  Mute: **{cfg.get('spam_mute_minutes', 10)}m**"
            ),
            inline=False,
        )
        # Links
        wl = _load_json_list(cfg.get("link_whitelist"))
        bl = _load_json_list(cfg.get("link_blacklist"))
        embed.add_field(
            name=f"Links {yn(cfg.get('link_filter_enabled'))}",
            value=(
                f"Mode: **{cfg.get('link_mode', 'whitelist')}**  ·  Action: **{cfg.get('link_action', 'delete')}**\n"
                f"Whitelist: **{len(wl)}** domains  ·  Blacklist: **{len(bl)}** domains\n"
                f"Bypass roles: **{len(_load_json_list(cfg.get('link_bypass_roles')))}**  ·  "
                f"Bypass channels: **{len(_load_json_list(cfg.get('link_bypass_channels')))}**"
            ),
            inline=False,
        )
        # Invites
        embed.add_field(
            name=f"Invites {yn(cfg.get('invite_filter_enabled'))}",
            value=f"Action: **{cfg.get('invite_action', 'delete')}**",
            inline=False,
        )
        # Raid
        embed.add_field(
            name="Raid",
            value=(
                f"Join threshold: **{cfg.get('raid_join_count', 10)}** in **{cfg.get('raid_join_seconds', 10)}s**\n"
                f"Min account age: **{cfg.get('raid_min_account_age_days', 0)}d** (0 = off)\n"
                f"During raid: **{cfg.get('raid_active_action', 'kick')}** joiners  ·  "
                f"Auto-verification: {yn(cfg.get('raid_auto_verification'))}\n"
                f"Auto-unlock after: **{cfg.get('raid_lockdown_cooldown_min', 5)}m** (0 = manual only)"
            ),
            inline=False,
        )
        # Immune
        immune = _load_json_list(cfg.get("automod_immune_roles"))
        embed.add_field(
            name="Immune roles",
            value=(", ".join(f"<@&{rid}>" for rid in immune) if immune else "*(none)*"),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Spam ─────────────────────────────────────────────────────────────────
    @automod_group.command(name="spam", description="Turn spam detection on or off.")
    @app_commands.describe(enabled="Enable or disable spam detection")
    async def spam_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, spam_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"✅ Spam detection is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @automod_group.command(name="spam_threshold", description="Set spam velocity: N messages in S seconds triggers action.")
    @app_commands.describe(messages="Messages allowed in the window (min 2)", seconds="Window size in seconds (min 3)")
    async def spam_threshold(self, interaction: discord.Interaction, messages: int, seconds: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(
            interaction.guild_id,
            spam_msg_limit=max(2, messages),
            spam_window_sec=max(3, seconds),
        )
        await interaction.response.send_message(
            f"✅ Spam threshold: **{max(2, messages)}** msgs in **{max(3, seconds)}s**.", ephemeral=True
        )

    @automod_group.command(name="spam_action", description="Set what happens when spam is detected.")
    @app_commands.choices(action=[
        app_commands.Choice(name="delete only", value="delete"),
        app_commands.Choice(name="delete + mute (timeout)", value="mute"),
        app_commands.Choice(name="delete + kick",           value="kick"),
        app_commands.Choice(name="delete + ban",            value="ban"),
    ])
    async def spam_action(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, spam_action=action.value)
        await interaction.response.send_message(
            f"✅ Spam action set to **{action.name}**.", ephemeral=True
        )

    # ── Links ────────────────────────────────────────────────────────────────
    @automod_group.command(name="links", description="Turn link filtering on or off.")
    @app_commands.describe(enabled="Enable or disable link filtering")
    async def links_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, link_filter_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"✅ Link filter is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @automod_group.command(name="link_mode", description="Whitelist blocks all except approved. Blacklist allows all except blocked.")
    @app_commands.choices(mode=[
        app_commands.Choice(name="whitelist (strict)", value="whitelist"),
        app_commands.Choice(name="blacklist (permissive)", value="blacklist"),
    ])
    async def link_mode(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, link_mode=mode.value)
        await interaction.response.send_message(
            f"✅ Link mode set to **{mode.name}**.", ephemeral=True
        )

    @automod_group.command(name="link_add", description="Add a domain to whitelist or blacklist.")
    @app_commands.describe(list_type="Which list to add to", domain="Domain (e.g. example.com)")
    @app_commands.choices(list_type=[
        app_commands.Choice(name="whitelist", value="whitelist"),
        app_commands.Choice(name="blacklist", value="blacklist"),
    ])
    async def link_add(self, interaction: discord.Interaction, list_type: app_commands.Choice[str], domain: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        domain = domain.lower().strip().removeprefix("http://").removeprefix("https://").removeprefix("www.").split("/")[0]
        if not domain or "." not in domain:
            return await interaction.response.send_message("❌ Invalid domain.", ephemeral=True)
        col = "link_whitelist" if list_type.value == "whitelist" else "link_blacklist"
        cfg = db.get_config(interaction.guild_id) or {}
        current = _load_json_list(cfg.get(col))
        if domain in current:
            return await interaction.response.send_message(
                f"ℹ️ `{domain}` is already on the {list_type.value}.", ephemeral=True
            )
        current.append(domain)
        db.upsert_config(interaction.guild_id, **{col: _dump_json_list(current)})
        await interaction.response.send_message(
            f"✅ Added `{domain}` to the {list_type.value}.", ephemeral=True
        )

    @automod_group.command(name="link_remove", description="Remove a domain from whitelist or blacklist.")
    @app_commands.describe(list_type="Which list to remove from", domain="Domain to remove")
    @app_commands.choices(list_type=[
        app_commands.Choice(name="whitelist", value="whitelist"),
        app_commands.Choice(name="blacklist", value="blacklist"),
    ])
    async def link_remove(self, interaction: discord.Interaction, list_type: app_commands.Choice[str], domain: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        domain = domain.lower().strip()
        col = "link_whitelist" if list_type.value == "whitelist" else "link_blacklist"
        cfg = db.get_config(interaction.guild_id) or {}
        current = _load_json_list(cfg.get(col))
        if domain not in current:
            return await interaction.response.send_message(
                f"ℹ️ `{domain}` isn't on the {list_type.value}.", ephemeral=True
            )
        current.remove(domain)
        db.upsert_config(interaction.guild_id, **{col: _dump_json_list(current)})
        await interaction.response.send_message(
            f"✅ Removed `{domain}` from the {list_type.value}.", ephemeral=True
        )

    @automod_group.command(name="link_action", description="Set what happens when a disallowed link is posted.")
    @app_commands.choices(action=[
        app_commands.Choice(name="delete only",             value="delete"),
        app_commands.Choice(name="delete + mute (timeout)", value="mute"),
        app_commands.Choice(name="delete + kick",           value="kick"),
        app_commands.Choice(name="delete + ban",            value="ban"),
    ])
    async def link_action(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, link_action=action.value)
        await interaction.response.send_message(
            f"✅ Link action set to **{action.name}**.", ephemeral=True
        )

    @automod_group.command(name="link_bypass_channel", description="Toggle a channel as bypassing the link filter.")
    async def link_bypass_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        current = [int(x) for x in _load_json_list(cfg.get("link_bypass_channels")) if str(x).isdigit()]
        if channel.id in current:
            current.remove(channel.id)
            msg = f"✅ {channel.mention} no longer bypasses the link filter."
        else:
            current.append(channel.id)
            msg = f"✅ {channel.mention} now bypasses the link filter."
        db.upsert_config(interaction.guild_id, link_bypass_channels=_dump_json_list(current))
        await interaction.response.send_message(msg, ephemeral=True)

    @automod_group.command(name="link_bypass_role", description="Toggle a role as bypassing the link filter.")
    async def link_bypass_role(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        current = [int(x) for x in _load_json_list(cfg.get("link_bypass_roles")) if str(x).isdigit()]
        if role.id in current:
            current.remove(role.id)
            msg = f"✅ {role.mention} no longer bypasses the link filter."
        else:
            current.append(role.id)
            msg = f"✅ {role.mention} now bypasses the link filter."
        db.upsert_config(interaction.guild_id, link_bypass_roles=_dump_json_list(current))
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Invites ──────────────────────────────────────────────────────────────
    @automod_group.command(name="invites", description="Turn Discord invite-link filtering on or off.")
    async def invites_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, invite_filter_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"✅ Invite filter is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @automod_group.command(name="invite_action", description="Set what happens when a Discord invite is posted.")
    @app_commands.choices(action=[
        app_commands.Choice(name="delete only",             value="delete"),
        app_commands.Choice(name="delete + mute (timeout)", value="mute"),
        app_commands.Choice(name="delete + kick",           value="kick"),
        app_commands.Choice(name="delete + ban",            value="ban"),
    ])
    async def invite_action(self, interaction: discord.Interaction, action: app_commands.Choice[str]):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, invite_action=action.value)
        await interaction.response.send_message(
            f"✅ Invite action set to **{action.name}**.", ephemeral=True
        )

    # ── Immune ───────────────────────────────────────────────────────────────
    @automod_group.command(name="immune", description="Toggle a role as immune to all AutoMod filters.")
    async def immune(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Manage Server required.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        current = [int(x) for x in _load_json_list(cfg.get("automod_immune_roles")) if str(x).isdigit()]
        if role.id in current:
            current.remove(role.id)
            msg = f"✅ {role.mention} is no longer immune to AutoMod."
        else:
            current.append(role.id)
            msg = f"✅ {role.mention} is now immune to AutoMod."
        db.upsert_config(interaction.guild_id, automod_immune_roles=_dump_json_list(current))
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
