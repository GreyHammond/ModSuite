"""
cogs/starboard.py — Customisable multi-board starboard system.
Multiple named boards, each with their own emoji triggers, channels, and thresholds.
Self-reacts are ignored. NSFW boards only pull from NSFW channels.
On edit: logs original to mod-log, updates board embed with edit notice.
"""

import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

import database as db

BRAND_FOOTER = "ModSuite · Hammond Digital Studios"


def _emoji_key(emoji: discord.PartialEmoji | discord.Emoji | str) -> str:
    """Normalise an emoji to a string key matching what's stored in DB."""
    if isinstance(emoji, str):
        return emoji
    if emoji.id:
        return f"<:{emoji.name}:{emoji.id}>"
    return emoji.name


def _build_starboard_embed(message: discord.Message, board_name: str,
                           edited: bool = False) -> discord.Embed:
    embed = discord.Embed(
        description=message.content or "",
        color=0xF0B429,
        timestamp=message.created_at,
    )
    embed.set_author(
        name=message.author.display_name,
        icon_url=str(message.author.display_avatar.url),
    )
    embed.add_field(
        name="Source",
        value=f"[Jump to message]({message.jump_url}) in <#{message.channel.id}>",
        inline=False,
    )

    # Attach first image if present
    for att in message.attachments:
        if att.content_type and att.content_type.startswith("image/"):
            embed.set_image(url=att.url)
            break

    # If message has image embeds (link previews), use the first one
    if not embed.image:
        for e in message.embeds:
            if e.image:
                embed.set_image(url=e.image.url)
                break
            if e.thumbnail:
                embed.set_image(url=e.thumbnail.url)
                break

    footer_text = f"⭐ {board_name}"
    if edited:
        footer_text += "  |  ✏️ This message was edited after being posted"
    footer_text += f"  |  {BRAND_FOOTER}"
    embed.set_footer(text=footer_text)

    return embed


async def _post_modlog(guild: discord.Guild, embed: discord.Embed):
    cfg = db.get_config(guild.id)
    ch_id = cfg.get("modlog_ch_id") if cfg else None
    if ch_id:
        ch = guild.get_channel(int(ch_id))
        if ch:
            await ch.send(embed=embed)


class Starboard(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Admin Commands ────────────────────────────────────────────────────────

    starboard_group = app_commands.Group(
        name="starboard",
        description="Manage starboard configurations.",
        default_permissions=discord.Permissions(administrator=True),
    )

    @starboard_group.command(
        name="create",
        description="[Admin] Create a new starboard.",
    )
    @app_commands.describe(
        name="Name for this board (e.g. quotes, best-clips)",
        channel="Channel to post highlighted messages to",
        emoji="Trigger emoji",
        threshold="How many reactions needed (default 5)",
        nsfw_only="Only pull from NSFW channels?",
    )
    async def starboard_create(
        self,
        interaction: discord.Interaction,
        name: str,
        channel: discord.TextChannel,
        emoji: str,
        threshold: int = 5,
        nsfw_only: bool = False,
    ):
        guild_id = str(interaction.guild_id)
        name = name.lower().strip().replace(" ", "-")

        existing = db.get_starboard(guild_id, name)
        if existing:
            await interaction.response.send_message(
                f"❌ A board named **{name}** already exists.", ephemeral=True
            )
            return

        if threshold < 1:
            await interaction.response.send_message(
                "❌ Threshold must be at least 1.", ephemeral=True
            )
            return

        board_id = db.create_starboard(guild_id, name, str(channel.id), threshold, int(nsfw_only))
        db.add_starboard_emoji(board_id, emoji)

        await interaction.response.send_message(
            f"✅ Created board **{name}** → {channel.mention}\n"
            f"Emoji: {emoji} | Threshold: {threshold} | NSFW only: {'Yes' if nsfw_only else 'No'}",
            ephemeral=True,
        )

    @starboard_group.command(
        name="delete",
        description="[Admin] Delete a starboard and all its entries.",
    )
    @app_commands.describe(name="Board name to delete")
    async def starboard_delete(self, interaction: discord.Interaction, name: str):
        guild_id = str(interaction.guild_id)
        name = name.lower().strip()
        deleted = db.delete_starboard(guild_id, name)
        if deleted:
            await interaction.response.send_message(
                f"✅ Board **{name}** deleted.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ No board named **{name}** found.", ephemeral=True
            )

    @starboard_group.command(
        name="addemoji",
        description="[Admin] Add a trigger emoji to an existing board.",
    )
    @app_commands.describe(name="Board name", emoji="Emoji to add")
    async def starboard_addemoji(self, interaction: discord.Interaction, name: str, emoji: str):
        guild_id = str(interaction.guild_id)
        board = db.get_starboard(guild_id, name.lower().strip())
        if not board:
            await interaction.response.send_message(
                f"❌ No board named **{name}** found.", ephemeral=True
            )
            return
        added = db.add_starboard_emoji(board["board_id"], emoji)
        if added:
            await interaction.response.send_message(
                f"✅ Added {emoji} to **{name}**.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ {emoji} is already on **{name}**.", ephemeral=True
            )

    @starboard_group.command(
        name="removeemoji",
        description="[Admin] Remove a trigger emoji from a board.",
    )
    @app_commands.describe(name="Board name", emoji="Emoji to remove")
    async def starboard_removeemoji(self, interaction: discord.Interaction, name: str, emoji: str):
        guild_id = str(interaction.guild_id)
        board = db.get_starboard(guild_id, name.lower().strip())
        if not board:
            await interaction.response.send_message(
                f"❌ No board named **{name}** found.", ephemeral=True
            )
            return
        removed = db.remove_starboard_emoji(board["board_id"], emoji)
        if removed:
            await interaction.response.send_message(
                f"✅ Removed {emoji} from **{name}**.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ {emoji} wasn't on **{name}**.", ephemeral=True
            )

    @starboard_group.command(
        name="threshold",
        description="[Admin] Change how many reactions are needed for a board.",
    )
    @app_commands.describe(name="Board name", threshold="New threshold")
    async def starboard_threshold(self, interaction: discord.Interaction, name: str, threshold: int):
        guild_id = str(interaction.guild_id)
        board = db.get_starboard(guild_id, name.lower().strip())
        if not board:
            await interaction.response.send_message(
                f"❌ No board named **{name}** found.", ephemeral=True
            )
            return
        if threshold < 1:
            await interaction.response.send_message(
                "❌ Threshold must be at least 1.", ephemeral=True
            )
            return
        db.update_starboard_threshold(board["board_id"], threshold)
        await interaction.response.send_message(
            f"✅ **{name}** threshold updated to **{threshold}**.", ephemeral=True
        )

    @starboard_group.command(
        name="list",
        description="[Admin] View all configured starboards.",
    )
    async def starboard_list(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        boards = db.get_all_starboards(guild_id)
        if not boards:
            await interaction.response.send_message(
                "ℹ️ No starboards configured. Use `/starboard create` to set one up.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title="⭐ Starboard Configuration", color=0xF0B429)
        for b in boards:
            emojis = db.get_starboard_emojis(b["board_id"])
            emoji_str = " ".join(emojis) if emojis else "None"
            nsfw_tag = " | NSFW only" if b["nsfw_only"] else ""
            embed.add_field(
                name=b["name"],
                value=f"Channel: <#{b['channel_id']}>\nEmojis: {emoji_str}\nThreshold: {b['threshold']}{nsfw_tag}",
                inline=False,
            )
        embed.set_footer(text=BRAND_FOOTER)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── Reaction Listener ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return

        emoji = _emoji_key(payload.emoji)
        guild_id = str(payload.guild_id)

        # Find board for this emoji
        board = db.get_board_for_emoji(guild_id, emoji)
        if board is None:
            return

        # Already posted?
        existing = db.get_starboard_entry(board["board_id"], str(payload.message_id))
        if existing:
            return

        # Fetch the source message
        source_channel = guild.get_channel(payload.channel_id)
        if source_channel is None:
            return

        # NSFW check
        if board["nsfw_only"] and not getattr(source_channel, "nsfw", False):
            return

        try:
            message = await source_channel.fetch_message(payload.message_id)
        except (discord.NotFound, discord.Forbidden):
            return

        # Don't starboard bot messages
        if message.author.bot:
            return

        # Count qualifying reactions (exclude self-reacts from the author)
        count = 0
        for reaction in message.reactions:
            reaction_key = _emoji_key(reaction.emoji)
            # Check if this reaction emoji is registered for this board
            board_emojis = db.get_starboard_emojis(board["board_id"])
            if reaction_key not in board_emojis:
                continue
            async for user in reaction.users():
                if user.id != message.author.id and not user.bot:
                    count += 1

        if count < board["threshold"]:
            return

        # Post to board channel
        board_channel = guild.get_channel(int(board["channel_id"]))
        if board_channel is None:
            return

        embed = _build_starboard_embed(message, board["name"])
        try:
            board_msg = await board_channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            return

        db.add_starboard_entry(
            board_id=board["board_id"],
            source_message_id=str(message.id),
            source_channel_id=str(message.channel.id),
            board_message_id=str(board_msg.id),
            original_content=message.content or "",
        )

    # ── Edit Listener ─────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if payload.guild_id is None:
            return

        guild_id = str(payload.guild_id)
        message_id = str(payload.message_id)

        # Check all boards for this guild
        boards = db.get_all_starboards(guild_id)
        for board in boards:
            entry = db.get_starboard_entry(board["board_id"], message_id)
            if entry is None:
                continue

            guild = self.bot.get_guild(payload.guild_id)
            if guild is None:
                return

            # Fetch the edited source message
            source_channel = guild.get_channel(int(entry["source_channel_id"]))
            if source_channel is None:
                continue

            try:
                message = await source_channel.fetch_message(int(message_id))
            except (discord.NotFound, discord.Forbidden):
                continue

            # Log original content to mod-log
            if entry["original_content"] and entry["original_content"] != message.content:
                log_embed = discord.Embed(
                    title="✏️ Starboard — Original Message Edited",
                    color=0xE67E22,
                    timestamp=datetime.utcnow(),
                )
                log_embed.add_field(
                    name="Author",
                    value=f"{message.author} (`{message.author.id}`)",
                    inline=True,
                )
                log_embed.add_field(
                    name="Board",
                    value=board["name"],
                    inline=True,
                )
                log_embed.add_field(
                    name="Original Content",
                    value=entry["original_content"][:1024] or "(empty)",
                    inline=False,
                )
                log_embed.add_field(
                    name="New Content",
                    value=message.content[:1024] or "(empty)",
                    inline=False,
                )
                log_embed.add_field(
                    name="Source",
                    value=f"[Jump]({message.jump_url})",
                    inline=True,
                )
                log_embed.set_footer(text=BRAND_FOOTER)
                await _post_modlog(guild, log_embed)

            # Delete old board message and post updated one
            board_channel = guild.get_channel(int(board["channel_id"]))
            if board_channel is None:
                continue

            try:
                old_board_msg = await board_channel.fetch_message(int(entry["board_message_id"]))
                await old_board_msg.delete()
            except (discord.NotFound, discord.Forbidden):
                pass

            # Post new embed with edit notice
            new_embed = _build_starboard_embed(message, board["name"], edited=True)
            try:
                new_board_msg = await board_channel.send(embed=new_embed)
                db.update_starboard_entry_content(entry["entry_id"], str(new_board_msg.id))
            except (discord.Forbidden, discord.HTTPException):
                continue


async def setup(bot: commands.Bot):
    await bot.add_cog(Starboard(bot))
