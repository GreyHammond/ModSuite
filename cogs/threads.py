import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
import database as db


async def _post_modlog(guild: discord.Guild, cfg: dict, embed: discord.Embed):
    ch_id = cfg.get("modlog_ch_id") if cfg else None
    if ch_id:
        ch = guild.get_channel(ch_id)
        if ch:
            await ch.send(embed=embed)


class DeleteThreadView(discord.ui.View):
    """Two-step confirmation for a thread owner deleting their own forum thread."""

    def __init__(self, thread: discord.Thread, invoker: discord.Member):
        super().__init__(timeout=60)
        self.thread   = thread
        self.invoker  = invoker
        self._stage   = 1  # 1 = first confirm, 2 = final warning

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "❌ Only the person who ran the command can use these buttons.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Yes, delete", style=discord.ButtonStyle.danger, custom_id="thread_del_yes")
    async def yes_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._stage == 1:
            # Move to final warning
            self._stage = 2
            button.label = "Permanently delete"
            await interaction.response.edit_message(
                content=(
                    "⚠️ **Final warning.**\n"
                    "All messages and media in this thread will be **permanently deleted** "
                    "and **cannot be recovered.**\n\nContinue?"
                ),
                view=self,
            )
            return

        # Stage 2 -- actually delete
        self.stop()
        thread_name = self.thread.name
        deleted_by  = self.invoker
        deleted_at  = datetime.utcnow()

        await interaction.response.edit_message(
            content="🗑️ Deleting thread…", view=None
        )

        try:
            await self.thread.delete(
                reason=f"Deleted by thread owner {deleted_by} ({deleted_by.id}) via /delete"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to delete this thread. Please contact a mod.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"❌ Failed to delete thread: {e}", ephemeral=True
            )
            return

        # ── Log to mod-log channel ────────────────────────────────────────────
        cfg = db.get_config(interaction.guild_id)
        embed = discord.Embed(
            title="🗑️ Thread Deleted by Owner",
            color=discord.Color.red(),
            timestamp=deleted_at,
        )
        embed.add_field(name="User",        value=f"{deleted_by.mention} (`{deleted_by.id}`)", inline=True)
        embed.add_field(name="Deleted by",  value=deleted_by.mention,                          inline=True)
        embed.add_field(name="Thread Name", value=thread_name,                                 inline=False)
        embed.add_field(
            name="Deleted",
            value=f"<t:{int(deleted_at.timestamp())}:F>",
            inline=False,
        )
        await _post_modlog(interaction.guild, cfg, embed)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="thread_del_no")
    async def no_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(
            content="Cancelled. Thread was not deleted.", view=None
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class Threads(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="delete",
        description="Delete your own forum thread (owner only). Cannot be undone.",
    )
    async def delete(self, interaction: discord.Interaction):
        channel = interaction.channel

        # Must be a thread inside a forum channel
        if not isinstance(channel, discord.Thread) or not isinstance(
            channel.parent, discord.ForumChannel
        ):
            return await interaction.response.send_message(
                "❌ This command only works inside a forum thread.", ephemeral=True
            )

        # Must be the OP (thread owner)
        if channel.owner_id != interaction.user.id:
            return await interaction.response.send_message(
                "❌ Only the person who created this thread can delete it.", ephemeral=True
            )

        view = DeleteThreadView(thread=channel, invoker=interaction.user)
        await interaction.response.send_message(
            content=f"Delete **{channel.name}**? This will remove the thread and all its messages.",
            view=view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Threads(bot))
