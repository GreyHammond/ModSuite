import asyncio
import json
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
            "cogs.notes",
            "cogs.admin",
            "cogs.messages",
            "cogs.verify",
            "cogs.reactmessage",
            "cogs.remindme",
            "cogs.move",
            "cogs.starboard",
            "cogs.streamer",
            "cogs.threads",
            "cogs.automod",
        ]
        for cog in cogs:
            await self.load_extension(cog)
            log.info(f"Loaded cog: {cog}")

        # ── Start REST API alongside the bot ──────────────────────────────────
        import uvicorn
        import api as api_module
        api_module.set_bot(self)
        uvicorn_config = uvicorn.Config(
            api_module.app,
            host="127.0.0.1",
            port=8000,
            log_level="warning",
        )
        server = uvicorn.Server(uvicorn_config)
        asyncio.get_event_loop().create_task(server.serve())
        log.info("REST API starting on http://127.0.0.1:8000")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        log.info(f"Serving {len(self.guilds)} guild(s).")

        from utils import DEFAULTS
        for guild in self.guilds:
            # Seed any missing bot_messages slots with defaults
            seeded = db.seed_bot_messages(str(guild.id), DEFAULTS)
            for slot in seeded:
                log.warning(
                    f"[{guild.name}] bot_messages slot '{slot}' was missing — seeded with default."
                )
            # Migrate built-in selfrole categories to the new tables (idempotent)
            db.migrate_builtin_selfrole_categories(guild.id)

        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info(f"Synced {len(synced)} command(s) to: {guild.name}")
            except Exception as e:
                log.warning(f"Failed to sync to {guild.name}: {e}")

        # Restore presence from DB if previously set, else use default
        presence_restored = False
        if self.guilds:
            cfg = db.get_config(self.guilds[0].id)
            if cfg and cfg.get("presence_type") and cfg.get("presence_text"):
                from cogs.admin import ACTIVITY_TYPES
                activity_type = ACTIVITY_TYPES.get(cfg["presence_type"], discord.ActivityType.watching)
                await self.change_presence(
                    activity=discord.Activity(type=activity_type, name=cfg["presence_text"])
                )
                presence_restored = True
        if not presence_restored:
            await self.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="Send Me A DM for Help",
                )
            )

        # ── Start bot_actions polling loop ────────────────────────────────────
        asyncio.get_event_loop().create_task(self._poll_bot_actions())
        log.info("Bot action polling loop started (interval: 5s).")

    async def _poll_bot_actions(self):
        """Poll the bot_actions table every 5 seconds and execute pending actions."""
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                pending = db.get_pending_actions()
                for action in pending:
                    await self._execute_action(action)
            except Exception as e:
                log.exception(f"Error in bot_actions poll loop: {e}")
            await asyncio.sleep(5)

    async def _execute_action(self, action: dict):
        action_id = action["action_id"]
        action_type = action["action_type"]
        try:
            payload = json.loads(action["payload"])
        except Exception:
            log.error(f"Action #{action_id}: invalid JSON payload — marking failed.")
            db.fail_action(action_id)
            return

        guild = self.get_guild(int(action["guild_id"]))
        if guild is None:
            log.warning(f"Action #{action_id}: guild {action['guild_id']} not found — skipping.")
            db.fail_action(action_id)
            return

        try:
            if action_type == "post_message":
                await self._action_post_message(guild, action_id, payload)

            elif action_type == "create_selfrole_category":
                await self._action_create_selfrole_category(guild, action_id, payload)

            else:
                log.warning(f"Action #{action_id}: unknown action_type '{action_type}' — skipping.")
                db.fail_action(action_id)

        except Exception as e:
            log.exception(f"Action #{action_id} ({action_type}) failed: {e}")
            db.fail_action(action_id)

    async def _action_post_message(self, guild, action_id: int, payload: dict):
        channel_id = int(payload["channel_id"])
        content = payload["content"]
        channel = guild.get_channel(channel_id)
        if channel is None:
            log.error(f"Action #{action_id}: channel {channel_id} not found.")
            db.fail_action(action_id)
            return
        await channel.send(content)
        db.complete_action(action_id)
        log.info(f"Action #{action_id}: posted message to #{channel.name}.")

    async def _action_create_selfrole_category(self, guild, action_id: int, payload: dict):
        """
        Create Discord roles for a new self-role category, post the
        reaction-role message, and update the DB with the real role IDs
        and message ID.
        """
        category_id = payload["category_id"]
        name = payload["name"]
        intro_text = payload.get("intro_text") or f"**{name}** — pick your role(s)!"
        roles_spec = payload.get("roles", [])  # [{"name": "PC", "emoji": "💻"}]

        # Find the self-roles channel from guild config
        cfg = db.get_config(guild.id)
        if not cfg or not cfg.get("selfroles_ch_id"):
            log.error(f"Action #{action_id}: selfroles_ch_id not configured.")
            db.fail_action(action_id)
            return

        selfroles_channel = guild.get_channel(int(cfg["selfroles_ch_id"]))
        if selfroles_channel is None:
            log.error(f"Action #{action_id}: selfroles channel not found.")
            db.fail_action(action_id)
            return

        # Create Discord roles and record (emoji, role_id) pairs
        created_pairs = []  # [(emoji, role_id_str)]
        for order, spec in enumerate(roles_spec):
            role_name = spec.get("name", f"Role {order + 1}")
            emoji = spec.get("emoji", "❓")
            try:
                discord_role = await guild.create_role(name=role_name, reason=f"Self-role category: {name}")
                created_pairs.append((emoji, str(discord_role.id), order))
                log.info(f"Action #{action_id}: created role '{role_name}' ({discord_role.id}).")
            except Exception as e:
                log.error(f"Action #{action_id}: failed to create role '{role_name}': {e}")

        # Insert role rows into DB
        with db.get_conn() as conn:
            for emoji, role_id, display_order in created_pairs:
                conn.execute(
                    "INSERT INTO selfrole_roles (category_id, role_id, emoji, display_order)"
                    " VALUES (?, ?, ?, ?)",
                    (category_id, role_id, emoji, display_order),
                )

        # Build and post the message
        lines = "\n".join(
            f"{emoji}  <@&{role_id}>"
            for emoji, role_id, _ in created_pairs
        )
        message_content = f"{intro_text}\n\n{lines}" if lines else intro_text
        msg = await selfroles_channel.send(message_content)

        # Add reactions
        for emoji, _, _ in created_pairs:
            try:
                await msg.add_reaction(emoji)
            except Exception:
                pass

        # Update category with message_id and channel_id
        db.update_selfrole_category(
            category_id,
            message_id=str(msg.id),
            channel_id=str(selfroles_channel.id),
        )

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: created self-role category '{name}' (msg {msg.id}).")

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
