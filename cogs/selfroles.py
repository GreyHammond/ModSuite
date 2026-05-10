import discord
from discord.ext import commands
import database as db


class SelfRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_color_role(self, guild: discord.Guild, emoji_str: str, cfg: dict) -> discord.Role | None:
        """Return the Discord role for a given emoji string, or None."""
        color_roles: dict = cfg.get("color_roles", {})
        role_id = color_roles.get(emoji_str)
        if role_id is None:
            return None
        return guild.get_role(int(role_id))

    def _emoji_str(self, emoji) -> str:
        """Normalise a raw reaction emoji to a string key."""
        if isinstance(emoji, str):
            return emoji
        # Custom emoji → "<:name:id>"
        return str(emoji)

    async def _is_selfroles_message(self, guild_id: int, message_id: int) -> bool:
        cfg = db.get_config(guild_id)
        if cfg is None:
            return False
        return cfg.get("selfroles_msg_id") == message_id

    # ── on_raw_reaction_add ───────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None:
            return
        if not await self._is_selfroles_message(payload.guild_id, payload.message_id):
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = payload.member or guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        cfg = db.get_config(payload.guild_id)
        emoji_key = self._emoji_str(payload.emoji)
        role = self._get_color_role(guild, emoji_key, cfg)
        if role is None:
            return

        # Remove any other color roles the user already has
        color_role_ids = set(int(v) for v in cfg["color_roles"].values())
        roles_to_remove = [r for r in member.roles if r.id in color_role_ids and r.id != role.id]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="SelfRoles: color switch")

        if role not in member.roles:
            await member.add_roles(role, reason=f"SelfRoles: reacted {emoji_key}")

    # ── on_raw_reaction_remove ────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None:
            return
        if not await self._is_selfroles_message(payload.guild_id, payload.message_id):
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        cfg = db.get_config(payload.guild_id)
        emoji_key = self._emoji_str(payload.emoji)
        role = self._get_color_role(guild, emoji_key, cfg)
        if role is None:
            return

        if role in member.roles:
            await member.remove_roles(role, reason=f"SelfRoles: removed reaction {emoji_key}")

    # ── Guard: prevent anyone adding new emojis to the self-roles message ─────
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):  # noqa: F811
        """Combined handler: guard unknown emojis AND assign roles."""
        if payload.user_id == self.bot.user.id:
            return
        if payload.guild_id is None:
            return
        if not await self._is_selfroles_message(payload.guild_id, payload.message_id):
            return

        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = payload.member or guild.get_member(payload.user_id)
        if member is None or member.bot:
            return

        cfg = db.get_config(payload.guild_id)
        emoji_key = self._emoji_str(payload.emoji)
        role = self._get_color_role(guild, emoji_key, cfg)

        if role is None:
            # Unknown emoji — remove it to keep the message clean
            channel = guild.get_channel(payload.channel_id)
            if channel:
                msg = await channel.fetch_message(payload.message_id)
                await msg.remove_reaction(payload.emoji, member)
            return

        # Remove any other color roles
        color_role_ids = set(int(v) for v in cfg["color_roles"].values())
        roles_to_remove = [r for r in member.roles if r.id in color_role_ids and r.id != role.id]
        if roles_to_remove:
            await member.remove_roles(*roles_to_remove, reason="SelfRoles: color switch")

        if role not in member.roles:
            await member.add_roles(role, reason=f"SelfRoles: reacted {emoji_key}")


async def setup(bot: commands.Bot):
    await bot.add_cog(SelfRoles(bot))
