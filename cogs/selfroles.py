import discord
from discord.ext import commands
import database as db


class SelfRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _emoji_str(self, emoji) -> str:
        """Normalise a raw reaction emoji to a consistent string key."""
        if isinstance(emoji, str):
            return emoji
        return str(emoji)

    async def _remove_unknown_reaction(
        self,
        guild: discord.Guild,
        channel_id: int,
        message_id: int,
        emoji,
        member: discord.Member,
    ):
        """Remove an unrecognised reaction to keep self-roles messages clean."""
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.remove_reaction(emoji, member)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    # ── on_raw_reaction_add ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None:
            return

        # Find which category (if any) owns this message
        category = db.get_selfrole_category_by_message(
            str(payload.guild_id), str(payload.message_id)
        )
        if category is None:
            return  # Not a self-roles message — ignore entirely

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = payload.member or guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        emoji_key = self._emoji_str(payload.emoji)
        roles     = db.get_selfrole_roles(category["category_id"])
        role_row  = next((r for r in roles if r["emoji"] == emoji_key), None)

        if role_row is None:
            # Emoji not mapped to any role in this category — remove it
            await self._remove_unknown_reaction(
                guild, payload.channel_id, payload.message_id, payload.emoji, member
            )
            return

        role = guild.get_role(int(role_row["role_id"]))
        if role is None:
            return  # Role was deleted from Discord

        # Per-role toggle: 1 = single-select, 0 = multi-select
        # Fall back to category enforcement for legacy rows without toggle
        is_single = bool(role_row.get("toggle", 0)) or category["enforcement"] == "single"

        if is_single:
            # Single-select: strip every other role in this category first
            category_role_ids = {int(r["role_id"]) for r in roles}
            roles_to_remove = [
                r for r in member.roles
                if r.id in category_role_ids and r.id != role.id
            ]
            if roles_to_remove:
                await member.remove_roles(
                    *roles_to_remove,
                    reason=f"SelfRoles: {category['name']} switch",
                )
            if role not in member.roles:
                await member.add_roles(
                    role, reason=f"SelfRoles: {category['name']} {emoji_key}"
                )
        else:
            # Multi-select: just add the role if not already held
            if role not in member.roles:
                await member.add_roles(
                    role, reason=f"SelfRoles: {category['name']} {emoji_key}"
                )

    # ── on_raw_reaction_remove ────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None:
            return

        category = db.get_selfrole_category_by_message(
            str(payload.guild_id), str(payload.message_id)
        )
        if category is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        emoji_key = self._emoji_str(payload.emoji)
        roles     = db.get_selfrole_roles(category["category_id"])
        role_row  = next((r for r in roles if r["emoji"] == emoji_key), None)
        if role_row is None:
            return  # Emoji not mapped — nothing to remove

        role = guild.get_role(int(role_row["role_id"]))
        if role and role in member.roles:
            await member.remove_roles(
                role,
                reason=f"SelfRoles: removed {category['name']} {emoji_key}",
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(SelfRoles(bot))
