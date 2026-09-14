"""
cogs/move.py -- /move command.
Moves messages from selected users in the current channel to a target channel.
Uses webhooks to preserve author identity. Re-uploads attachments.
Permission: Moderator+
"""

import io
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timedelta, timezone

try:
    import aiohttp
    _AIOHTTP = True
except ImportError:
    _AIOHTTP = False

import database as db
from config import FOOTER_BRAND
from utils import parse_relative_time, can_moderate

BRAND_FOOTER = FOOTER_BRAND


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


async def _download_attachment(url: str) -> "tuple[bytes, str] | None":
    """Download a Discord attachment. Returns (data, filename) or None on failure."""
    if not _AIOHTTP:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    data = await resp.read()
                    filename = url.split("/")[-1].split("?")[0] or "attachment"
                    return data, filename
    except Exception:
        pass
    return None


async def _post_modlog(guild: discord.Guild, cfg: dict, embed: discord.Embed):
    ch_id = cfg.get("modlog_ch_id") if cfg else None
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if ch:
            await ch.send(embed=embed)


class Move(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="move",
        description="[Mod] Move recent messages from selected users to another channel.",
    )
    @app_commands.describe(
        time="How far back to look: 10m, 1h, 30m (max 24h)",
        user1="First user: mention, username, or numeric user ID",
        channel="Destination channel",
        user2="Second user (optional)",
        user3="Third user (optional)",
        user4="Fourth user (optional)",
    )
    async def move(
        self,
        interaction: discord.Interaction,
        time: str,
        user1: str,
        channel: discord.TextChannel,
        user2: str | None = None,
        user3: str | None = None,
        user4: str | None = None,
    ):
        cfg = db.get_config(interaction.guild_id)

        # Permission check
        if not _is_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "❌ You need to be a moderator to use this command.", ephemeral=True
            )
            return

        # Messages outlive their author's membership, so a departed user's
        # messages are still movable by ID.
        from utils import resolve_user
        resolved = []
        for raw in (user1, user2, user3, user4):
            if raw is None:
                continue
            try:
                who, _is_member = await resolve_user(self.bot, interaction.guild, raw)
            except ValueError as e:
                await interaction.response.send_message(f"❌ {e}", ephemeral=True)
                return
            resolved.append(who)
        user1 = resolved[0]
        user2 = resolved[1] if len(resolved) > 1 else None
        user3 = resolved[2] if len(resolved) > 2 else None
        user4 = resolved[3] if len(resolved) > 3 else None

        # Parse time span
        td = parse_relative_time(time)
        if td is None:
            await interaction.response.send_message(
                "❌ Invalid time format. Examples: `10m`, `1h`, `30m`, `2h`",
                ephemeral=True,
            )
            return
        if td.total_seconds() < 60:
            await interaction.response.send_message(
                "❌ Minimum time span is 1 minute.", ephemeral=True
            )
            return
        if td.total_seconds() > 86400:
            await interaction.response.send_message(
                "❌ Maximum time span is 24 hours.", ephemeral=True
            )
            return

        # Same channel check
        if channel.id == interaction.channel_id:
            await interaction.response.send_message(
                "❌ Destination must be a different channel.", ephemeral=True
            )
            return

        # Pre-flight permission checks
        dest_perms = channel.permissions_for(interaction.guild.me)
        if not dest_perms.manage_webhooks:
            await interaction.response.send_message(
                f"❌ I need **Manage Webhooks** permission in {channel.mention}.",
                ephemeral=True,
            )
            return

        source_perms = interaction.channel.permissions_for(interaction.guild.me)
        if not source_perms.manage_messages:
            await interaction.response.send_message(
                "❌ I need **Manage Messages** permission in this channel to delete messages.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Build target user set
        target_ids = {u.id for u in [user1, user2, user3, user4] if u is not None}
        target_members = [u for u in [user1, user2, user3, user4] if u is not None]

        # Scan message history
        cutoff = datetime.now(timezone.utc) - td
        collected = []
        async for msg in interaction.channel.history(after=cutoff, oldest_first=True, limit=500):
            if msg.author.id in target_ids and not msg.author.bot:
                collected.append(msg)

        if not collected:
            await interaction.followup.send(
                f"⚠️ No messages found from the selected users in the last **{time}**.",
                ephemeral=True,
            )
            return

        # Post destination notification FIRST (appears before reposted messages)
        user_mentions = " ".join(m.mention for m in target_members)
        dest_embed = discord.Embed(
            title="💬 We've moved this conversation here",
            description=(
                f"{user_mentions} -- we've brought your messages over from "
                f"{interaction.channel.mention}. Feel free to continue here!"
            ),
            color=0x57F287,
        )
        dest_embed.set_footer(text=BRAND_FOOTER)
        await channel.send(embed=dest_embed)

        # Create webhook in destination channel
        webhook = await channel.create_webhook(name="ModSuite Move")

        try:
            # Repost messages via webhook
            for msg in collected:
                files = []
                if msg.attachments:
                    for att in msg.attachments:
                        result = await _download_attachment(att.url)
                        if result:
                            data, filename = result
                            files.append(discord.File(io.BytesIO(data), filename=filename))

                content = msg.content or None
                try:
                    await webhook.send(
                        content=content,
                        username=msg.author.display_name,
                        avatar_url=str(msg.author.display_avatar.url),
                        files=files if files else discord.utils.MISSING,
                        embeds=msg.embeds if msg.embeds else discord.utils.MISSING,
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except Exception as e:
                    print(f"[move] Failed to repost message {msg.id}: {e}")
        finally:
            await webhook.delete()

        # Delete original messages
        now_utc = datetime.now(timezone.utc)
        cutoff_bulk = now_utc - timedelta(days=14)
        recent_msgs = [m for m in collected if m.created_at > cutoff_bulk]
        old_msgs    = [m for m in collected if m.created_at <= cutoff_bulk]

        # Bulk delete recent messages
        if recent_msgs:
            try:
                # delete_messages accepts up to 100 at a time
                for i in range(0, len(recent_msgs), 100):
                    chunk = recent_msgs[i:i+100]
                    if len(chunk) == 1:
                        await chunk[0].delete()
                    else:
                        await interaction.channel.delete_messages(chunk)
            except Exception as e:
                print(f"[move] Bulk delete failed: {e}")

        # Delete old messages individually
        for msg in old_msgs:
            try:
                await msg.delete()
                await asyncio.sleep(0.5)
            except discord.NotFound:
                pass
            except Exception as e:
                print(f"[move] Failed to delete old message {msg.id}: {e}")

        # Post source channel notification
        source_embed = discord.Embed(
            title="📦 Conversation Moved",
            description=(
                f"Hey {user_mentions}! Your conversation has been moved to "
                f"{channel.mention} where it fits better. Head over there to continue!"
            ),
            color=0x5865F2,
        )
        source_embed.set_footer(text=BRAND_FOOTER)
        await interaction.channel.send(embed=source_embed)

        # Mod log
        mod_log_embed = discord.Embed(
            title="📦 Messages Moved",
            color=0x5865F2,
            timestamp=datetime.utcnow(),
        )
        mod_log_embed.add_field(name="Moved by", value=interaction.user.mention, inline=True)
        mod_log_embed.add_field(name="From",     value=interaction.channel.mention, inline=True)
        mod_log_embed.add_field(name="To",       value=channel.mention, inline=True)
        mod_log_embed.add_field(
            name="Users",
            value=" ".join(m.mention for m in target_members),
            inline=False,
        )
        mod_log_embed.add_field(name="Messages", value=str(len(collected)), inline=True)
        mod_log_embed.add_field(name="Time span", value=time, inline=True)
        mod_log_embed.set_footer(text=BRAND_FOOTER)
        await _post_modlog(interaction.guild, cfg or {}, mod_log_embed)

        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="MOVE",
            target_id=",".join(str(m.id) for m in target_members),
            target_username=", ".join(m.display_name for m in target_members),
            actor_id=str(interaction.user.id),
            actor_username=interaction.user.display_name,
            reason=f"Moved {len(collected)} messages from #{interaction.channel.name} to #{channel.name}",
        )

        # Confirm to mod
        await interaction.followup.send(
            f"✅ Moved **{len(collected)}** message(s) from {interaction.channel.mention} "
            f"to {channel.mention}.\nUsers: {user_mentions}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Move(bot))
