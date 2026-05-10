import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import zipfile
import io
import database as db
import config


def _staff_embed(author_name: str, content: str, anonymous: bool) -> discord.Embed:
    display = "Staff" if anonymous else author_name
    embed = discord.Embed(
        description=content,
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name=f"💬 {display}")
    return embed


def _user_embed(author_name: str, content: str) -> discord.Embed:
    embed = discord.Embed(
        description=content,
        color=discord.Color.gold(),
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name=f"📨 {author_name}")
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
        lines.append(f"  {msg['content']}")
        lines.append("")
    return "\n".join(lines)


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

    # Build transcript
    messages  = db.get_ticket_messages(ticket["id"])
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
    zip_buf.seek(0)

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
        embed.set_footer(text=f"Ticket #{ticket['id']}")
        await closed_ch.send(
            embed=embed,
            file=discord.File(zip_buf, filename=zip_name),
        )

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

        user    = message.author
        content = message.content or "[attachment / embed]"

        # Check for existing open ticket
        existing = db.get_open_ticket_by_user(target_guild.id, user.id)

        if existing:
            # Route message to existing ticket channel
            ch = target_guild.get_channel(existing["channel_id"])
            if ch:
                embed = _user_embed(user.display_name, content)
                await ch.send(embed=embed)
                db.log_message(existing["id"], user.id, user.display_name, content, "from_user")
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
            title=f"📬 New ModMail — {user.display_name}",
            color=discord.Color.gold(),
            timestamp=datetime.utcnow(),
        )
        header.add_field(name="User",    value=f"{user.mention} (`{user.id}`)", inline=True)
        header.add_field(name="Account", value=f"<t:{int(user.created_at.timestamp())}:R>", inline=True)
        header.set_footer(text=f"Ticket #{ticket_id}")

        view = TicketView(self.bot, ticket, user)
        await ticket_ch.send(embed=header, view=view)

        # First message embed
        first_msg_embed = _user_embed(user.display_name, content)
        await ticket_ch.send(embed=first_msg_embed)
        db.log_message(ticket_id, user.id, user.display_name, content, "from_user")

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
                description=f"New ticket opened by {user.mention} — see {ticket_ch.mention}",
                color=discord.Color.gold(),
            )
            await mm_ch.send(content=pings, embed=notif)

    # ── /reply slash command (alternative to button) ──────────────────────────
    @app_commands.command(name="reply", description="Reply to the user in this ModMail ticket.")
    @app_commands.describe(message="Your reply", anonymous="Send as 'Staff' instead of your name?")
    async def reply(self, interaction: discord.Interaction, message: str, anonymous: bool = False):
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

        embed = _staff_embed(interaction.user.display_name, message, anonymous)
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ Cannot DM that user.", ephemeral=True
            )

        echo = discord.Embed(
            description=message,
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        display = "Staff" if anonymous else interaction.user.display_name
        echo.set_author(name=f"📤 Sent by {display}")
        if anonymous:
            echo.set_footer(text="Sent anonymously")
        await interaction.channel.send(embed=echo)

        db.log_message(
            ticket["id"], interaction.user.id, interaction.user.display_name,
            message, "to_user", anonymous=anonymous,
        )
        await interaction.response.send_message("✅ Reply sent.", ephemeral=True)

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
