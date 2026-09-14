"""
cogs/streamer.py -- Streamer management system.
- /streamer add/remove/edit -- manage streamers (mod+)
- /streamer links add/remove/list -- manage links (streamer self-service + mod)
- Twitch polling loop for go-live/offline detection
- Auto-creates personal channel with pinned info card
- Posts to #live-now with @Stream Alerts ping
"""

import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime

try:
    import aiohttp
    _AIOHTTP = True
except ImportError:
    _AIOHTTP = False

import database as db
import platforms as plat
from config import FOOTER_BRAND
from utils import resolve_user

BRAND_FOOTER = FOOTER_BRAND
LIVE_COLOR = 0xE74C3C       # Red -- live
OFFLINE_COLOR = 0x95A5A6    # Grey -- offline
INFO_COLOR = 0xD4A843       # Gold -- info card
CATEGORY_NAME = "Streamers"
LIVE_CHANNEL_NAME = "live-now"
ALERTS_ROLE_NAME = "Stream Alerts"

# Twitch API config -- set in .env
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID", "")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET", "")


# ── Twitch API helpers ────────────────────────────────────────────────────────

class TwitchAPI:
    def __init__(self):
        self._token: str | None = None
        self._token_expiry: float = 0

    async def _get_token(self) -> str | None:
        if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
            return None
        import time
        if self._token and time.time() < self._token_expiry:
            return self._token
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://id.twitch.tv/oauth2/token",
                    params={
                        "client_id": TWITCH_CLIENT_ID,
                        "client_secret": TWITCH_CLIENT_SECRET,
                        "grant_type": "client_credentials",
                    },
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        self._token = data["access_token"]
                        self._token_expiry = time.time() + data.get("expires_in", 3600) - 60
                        return self._token
        except Exception as e:
            print(f"[streamer] Twitch token error: {e}")
        return None

    async def get_streams(self, usernames: list[str]) -> dict[str, dict]:
        """Returns {lowercase_username: stream_data} for users currently live."""
        if not usernames:
            return {}
        token = await self._get_token()
        if not token:
            return {}

        results = {}
        # Twitch API allows up to 100 user_logins per request
        for i in range(0, len(usernames), 100):
            batch = usernames[i:i+100]
            params = [("user_login", u) for u in batch]
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://api.twitch.tv/helix/streams",
                        params=params,
                        headers={
                            "Client-ID": TWITCH_CLIENT_ID,
                            "Authorization": f"Bearer {token}",
                        },
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            for stream in data.get("data", []):
                                results[stream["user_login"].lower()] = stream
            except Exception as e:
                print(f"[streamer] Twitch API error: {e}")
        return results


_twitch = TwitchAPI()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_info_embed(member, streamer: dict,
                      links: list[dict]) -> discord.Embed:
    """
    member may be a discord.Member, a discord.User, or None. The card is built
    from the database row either way so that a streamer who has left the guild
    still renders instead of silently skipping.
    """
    embed = discord.Embed(
        title=f"📡 {streamer['twitch_username']} · "
              f"{plat.PLATFORM_LABELS.get((streamer.get('platform') or 'twitch').lower(), 'Twitch')}",
        color=INFO_COLOR,
    )
    avatar = getattr(member, "display_avatar", None) if member else None
    if avatar is not None:
        embed.set_thumbnail(url=str(avatar.url))

    embed.add_field(
        name="Discord",
        value=member.mention if member else f"`{streamer['user_id']}` (left the server)",
        inline=True,
    )
    embed.add_field(
        name="Twitch",
        value=plat.channel_url(streamer.get("platform") or "twitch",
                               streamer["twitch_username"]),
        inline=True,
    )

    if links:
        link_lines = "\n".join(f"**{l['label']}:** {l['url']}" for l in links)
        embed.add_field(name="Links", value=link_lines, inline=False)

    embed.set_footer(text=BRAND_FOOTER)
    return embed


def _build_live_embed(streamer: dict, links: list[dict],
                      member: discord.Member | None, stream_data: dict) -> discord.Embed:
    title = stream_data.get("title") or "Live Stream"
    # Providers normalise to 'game'; Twitch's raw key was 'game_name'.
    game  = stream_data.get("game") or stream_data.get("game_name") or ""

    embed = discord.Embed(
        title=f"🔴 LIVE on {plat.PLATFORM_LABELS.get((streamer.get('platform') or 'twitch').lower(), 'Twitch')}"
              f" -- {streamer['twitch_username']}",
        color=plat.PLATFORM_COLORS.get(
            (streamer.get("platform") or "twitch").lower(), LIVE_COLOR),
    )
    embed.add_field(name="📺 Title", value=title, inline=False)
    if game:
        embed.add_field(name="🎮 Playing", value=game, inline=True)

    watch_url = (stream_data or {}).get("url") or plat.channel_url(
        streamer.get("platform") or "twitch", streamer["twitch_username"])
    embed.add_field(name="🔗 Watch", value=watch_url, inline=False)
    viewers = (stream_data or {}).get("viewers")
    if viewers is not None:
        embed.add_field(name="👀 Viewers", value=f"{viewers:,}", inline=True)

    if links:
        link_lines = "\n".join(f"**{l['label']}:** {l['url']}" for l in links)
        embed.add_field(name="Links", value=link_lines, inline=False)

    if member:
        embed.set_thumbnail(url=str(member.display_avatar.url))

    # Providers already resolve Twitch's {width}/{height} template
    thumb = stream_data.get("thumbnail") or stream_data.get("thumbnail_url") or ""
    if thumb:
        thumb = thumb.replace("{width}", "440").replace("{height}", "248")
        embed.set_image(url=thumb)

    embed.set_footer(text=BRAND_FOOTER)
    return embed


def _build_offline_embed(streamer: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"⚫ {streamer['twitch_username']} has gone offline",
        description="Thanks for watching!",
        color=OFFLINE_COLOR,
    )
    embed.set_footer(text=BRAND_FOOTER)
    return embed


async def _get_or_create_category(guild: discord.Guild) -> discord.CategoryChannel:
    for cat in guild.categories:
        if cat.name.lower() == CATEGORY_NAME.lower():
            return cat
    return await guild.create_category(CATEGORY_NAME)


async def _get_or_create_live_channel(
    guild: discord.Guild, category: discord.CategoryChannel
) -> discord.TextChannel:
    for ch in category.text_channels:
        if ch.name == LIVE_CHANNEL_NAME:
            return ch
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(send_messages=False),
        guild.me: discord.PermissionOverwrite(send_messages=True),
    }
    return await guild.create_text_channel(
        LIVE_CHANNEL_NAME,
        category=category,
        overwrites=overwrites,
        topic="Live stream notifications -- read only",
    )


async def _get_or_create_alerts_role(guild: discord.Guild) -> discord.Role:
    for role in guild.roles:
        if role.name == ALERTS_ROLE_NAME:
            return role
    return await guild.create_role(
        name=ALERTS_ROLE_NAME,
        mentionable=True,
        reason="ModSuite: Stream Alerts role for go-live pings",
    )


async def _update_pinned_info(bot: commands.Bot, guild: discord.Guild,
                               streamer: dict) -> None:
    channel = guild.get_channel(int(streamer["channel_id"]))
    if not channel:
        return
    # A departed streamer still gets a card -- built from the DB row, with the
    # Discord field falling back to the raw user ID.
    member = guild.get_member(int(streamer["user_id"]))
    links = db.get_streamer_links(streamer["streamer_id"])
    embed = _build_info_embed(member, streamer, links)

    # Find existing pinned info card and edit it, or post new one
    pins = await channel.pins()
    for pin in pins:
        if pin.author.id == bot.user.id and pin.embeds:
            first_embed = pin.embeds[0]
            if first_embed.title and first_embed.title.startswith("📡"):
                await pin.edit(embed=embed)
                return

    msg = await channel.send(embed=embed)
    await msg.pin()


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if member.guild_permissions.administrator:
        return True
    if cfg is None:
        return False
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(str(r.id) in staff_ids for r in member.roles)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Streamer(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET:
            self.poll_twitch.start()
        else:
            print("[streamer] TWITCH_CLIENT_ID or TWITCH_CLIENT_SECRET not set -- polling disabled")

    def cog_unload(self):
        self.poll_twitch.cancel()

    # ── Polling loop ──────────────────────────────────────────────────────────

    @tasks.loop(seconds=90)
    async def poll_twitch(self):
        for guild in self.bot.guilds:
            try:
                await self._check_guild(guild)
            except Exception as e:
                print(f"[streamer] poll error in {guild.id}: {e}")

    @poll_twitch.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    async def _check_guild(self, guild: discord.Guild):
        guild_id = str(guild.id)
        streamers = db.get_all_streamers(guild_id)
        if not streamers:
            return

        # Group by platform so each provider is queried once, then ask them
        # all. A provider that fails returns nothing, which reads as offline
        # rather than taking down the poll for the other platforms.
        by_platform: dict[str, list[str]] = {}
        for row in streamers:
            p = (row.get("platform") or "twitch").lower()
            by_platform.setdefault(p, []).append(row["twitch_username"])
        results = await plat.poll_all(by_platform)

        for s in streamers:
            platform = (s.get("platform") or "twitch").lower()
            uname_lower = s["twitch_username"].lower()
            live_streams = results.get(platform, {})
            was_live = bool(s["is_live"])
            now_live = uname_lower in live_streams

            if now_live and not was_live:
                # WENT LIVE
                stream_data = live_streams[uname_lower]
                db.update_streamer(
                    s["streamer_id"],
                    is_live=1,
                    stream_title=stream_data.get("title", ""),
                    stream_game=stream_data.get("game", ""),
                )
                await self._notify_live(guild, s, stream_data)

            elif not now_live and was_live:
                # WENT OFFLINE
                db.update_streamer(s["streamer_id"], is_live=0, stream_title="", stream_game="")
                await self._notify_offline(guild, s)

    async def _notify_live(self, guild: discord.Guild, streamer: dict,
                            stream_data: dict):
        member = guild.get_member(int(streamer["user_id"]))
        links  = db.get_streamer_links(streamer["streamer_id"])
        embed  = _build_live_embed(streamer, links, member, stream_data)

        # Post in streamer's personal channel
        personal_ch = guild.get_channel(int(streamer["channel_id"]))
        if personal_ch:
            await personal_ch.send(embed=embed)

        # Post in #live-now with @Stream Alerts
        category = await _get_or_create_category(guild)
        live_ch  = await _get_or_create_live_channel(guild, category)
        alerts_role = await _get_or_create_alerts_role(guild)
        await live_ch.send(f"{alerts_role.mention}", embed=embed)

    async def _notify_offline(self, guild: discord.Guild, streamer: dict):
        embed = _build_offline_embed(streamer)

        personal_ch = guild.get_channel(int(streamer["channel_id"]))
        if personal_ch:
            await personal_ch.send(embed=embed)

        category = await _get_or_create_category(guild)
        live_ch  = await _get_or_create_live_channel(guild, category)
        await live_ch.send(embed=embed)

    # ── /streamer add ─────────────────────────────────────────────────────────

    streamer_group = app_commands.Group(
        name="streamer",
        description="Manage streamers and their channels.",
    )

    @streamer_group.command(
        name="add",
        description="[Mod] Add a streamer -- creates their channel and assigns the role.",
    )
    @app_commands.describe(
        member="Member mention, username, or numeric user ID",
        twitch_username="Their username or handle on the chosen platform",
        platform="Which platform to watch (default Twitch)",
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="Twitch", value="twitch"),
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="Kick", value="kick"),
        app_commands.Choice(name="Rumble", value="rumble"),
    ])
    async def streamer_add(
        self,
        interaction: discord.Interaction,
        member: str,
        twitch_username: str,
        platform: str = "twitch",
    ):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Moderator or Administrator only.", ephemeral=True
            )
            return

        try:
            member, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        # Adding requires a real member: the personal channel is created with a
        # per-member permission overwrite and the Streamer role has to land
        # somewhere. Removal and editing do not have that constraint.
        if not is_member:
            await interaction.response.send_message(
                f"❌ **{member}** is not in this server, so their channel "
                f"overwrites and Streamer role cannot be set up. "
                f"They need to join before being added.",
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild_id)
        existing = db.get_streamer(guild_id, str(member.id))
        if existing:
            await interaction.response.send_message(
                f"❌ {member.mention} is already a streamer.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        # Get or create Streamers category
        category = await _get_or_create_category(guild)

        # Get or create #live-now
        await _get_or_create_live_channel(guild, category)

        # Get or create @Stream Alerts role
        await _get_or_create_alerts_role(guild)

        # Create personal channel
        channel_name = f"{twitch_username.lower().lstrip('@')}-chat"
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
            ),
            member: discord.PermissionOverwrite(
                manage_messages=True,
                pin_messages=True,
            ),
            guild.me: discord.PermissionOverwrite(
                send_messages=True,
                manage_messages=True,
            ),
        }
        personal_ch = await guild.create_text_channel(
            channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Chat for {twitch_username} | Twitch: twitch.tv/{twitch_username}",
        )

        # Assign Streamer role
        streamer_role = discord.utils.get(guild.roles, name="Streamer")
        if streamer_role:
            try:
                await member.add_roles(streamer_role, reason="ModSuite: Streamer added")
            except discord.Forbidden:
                pass

        # Save to DB
        streamer_id = db.add_streamer(
            guild_id=guild_id,
            user_id=str(member.id),
            twitch_username=twitch_username,
            channel_id=str(personal_ch.id),
            platform=platform,
        )

        # Pin info card
        streamer_data = db.get_streamer(guild_id, str(member.id))
        await _update_pinned_info(self.bot, guild, streamer_data)

        await interaction.followup.send(
            f"✅ **{member.display_name}** added as a streamer.\n"
            f"Channel: {personal_ch.mention}\n"
            f"Twitch: `{twitch_username}`\n"
            f"Tracking is {'active' if TWITCH_CLIENT_ID else '**disabled** (no Twitch API keys)'}.",
            ephemeral=True,
        )

    # ── /streamer remove ──────────────────────────────────────────────────────

    @streamer_group.command(
        name="remove",
        description="[Mod] Remove a streamer -- deletes their channel and removes the role.",
    )
    @app_commands.describe(member="Streamer mention, username, or numeric user ID")
    async def streamer_remove(
        self,
        interaction: discord.Interaction,
        member: str,
    ):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Moderator or Administrator only.", ephemeral=True
            )
            return

        try:
            member, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        streamer = db.get_streamer(guild_id, str(member.id))
        if not streamer:
            await interaction.response.send_message(
                f"❌ **{member}** is not a streamer.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        notes: list[str] = []

        # Delete personal channel. This is guild-side state and does not depend
        # on the streamer still being present.
        ch = guild.get_channel(int(streamer["channel_id"]))
        if ch:
            try:
                await ch.delete(reason="ModSuite: Streamer removed")
                notes.append(f"Channel `#{ch.name}` deleted.")
            except discord.Forbidden:
                notes.append("⚠️ Could not delete their channel (missing permissions).")
        else:
            notes.append("Their channel was already gone.")

        # Role removal only applies if they are still here. A departed member
        # has no roles to strip, and that must not block the DB cleanup.
        if is_member:
            streamer_role = discord.utils.get(guild.roles, name="Streamer")
            if streamer_role and streamer_role in member.roles:
                try:
                    await member.remove_roles(streamer_role, reason="ModSuite: Streamer removed")
                    notes.append("Streamer role removed.")
                except discord.Forbidden:
                    notes.append("⚠️ Could not remove their Streamer role (missing permissions).")
        else:
            notes.append("They are no longer in the server, so no role was removed.")

        db.remove_streamer(guild_id, str(member.id))

        db.add_mod_log(
            guild_id=guild_id,
            action="STREAMER_REMOVED",
            target_id=str(member.id),
            target_username=str(member),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=f"Twitch: {streamer['twitch_username']}",
        )

        detail = "\n".join(f"• {n}" for n in notes)
        await interaction.followup.send(
            f"✅ **{member}** (`{member.id}`) removed as a streamer.\n{detail}",
            ephemeral=True,
        )

    # ── /streamer edit ────────────────────────────────────────────────────────

    @streamer_group.command(
        name="edit",
        description="[Mod] Update a streamer's Twitch username.",
    )
    @app_commands.describe(
        member="Streamer mention, username, or numeric user ID",
        twitch_username="New Twitch username",
    )
    async def streamer_edit(
        self,
        interaction: discord.Interaction,
        member: str,
        twitch_username: str,
    ):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Moderator or Administrator only.", ephemeral=True
            )
            return

        try:
            member, is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return

        guild_id = str(interaction.guild_id)
        streamer = db.get_streamer(guild_id, str(member.id))
        if not streamer:
            await interaction.response.send_message(
                f"❌ **{member}** is not a streamer.", ephemeral=True
            )
            return

        db.update_streamer(streamer["streamer_id"], twitch_username=twitch_username)

        # Update channel name and topic
        ch = interaction.guild.get_channel(int(streamer["channel_id"]))
        if ch:
            try:
                await ch.edit(
                    name=f"{twitch_username.lower()}-chat",
                    topic=f"Chat for {twitch_username} | Twitch: twitch.tv/{twitch_username}",
                )
            except discord.Forbidden:
                pass

        # Update pinned info
        updated = db.get_streamer(guild_id, str(member.id))
        await _update_pinned_info(self.bot, interaction.guild, updated)

        await interaction.response.send_message(
            f"✅ Updated **{member}** → Twitch: `{twitch_username}`",
            ephemeral=True,
        )

    # ── /streamer list ────────────────────────────────────────────────────────

    @streamer_group.command(
        name="list",
        description="[Mod] List every registered streamer, including any who have left.",
    )
    async def streamer_list(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Moderator or Administrator only.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        streamers = db.get_all_streamers(guild_id)
        if not streamers:
            await interaction.response.send_message(
                "ℹ️ No streamers registered yet.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"📡 Registered Streamers ({len(streamers)})",
            color=INFO_COLOR,
        )

        orphans = 0
        for st in streamers[:25]:
            member = interaction.guild.get_member(int(st["user_id"]))
            if member is None:
                orphans += 1
                who = f"`{st['user_id']}` — **left the server**"
            else:
                who = f"{member.mention} (`{st['user_id']}`)"
            live = " 🔴 LIVE" if st.get("is_live") else ""
            embed.add_field(
                name=f"{st['twitch_username']}{live}",
                value=who,
                inline=False,
            )

        if len(streamers) > 25:
            embed.description = f"Showing the first 25 of {len(streamers)}."
        if orphans:
            embed.set_footer(
                text=f"{orphans} streamer(s) have left the server — "
                     f"remove them with /streamer remove <user ID>. · {BRAND_FOOTER}"
            )
        else:
            embed.set_footer(text=BRAND_FOOTER)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Shared resolution for the links subcommands ───────────────────────────

    async def _streamer_for(self, interaction: discord.Interaction,
                            member: "str | None"):
        """
        Return the streamer row the caller is allowed to act on, or None after
        sending an error response.

        With no ``member`` argument this is self-service: the caller's own
        streamer row. With a ``member`` argument it is a staff action against
        another streamer, resolved from a mention, username, or numeric user
        ID -- the last of which keeps working after they leave the guild.
        """
        guild_id = str(interaction.guild_id)
        cfg = db.get_config(interaction.guild_id)

        if member is None:
            streamer = db.get_streamer(guild_id, str(interaction.user.id))
            if not streamer:
                await interaction.response.send_message(
                    "❌ You're not registered as a streamer. "
                    "Staff can pass `member:` to manage someone else's links.",
                    ephemeral=True,
                )
                return None
            return streamer

        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Only moderators can manage another streamer's links.",
                ephemeral=True,
            )
            return None

        try:
            target, _is_member = await resolve_user(self.bot, interaction.guild, member)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)
            return None

        streamer = db.get_streamer(guild_id, str(target.id))
        if not streamer:
            await interaction.response.send_message(
                f"❌ **{target}** (`{target.id}`) is not a registered streamer.",
                ephemeral=True,
            )
            return None
        return streamer

    # ── /streamer links ───────────────────────────────────────────────────────

    links_group = app_commands.Group(
        name="links",
        description="Manage your streamer links.",
        parent=streamer_group,
    )

    @links_group.command(
        name="add",
        description="Add a link to your streamer profile.",
    )
    @app_commands.describe(
        label="Label for the link (e.g. YouTube, Twitter, Kick)",
        url="The URL",
        member="[Mod only] Act on another streamer: mention, username, or user ID",
    )
    async def links_add(self, interaction: discord.Interaction, label: str, url: str,
                        member: str | None = None):
        streamer = await self._streamer_for(interaction, member)
        if streamer is None:
            return

        db.add_streamer_link(streamer["streamer_id"], label, url)

        # Update pinned info card
        await _update_pinned_info(self.bot, interaction.guild, streamer)

        await interaction.response.send_message(
            f"✅ Added link: **{label}** → {url}", ephemeral=True
        )

    @links_group.command(
        name="remove",
        description="Remove a link from your streamer profile.",
    )
    @app_commands.describe(
        label="Label of the link to remove",
        member="[Mod only] Act on another streamer: mention, username, or user ID",
    )
    async def links_remove(self, interaction: discord.Interaction, label: str,
                           member: str | None = None):
        streamer = await self._streamer_for(interaction, member)
        if streamer is None:
            return

        removed = db.remove_streamer_link(streamer["streamer_id"], label)
        if removed:
            await _update_pinned_info(self.bot, interaction.guild, streamer)
            await interaction.response.send_message(
                f"✅ Removed link: **{label}**", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ No link with label **{label}** found.", ephemeral=True
            )

    @links_group.command(
        name="list",
        description="View your streamer links.",
    )
    @app_commands.describe(
        member="[Mod only] View another streamer's links: mention, username, or user ID",
    )
    async def links_list(self, interaction: discord.Interaction, member: str | None = None):
        streamer = await self._streamer_for(interaction, member)
        if streamer is None:
            return

        links = db.get_streamer_links(streamer["streamer_id"])
        if not links:
            await interaction.response.send_message(
                "ℹ️ You have no links set. Use `/streamer links add` to add some.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="🔗 Your Streamer Links", color=INFO_COLOR)
        for l in links:
            embed.add_field(name=l["label"], value=l["url"], inline=False)
        embed.set_footer(text=BRAND_FOOTER)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Streamer(bot))
