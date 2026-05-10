import asyncio
import logging
import discord
from discord.ext import commands
import database as db
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("CommunityBot")

intents = discord.Intents.default()
intents.members         = True
intents.message_content = True
intents.reactions       = True
intents.guilds          = True


class CommunityBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        db.init_db()
        log.info("Database initialised.")

        cogs = [
            "cogs.setup",
            "cogs.selfroles",
            "cogs.modmail",
            "cogs.moderation",
            "cogs.warns",
            "cogs.jail",
            "cogs.userinfo",
            "cogs.raid",
            "cogs.panel",
            "cogs.reports",
        ]
        for cog in cogs:
            await self.load_extension(cog)
            log.info(f"Loaded cog: {cog}")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        log.info(f"Serving {len(self.guilds)} guild(s).")

        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info(f"Synced {len(synced)} command(s) to: {guild.name}")
            except Exception as e:
                log.warning(f"Failed to sync to {guild.name}: {e}")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="for /setup | DM for help",
            )
        )

    async def on_guild_join(self, guild: discord.Guild):
        log.info(f"Joined guild: {guild.name} (ID: {guild.id})")
        try:
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info(f"Synced {len(synced)} command(s) to new guild: {guild.name}")
        except Exception as e:
            log.warning(f"Failed to sync to {guild.name}: {e}")

    async def on_error(self, event_method: str, *args, **kwargs):
        log.exception(f"Unhandled exception in {event_method}")


async def main():
    bot = CommunityBot()
    async with bot:
        await bot.start(config.BOT_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
