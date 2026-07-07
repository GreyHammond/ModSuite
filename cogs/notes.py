"""
notes.py — Staff Note System.

Notes are internal staff annotations attached to users.
They are NEVER shown to the subject user under any circumstance.
They do NOT appear in /userinfo — only in /history (staff-only).
Supports targeting by @mention or user ID for users not in the server.
"""
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import database as db
from utils import resolve_user


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


class Notes(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="note", description="Add a private staff note to a user. Never shown to the subject.")
    @app_commands.describe(target="Member mention or user ID", text="Note content")
    async def note(self, interaction: discord.Interaction, target: str, text: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        try:
            user, is_member = await resolve_user(self.bot, interaction.guild, target)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        if user.bot:
            return await interaction.response.send_message("❌ Cannot add notes to a bot.", ephemeral=True)

        note_id = db.add_note(
            str(interaction.guild_id),
            str(user.id),
            str(interaction.user.id),
            text,
        )

        embed = discord.Embed(
            title="📝 Note Added",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        name_display = f"{user} (`{user.id}`)"
        if not is_member:
            name_display += " *(not in server)*"
        embed.add_field(name="User",    value=name_display, inline=True)
        embed.add_field(name="Note ID", value=f"#{note_id}", inline=True)
        embed.add_field(name="Content", value=text,          inline=False)
        embed.set_footer(text="This note is visible to staff only.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="notes", description="List all active staff notes for a user.")
    @app_commands.describe(target="Member mention or user ID")
    async def notes(self, interaction: discord.Interaction, target: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        try:
            user, is_member = await resolve_user(self.bot, interaction.guild, target)
        except ValueError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        active_notes = db.get_notes(str(interaction.guild_id), str(user.id), active_only=True)

        name_display = user.display_name if is_member else str(user)
        embed = discord.Embed(
            title=f"📝 Staff Notes — {name_display}",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        if is_member:
            embed.set_thumbnail(url=user.display_avatar.url)

        if not is_member:
            embed.description = f"*User is not in the server* (`{user.id}`)\n\n"
        else:
            embed.description = ""

        if not active_notes:
            embed.description += "No active notes on record for this user."
        else:
            embed.description += f"**{len(active_notes)} active note(s)**"
            for n in active_notes:
                date_str = n["created_at"][:10]
                embed.add_field(
                    name=f"Note #{n['note_id']} | {date_str} | by <@{n['author_id']}>",
                    value=n["content"],
                    inline=False,
                )

        embed.set_footer(text="Staff eyes only — never shown to the subject user.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="delnote", description="Soft-delete a staff note by ID.")
    @app_commands.describe(note_id="The note ID to delete (shown in /notes or /history)")
    async def delnote(self, interaction: discord.Interaction, note_id: int):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("❌ Staff only.", ephemeral=True)

        note = db.get_note_by_id(note_id)
        if note is None or note.get("deleted"):
            return await interaction.response.send_message(
                f"❌ Note `#{note_id}` not found or already deleted.", ephemeral=True
            )
        if str(note["guild_id"]) != str(interaction.guild_id):
            return await interaction.response.send_message(
                "❌ That note does not belong to this server.", ephemeral=True
            )

        deleted = db.delete_note(note_id)
        if deleted:
            await interaction.response.send_message(f"✅ Note `#{note_id}` has been deleted.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"❌ Note `#{note_id}` not found or already deleted.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(Notes(bot))
