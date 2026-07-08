import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime, timezone
import json
import database as db
from utils import is_protected, get_bot_message, _fmt


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


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


async def _post_modlog(guild: discord.Guild, cfg: dict, embed: discord.Embed):
    ch_id = cfg.get("modlog_ch_id") if cfg else None
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            try:
                await ch.send(embed=embed)
            except discord.HTTPException:
                pass


# ── Cog ────────────────────────────────────────────────────────────────────────

class Honeypot(commands.Cog):
    """
    Honeypot channel -- any non-staff member who posts a message in a
    designated channel is immediately banned.  The channel acts as a
    trap for bots and spammers who blast every visible channel without
    reading its contents.

    Multiple honeypot channels can be configured per server.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Message listener ─────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignore bots, DMs, non-members
        if message.author.bot or message.guild is None:
            return
        if not isinstance(message.author, discord.Member):
            return

        cfg = db.get_config(message.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return

        # Check if this channel is a honeypot
        honeypot_channels = set(
            int(x) for x in _load_json_list(cfg.get("honeypot_channels"))
            if str(x).isdigit()
        )
        if message.channel.id not in honeypot_channels:
            return

        member = message.author
        guild = message.guild

        # Staff and protected members are immune
        if _is_staff(member, cfg):
            return
        if is_protected(member, cfg):
            return

        # Immune roles bypass honeypot (shares the automod immune list)
        immune_roles = set(_load_json_list(cfg.get("automod_immune_roles")))
        if any(str(r.id) in {str(i) for i in immune_roles} for r in member.roles):
            return

        # ── Trap sprung ──────────────────────────────────────────────────────

        # Delete the message
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

        # DM the user before banning (best effort)
        reason = "Honeypot -- posted in a restricted channel"
        try:
            text = _fmt(
                get_bot_message(db, str(guild.id), "ban_dm"),
                user=member.mention,
                reason=reason,
            )
            await member.send(
                embed=discord.Embed(
                    description=text,
                    color=discord.Color.red(),
                )
            )
        except (discord.Forbidden, discord.HTTPException):
            pass

        # Ban -- delete 1 day of messages to clean up any other spam
        acted = "Banned"
        try:
            await member.ban(reason=f"Honeypot: {reason}", delete_message_days=1)
        except discord.Forbidden:
            acted = "Ban failed (missing Ban Members permission)"
        except discord.HTTPException:
            acted = "Ban failed"

        # Persist to mod_logs
        try:
            bot_user = self.bot.user
            db.add_mod_log(
                guild_id=str(guild.id),
                action="BAN",
                target_id=str(member.id),
                target_username=str(member),
                actor_id=str(bot_user.id) if bot_user else "",
                actor_username="Honeypot",
                reason=f"Honeypot -- {reason}",
            )
        except Exception:
            pass

        # Post to mod-log channel
        embed = discord.Embed(
            title="🍯 Honeypot Triggered",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{member.mention} (`{member.id}`)", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Action", value=acted, inline=False)
        if message.content:
            snippet = message.content if len(message.content) <= 500 else message.content[:497] + "..."
            embed.add_field(name="Content", value=f"```{snippet}```", inline=False)
        embed.set_footer(text="Honeypot auto-ban")

        await _post_modlog(guild, cfg, embed)

    # ── /honeypot command group ──────────────────────────────────────────────
    honeypot_group = app_commands.Group(
        name="honeypot",
        description="Configure honeypot channels that auto-ban anyone who posts in them",
    )

    @honeypot_group.command(
        name="add",
        description="Designate a channel as a honeypot. Anyone who posts in it gets banned.",
    )
    @app_commands.describe(channel="The channel to turn into a honeypot trap")
    async def honeypot_add(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                "You need Manage Server permission to configure honeypots.", ephemeral=True
            )

        cfg = db.get_config(interaction.guild_id) or {}
        current = [int(x) for x in _load_json_list(cfg.get("honeypot_channels")) if str(x).isdigit()]

        if channel.id in current:
            return await interaction.response.send_message(
                f"{channel.mention} is already a honeypot channel.", ephemeral=True
            )

        current.append(channel.id)
        db.upsert_config(interaction.guild_id, honeypot_channels=_dump_json_list(current))

        await interaction.response.send_message(
            f"🍯 {channel.mention} is now a honeypot. Any non-staff member who posts there will be banned immediately.",
            ephemeral=True,
        )

    @honeypot_group.command(
        name="remove",
        description="Remove a channel from the honeypot list.",
    )
    @app_commands.describe(channel="The channel to remove from honeypot duty")
    async def honeypot_remove(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message(
                "You need Manage Server permission to configure honeypots.", ephemeral=True
            )

        cfg = db.get_config(interaction.guild_id) or {}
        current = [int(x) for x in _load_json_list(cfg.get("honeypot_channels")) if str(x).isdigit()]

        if channel.id not in current:
            return await interaction.response.send_message(
                f"{channel.mention} is not a honeypot channel.", ephemeral=True
            )

        current.remove(channel.id)
        db.upsert_config(interaction.guild_id, honeypot_channels=_dump_json_list(current))

        await interaction.response.send_message(
            f"🍯 {channel.mention} has been removed from the honeypot list.", ephemeral=True
        )

    @honeypot_group.command(
        name="list",
        description="Show all honeypot channels in this server.",
    )
    async def honeypot_list(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id) or {}
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        current = [int(x) for x in _load_json_list(cfg.get("honeypot_channels")) if str(x).isdigit()]

        if not current:
            return await interaction.response.send_message(
                "🍯 No honeypot channels configured. Use `/honeypot add` to set one up.",
                ephemeral=True,
            )

        lines = []
        for ch_id in current:
            ch = interaction.guild.get_channel(ch_id)
            if ch:
                lines.append(f"- {ch.mention}")
            else:
                lines.append(f"- `{ch_id}` (channel not found)")

        embed = discord.Embed(
            title="🍯 Honeypot Channels",
            description="\n".join(lines),
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text="Any non-staff post in these channels triggers an instant ban")

        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Honeypot(bot))
