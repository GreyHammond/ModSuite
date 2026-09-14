import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import zipfile
import io
import json
import logging
import database as db
import config

log = logging.getLogger("ModSuite.ModMail")

# Extensions Discord renders inline. Anything else is relayed as a plain file.
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp")

# Fallback when the guild's real limit cannot be read. 10 MB is the floor for
# an unboosted guild, so it is always safe.
_DEFAULT_UPLOAD_LIMIT = 10 * 1024 * 1024


def _is_image(filename: str) -> bool:
    return filename.lower().endswith(_IMAGE_EXTS)


def _upload_limit(guild: "discord.Guild | None") -> int:
    """The guild's real attachment ceiling, which rises with boost tier."""
    try:
        return int(guild.filesize_limit)
    except Exception:
        return _DEFAULT_UPLOAD_LIMIT


def _describe_size(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} B"


async def _download_attachments(attachments, limit: int):
    """
    Pull attachment bytes down so they can be re-uploaded.

    Re-uploading rather than linking is deliberate. Discord's CDN URLs are
    signed and expire within about 24 hours, so a ticket that only stored links
    would have dead media by the time anyone reviewed the transcript. The copy
    the bot uploads lives as long as the message does.

    Returns (files, oversized, failed) where `files` are ready-to-send
    discord.File objects and the other two are attachment objects that could
    not be included.
    """
    files, oversized, failed = [], [], []
    for att in attachments:
        if att.size > limit:
            oversized.append(att)
            continue
        try:
            buf = io.BytesIO(await att.read())
            buf.seek(0)
            files.append(discord.File(
                buf,
                filename=att.filename,
                spoiler=att.is_spoiler(),
            ))
        except (discord.HTTPException, discord.NotFound, discord.Forbidden) as e:
            log.warning("Could not download attachment %s: %s", att.filename, e)
            failed.append(att)
    return files, oversized, failed


def _attachment_records(attachments) -> list[dict]:
    """Metadata persisted alongside the message so transcripts stay complete."""
    return [{
        "filename": a.filename,
        "size": a.size,
        "content_type": a.content_type,
        "url": a.url,
        "spoiler": a.is_spoiler(),
    } for a in attachments]


def _record_relayed_urls(records: list[dict], sent_message) -> None:
    """
    Point each stored record at the bot's re-uploaded copy.

    The original URL on the user's DM expires, but the copy in the ticket
    channel lives as long as that message does, which is what the transcript
    packer fetches from on close.
    """
    if sent_message is None:
        return
    by_name = {a.filename: a.url for a in sent_message.attachments}
    for rec in records:
        if rec["filename"] in by_name:
            rec["relayed_url"] = by_name[rec["filename"]]


def _attachment_note(oversized, failed, limit: int) -> str:
    """Explain, in the channel, anything that could not be relayed."""
    parts = []
    for a in oversized:
        parts.append(
            f"\u26a0\ufe0f **{a.filename}** ({_describe_size(a.size)}) exceeds this "
            f"server's {_describe_size(limit)} upload limit, so it could not be "
            f"copied across. Original link (expires within ~24h): {a.url}"
        )
    for a in failed:
        parts.append(
            f"\u26a0\ufe0f **{a.filename}** could not be downloaded from Discord. "
            f"Original link (expires within ~24h): {a.url}"
        )
    return "\n".join(parts)


def _staff_embed(author_name: str, content: str, anonymous: bool,
                 inline_image: "str | None" = None) -> discord.Embed:
    display = "Staff" if anonymous else author_name
    embed = discord.Embed(
        description=content or None,
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name=f"💬 {display}")
    if inline_image:
        embed.set_image(url=inline_image)
    return embed


def _user_embed(author_name: str, content: str,
                attachments: "list | None" = None,
                inline_image: "str | None" = None) -> discord.Embed:
    """
    `inline_image` is an ``attachment://filename`` reference pointing at a file
    sent in the same message, which makes the image render inside the embed
    rather than as a separate block underneath it.
    """
    embed = discord.Embed(
        description=content or None,
        color=discord.Color.gold(),
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name=f"📨 {author_name}")
    if inline_image:
        embed.set_image(url=inline_image)
    if attachments:
        names = ", ".join(f"`{a.filename}` ({_describe_size(a.size)})" for a in attachments)
        embed.add_field(
            name=f"📎 Attachment{'s' if len(attachments) > 1 else ''} ({len(attachments)})",
            value=names[:1024],
            inline=False,
        )
    return embed


def _build_transcript(ticket: dict, messages: list[dict]) -> str:
    lines = [
        f"ModMail Transcript",
        f"Ticket ID : {ticket['id']}",
        f"User ID   : {ticket['user_id']}",
        f"Opened    : {ticket['opened_at']}",
        f"Closed    : {ticket.get('closed_at', 'N/A')}",
        "=" * 60,
        "",
    ]
    for msg in messages:
        direction = "→ USER" if msg["direction"] == "to_user" else "← USER"
        anon_tag  = " [anon]" if msg["anonymous"] else ""
        lines.append(f"[{msg['timestamp']}] {direction} {msg['author_name']}{anon_tag}:")
        if msg.get("content"):
            lines.append(f"  {msg['content']}")
        for att in msg.get("attachments") or []:
            lines.append(
                f"  [attachment] {att.get('filename')} "
                f"({_describe_size(att.get('size') or 0)})"
                f"{' -- see media/ folder' if att.get('_archived') else ''}"
            )
        if not msg.get("content") and not (msg.get("attachments") or []):
            lines.append("  (empty message)")
        lines.append("")
    return "\n".join(lines)


async def _fetch_bytes(url: str) -> "bytes | None":
    """Fetch a CDN URL. Returns None on any failure rather than raising."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception as e:
        log.warning("Could not fetch %s: %s", url, e)
        return None


async def _collect_media(messages: list[dict], budget: int) -> list[tuple]:
    """
    Download every attachment the ticket carried, for bundling into the
    transcript zip.

    This has to happen before the ticket channel is deleted: the re-uploaded
    copies live on that channel's messages, so deleting it takes the media with
    it. Without this step a closed ticket would keep a text log referencing
    files nobody can ever open again.

    Returns [(archive_path, bytes)], newest skipped once `budget` is exhausted.
    """
    collected, used, seen = [], 0, set()
    for msg in messages:
        for att in msg.get("attachments") or []:
            url = att.get("relayed_url") or att.get("url")
            name = att.get("filename") or "file"
            if not url:
                continue
            size = att.get("size") or 0
            if used + size > budget:
                continue
            data = await _fetch_bytes(url)
            if data is None:
                continue

            # Two users can both send "image.png"; keep both.
            path = f"media/{name}"
            n = 1
            while path in seen:
                stem, _, ext = name.rpartition(".")
                path = f"media/{stem or name}_{n}{('.' + ext) if stem else ''}"
                n += 1
            seen.add(path)

            collected.append((path, data))
            used += len(data)
            att["_archived"] = True
    return collected


class ReplyModal(discord.ui.Modal, title="Reply to User"):
    message = discord.ui.TextInput(
        label="Your message",
        style=discord.TextStyle.long,
        max_length=1800,
    )
    anonymous = discord.ui.TextInput(
        label="Send anonymously? (yes / no)",
        style=discord.TextStyle.short,
        placeholder="no",
        default="no",
        max_length=3,
    )

    def __init__(self, bot: commands.Bot, ticket: dict, user: discord.User):
        super().__init__()
        self.bot    = bot
        self.ticket = ticket
        self._user  = user

    async def on_submit(self, interaction: discord.Interaction):
        anon = self.anonymous.value.strip().lower() in ("yes", "y", "true", "1")
        content = self.message.value.strip()
        author  = interaction.user

        # DM the user
        embed = _staff_embed(author.display_name, content, anon)
        try:
            await self._user.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Cannot DM the user (they may have DMs disabled).", ephemeral=True
            )
            return

        # Echo in the ticket channel
        echo = discord.Embed(
            description=content,
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        display = "Staff" if anon else author.display_name
        echo.set_author(name=f"📤 Sent by {display}")
        if anon:
            echo.set_footer(text="Sent anonymously")
        await interaction.channel.send(embed=echo)

        # Log to DB
        db.log_message(
            ticket_id=self.ticket["id"],
            author_id=author.id,
            author_name=author.display_name,
            content=content,
            direction="to_user",
            anonymous=anon,
        )
        await interaction.response.send_message("✅ Reply sent.", ephemeral=True)


class TicketView(discord.ui.View):
    """Persistent view attached to the ticket channel's header message."""

    def __init__(self, bot: commands.Bot, ticket: dict, user: discord.User):
        super().__init__(timeout=None)
        self.bot    = bot
        self.ticket = ticket
        self._user  = user

    @discord.ui.button(label="💬 Reply", style=discord.ButtonStyle.primary, custom_id="mm_reply")
    async def reply_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = ReplyModal(self.bot, self.ticket, self._user)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="🔒 Close Ticket", style=discord.ButtonStyle.danger, custom_id="mm_close")
    async def close_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await _close_ticket(self.bot, interaction.guild, self.ticket, interaction.channel, closed_by=interaction.user)


async def _close_ticket(bot: commands.Bot, guild: discord.Guild, ticket: dict,
                        channel: discord.TextChannel, closed_by: discord.Member):
    cfg = db.get_config(guild.id)
    if cfg is None:
        return

    messages = db.get_ticket_messages(ticket["id"])

    # Grab the media *before* the channel is deleted below. The re-uploaded
    # copies hang off that channel's messages, so once it goes, so do they.
    # Leave headroom under the upload limit for the text log and zip overhead.
    budget = int(_upload_limit(guild) * 0.85)
    media = await _collect_media(messages, budget)

    # _collect_media marks what it managed to archive, so build the text after.
    transcript = _build_transcript(ticket, messages)

    # Pack into zip
    zip_buf = io.BytesIO()
    stamp   = datetime.utcnow().strftime("%m%d%Y")
    # Try to get username
    try:
        user = await bot.fetch_user(ticket["user_id"])
        username = user.name
    except Exception:
        username = str(ticket["user_id"])

    zip_name = f"{stamp}-{username}.zip"
    txt_name = f"{stamp}-{username}.txt"
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(txt_name, transcript)
        for path, data in media:
            zf.writestr(path, data)
    zip_buf.seek(0)

    total_attachments = sum(len(m.get("attachments") or []) for m in messages)

    # Post to closed-tickets channel
    closed_ch_id = cfg.get("closed_ch_id")
    closed_ch    = guild.get_channel(closed_ch_id) if closed_ch_id else None
    if closed_ch:
        embed = discord.Embed(
            title="📁 Ticket Closed",
            color=discord.Color.greyple(),
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="User",      value=f"<@{ticket['user_id']}> (`{username}`)", inline=True)
        embed.add_field(name="Closed by", value=closed_by.mention, inline=True)
        embed.add_field(name="Opened",    value=ticket["opened_at"][:19], inline=False)
        if total_attachments:
            embed.add_field(
                name="Attachments",
                value=(f"{len(media)} of {total_attachments} bundled into the zip"
                       if len(media) != total_attachments
                       else f"{total_attachments} bundled into the zip"),
                inline=False,
            )
        embed.set_footer(text=f"Ticket #{ticket['id']}")
        try:
            await closed_ch.send(
                embed=embed,
                file=discord.File(zip_buf, filename=zip_name),
            )
        except discord.HTTPException as e:
            # Bundled media can push the archive past the limit even with the
            # budget. Falling back to the text log keeps the record rather than
            # losing the whole transcript.
            log.warning("Transcript zip rejected (%s); sending text log only.", e)
            txt_buf = io.BytesIO(transcript.encode("utf-8"))
            embed.add_field(
                name="\u26a0\ufe0f Note",
                value="Media was too large to attach; text log only.",
                inline=False,
            )
            await closed_ch.send(embed=embed, file=discord.File(txt_buf, filename=txt_name))

    # Notify user
    try:
        user_obj = await bot.fetch_user(ticket["user_id"])
        close_embed = discord.Embed(
            description="Your ModMail ticket has been closed. If you need further help, feel free to DM me again.",
            color=discord.Color.greyple(),
        )
        await user_obj.send(embed=close_embed)
    except Exception:
        pass

    # Mark closed in DB
    db.close_ticket(ticket["id"])

    # Delete the ticket channel
    await channel.delete(reason=f"ModMail ticket #{ticket['id']} closed by {closed_by}")


class ModMail(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Incoming DM ───────────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is not None:
            return  # only handle DMs here

        # Find a guild that has setup complete and the user is a member of
        target_guild = None
        cfg          = None
        for guild in self.bot.guilds:
            c = db.get_config(guild.id)
            if c and c.get("setup_complete"):
                if guild.get_member(message.author.id):
                    target_guild = guild
                    cfg          = c
                    break

        if target_guild is None:
            return

        user = message.author
        content = message.content or ""

        # Pull down any media so it can be re-uploaded into the ticket. This
        # used to be thrown away and replaced with the literal string
        # "[attachment / embed]", so staff saw that a file had been sent but
        # never got the file itself.
        limit = _upload_limit(target_guild)
        files, oversized, failed = await _download_attachments(message.attachments, limit)
        records = _attachment_records(message.attachments)
        note = _attachment_note(oversized, failed, limit)

        # Discord renders one image inside an embed, so promote the first image
        # for a cleaner card and leave the rest as ordinary attachments.
        inline = None
        if files and _is_image(files[0].filename):
            inline = f"attachment://{files[0].filename}"

        if not content and not records:
            return  # nothing to relay

        # Check for existing open ticket
        existing = db.get_open_ticket_by_user(target_guild.id, user.id)

        if existing:
            # Route message to existing ticket channel
            ch = target_guild.get_channel(existing["channel_id"])
            if ch:
                embed = _user_embed(
                    user.display_name, content,
                    attachments=message.attachments if not inline else message.attachments[1:],
                    inline_image=inline,
                )
                sent = await ch.send(embed=embed, files=files)
                _record_relayed_urls(records, sent)
                if note:
                    await ch.send(note)
                db.log_message(existing["id"], user.id, user.display_name,
                               content, "from_user", attachments=records)
            return

        # ── Open a new ticket ──────────────────────────────────────────────────
        mm_cat = target_guild.get_channel(cfg["modmail_cat_id"])
        if mm_cat is None:
            return

        owner_role = target_guild.get_role(cfg["owner_role_id"])
        mod_role   = target_guild.get_role(cfg["mod_role_id"])
        everyone   = target_guild.default_role

        overwrites = {
            everyone:              discord.PermissionOverwrite(read_messages=False),
            target_guild.me:       discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if owner_role:
            overwrites[owner_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if mod_role:
            overwrites[mod_role]   = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        safe_name = "".join(c for c in user.name if c.isalnum() or c in "-_").lower() or "user"
        ticket_ch = await mm_cat.create_text_channel(
            f"ticket-{safe_name}",
            overwrites=overwrites,
            reason=f"ModMail ticket for {user}",
        )

        ticket_id = db.open_ticket(target_guild.id, user.id, ticket_ch.id)
        ticket    = db.get_open_ticket_by_channel(ticket_ch.id)

        # Header embed in ticket channel
        header = discord.Embed(
            title=f"📬 New ModMail -- {user.display_name}",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        header.add_field(name="User",    value=f"{user.mention} (`{user.id}`)", inline=True)
        header.add_field(name="Account", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)
        header.set_footer(text=f"Ticket #{ticket_id}")

        view = TicketView(self.bot, ticket, user)
        await ticket_ch.send(embed=header, view=view)

        # First message embed
        first_msg_embed = _user_embed(
            user.display_name, content,
            attachments=message.attachments if not inline else message.attachments[1:],
            inline_image=inline,
        )
        sent = await ticket_ch.send(embed=first_msg_embed, files=files)
        _record_relayed_urls(records, sent)
        if note:
            await ticket_ch.send(note)
        db.log_message(ticket_id, user.id, user.display_name,
                       content, "from_user", attachments=records)

        # Send opening message to user
        open_msg = cfg.get("modmail_open_msg") or config.DEFAULT_MODMAIL_OPEN_MSG
        open_embed = discord.Embed(description=open_msg, color=discord.Color.gold())
        open_embed.set_footer(text="Reply here to continue the conversation.")
        try:
            await user.send(embed=open_embed)
        except discord.Forbidden:
            pass

        # Ping staff in modmail channel
        mm_ch = target_guild.get_channel(cfg["modmail_ch_id"])
        if mm_ch:
            pings = " ".join(r.mention for r in [owner_role, mod_role] if r)
            notif = discord.Embed(
                description=f"New ticket opened by {user.mention} -- see {ticket_ch.mention}",
                color=discord.Color.gold(),
            )
            await mm_ch.send(content=pings, embed=notif)

    # ── /reply slash command (alternative to button) ──────────────────────────
    @app_commands.command(name="reply", description="Reply to the user in this ModMail ticket.")
    @app_commands.describe(
        message="Your reply",
        anonymous="Send as 'Staff' instead of your name?",
        attachment="Optional file or image to send to the user",
    )
    async def reply(self, interaction: discord.Interaction, message: str,
                    anonymous: bool = False,
                    attachment: "discord.Attachment | None" = None):
        ticket = db.get_open_ticket_by_channel(interaction.channel_id)
        if ticket is None:
            return await interaction.response.send_message(
                "❌ This channel is not an active ModMail ticket.", ephemeral=True
            )

        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        try:
            user = await self.bot.fetch_user(ticket["user_id"])
        except discord.NotFound:
            return await interaction.response.send_message("❌ Cannot find the user.", ephemeral=True)

        # Downloading and re-uploading can outrun the 3 second interaction
        # window, so acknowledge first.
        await interaction.response.defer(ephemeral=True)

        # A DM channel is always at the base 10 MB ceiling regardless of how
        # boosted the guild is, so the guild limit is the wrong yardstick here.
        records, dm_file, echo_file, inline = [], None, None, None
        if attachment is not None:
            if attachment.size > _DEFAULT_UPLOAD_LIMIT:
                return await interaction.followup.send(
                    f"❌ **{attachment.filename}** is {_describe_size(attachment.size)}. "
                    f"DMs cap out at {_describe_size(_DEFAULT_UPLOAD_LIMIT)} no matter how "
                    f"boosted the server is, so it cannot be sent this way.",
                    ephemeral=True,
                )
            try:
                raw = await attachment.read()
            except (discord.HTTPException, discord.NotFound) as e:
                log.warning("Could not read staff attachment %s: %s", attachment.filename, e)
                return await interaction.followup.send(
                    f"❌ Could not read **{attachment.filename}** back from Discord. Try again.",
                    ephemeral=True,
                )
            # Two File objects from the same bytes: a File may only be sent once.
            dm_file = discord.File(io.BytesIO(raw), filename=attachment.filename)
            echo_file = discord.File(io.BytesIO(raw), filename=attachment.filename)
            if _is_image(attachment.filename):
                inline = f"attachment://{attachment.filename}"
            records = _attachment_records([attachment])

        embed = _staff_embed(interaction.user.display_name, message, anonymous,
                             inline_image=inline)
        try:
            await user.send(embed=embed, file=dm_file) if dm_file else await user.send(embed=embed)
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ Cannot DM that user. They may have closed DMs or left the server.",
                ephemeral=True,
            )

        echo = discord.Embed(
            description=message or None,
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        display = "Staff" if anonymous else interaction.user.display_name
        echo.set_author(name=f"📤 Sent by {display}")
        if inline:
            echo.set_image(url=inline)
        if anonymous:
            echo.set_footer(text="Sent anonymously")
        sent = await interaction.channel.send(embed=echo, file=echo_file) if echo_file \
            else await interaction.channel.send(embed=echo)
        _record_relayed_urls(records, sent)

        db.log_message(
            ticket["id"], interaction.user.id, interaction.user.display_name,
            message, "to_user", anonymous=anonymous, attachments=records,
        )
        await interaction.followup.send("✅ Reply sent.", ephemeral=True)

    # ── /close slash command ──────────────────────────────────────────────────
    @app_commands.command(name="close", description="Close this ModMail ticket and archive it.")
    async def close(self, interaction: discord.Interaction):
        ticket = db.get_open_ticket_by_channel(interaction.channel_id)
        if ticket is None:
            return await interaction.response.send_message(
                "❌ This channel is not an active ModMail ticket.", ephemeral=True
            )

        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        await interaction.response.send_message("🔒 Closing ticket…", ephemeral=True)
        await _close_ticket(
            self.bot, interaction.guild, ticket, interaction.channel, closed_by=interaction.user
        )


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


async def setup(bot: commands.Bot):
    await bot.add_cog(ModMail(bot))
