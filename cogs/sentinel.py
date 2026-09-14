"""
Sentinel cog -- forensic message archive.

Ported from the standalone Sentinel bot (Hammond Digital Studios) onto
ModSuite's foundations. Three things changed in the port, each because the
original would not survive a public server:

1. Storage is SQLite, not `logs.json`. The original read and rewrote the whole
   JSON file on every message; one crash mid-write lost the archive.
2. Vault files are served through the authenticated dashboard route, not a
   public StaticFiles mount. The original exposed every archived attachment at
   a guessable URL with no login.
3. Retention actually runs. The original had no purge logic of any kind, so it
   grew without limit despite being described as a 30-day rolling window.

Scope defaults to public channels only. Private categories -- ModMail, the
Pull Room, the Round Table, contributors, newsroom -- are excluded, because a
bulk archive of private deliberation is the part that carries legal exposure
and offers the least newsgathering value.
"""
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from config import FOOTER_BRAND, BRAND_COLOR

log = logging.getLogger("ModSuite.sentinel")

VAULT_DIR = Path(os.getenv("VAULT_DIR", "vault"))
VAULT_DIR.mkdir(parents=True, exist_ok=True)

# Attachments larger than this are recorded as metadata only. Archiving a
# 300 MB upload to preserve a deleted message is not worth the disk.
MAX_VAULT_BYTES = int(os.getenv("VAULT_MAX_BYTES", str(25 * 1024 * 1024)))

# Categories excluded by default under 'public' scope, matched case-insensitively
DEFAULT_PRIVATE_CATEGORIES = {
    "modmail", "pull room", "the round table", "cfj contributors",
    "cfj newsroom", "jail",
}


def _is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator


def _vault_name(message_id: int, index: int, original: str) -> str:
    safe = re.sub(r"[^\w.\-]", "_", original)[:120]
    return f"{message_id}__{index}__{safe}"


def _load_list(raw) -> list:
    try:
        return json.loads(raw) if raw else []
    except (json.JSONDecodeError, TypeError):
        return []


class Sentinel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.retention_loop.start()

    def cog_unload(self):
        self.retention_loop.cancel()

    # ── Scope ────────────────────────────────────────────────────────────────
    def _should_archive(self, message: discord.Message, cfg: dict) -> bool:
        if message.guild is None or message.author.bot:
            return False
        if not cfg or not cfg.get("archive_enabled"):
            return False

        channel = message.channel
        if str(channel.id) in {str(x) for x in _load_list(cfg.get("archive_excluded_channels"))}:
            return False

        category = getattr(channel, "category", None)
        if category is not None:
            if str(category.id) in {str(x) for x in _load_list(cfg.get("archive_excluded_categories"))}:
                return False
            if (cfg.get("archive_scope") or "public") == "public":
                if category.name.lower() in DEFAULT_PRIVATE_CATEGORIES:
                    return False

        # Under 'public' scope, a channel @everyone cannot see is not public.
        if (cfg.get("archive_scope") or "public") == "public":
            try:
                if not channel.permissions_for(message.guild.default_role).view_channel:
                    return False
            except (AttributeError, TypeError):
                pass
        return True

    # ── Vault ────────────────────────────────────────────────────────────────
    async def _save_attachments(self, message: discord.Message) -> list[dict]:
        saved = []
        if not message.attachments:
            return saved
        async with aiohttp.ClientSession() as session:
            for i, att in enumerate(message.attachments):
                entry = {
                    "filename": att.filename,
                    "size": att.size,
                    "content_type": att.content_type,
                    "url": att.url,
                    "vault": None,
                }
                if att.size and att.size > MAX_VAULT_BYTES:
                    entry["skipped"] = "too large"
                    saved.append(entry)
                    continue
                name = _vault_name(message.id, i, att.filename)
                path = VAULT_DIR / name
                try:
                    async with session.get(att.url) as resp:
                        if resp.status == 200:
                            path.write_bytes(await resp.read())
                            entry["vault"] = name
                except (aiohttp.ClientError, OSError) as e:
                    log.warning(f"Vault save failed for {att.filename}: {e}")
                saved.append(entry)
        return saved

    # ── Listeners ────────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild is None:
            return
        cfg = db.get_config(message.guild.id)
        if not self._should_archive(message, cfg):
            return
        attachments = await self._save_attachments(message)
        db.archive_message(
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            channel_name=getattr(message.channel, "name", ""),
            message_id=str(message.id),
            author_id=str(message.author.id),
            author_name=str(message.author),
            content=message.content or "",
            attachments=attachments,
            created_at=message.created_at.isoformat(),
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if after.guild is None or before.content == after.content:
            return
        cfg = db.get_config(after.guild.id)
        if not self._should_archive(after, cfg):
            return
        db.archive_record_edit(str(after.id), after.content or "")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.guild is None:
            return
        cfg = db.get_config(message.guild.id)
        if not cfg or not cfg.get("archive_enabled"):
            return

        record = db.archive_mark_deleted(str(message.id))
        if record is None:
            return

        channel_id = cfg.get("archive_restore_channel")
        if not channel_id:
            return
        restore = self.bot.get_channel(int(channel_id))
        if restore is None:
            return

        await self._post_restore(restore, record)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: list[discord.Message]):
        # Fires on a purge. Without this, a moderator clearing a channel wipes
        # the very messages the archive exists to preserve.
        for message in messages:
            await self.on_message_delete(message)

    async def _post_restore(self, restore: discord.TextChannel, record: dict):
        author = record.get("author_name") or record.get("author_id")
        embed = discord.Embed(
            title="Deleted message recovered",
            description=(record.get("content") or "*no text content*")[:4000],
            colour=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Author", value=f"{author}\n`{record['author_id']}`", inline=True)
        embed.add_field(name="Channel", value=f"<#{record['channel_id']}>", inline=True)
        embed.add_field(name="Posted", value=record.get("created_at", "")[:19], inline=True)
        if record.get("edited"):
            embed.add_field(
                name="Note",
                value="This message was edited before deletion. Full revision history is in the dashboard.",
                inline=False,
            )
        embed.set_footer(text=FOOTER_BRAND)

        files = []
        for att in record.get("attachments", []):
            vault_name = att.get("vault")
            if not vault_name:
                continue
            path = VAULT_DIR / vault_name
            if path.exists() and path.stat().st_size < 8 * 1024 * 1024:
                try:
                    files.append(discord.File(str(path), filename=att["filename"]))
                except OSError:
                    pass
        if record.get("attachments") and not files:
            embed.add_field(
                name="Attachments",
                value=f"{len(record['attachments'])} file(s) held in the vault. "
                      f"View them in the dashboard archive.",
                inline=False,
            )

        try:
            await restore.send(embed=embed, files=files[:10])
        except discord.HTTPException as e:
            log.warning(f"Restore post failed: {e}")

    # ── Retention ────────────────────────────────────────────────────────────
    @tasks.loop(hours=6)
    async def retention_loop(self):
        """
        Rolling delete. The original Sentinel described this behaviour but never
        implemented it, so archives grew without bound.
        """
        for guild in self.bot.guilds:
            cfg = db.get_config(guild.id)
            if not cfg or not cfg.get("archive_enabled"):
                continue
            days = int(cfg.get("archive_retention_days") or 30)
            if days <= 0:
                continue
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

            expired = db.archive_expired(str(guild.id), cutoff)
            if not expired:
                continue

            # Remove vault files first; a crash between the two leaves orphan
            # files rather than DB rows pointing at nothing.
            removed_files = 0
            for row in expired:
                for att in row.get("attachments", []):
                    name = att.get("vault")
                    if not name:
                        continue
                    path = VAULT_DIR / name
                    try:
                        if path.exists():
                            path.unlink()
                            removed_files += 1
                    except OSError as e:
                        log.warning(f"Vault purge failed for {name}: {e}")

            deleted = db.archive_delete_ids([r["id"] for r in expired])
            log.info(
                f"[{guild.name}] Archive retention: purged {deleted} message(s) "
                f"and {removed_files} vault file(s) older than {days} days."
            )

    @retention_loop.before_loop
    async def _before_retention(self):
        await self.bot.wait_until_ready()

    # ── Commands ─────────────────────────────────────────────────────────────
    archive_group = app_commands.Group(
        name="archive",
        description="Forensic message archive.",
    )

    @archive_group.command(name="setup", description="Turn the archive on and set the restore channel.")
    @app_commands.describe(
        restore_channel="Private channel where deleted messages are reposted",
        retention_days="How many days to keep messages (default 30)",
        scope="public = open channels only (recommended). all = every channel.",
    )
    @app_commands.choices(scope=[
        app_commands.Choice(name="Public channels only (recommended)", value="public"),
        app_commands.Choice(name="Every channel", value="all"),
    ])
    async def archive_setup(self, interaction: discord.Interaction,
                            restore_channel: discord.TextChannel,
                            retention_days: int = 30,
                            scope: str = "public"):
        if not _is_admin(interaction):
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        if retention_days < 1 or retention_days > 365:
            return await interaction.response.send_message(
                "Retention must be between 1 and 365 days.", ephemeral=True)

        db.upsert_config(
            interaction.guild_id,
            archive_enabled=1,
            archive_restore_channel=restore_channel.id,
            archive_retention_days=retention_days,
            archive_scope=scope,
        )
        e = discord.Embed(title="Archive enabled", colour=BRAND_COLOR)
        e.add_field(name="Restore channel", value=restore_channel.mention, inline=True)
        e.add_field(name="Retention", value=f"{retention_days} days", inline=True)
        e.add_field(name="Scope", value=scope, inline=True)
        if scope == "all":
            e.add_field(
                name="Warning",
                value=("Archiving every channel includes ModMail and private "
                       "staff discussion. That archive is discoverable. "
                       "`public` is the safer default."),
                inline=False,
            )
        e.add_field(
            name="Disclose this",
            value="Tell members in writing that messages are logged. An undisclosed "
                  "archive is surveillance; a disclosed one is a public record.",
            inline=False,
        )
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @archive_group.command(name="off", description="Stop archiving new messages.")
    async def archive_off(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        db.upsert_config(interaction.guild_id, archive_enabled=0)
        await interaction.response.send_message(
            "Archiving stopped. Existing records are kept and will still age out "
            "on the retention schedule.", ephemeral=True)

    @archive_group.command(name="status", description="Show archive settings and size.")
    async def archive_status(self, interaction: discord.Interaction):
        if not _is_admin(interaction):
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        stats = db.archive_stats(str(interaction.guild_id))
        vault_files = len(list(VAULT_DIR.glob("*"))) if VAULT_DIR.exists() else 0
        vault_mb = sum(f.stat().st_size for f in VAULT_DIR.glob("*") if f.is_file()) / (1024 * 1024)

        e = discord.Embed(title="Archive status", colour=BRAND_COLOR)
        e.add_field(name="Enabled", value="yes" if cfg.get("archive_enabled") else "no", inline=True)
        e.add_field(name="Scope", value=cfg.get("archive_scope") or "public", inline=True)
        e.add_field(name="Retention", value=f"{cfg.get('archive_retention_days') or 30} days", inline=True)
        e.add_field(name="Messages held", value=f"{stats['total']:,}", inline=True)
        e.add_field(name="Deleted recovered", value=f"{stats['deleted']:,}", inline=True)
        e.add_field(name="Vault", value=f"{vault_files} files · {vault_mb:.1f} MB", inline=True)
        if stats["oldest"]:
            e.add_field(name="Oldest record", value=stats["oldest"][:19], inline=False)
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @archive_group.command(name="exclude", description="Exclude a channel from archiving.")
    @app_commands.describe(channel="Channel to stop archiving")
    async def archive_exclude(self, interaction: discord.Interaction,
                              channel: discord.TextChannel):
        if not _is_admin(interaction):
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        cfg = db.get_config(interaction.guild_id) or {}
        excluded = _load_list(cfg.get("archive_excluded_channels"))
        if str(channel.id) in {str(x) for x in excluded}:
            return await interaction.response.send_message(
                f"{channel.mention} is already excluded.", ephemeral=True)
        excluded.append(str(channel.id))
        db.upsert_config(interaction.guild_id,
                         archive_excluded_channels=json.dumps(excluded))
        await interaction.response.send_message(
            f"{channel.mention} will no longer be archived.", ephemeral=True)

    @archive_group.command(name="purge", description="Immediately delete archived messages older than N days.")
    @app_commands.describe(older_than_days="Delete records older than this many days",
                           confirm="Must be True")
    async def archive_purge(self, interaction: discord.Interaction,
                            older_than_days: int, confirm: bool = False):
        if not _is_admin(interaction):
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        if not confirm:
            return await interaction.response.send_message(
                f"This permanently deletes archived messages older than "
                f"{older_than_days} days. Re-run with `confirm:True`.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
        expired = db.archive_expired(str(interaction.guild_id), cutoff)
        files = 0
        for row in expired:
            for att in row.get("attachments", []):
                name = att.get("vault")
                if name and (VAULT_DIR / name).exists():
                    try:
                        (VAULT_DIR / name).unlink()
                        files += 1
                    except OSError:
                        pass
        count = db.archive_delete_ids([r["id"] for r in expired])
        await interaction.followup.send(
            f"Purged {count:,} message(s) and {files} vault file(s).", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Sentinel(bot))
