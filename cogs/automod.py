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
from utils import get_bot_message, _fmt


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


def _append_domain_fields(embed: "discord.Embed", label: str, domains: list) -> None:
    """
    Append one or more embed fields listing every domain in `domains`.
    Handles Discord's 1024-char per-field limit by splitting into multiple
    fields ("Whitelist", "Whitelist (cont.)", ...) if needed.
    """
    if not domains:
        embed.add_field(name=f"{label} (0)", value="*(empty)*", inline=False)
        return

    # Build "chunks" that each fit within 1024 characters.
    chunks: list[list[str]] = [[]]
    running_len = 0
    for d in domains:
        piece = f"`{d}`\n"
        if running_len + len(piece) > 1000:  # leave a small margin
            chunks.append([])
            running_len = 0
        chunks[-1].append(piece)
        running_len += len(piece)

    total = len(domains)
    for i, chunk in enumerate(chunks):
        name = f"{label} ({total})" if i == 0 else f"{label} (cont. {i + 1})"
        embed.add_field(name=name, value="".join(chunk) or "*(empty)*", inline=False)


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
        # (guild_id, channel_id, user_id) -> last_message_timestamp
        self._slowmode_last: dict[tuple[int, int, int], float] = {}

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

        # Apply active profile overrides to config
        cfg = db.get_effective_config(message.guild.id)

        # Staff and immune roles bypass all automod
        if _is_staff(message.author, cfg):
            return
        immune_roles = set(_load_json_list(cfg.get("automod_immune_roles")))
        if any(str(r.id) in {str(i) for i in immune_roles} for r in message.author.roles):
            return

        # Run each filter -- first one to act stops the chain to avoid double-punishing
        if cfg.get("invite_filter_enabled") and await self._check_invites(message, cfg):
            return
        if cfg.get("link_filter_enabled") and await self._check_links(message, cfg):
            return
        if cfg.get("antiphish_enabled", 1) and await self._check_phishing(message, cfg):
            return
        if cfg.get("wordlist_enabled") and await self._check_word_lists(message, cfg):
            return
        if await self._check_message_length(message, cfg):
            return
        if cfg.get("allcaps_enabled") and await self._check_allcaps(message, cfg):
            return
        if cfg.get("slowmode_enabled") and await self._check_slowmode(message, cfg):
            return
        if cfg.get("spam_enabled") and await self._check_spam(message, cfg):
            return

    # ── Invite filter ────────────────────────────────────────────────────────
    async def _check_invites(self, message: discord.Message, cfg: dict) -> bool:
        if not INVITE_PATTERN.search(message.content):
            return False
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        from .violations import record_violation
        await record_violation(
            message.guild, message.author,
            violation_name="invite",
            trigger_detail="Posted a Discord invite link",
            bot=self.bot,
            message=message,
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

        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        from .violations import record_violation
        await record_violation(
            message.guild, message.author,
            violation_name="link",
            trigger_detail=f"Disallowed link ({offender}) -- mode: {mode}",
            bot=self.bot,
            message=message,
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

    # ── Word list filter ────────────────────────────────────────────────────
    async def _check_word_lists(self, message: discord.Message, cfg: dict) -> bool:
        word_lists = db.get_all_word_lists(str(message.guild.id))
        if not word_lists:
            return False
        content_lower = message.content.lower()
        # Split into words for whole-word matching
        import re as _re
        content_words = set(_re.findall(r'\w+', content_lower))
        for wl in word_lists:
            for word in wl.get("words", []):
                w = word.lower().strip()
                if not w:
                    continue
                # Multi-word phrases: substring match. Single words: whole-word match.
                if " " in w:
                    if w in content_lower:
                        try:
                            await message.delete()
                        except (discord.NotFound, discord.Forbidden):
                            pass
                        from .violations import record_violation
                        await record_violation(
                            message.guild, message.author,
                            violation_name="word_filter",
                            trigger_detail=f"Matched '{word}' in list '{wl['list_name']}'",
                            bot=self.bot,
                            message=message,
                        )
                        return True
                else:
                    if w in content_words:
                        try:
                            await message.delete()
                        except (discord.NotFound, discord.Forbidden):
                            pass
                        from .violations import record_violation
                        await record_violation(
                            message.guild, message.author,
                            violation_name="word_filter",
                            trigger_detail=f"Matched '{word}' in list '{wl['list_name']}'",
                            bot=self.bot,
                            message=message,
                        )
                        return True
        return False

    # ── Anti-phishing link scan ──────────────────────────────────────────────
    async def _check_phishing(self, message: discord.Message, cfg: dict) -> bool:
        """Check all URLs against the SinkingYachts phishing database."""
        urls = URL_PATTERN.findall(message.content)
        if not urls:
            return False

        # Deduplicate hosts to avoid redundant API calls
        hosts = set()
        for url in urls:
            try:
                host = urlparse(url).netloc.lower()
            except ValueError:
                continue
            if not host:
                continue
            if host.startswith("www."):
                host = host[4:]
            hosts.add(host)

        if not hosts:
            return False

        import aiohttp
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as session:
                for host in hosts:
                    try:
                        async with session.get(
                            f"https://phish.sinking.yachts/v2/check/{host}",
                            headers={"Accept": "application/json"},
                        ) as resp:
                            if resp.status == 200:
                                result = await resp.json()
                                if result is True:
                                    try:
                                        await message.delete()
                                    except (discord.NotFound, discord.Forbidden):
                                        pass
                                    from .violations import record_violation
                                    await record_violation(
                                        message.guild, message.author,
                                        violation_name="phishing",
                                        trigger_detail=f"Phishing domain detected: {host}",
                                        bot=self.bot,
                                        message=message,
                                    )
                                    return True
                    except Exception:
                        pass  # individual host check failure; try next
        except Exception:
            # Session creation failure -- fail open
            pass

        return False

    # ── Message length filter ────────────────────────────────────────────────
    async def _check_message_length(self, message: discord.Message, cfg: dict) -> bool:
        max_len = cfg.get("max_message_length") or 0
        min_len = cfg.get("min_message_length") or 0
        content_len = len(message.content)

        if max_len > 0 and content_len > max_len:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            from .violations import record_violation
            await record_violation(
                message.guild, message.author,
                violation_name="message_length",
                trigger_detail=f"Message too long ({content_len} chars, max {max_len})",
                bot=self.bot,
                message=message,
            )
            return True

        if min_len > 0 and content_len < min_len and content_len > 0:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            from .violations import record_violation
            await record_violation(
                message.guild, message.author,
                violation_name="message_length",
                trigger_detail=f"Message too short ({content_len} chars, min {min_len})",
                bot=self.bot,
                message=message,
            )
            return True

        return False

    # ── All-caps filter ──────────────────────────────────────────────────────
    async def _check_allcaps(self, message: discord.Message, cfg: dict) -> bool:
        threshold = cfg.get("allcaps_threshold") or 70
        min_len = cfg.get("allcaps_min_length") or 10
        text = message.content

        # Only check messages with enough alpha characters
        alpha_chars = [c for c in text if c.isalpha()]
        if len(alpha_chars) < min_len:
            return False

        upper_count = sum(1 for c in alpha_chars if c.isupper())
        pct = (upper_count / len(alpha_chars)) * 100

        if pct >= threshold:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            from .violations import record_violation
            await record_violation(
                message.guild, message.author,
                violation_name="allcaps",
                trigger_detail=f"All-caps message ({pct:.0f}% uppercase, threshold {threshold}%)",
                bot=self.bot,
                message=message,
            )
            return True

        return False

    # ── Per-channel slowmode ─────────────────────────────────────────────────
    async def _check_slowmode(self, message: discord.Message, cfg: dict) -> bool:
        """Per-user-per-channel rate limit enforced by the bot."""
        slowmode_seconds = cfg.get("slowmode_seconds") or 5
        slowmode_channels = {int(x) for x in _load_json_list(cfg.get("slowmode_channels")) if str(x).isdigit()}

        # If channel list is set, only enforce in those channels
        if slowmode_channels and message.channel.id not in slowmode_channels:
            return False

        gid = message.guild.id
        uid = message.author.id
        cid = message.channel.id
        key = (gid, cid, uid)
        now = datetime.now(timezone.utc).timestamp()

        last = self._slowmode_last.get(key, 0)
        if now - last < slowmode_seconds:
            try:
                await message.delete()
            except (discord.NotFound, discord.Forbidden):
                pass
            from .violations import record_violation
            await record_violation(
                message.guild, message.author,
                violation_name="slowmode",
                trigger_detail=f"Posting too fast in #{message.channel.name} ({slowmode_seconds}s cooldown)",
                bot=self.bot,
                message=message,
            )
            return True

        self._slowmode_last[key] = now
        return False

    # ── Spam detection ───────────────────────────────────────────────────────
    async def _check_spam(self, message: discord.Message, cfg: dict) -> bool:
        # Per-message checks first (mentions, emojis) -- cheap
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

        # Velocity + duplicate check -- needs the tracker
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
        # Always delete the offending message
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass
        # Feed into the violation engine instead of punishing directly
        from .violations import record_violation
        await record_violation(
            message.guild, message.author,
            violation_name="spam",
            trigger_detail=f"{trigger}: {reason}",
            bot=self.bot,
            message=message,
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
            # Route through the bot's own mute system for consistency with /mute:
            # - Discord timeout is still the enforcement mechanism (that's how /mute
            #   works too -- timeout is not a role in this bot).
            # - The mute is recorded in the `mutes` table so /history and /unmute
            #   see it just like a manual mute.
            # - The user is DMed using the customizable `mute_dm` message template.
            duration = timedelta(minutes=mute_minutes)
            # Discord's max timeout is 28 days -- cap it defensively.
            discord_td = min(duration, timedelta(days=28))
            until = datetime.now(timezone.utc) + duration
            try:
                await member.timeout(
                    datetime.now(timezone.utc) + discord_td,
                    reason=f"AutoMod: {reason}",
                )
                # Log to mutes DB so it appears in /history and can be lifted with /unmute
                try:
                    db.add_mute(guild.id, member.id, until, f"AutoMod: {reason}")
                except Exception:
                    pass  # DB write failure shouldn't undo the mute
                # DM the user using the standard mute template
                try:
                    text = _fmt(
                        get_bot_message(db, str(guild.id), "mute_dm"),
                        user=member.mention,
                        reason=f"AutoMod: {reason}",
                        duration=f"{mute_minutes}m",
                    )
                    await member.send(
                        embed=discord.Embed(
                            description=text,
                            color=discord.Color.dark_orange(),
                        )
                    )
                except (discord.Forbidden, discord.HTTPException):
                    pass  # user has DMs closed; not fatal
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

        # else: action == "delete" -- nothing else to do

        # Persist to mod_logs so this appears on the user's /history + dashboard.
        # Action name matches manual moderation actions (MUTE / KICK / BAN)
        # so filters work uniformly. Actor is the bot; the "AutoMod -- trigger"
        # prefix in the reason field makes the source unmistakable.
        try:
            mod_log_action = {
                "mute":   "MUTE",
                "kick":   "KICK",
                "ban":    "BAN",
                "delete": "AUTOMOD_DELETE",
            }.get(action, "AUTOMOD_DELETE")
            bot_user = self.bot.user
            db.add_mod_log(
                guild_id=str(guild.id),
                action=mod_log_action,
                target_id=str(member.id),
                target_username=str(member),
                actor_id=str(bot_user.id) if bot_user else "",
                actor_username="AutoMod",
                reason=f"AutoMod -- {trigger}: {reason}",
            )
        except Exception:
            pass  # never let the audit-log write fail an action

        # Modlog embed
        embed = discord.Embed(
            title=f"🛡️ AutoMod -- {trigger}",
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
        # Word lists
        word_lists = db.get_all_word_lists(str(interaction.guild_id))
        wl_count = sum(len(wl.get("words", [])) for wl in word_lists)
        embed.add_field(
            name=f"Word Lists {yn(cfg.get('wordlist_enabled'))}",
            value=f"**{len(word_lists)}** list(s), **{wl_count}** total word(s)",
            inline=False,
        )
        # Anti-phishing
        embed.add_field(
            name=f"Anti-Phishing {yn(cfg.get('antiphish_enabled', 1))}",
            value="SinkingYachts API -- scans every URL for known phishing domains",
            inline=False,
        )
        # Message length
        max_len = cfg.get("max_message_length") or 0
        min_len = cfg.get("min_message_length") or 0
        len_parts = []
        if max_len > 0:
            len_parts.append(f"max: **{max_len}**")
        if min_len > 0:
            len_parts.append(f"min: **{min_len}**")
        embed.add_field(
            name=f"Message Length {yn(max_len > 0 or min_len > 0)}",
            value=", ".join(len_parts) if len_parts else "No limits set",
            inline=False,
        )
        # All-caps
        embed.add_field(
            name=f"All-Caps Filter {yn(cfg.get('allcaps_enabled'))}",
            value=f"Threshold: **{cfg.get('allcaps_threshold', 70)}%** (min **{cfg.get('allcaps_min_length', 10)}** alpha chars)",
            inline=False,
        )
        # Slowmode
        sm_channels = _load_json_list(cfg.get("slowmode_channels"))
        embed.add_field(
            name=f"Slowmode {yn(cfg.get('slowmode_enabled'))}",
            value=(
                f"Interval: **{cfg.get('slowmode_seconds', 5)}s** per user per channel\n"
                f"Channels: **{len(sm_channels) if sm_channels else 'all'}**"
            ),
            inline=False,
        )
        # Violations
        embed.add_field(
            name="Violation Engine",
            value=(
                f"Threshold: **{cfg.get('violation_jail_threshold', 5)}** in **{cfg.get('violation_window_minutes', 60)}m**\n"
                f"Auto-jail duration: **{cfg.get('violation_jail_duration', '1d')}**\n"
                f"Role persistence: {yn(cfg.get('role_persist_enabled', 1))}\n"
                f"Active profile: **{cfg.get('active_profile', 'normal')}**"
            ),
            inline=False,
        )
        # Name filter
        name_words = _load_json_list(cfg.get("name_filter_words"))
        embed.add_field(
            name=f"Name Filter {yn(cfg.get('name_filter_enabled'))}",
            value=(
                f"Action: **{cfg.get('name_filter_action', 'log')}**  ·  "
                f"Confusables: {yn(cfg.get('name_filter_confusables', 1))}\n"
                f"Blocked words: **{len(name_words)}**"
            ),
            inline=False,
        )
        # Verify gate
        embed.add_field(
            name=f"Verification Gate {yn(cfg.get('verify_gate_enabled'))}",
            value=(
                f"Role: {('<@&' + str(cfg.get('verify_gate_role_id')) + '>') if cfg.get('verify_gate_role_id') else '*(not set)*'}  ·  "
                f"Channel: {('<#' + str(cfg.get('verify_gate_channel_id')) + '>') if cfg.get('verify_gate_channel_id') else '*(not set)*'}"
            ),
            inline=False,
        )
        # Raid
        embed.add_field(
            name="Raid",
            value=(
                f"Join threshold: **{cfg.get('raid_join_count', 10)}** in **{cfg.get('raid_join_seconds', 10)}s**\n"
                f"Min account age: **{cfg.get('raid_min_account_age_days', 0)}d** (0 = off)\n"
                f"During raid: **{cfg.get('raid_active_action', 'ban')}** joiners  ·  "
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

    @automod_group.command(name="link_list", description="Show every domain on the whitelist and blacklist.")
    @app_commands.describe(list_type="Which list to show -- omit for both")
    @app_commands.choices(list_type=[
        app_commands.Choice(name="both",      value="both"),
        app_commands.Choice(name="whitelist", value="whitelist"),
        app_commands.Choice(name="blacklist", value="blacklist"),
    ])
    async def link_list(self, interaction: discord.Interaction,
                        list_type: app_commands.Choice[str] = None):
        cfg = db.get_config(interaction.guild_id) or {}
        which = (list_type.value if list_type else "both")

        embed = discord.Embed(
            title="🔗 AutoMod Link Lists",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        embed.description = (
            f"Filter: **{'on' if cfg.get('link_filter_enabled') else 'off'}** · "
            f"Mode: **{cfg.get('link_mode', 'whitelist')}** · "
            f"Action: **{cfg.get('link_action', 'delete')}**"
        )

        if which in ("both", "whitelist"):
            wl = _load_json_list(cfg.get("link_whitelist"))
            _append_domain_fields(embed, "✅ Whitelist", wl)

        if which in ("both", "blacklist"):
            bl = _load_json_list(cfg.get("link_blacklist"))
            _append_domain_fields(embed, "⛔ Blacklist", bl)

        await interaction.response.send_message(embed=embed, ephemeral=True)

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

    # ── Anti-Phishing ────────────────────────────────────────────────────────
    @automod_group.command(name="antiphish", description="Turn anti-phishing link scanning on or off.")
    @app_commands.describe(enabled="Enable or disable phishing link scanning")
    async def antiphish_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, antiphish_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"Anti-phishing scanning is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    # ── Message Length ────────────────────────────────────────────────────────
    @automod_group.command(name="max_length", description="Set max message length (0 to disable).")
    @app_commands.describe(chars="Max characters per message (0 = no limit)")
    async def max_length(self, interaction: discord.Interaction, chars: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, max_message_length=max(0, chars))
        if chars > 0:
            await interaction.response.send_message(
                f"Max message length set to **{chars}** characters.", ephemeral=True
            )
        else:
            await interaction.response.send_message("Max message length filter disabled.", ephemeral=True)

    @automod_group.command(name="min_length", description="Set min message length (0 to disable).")
    @app_commands.describe(chars="Min characters per message (0 = no limit)")
    async def min_length(self, interaction: discord.Interaction, chars: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, min_message_length=max(0, chars))
        if chars > 0:
            await interaction.response.send_message(
                f"Min message length set to **{chars}** characters.", ephemeral=True
            )
        else:
            await interaction.response.send_message("Min message length filter disabled.", ephemeral=True)

    # ── All-Caps ──────────────────────────────────────────────────────────────
    @automod_group.command(name="allcaps", description="Turn all-caps message filtering on or off.")
    @app_commands.describe(enabled="Enable or disable all-caps filter")
    async def allcaps_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, allcaps_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"All-caps filter is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @automod_group.command(name="allcaps_threshold", description="Set the % of uppercase characters that triggers the filter.")
    @app_commands.describe(percent="Percentage threshold (50-100)", min_chars="Min alphabetic characters to check (default 10)")
    async def allcaps_threshold(self, interaction: discord.Interaction, percent: int, min_chars: int = 10):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(
            interaction.guild_id,
            allcaps_threshold=max(50, min(100, percent)),
            allcaps_min_length=max(5, min_chars),
        )
        await interaction.response.send_message(
            f"All-caps threshold: **{max(50, min(100, percent))}%** (min {max(5, min_chars)} alpha chars).",
            ephemeral=True,
        )

    # ── Slowmode ──────────────────────────────────────────────────────────────
    @automod_group.command(name="slowmode", description="Turn bot-enforced per-channel slowmode on or off.")
    @app_commands.describe(enabled="Enable or disable slowmode enforcement")
    async def slowmode_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, slowmode_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"Bot slowmode is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @automod_group.command(name="slowmode_interval", description="Set slowmode interval in seconds per user per channel.")
    @app_commands.describe(seconds="Seconds between messages (min 2)")
    async def slowmode_interval(self, interaction: discord.Interaction, seconds: int):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, slowmode_seconds=max(2, seconds))
        await interaction.response.send_message(
            f"Slowmode interval set to **{max(2, seconds)}s** per user per channel.", ephemeral=True
        )

    @automod_group.command(name="slowmode_channel", description="Toggle a channel for bot-enforced slowmode. Empty list = all channels.")
    async def slowmode_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        current = [int(x) for x in _load_json_list(cfg.get("slowmode_channels")) if str(x).isdigit()]
        if channel.id in current:
            current.remove(channel.id)
            msg = f"{channel.mention} removed from slowmode list."
        else:
            current.append(channel.id)
            msg = f"{channel.mention} added to slowmode list."
        db.upsert_config(interaction.guild_id, slowmode_channels=_dump_json_list(current))
        if not current:
            msg += " List is empty, so slowmode applies to **all channels**."
        await interaction.response.send_message(msg, ephemeral=True)

    # ── Word Lists (separate group -- Discord 25-subcommand limit) ─────────
    wordlist_group = app_commands.Group(
        name="wordlist",
        description="Manage word list filters for AutoMod.",
    )

    @wordlist_group.command(name="toggle", description="Turn word list filtering on or off.")
    @app_commands.describe(enabled="Enable or disable word list filtering")
    async def wordlist_toggle(self, interaction: discord.Interaction, enabled: bool):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        db.upsert_config(interaction.guild_id, wordlist_enabled=1 if enabled else 0)
        await interaction.response.send_message(
            f"Word list filter is now **{'on' if enabled else 'off'}**.", ephemeral=True
        )

    @wordlist_group.command(name="add", description="Add words to a word list (creates the list if new).")
    @app_commands.describe(list_name="Name of the word list", words="Words to add, separated by commas")
    async def wordlist_add(self, interaction: discord.Interaction, list_name: str, words: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        list_name = list_name.strip().lower()
        new_words = [w.strip() for w in words.split(",") if w.strip()]
        if not new_words:
            return await interaction.response.send_message("Provide at least one word.", ephemeral=True)

        existing = db.get_word_list(str(interaction.guild_id), list_name)
        if existing:
            current = existing["words"]
            added = [w for w in new_words if w.lower() not in [x.lower() for x in current]]
            current.extend(added)
            db.update_word_list(str(interaction.guild_id), list_name, current)
        else:
            db.create_word_list(str(interaction.guild_id), list_name, new_words)
            added = new_words

        await interaction.response.send_message(
            f"Added **{len(added)}** word(s) to list `{list_name}`.", ephemeral=True
        )

    @wordlist_group.command(name="remove", description="Remove words from a word list.")
    @app_commands.describe(list_name="Name of the word list", words="Words to remove, separated by commas")
    async def wordlist_remove(self, interaction: discord.Interaction, list_name: str, words: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        existing = db.get_word_list(str(interaction.guild_id), list_name.strip().lower())
        if not existing:
            return await interaction.response.send_message(f"List `{list_name}` not found.", ephemeral=True)
        to_remove = {w.strip().lower() for w in words.split(",") if w.strip()}
        updated = [w for w in existing["words"] if w.lower() not in to_remove]
        db.update_word_list(str(interaction.guild_id), list_name.strip().lower(), updated)
        await interaction.response.send_message(
            f"Removed words from `{list_name}`. List now has **{len(updated)}** word(s).", ephemeral=True
        )

    @wordlist_group.command(name="view", description="View all word lists and their contents.")
    async def wordlist_view(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id) or {}
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)
        lists = db.get_all_word_lists(str(interaction.guild_id))
        if not lists:
            return await interaction.response.send_message("No word lists configured.", ephemeral=True)

        embed = discord.Embed(
            title="Word Lists",
            color=discord.Color.blurple(),
            description=f"Filter: **{'on' if cfg.get('wordlist_enabled') else 'off'}**",
        )
        for wl in lists:
            preview = ", ".join(wl["words"][:20])
            if len(wl["words"]) > 20:
                preview += f" ...+{len(wl['words']) - 20} more"
            embed.add_field(
                name=f"{wl['list_name']} ({len(wl['words'])} words)",
                value=preview or "*(empty)*",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @wordlist_group.command(name="delete", description="Delete an entire word list.")
    @app_commands.describe(list_name="Name of the word list to delete")
    async def wordlist_delete(self, interaction: discord.Interaction, list_name: str):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        deleted = db.delete_word_list(str(interaction.guild_id), list_name.strip().lower())
        if deleted:
            await interaction.response.send_message(f"Deleted word list `{list_name}`.", ephemeral=True)
        else:
            await interaction.response.send_message(f"List `{list_name}` not found.", ephemeral=True)

    # ── Immune (standalone -- keeps automod_group under 25) ──────────────
    @app_commands.command(name="immune", description="Toggle a role as immune to all AutoMod filters.")
    async def immune(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("Manage Server required.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        current = [int(x) for x in _load_json_list(cfg.get("automod_immune_roles")) if str(x).isdigit()]
        if role.id in current:
            current.remove(role.id)
            msg = f"{role.mention} is no longer immune to AutoMod."
        else:
            current.append(role.id)
            msg = f"{role.mention} is now immune to AutoMod."
        db.upsert_config(interaction.guild_id, automod_immune_roles=_dump_json_list(current))
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))
