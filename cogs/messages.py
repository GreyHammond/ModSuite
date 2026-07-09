"""
messages.py -- Bot message slot management (Admin only)
/setmessage   -- Edit any bot message slot via Discord modal
/viewmessages -- View all slots and current values
/resetmessage -- Reset a slot back to its default
"""

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from utils import DEFAULTS

# ── Slot metadata ─────────────────────────────────────────────────────────────

SLOTS = {
    "warn_dm":         ("Warn DM",         "{user} {reason}"),
    "jail_dm":         ("Jail DM",         "{user} {reason} {duration}"),
    "unjail_dm":       ("Unjail DM",       "{user}"),
    "mute_dm":         ("Mute DM",         "{user} {reason} {duration}"),
    "ban_dm":          ("Ban DM",          "{user} {reason}"),
    "join_message":    ("Join Message",    "{user}"),
    "welcome_message": ("Welcome Message", "{user}"),
}

SLOT_CHOICES = [
    app_commands.Choice(name=label, value=key)
    for key, (label, _) in SLOTS.items()
]


# ── Modal ─────────────────────────────────────────────────────────────────────

class MessageEditModal(discord.ui.Modal):
    def __init__(self, slot: str, current_text: str):
        label, variables = SLOTS[slot]
        super().__init__(title=f"Edit: {label}")
        self.slot = slot
        self.message_input = discord.ui.TextInput(
            label=f"{label}  ({variables})",
            style=discord.TextStyle.paragraph,
            default=current_text,
            max_length=1000,
            required=True,
            placeholder=f"Available placeholders: {variables}",
        )
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild_id)
        db.upsert_bot_message(guild_id, self.slot, self.message_input.value)
        label = SLOTS[self.slot][0]
        embed = discord.Embed(
            title="✅ Message Updated",
            description=f"**{label}** has been saved.",
            color=0xD4A843,
        )
        embed.add_field(name="New value", value=self.message_input.value, inline=False)
        embed.set_footer(text="ModSuite · Hammond Digital Studios")
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Messages(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /setmessage ───────────────────────────────────────────────────────────

    @app_commands.command(
        name="setmessage",
        description="Edit any bot message slot via a popup form.",
    )
    @app_commands.describe(slot="Which message to edit")
    @app_commands.choices(slot=SLOT_CHOICES)
    async def setmessage(self, interaction: discord.Interaction, slot: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "⛔ Administrator only.", ephemeral=True
            )

        guild_id = str(interaction.guild_id)
        # Pre-fill with current custom value, or the default if none set
        current = db.get_bot_message_content(guild_id, slot) or DEFAULTS.get(slot, "")
        modal = MessageEditModal(slot=slot, current_text=current)
        await interaction.response.send_modal(modal)

    # ── /viewmessages ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="viewmessages",
        description="View all bot message slots and their current values.",
    )
    async def viewmessages(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "⛔ Administrator only.", ephemeral=True
            )

        guild_id = str(interaction.guild_id)
        custom   = db.get_all_bot_messages(guild_id)

        embed = discord.Embed(
            title="📝 Bot Message Slots",
            color=0xD4A843,
        )

        for key, (label, variables) in SLOTS.items():
            is_custom  = key in custom
            value_text = custom.get(key) or DEFAULTS.get(key, "*(no default)*")
            tag        = "✏️ Custom" if is_custom else "📋 Default"
            embed.add_field(
                name=f"{label}  --  {tag}  `{variables}`",
                value=f"```{value_text}```",
                inline=False,
            )

        embed.set_footer(text="ModSuite · Hammond Digital Studios  |  Use /setmessage to edit  |  /resetmessage to restore default")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ── /resetmessage ─────────────────────────────────────────────────────────

    @app_commands.command(
        name="resetmessage",
        description="Reset a bot message slot back to its default.",
    )
    @app_commands.describe(slot="Which message to reset")
    @app_commands.choices(slot=SLOT_CHOICES)
    async def resetmessage(self, interaction: discord.Interaction, slot: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message(
                "⛔ Administrator only.", ephemeral=True
            )

        guild_id = str(interaction.guild_id)
        db.delete_bot_message(guild_id, slot)

        label   = SLOTS[slot][0]
        default = DEFAULTS.get(slot, "*(no default)*")

        embed = discord.Embed(
            title="🔄 Message Reset",
            description=f"**{label}** has been reset to its default.",
            color=0xD4A843,
        )
        embed.add_field(name="Default value", value=f"```{default}```", inline=False)
        embed.set_footer(text="ModSuite · Hammond Digital Studios")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Messages(bot))
