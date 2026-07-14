"""
Autoresponse cog -- listens for trigger words/phrases and auto-replies.
Triggers and responses are managed via the dashboard or slash commands.
"""
import discord
from discord import app_commands
from discord.ext import commands
import database as db


def _is_staff(member: discord.Member, cfg: dict | None) -> bool:
    if cfg is None:
        return member.guild_permissions.administrator
    staff_ids = {cfg.get("owner_role_id"), cfg.get("mod_role_id")}
    return any(r.id in staff_ids for r in member.roles) or member.guild_permissions.administrator


class AutoResponse(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -- Message listener --------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return

        cfg = db.get_config(message.guild.id)
        if cfg is None or not cfg.get("setup_complete"):
            return

        responses = db.get_autoresponses(str(message.guild.id), enabled_only=True)
        if not responses:
            return

        content_lower = message.content.lower()

        for ar in responses:
            trigger = ar["trigger"]  # already stored lowercase
            mode = ar.get("match_mode", "contains")

            matched = False
            if mode == "exact":
                matched = content_lower.strip() == trigger
            elif mode == "startswith":
                matched = content_lower.startswith(trigger)
            else:  # contains (default)
                matched = trigger in content_lower

            if matched:
                try:
                    await message.channel.send(ar["response"])
                except discord.Forbidden:
                    pass
                # Only fire the first matching trigger per message
                return

    # -- Slash commands ----------------------------------------------------------
    autoresponse_group = app_commands.Group(
        name="autoresponse",
        description="Manage automatic trigger-response pairs.",
    )

    @autoresponse_group.command(name="add", description="Add a new autoresponse trigger.")
    @app_commands.describe(
        trigger="The word or phrase to listen for (case-insensitive)",
        response="The message the bot will reply with",
        match_mode="How to match: contains (default), exact, or startswith",
    )
    @app_commands.choices(match_mode=[
        app_commands.Choice(name="Contains", value="contains"),
        app_commands.Choice(name="Exact match", value="exact"),
        app_commands.Choice(name="Starts with", value="startswith"),
    ])
    async def ar_add(
        self,
        interaction: discord.Interaction,
        trigger: str,
        response: str,
        match_mode: str = "contains",
    ):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        trigger_clean = trigger.strip().lower()
        if not trigger_clean or not response.strip():
            return await interaction.response.send_message(
                "Both trigger and response are required.", ephemeral=True
            )

        try:
            ar_id = db.add_autoresponse(
                str(interaction.guild_id), trigger_clean, response.strip(), match_mode
            )
        except Exception:
            return await interaction.response.send_message(
                f"A trigger for `{trigger_clean}` already exists in this server.", ephemeral=True
            )

        embed = discord.Embed(
            title="Autoresponse Added",
            color=discord.Color.green(),
        )
        embed.add_field(name="Trigger", value=f"`{trigger_clean}`", inline=True)
        embed.add_field(name="Match Mode", value=match_mode, inline=True)
        embed.add_field(name="Response", value=response.strip()[:200], inline=False)
        embed.set_footer(text=f"ID: {ar_id}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @autoresponse_group.command(name="remove", description="Remove an autoresponse by its trigger text.")
    @app_commands.describe(trigger="The trigger text to remove")
    async def ar_remove(self, interaction: discord.Interaction, trigger: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        all_ar = db.get_autoresponses(str(interaction.guild_id))
        target = trigger.strip().lower()
        found = next((a for a in all_ar if a["trigger"] == target), None)
        if not found:
            return await interaction.response.send_message(
                f"No autoresponse found for `{target}`.", ephemeral=True
            )

        db.delete_autoresponse(found["id"])
        await interaction.response.send_message(
            f"Removed autoresponse for `{target}`.", ephemeral=True
        )

    @autoresponse_group.command(name="list", description="List all autoresponses for this server.")
    async def ar_list(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_staff(interaction.user, cfg):
            return await interaction.response.send_message("Staff only.", ephemeral=True)

        all_ar = db.get_autoresponses(str(interaction.guild_id))
        if not all_ar:
            return await interaction.response.send_message(
                "No autoresponses configured.", ephemeral=True
            )

        lines = []
        for ar in all_ar:
            status = "on" if ar["enabled"] else "off"
            mode = ar.get("match_mode", "contains")
            preview = ar["response"][:60] + ("..." if len(ar["response"]) > 60 else "")
            lines.append(
                f"`{ar['trigger']}` ({mode}, {status}) -> {preview}"
            )

        embed = discord.Embed(
            title=f"Autoresponses ({len(all_ar)})",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoResponse(bot))
