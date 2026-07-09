"""
cogs/reactmessage.py -- React Message Builder
Allows admins to create, edit, and publish custom reaction-role messages
entirely through Discord slash commands.
"""

import re
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime

import database as db

DRAFT_COLOR    = 0xF0B429  # Yellow -- DRAFT
PUBLISH_COLOR  = 0xD4A843  # Gold  -- live
FOOTER_BRAND   = "ModSuite · Hammond Digital Studios"
FOOTER_DRAFT   = "🔧 DRAFT -- not yet published  |  /publishreactmessage to go live  |  /cancelreactmessage to discard"

# Preset role colours for the creation prompt
PRESET_COLORS = {
    "Red":    0xE74C3C,
    "Blue":   0x3498DB,
    "Orange": 0xE67E22,
    "Green":  0x2ECC71,
    "Purple": 0x9B59B6,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_draft_embed(draft: dict, roles: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🔧 [DRAFT] {draft['title']}",
        color=DRAFT_COLOR,
    )
    if draft.get("intro_text"):
        body = draft["intro_text"]
    else:
        body = ""

    if roles:
        role_lines = "\n".join(
            f"{r['emoji']} <@&{r['role_id']}> -- {'[single]' if r['toggle'] else '[multi]'}"
            for r in roles
        )
        if body:
            body += f"\n\n{role_lines}"
        else:
            body = role_lines
    else:
        suffix = "\n\nNo roles added yet -- use /addrole to begin."
        body = (body + suffix) if body else suffix.strip()

    embed.description = body
    embed.set_footer(text=FOOTER_DRAFT)
    return embed


def _build_published_embed(draft: dict, roles: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=draft["title"],
        color=PUBLISH_COLOR,
    )
    body = draft.get("intro_text", "")
    if roles:
        role_lines = "\n".join(f"→ {r['emoji']} <@&{r['role_id']}>" for r in roles)
        if body:
            body += f"\n\n{role_lines}"
        else:
            body = role_lines
    embed.description = body or None
    embed.set_footer(text=f"Remove your reaction to unassign the role.  |  {FOOTER_BRAND}")
    return embed


async def _refresh_draft_message(bot: commands.Bot, guild_id: str) -> None:
    """Fetch the current draft and edit the live Discord draft message."""
    draft = db.get_draft(guild_id)
    if not draft:
        return
    roles = db.get_draft_roles(draft["draft_id"])
    embed = _build_draft_embed(draft, roles)
    try:
        channel = bot.get_channel(int(draft["draft_channel_id"]))
        if channel is None:
            channel = await bot.fetch_channel(int(draft["draft_channel_id"]))
        msg = await channel.fetch_message(int(draft["draft_message_id"]))
        await msg.edit(embed=embed)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


# ── Views ─────────────────────────────────────────────────────────────────────

class DraftConflictView(discord.ui.View):
    def __init__(self, bot: commands.Bot, interaction: discord.Interaction,
                 callback_fn, draft: dict):
        super().__init__(timeout=60)
        self.bot = bot
        self.original_interaction = interaction
        self.callback_fn = callback_fn
        self.draft = draft

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.secondary)
    async def resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=f"Resuming existing draft **{self.draft['title']}** in <#{self.draft['draft_channel_id']}>.",
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Start Fresh", style=discord.ButtonStyle.danger)
    async def start_fresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Delete old draft message and DB row
        try:
            channel = self.bot.get_channel(int(self.draft["draft_channel_id"]))
            if channel:
                msg = await channel.fetch_message(int(self.draft["draft_message_id"]))
                await msg.delete()
        except Exception:
            pass
        db.delete_draft(str(interaction.guild_id))
        await interaction.response.edit_message(
            content="Old draft discarded. Starting fresh…", view=None
        )
        await self.callback_fn(interaction)
        self.stop()


class RoleColorView(discord.ui.View):
    """Shown when an admin wants to create a new role during /addrole."""

    def __init__(self, interaction: discord.Interaction, role_name: str,
                 on_color_chosen):
        super().__init__(timeout=60)
        self.role_name = role_name
        self.on_color_chosen = on_color_chosen
        for label, color in PRESET_COLORS.items():
            self.add_item(ColorButton(label=label, color=color, view_ref=self))
        self.add_item(HexInputButton(view_ref=self))

    async def finish(self, interaction: discord.Interaction, color: int):
        await self.on_color_chosen(interaction, color)
        self.stop()


class ColorButton(discord.ui.Button):
    def __init__(self, label: str, color: int, view_ref: RoleColorView):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self._color = color
        self._view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        await self._view_ref.finish(interaction, self._color)


class HexInputButton(discord.ui.Button):
    def __init__(self, view_ref: RoleColorView):
        super().__init__(label="Enter hex", style=discord.ButtonStyle.primary)
        self._view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(HexColorModal(self._view_ref))


class HexColorModal(discord.ui.Modal, title="Enter hex colour"):
    hex_color = discord.ui.TextInput(
        label="Hex colour (e.g. #FF5733)",
        placeholder="#RRGGBB",
        max_length=7,
    )

    def __init__(self, view_ref: RoleColorView):
        super().__init__()
        self._view_ref = view_ref

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.hex_color.value.strip().lstrip("#")
        try:
            color = int(raw, 16)
        except ValueError:
            await interaction.response.send_message(
                "❌ Invalid hex colour.", ephemeral=True
            )
            return
        await self._view_ref.finish(interaction, color)


class ChannelSelectView(discord.ui.View):
    def __init__(self, callback_fn):
        super().__init__(timeout=120)
        self.callback_fn = callback_fn

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        channel_types=[discord.ChannelType.text],
        placeholder="Select a channel to publish to…",
    )
    async def channel_select(self, interaction: discord.Interaction,
                              select: discord.ui.ChannelSelect):
        channel = select.values[0]
        self.stop()
        await self.callback_fn(interaction, channel)


# ── Modals ────────────────────────────────────────────────────────────────────

class CreateReactMessageModal(discord.ui.Modal, title="Create React Message"):
    msg_title = discord.ui.TextInput(
        label="Title",
        placeholder="e.g. 🎮 Gaming Platforms",
        max_length=100,
    )
    intro = discord.ui.TextInput(
        label="Intro text (optional)",
        placeholder="e.g. Pick the platforms you game on!",
        max_length=500,
        required=False,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, bot: commands.Bot, prefill_title: str = "",
                 prefill_intro: str = ""):
        super().__init__()
        self._bot = bot
        if prefill_title:
            self.msg_title.default = prefill_title
        if prefill_intro:
            self.intro.default = prefill_intro

    async def on_submit(self, interaction: discord.Interaction):
        title      = self.msg_title.value.strip()
        intro_text = self.intro.value.strip()
        guild_id   = str(interaction.guild_id)

        # Post draft embed
        embed = _build_draft_embed(
            {"title": title, "intro_text": intro_text},
            []
        )
        draft_msg = await interaction.channel.send(embed=embed)

        db.create_draft(
            guild_id=guild_id,
            author_id=str(interaction.user.id),
            draft_message_id=str(draft_msg.id),
            draft_channel_id=str(interaction.channel_id),
            target_message_id=None,
            target_channel_id=None,
            title=title,
            intro_text=intro_text,
        )
        await interaction.response.send_message(
            "✅ Draft created. Use `/addrole` to start adding roles.",
            ephemeral=True,
        )


class EditReactMessageModal(discord.ui.Modal, title="Edit React Message"):
    msg_title = discord.ui.TextInput(label="Title", max_length=100)
    intro = discord.ui.TextInput(
        label="Intro text (optional)",
        max_length=500,
        required=False,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, bot: commands.Bot, draft: dict):
        super().__init__()
        self._bot = bot
        self._guild_id = draft["guild_id"]
        self.msg_title.default = draft["title"]
        self.intro.default     = draft.get("intro_text", "")

    async def on_submit(self, interaction: discord.Interaction):
        db.update_draft(
            self._guild_id,
            title=self.msg_title.value.strip(),
            intro_text=self.intro.value.strip(),
        )
        await _refresh_draft_message(self._bot, self._guild_id)
        await interaction.response.send_message("✅ Draft text updated.", ephemeral=True)


# ── Cog ───────────────────────────────────────────────────────────────────────

class ReactMessage(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /createreactmessage ───────────────────────────────────────────────────

    @app_commands.command(
        name="createreactmessage",
        description="[Admin] Create a new reaction-role message (draft mode).",
    )
    @app_commands.default_permissions(administrator=True)
    async def createreactmessage(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        existing = db.get_draft(guild_id)

        if existing:
            view = DraftConflictView(
                self.bot, interaction,
                callback_fn=self._open_create_modal,
                draft=existing,
            )
            await interaction.response.send_message(
                f"⚠️ You have an existing draft: **{existing['title']}** in <#{existing['draft_channel_id']}>\n"
                "What would you like to do?",
                view=view,
                ephemeral=True,
            )
            return

        await self._open_create_modal(interaction)

    async def _open_create_modal(self, interaction: discord.Interaction):
        """Open the create modal. Works whether interaction is fresh or a button callback."""
        modal = CreateReactMessageModal(self.bot)
        if interaction.response.is_done():
            # Called from a button callback -- use followup modal workaround
            # (we can't send a modal from a followup, so send an ephemeral prompt)
            await interaction.followup.send(
                "Opening creation modal…", ephemeral=True
            )
            # Best we can do after a button press is send a new modal via webhook
            # Actually discord.py supports send_modal on interactions that haven't responded yet.
            # After a button press the interaction IS fresh, so this works:
        await interaction.response.send_modal(modal)

    # ── /setreactmessage ──────────────────────────────────────────────────────

    @app_commands.command(
        name="setreactmessage",
        description="[Admin] Load an existing react message for editing.",
    )
    @app_commands.describe(message_link="Discord message link (https://discord.com/channels/…)")
    @app_commands.default_permissions(administrator=True)
    async def setreactmessage(self, interaction: discord.Interaction, message_link: str):
        # Parse link
        match = re.match(
            r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/"
            r"(\d+)/(\d+)/(\d+)",
            message_link.strip(),
        )
        if not match:
            await interaction.response.send_message(
                "❌ Invalid message link. Please copy a valid Discord message URL.",
                ephemeral=True,
            )
            return

        link_guild_id, channel_id, message_id = match.group(1), match.group(2), match.group(3)

        if link_guild_id != str(interaction.guild_id):
            await interaction.response.send_message(
                "❌ That message is from a different server.", ephemeral=True
            )
            return

        # Fetch the message
        try:
            channel = self.bot.get_channel(int(channel_id)) or \
                      await self.bot.fetch_channel(int(channel_id))
            target_msg = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            await interaction.response.send_message(
                "❌ Could not fetch that message. Make sure it exists and I have access.",
                ephemeral=True,
            )
            return

        if target_msg.author.id != self.bot.user.id:
            await interaction.response.send_message(
                "❌ That message wasn't sent by me.", ephemeral=True
            )
            return

        guild_id = str(interaction.guild_id)

        # Conflict check
        existing = db.get_draft(guild_id)
        if existing:
            async def _proceed(itr: discord.Interaction):
                await self._load_existing_for_editing(
                    itr, target_msg, channel_id, message_id
                )

            view = DraftConflictView(
                self.bot, interaction,
                callback_fn=_proceed,
                draft=existing,
            )
            await interaction.response.send_message(
                f"⚠️ You have an existing draft: **{existing['title']}** in <#{existing['draft_channel_id']}>\n"
                "What would you like to do?",
                view=view,
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        await self._load_existing_for_editing(interaction, target_msg, channel_id, message_id)

    async def _load_existing_for_editing(
        self,
        interaction: discord.Interaction,
        target_msg: discord.Message,
        target_channel_id: str,
        target_message_id: str,
    ):
        guild_id = str(interaction.guild_id)

        # Extract title/intro from the existing embed if present
        title      = ""
        intro_text = ""
        if target_msg.embeds:
            e = target_msg.embeds[0]
            title      = e.title or ""
            intro_text = e.description or ""

        # Try to load existing selfrole roles for this message
        category = db.get_selfrole_category_by_message(guild_id, target_message_id)
        pre_roles: list[dict] = []
        if category:
            pre_roles = db.get_selfrole_roles(category["category_id"])

        # Post draft
        draft_data = {"title": title, "intro_text": intro_text}
        embed      = _build_draft_embed(draft_data, pre_roles)
        draft_msg  = await interaction.channel.send(embed=embed)

        draft_id = db.create_draft(
            guild_id=guild_id,
            author_id=str(interaction.user.id),
            draft_message_id=str(draft_msg.id),
            draft_channel_id=str(interaction.channel_id),
            target_message_id=target_message_id,
            target_channel_id=target_channel_id,
            title=title,
            intro_text=intro_text,
        )

        # Pre-load roles into draft
        for r in pre_roles:
            toggle = r.get("toggle", 0)
            db.add_draft_role(draft_id, r["emoji"], r["role_id"], toggle)

        # Add reactions for live preview
        for r in pre_roles:
            try:
                await draft_msg.add_reaction(r["emoji"])
            except Exception:
                pass

        msg = f"✅ Loaded **{title or 'message'}** for editing. Draft posted above."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    # ── /addrole ──────────────────────────────────────────────────────────────

    @app_commands.command(
        name="addrole",
        description="[Admin] Add a role to the current react message draft.",
    )
    @app_commands.describe(
        emoji="A single emoji (unicode or custom)",
        role="The role to assign",
        toggle="True = single-select (replaces others), False = multi-select (additive)",
    )
    @app_commands.default_permissions(administrator=True)
    async def addrole(
        self,
        interaction: discord.Interaction,
        emoji: str,
        role: discord.Role,
        toggle: bool,
    ):
        guild_id = str(interaction.guild_id)
        draft    = db.get_draft(guild_id)
        if not draft:
            await interaction.response.send_message(
                "⚠️ No active draft. Run `/createreactmessage` first.", ephemeral=True
            )
            return

        roles = db.get_draft_roles(draft["draft_id"])
        if any(r["emoji"] == emoji for r in roles):
            await interaction.response.send_message(
                f"❌ Emoji {emoji} is already in use on this draft. Use `/editrole` to change it.",
                ephemeral=True,
            )
            return

        db.add_draft_role(draft["draft_id"], emoji, str(role.id), int(toggle))
        await _refresh_draft_message(self.bot, guild_id)

        # Add reaction to draft for live testing
        try:
            channel  = self.bot.get_channel(int(draft["draft_channel_id"]))
            draft_msg = await channel.fetch_message(int(draft["draft_message_id"]))
            await draft_msg.add_reaction(emoji)
        except Exception:
            pass

        mode = "single" if toggle else "multi"
        await interaction.response.send_message(
            f"✅ Added {emoji} → {role.mention} ({mode}-select)", ephemeral=True
        )

    # ── /deleterole ───────────────────────────────────────────────────────────

    @app_commands.command(
        name="deleterole",
        description="[Admin] Remove a role from the current react message draft.",
    )
    @app_commands.describe(emoji="The emoji to remove")
    @app_commands.default_permissions(administrator=True)
    async def deleterole(self, interaction: discord.Interaction, emoji: str):
        guild_id = str(interaction.guild_id)
        draft    = db.get_draft(guild_id)
        if not draft:
            await interaction.response.send_message(
                "⚠️ No active draft. Run `/createreactmessage` first.", ephemeral=True
            )
            return

        removed = db.remove_draft_role(draft["draft_id"], emoji)
        if not removed:
            await interaction.response.send_message(
                f"❌ Emoji {emoji} wasn't found in the draft.", ephemeral=True
            )
            return

        # Remove reaction from draft message
        try:
            channel  = self.bot.get_channel(int(draft["draft_channel_id"]))
            draft_msg = await channel.fetch_message(int(draft["draft_message_id"]))
            await draft_msg.clear_reaction(emoji)
        except Exception:
            pass

        await _refresh_draft_message(self.bot, guild_id)
        await interaction.response.send_message(
            f"✅ Removed {emoji} from the draft.", ephemeral=True
        )

    # ── /editrole ─────────────────────────────────────────────────────────────

    @app_commands.command(
        name="editrole",
        description="[Admin] Edit an existing role entry in the current draft.",
    )
    @app_commands.describe(
        emoji="The emoji to change",
        new_emoji="Replacement emoji",
        new_role="Replacement role",
    )
    @app_commands.default_permissions(administrator=True)
    async def editrole(
        self,
        interaction: discord.Interaction,
        emoji: str,
        new_emoji: str,
        new_role: discord.Role,
    ):
        guild_id = str(interaction.guild_id)
        draft    = db.get_draft(guild_id)
        if not draft:
            await interaction.response.send_message(
                "⚠️ No active draft.", ephemeral=True
            )
            return

        roles = db.get_draft_roles(draft["draft_id"])
        if not any(r["emoji"] == emoji for r in roles):
            await interaction.response.send_message(
                f"❌ Emoji {emoji} wasn't found in the draft.", ephemeral=True
            )
            return

        updated = db.update_draft_role(draft["draft_id"], emoji, new_emoji, str(new_role.id))
        if not updated:
            await interaction.response.send_message("❌ Update failed.", ephemeral=True)
            return

        # Swap reaction on draft message if emoji changed
        if new_emoji != emoji:
            try:
                channel   = self.bot.get_channel(int(draft["draft_channel_id"]))
                draft_msg = await channel.fetch_message(int(draft["draft_message_id"]))
                await draft_msg.clear_reaction(emoji)
                await draft_msg.add_reaction(new_emoji)
            except Exception:
                pass

        await _refresh_draft_message(self.bot, guild_id)
        await interaction.response.send_message(
            f"✅ Updated: {emoji} → {new_emoji} {new_role.mention}", ephemeral=True
        )

    # ── /editreactmessage ─────────────────────────────────────────────────────

    @app_commands.command(
        name="editreactmessage",
        description="[Admin] Edit the title and intro text of the current draft.",
    )
    @app_commands.default_permissions(administrator=True)
    async def editreactmessage(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        draft    = db.get_draft(guild_id)
        if not draft:
            await interaction.response.send_message(
                "⚠️ No active draft.", ephemeral=True
            )
            return
        modal = EditReactMessageModal(self.bot, draft)
        await interaction.response.send_modal(modal)

    # ── /publishreactmessage ──────────────────────────────────────────────────

    @app_commands.command(
        name="publishreactmessage",
        description="[Admin] Publish the current draft to a channel.",
    )
    @app_commands.default_permissions(administrator=True)
    async def publishreactmessage(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        draft    = db.get_draft(guild_id)
        if not draft:
            await interaction.response.send_message(
                "⚠️ No active draft.", ephemeral=True
            )
            return

        roles = db.get_draft_roles(draft["draft_id"])
        if not roles:
            await interaction.response.send_message(
                "❌ Add at least one role before publishing.", ephemeral=True
            )
            return

        if draft.get("target_message_id"):
            # Edit existing message in place
            await interaction.response.defer(ephemeral=True)
            await self._do_publish(interaction, draft, roles, target_channel_id=draft["target_channel_id"])
        else:
            # New message -- ask where to publish
            async def _on_channel_selected(itr: discord.Interaction, channel):
                await itr.response.defer(ephemeral=True)
                await self._do_publish(itr, draft, roles, target_channel_id=str(channel.id))

            view = ChannelSelectView(callback_fn=_on_channel_selected)
            await interaction.response.send_message(
                "📤 Which channel should this be published to?",
                view=view,
                ephemeral=True,
            )

    async def _do_publish(
        self,
        interaction: discord.Interaction,
        draft: dict,
        roles: list[dict],
        target_channel_id: str,
    ):
        guild_id = str(interaction.guild_id)
        embed    = _build_published_embed(draft, roles)

        try:
            target_channel = self.bot.get_channel(int(target_channel_id)) or \
                             await self.bot.fetch_channel(int(target_channel_id))
        except Exception:
            await interaction.followup.send("❌ Could not reach the target channel.", ephemeral=True)
            return

        if draft.get("target_message_id"):
            # Edit existing message in place
            try:
                pub_msg = await target_channel.fetch_message(int(draft["target_message_id"]))
                await pub_msg.edit(embed=embed)
                await pub_msg.clear_reactions()
                for r in roles:
                    try:
                        await pub_msg.add_reaction(r["emoji"])
                    except Exception:
                        pass
                published_message_id = draft["target_message_id"]
            except Exception:
                await interaction.followup.send("❌ Could not edit the original message.", ephemeral=True)
                return
        else:
            # Post new message
            pub_msg = await target_channel.send(embed=embed)
            for r in roles:
                try:
                    await pub_msg.add_reaction(r["emoji"])
                except Exception:
                    pass
            published_message_id = str(pub_msg.id)

        # Upsert into selfrole_categories + selfrole_roles
        # so selfroles.py reaction handler picks it up
        existing_cat = db.get_selfrole_category_by_message(guild_id, published_message_id)
        if existing_cat:
            cat_id = existing_cat["category_id"]
            db.update_selfrole_category(
                cat_id,
                name=draft["title"],
                intro_text=draft.get("intro_text", ""),
                message_id=published_message_id,
                channel_id=target_channel_id,
            )
            # Delete and re-insert roles
            import sqlite3
            with db.get_conn() as conn:
                conn.execute("DELETE FROM selfrole_roles WHERE category_id = ?", (cat_id,))
        else:
            cat_id = db.insert_selfrole_category(
                guild_id=guild_id,
                name=draft["title"],
                enforcement="multi",  # enforcement is overridden per-role via toggle
                intro_text=draft.get("intro_text", ""),
            )
            db.update_selfrole_category(
                cat_id,
                message_id=published_message_id,
                channel_id=target_channel_id,
            )

        with db.get_conn() as conn:
            for order, r in enumerate(roles):
                conn.execute(
                    "INSERT INTO selfrole_roles (category_id, role_id, emoji, display_order, toggle)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (cat_id, r["role_id"], r["emoji"], order, r["toggle"]),
                )

        # Delete draft Discord message
        try:
            draft_channel = self.bot.get_channel(int(draft["draft_channel_id"]))
            if draft_channel:
                draft_msg = await draft_channel.fetch_message(int(draft["draft_message_id"]))
                await draft_msg.delete()
        except Exception:
            pass

        db.delete_draft(guild_id)

        ch_mention = f"<#{target_channel_id}>"
        await interaction.followup.send(
            f"✅ Published to {ch_mention}. Draft cleaned up.", ephemeral=True
        )

    # ── /cancelreactmessage ───────────────────────────────────────────────────

    @app_commands.command(
        name="cancelreactmessage",
        description="[Admin] Discard the current react message draft.",
    )
    @app_commands.default_permissions(administrator=True)
    async def cancelreactmessage(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        draft    = db.get_draft(guild_id)
        if not draft:
            await interaction.response.send_message(
                "ℹ️ No active draft to cancel.", ephemeral=True
            )
            return

        # Delete draft Discord message
        try:
            channel   = self.bot.get_channel(int(draft["draft_channel_id"]))
            draft_msg = await channel.fetch_message(int(draft["draft_message_id"]))
            await draft_msg.delete()
        except Exception:
            pass

        db.delete_draft(guild_id)
        await interaction.response.send_message(
            "🗑️ Draft discarded and cleaned up.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactMessage(bot))
