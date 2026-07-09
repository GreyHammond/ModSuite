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

BRAND_FOOTER = "ModSuite · Hammond Digital Studios"
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

def _build_info_embed(member: discord.Member, streamer: dict,
                      links: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"📡 {streamer['twitch_username']}",
        color=INFO_COLOR,
    )
    embed.set_thumbnail(url=str(member.display_avatar.url))

    embed.add_field(
        name="Discord",
        value=member.mention,
        inline=True,
    )
    embed.add_field(
        name="Twitch",
        value=f"[twitch.tv/{streamer['twitch_username']}](https://twitch.tv/{streamer['twitch_username']})",
        inline=True,
    )

    if links:
        link_lines = "\n".join(f"**{l['label']}:** {l['url']}" for l in links)
        embed.add_field(name="Links", value=link_lines, inline=False)

    embed.set_footer(text=BRAND_FOOTER)
    return embed


def _build_live_embed(streamer: dict, links: list[dict],
                      member: discord.Member | None, stream_data: dict) -> discord.Embed:
    title = stream_data.get("title", "Live Stream")
    game  = stream_data.get("game_name", "")

    embed = discord.Embed(
        title=f"🔴 LIVE -- {streamer['twitch_username']}",
        color=LIVE_COLOR,
    )
    embed.add_field(name="📺 Title", value=title, inline=False)
    if game:
        embed.add_field(name="🎮 Playing", value=game, inline=True)

    twitch_url = f"https://twitch.tv/{streamer['twitch_username']}"
    embed.add_field(name="🔗 Watch", value=twitch_url, inline=False)

    if links:
        link_lines = "\n".join(f"**{l['label']}:** {l['url']}" for l in links)
        embed.add_field(name="Links", value=link_lines, inline=False)

    if member:
        embed.set_thumbnail(url=str(member.display_avatar.url))

    # Twitch thumbnail
    thumb = stream_data.get("thumbnail_url", "")
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
    member = guild.get_member(int(streamer["user_id"]))
    if not member:
        return
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

        usernames = [s["twitch_username"].lower() for s in streamers]
        live_streams = await _twitch.get_streams(usernames)

        for s in streamers:
            twitch_lower = s["twitch_username"].lower()
            was_live = bool(s["is_live"])
            now_live = twitch_lower in live_streams

            if now_live and not was_live:
                # WENT LIVE
                stream_data = live_streams[twitch_lower]
                db.update_streamer(
                    s["streamer_id"],
                    is_live=1,
                    stream_title=stream_data.get("title", ""),
                    stream_game=stream_data.get("game_name", ""),
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
        member="The member to add as a streamer",
        twitch_username="Their Twitch username",
    )
    async def streamer_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        twitch_username: str,
    ):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Moderator or Administrator only.", ephemeral=True
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
        channel_name = f"{twitch_username.lower()}-chat"
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
    @app_commands.describe(member="The streamer to remove")
    async def streamer_remove(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
    ):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Moderator or Administrator only.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        streamer = db.get_streamer(guild_id, str(member.id))
        if not streamer:
            await interaction.response.send_message(
                f"❌ {member.mention} is not a streamer.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild

        # Delete personal channel
        ch = guild.get_channel(int(streamer["channel_id"]))
        if ch:
            try:
                await ch.delete(reason="ModSuite: Streamer removed")
            except discord.Forbidden:
                pass

        # Remove Streamer role
        streamer_role = discord.utils.get(guild.roles, name="Streamer")
        if streamer_role and streamer_role in member.roles:
            try:
                await member.remove_roles(streamer_role, reason="ModSuite: Streamer removed")
            except discord.Forbidden:
                pass

        db.remove_streamer(guild_id, str(member.id))

        await interaction.followup.send(
            f"✅ **{member.display_name}** removed as a streamer. Channel deleted.",
            ephemeral=True,
        )

    # ── /streamer edit ────────────────────────────────────────────────────────

    @streamer_group.command(
        name="edit",
        description="[Mod] Update a streamer's Twitch username.",
    )
    @app_commands.describe(
        member="The streamer to edit",
        twitch_username="New Twitch username",
    )
    async def streamer_edit(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        twitch_username: str,
    ):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ Moderator or Administrator only.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)
        streamer = db.get_streamer(guild_id, str(member.id))
        if not streamer:
            await interaction.response.send_message(
                f"❌ {member.mention} is not a streamer.", ephemeral=True
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
            f"✅ Updated **{member.display_name}** → Twitch: `{twitch_username}`",
            ephemeral=True,
        )

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
    )
    async def links_add(self, interaction: discord.Interaction, label: str, url: str):
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)
        cfg      = db.get_config(interaction.guild_id)

        # Allow the streamer themselves OR a mod
        streamer = db.get_streamer(guild_id, user_id)
        if not streamer:
            if _is_staff(interaction.user, cfg):
                await interaction.response.send_message(
                    "❌ Use this on behalf of a streamer by having them run it, "
                    "or use `/streamer edit` to update their Twitch.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "❌ You're not registered as a streamer.", ephemeral=True
                )
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
    @app_commands.describe(label="Label of the link to remove")
    async def links_remove(self, interaction: discord.Interaction, label: str):
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        streamer = db.get_streamer(guild_id, user_id)
        if not streamer:
            await interaction.response.send_message(
                "❌ You're not registered as a streamer.", ephemeral=True
            )
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
    async def links_list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        user_id  = str(interaction.user.id)

        streamer = db.get_streamer(guild_id, user_id)
        if not streamer:
            await interaction.response.send_message(
                "❌ You're not registered as a streamer.", ephemeral=True
            )
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
