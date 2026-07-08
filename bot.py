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

            elif action_type == "add_warn":
                await self._action_add_warn(guild, action_id, payload)

            elif action_type == "ticket_reply":
                await self._action_ticket_reply(guild, action_id, payload)

            elif action_type == "close_ticket":
                await self._action_close_ticket(guild, action_id, payload)

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

    # ── v2.5 Dashboard-driven action handlers ────────────────────────────────

    async def _action_add_warn(self, guild, action_id: int, payload: dict):
        """
        Add a warn from the dashboard, DM the user, and log to #mod-log.
        Payload: { user_id, reason, mod_id (optional), mod_name }
        """
        user_id  = int(payload["user_id"])
        reason   = payload["reason"]
        mod_id   = int(payload.get("mod_id")) if payload.get("mod_id") else self.user.id
        mod_name = payload.get("mod_name") or "Dashboard"

        warn_id = db.add_warn(guild.id, user_id, mod_id, mod_name, reason)

        # Also log to the canonical mod_logs table so this shows on the user's
        # /history and in the dashboard Mod Logs page alongside other actions.
        try:
            db.add_mod_log(
                guild_id=str(guild.id),
                action="WARN",
                target_id=str(user_id),
                target_username="",
                actor_id=str(mod_id),
                actor_username=mod_name,
                reason=reason,
            )
        except Exception:
            pass

        member = guild.get_member(user_id)
        if member is not None:
            try:
                template = None
                if hasattr(db, "get_bot_message"):
                    template = db.get_bot_message(guild.id, "warn_dm")
                dm_text = (template or "You have been warned in **{server}**.\nReason: {reason}").format(
                    server=guild.name,
                    user=member.mention,
                    reason=reason,
                )
                await member.send(dm_text)
            except Exception:
                pass

        cfg = db.get_config(guild.id) or {}
        modlog_id = cfg.get("modlog_ch_id")
        if modlog_id:
            ch = guild.get_channel(int(modlog_id))
            if ch is not None:
                embed = discord.Embed(
                    title="⚠️ Warn added (from dashboard)",
                    color=discord.Color.orange(),
                    timestamp=datetime.utcnow(),
                )
                embed.add_field(name="User",   value=f"<@{user_id}> (`{user_id}`)", inline=True)
                embed.add_field(name="By",     value=f"{mod_name}",                 inline=True)
                embed.add_field(name="Warn #", value=str(warn_id),                  inline=True)
                embed.add_field(name="Reason", value=reason, inline=False)
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: added warn #{warn_id} for user {user_id}.")

    async def _action_ticket_reply(self, guild, action_id: int, payload: dict):
        """
        Send a staff reply to a ModMail ticket from the dashboard.
        Payload: { ticket_id, message, anonymous }
        """
        ticket_id = int(payload["ticket_id"])
        message   = payload["message"]
        anonymous = bool(payload.get("anonymous"))

        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM modmail_tickets WHERE id = ? AND status = 'open'",
                (ticket_id,),
            ).fetchone()
        if row is None:
            log.error(f"Action #{action_id}: ticket {ticket_id} not found or not open.")
            db.fail_action(action_id)
            return

        ticket = dict(row)

        try:
            user = await self.fetch_user(int(ticket["user_id"]))
        except Exception as e:
            log.error(f"Action #{action_id}: could not fetch ticket opener: {e}")
            db.fail_action(action_id)
            return

        display = "Staff" if anonymous else "Dashboard"

        dm_embed = discord.Embed(
            description=message,
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow(),
        )
        dm_embed.set_author(name=f"💬 Reply from {display}")

        try:
            await user.send(embed=dm_embed)
        except discord.Forbidden:
            log.warning(f"Action #{action_id}: cannot DM user {user.id}.")
            db.fail_action(action_id)
            return

        channel = guild.get_channel(int(ticket["channel_id"]))
        if channel is not None:
            echo = discord.Embed(
                description=message,
                color=discord.Color.blurple(),
                timestamp=datetime.utcnow(),
            )
            echo.set_author(name=f"📤 Sent from Dashboard{' (anonymous)' if anonymous else ''}")
            try:
                await channel.send(embed=echo)
            except Exception:
                pass

        db.log_message(
            ticket["id"], self.user.id, "Dashboard",
            message, "to_user", anonymous=anonymous,
        )

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: sent dashboard reply to ticket #{ticket_id}.")

    async def _action_close_ticket(self, guild, action_id: int, payload: dict):
        """
        Close a ModMail ticket from the dashboard.
        Payload: { ticket_id }
        """
        ticket_id = int(payload["ticket_id"])

        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM modmail_tickets WHERE id = ? AND status = 'open'",
                (ticket_id,),
            ).fetchone()
        if row is None:
            log.error(f"Action #{action_id}: ticket {ticket_id} not found or already closed.")
            db.fail_action(action_id)
            return

        ticket = dict(row)
        channel = guild.get_channel(int(ticket["channel_id"]))
        if channel is None:
            with db.get_conn() as conn:
                conn.execute(
                    "UPDATE modmail_tickets SET status = 'closed', closed_at = ? WHERE id = ?",
                    (datetime.utcnow().isoformat(), ticket_id),
                )
            db.complete_action(action_id)
            log.info(f"Action #{action_id}: ticket #{ticket_id} channel missing — marked closed.")
            return

        from cogs.modmail import _close_ticket
        closed_by = guild.me if guild.me is not None else self.user

        try:
            await _close_ticket(self, guild, ticket, channel, closed_by)
        except Exception as e:
            log.exception(f"Action #{action_id}: close_ticket failed: {e}")
            db.fail_action(action_id)
            return

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: closed ticket #{ticket_id} from dashboard.")

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
