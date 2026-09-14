import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands
import database as db
import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ModSuite")

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
            "cogs.honeypot",
            "cogs.violations",
            "cogs.profiles",
            "cogs.namefilter",
            "cogs.autoresponse",
            "cogs.blueprint",
            "cogs.sentinel",
            "cogs.foia",
            "cogs.auditlog",
            "cogs.rss",
            "cogs.meetings",
            "cogs.roster",
            "cogs.boosters",
        ]
        for cog in cogs:
            await self.load_extension(cog)
            log.info(f"Loaded cog: {cog}")

        # ── Start REST API alongside the bot ──────────────────────────────────
        import uvicorn
        import os as _os
        import api as api_module
        api_module.set_bot(self)
        api_module.register_auth_routes(bot=self)
        api_host = _os.getenv("API_HOST", "0.0.0.0")
        api_port = int(_os.getenv("API_PORT", "8000"))
        uvicorn_config = uvicorn.Config(
            api_module.app,
            host=api_host,
            port=api_port,
            log_level="warning",
        )
        server = uvicorn.Server(uvicorn_config)
        asyncio.get_event_loop().create_task(server.serve())
        log.info(f"REST API starting on http://{api_host}:{api_port}")

    async def on_ready(self):
        log.info(f"Logged in as {self.user} (ID: {self.user.id})")
        log.info(f"Serving {len(self.guilds)} guild(s).")

        from utils import DEFAULTS
        for guild in self.guilds:
            # Seed any missing bot_messages slots with defaults
            seeded = db.seed_bot_messages(str(guild.id), DEFAULTS)
            for slot in seeded:
                log.warning(
                    f"[{guild.name}] bot_messages slot '{slot}' was missing -- seeded with default."
                )
            # Migrate built-in selfrole categories to the new tables (idempotent)
            db.migrate_builtin_selfrole_categories(guild.id)
            # Seed built-in automod profiles (normal, strict, raid)
            db.seed_profiles(str(guild.id))

        # Load any blueprint JSON files shipped in blueprints/ into the DB.
        # Global scope, so every guild can see them; guild-owned blueprints
        # with the same name still take precedence.
        try:
            from cogs.blueprint import seed_bundled_blueprints
            names = seed_bundled_blueprints()
            if names:
                log.info(f"Loaded {len(names)} bundled blueprint(s): {', '.join(names)}")
        except Exception as e:
            log.warning(f"Blueprint seeding failed: {e}")

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
            log.error(f"Action #{action_id}: invalid JSON payload -- marking failed.")
            db.fail_action(action_id)
            return

        guild = self.get_guild(int(action["guild_id"]))
        if guild is None:
            log.warning(f"Action #{action_id}: guild {action['guild_id']} not found -- skipping.")
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

            elif action_type == "streamer_add":
                await self._action_streamer_add(guild, action_id, payload)

            elif action_type == "streamer_remove":
                await self._action_streamer_remove(guild, action_id, payload)

            elif action_type == "streamer_edit":
                await self._action_streamer_edit(guild, action_id, payload)

            elif action_type == "streamer_refresh_card":
                await self._action_streamer_refresh_card(guild, action_id, payload)

            elif action_type == "react_publish":
                await self._action_react_publish(guild, action_id, payload)

            elif action_type == "react_delete":
                await self._action_react_delete(guild, action_id, payload)

            elif action_type.startswith("mod_"):
                await self._action_moderation(
                    guild, action_id, payload, action_type[len("mod_"):]
                )

            else:
                log.warning(f"Action #{action_id}: unknown action_type '{action_type}' -- skipping.")
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
        intro_text = payload.get("intro_text") or f"**{name}** -- pick your role(s)!"
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
            log.info(f"Action #{action_id}: ticket #{ticket_id} channel missing -- marked closed.")
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

    # ── Streamer actions (dashboard) ─────────────────────────────────────────
    #
    # The API writes database state and queues these for the Discord-side work,
    # because the API process has no gateway connection. Each handler is
    # tolerant of the streamer having left the guild: role work is skipped,
    # channel work still happens.

    async def _action_streamer_add(self, guild, action_id: int, payload: dict):
        """
        Register a streamer: create their personal channel, grant the Streamer
        role, write the DB row, and pin the info card.
        Payload: { user_id, twitch_username }
        """
        from cogs.streamer import (
            _get_or_create_category, _get_or_create_live_channel,
            _get_or_create_alerts_role, _update_pinned_info,
        )

        user_id = str(payload["user_id"])
        twitch = payload["twitch_username"]
        guild_id = str(guild.id)

        if db.get_streamer(guild_id, user_id):
            log.warning(f"Action #{action_id}: {user_id} is already a streamer.")
            db.fail_action(action_id)
            return

        member = guild.get_member(int(user_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(user_id))
            except Exception:
                member = None
        if member is None:
            log.error(f"Action #{action_id}: {user_id} is not in the guild -- cannot create channel overwrites.")
            db.fail_action(action_id)
            return

        category = await _get_or_create_category(guild)
        await _get_or_create_live_channel(guild, category)
        await _get_or_create_alerts_role(guild)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True),
            member: discord.PermissionOverwrite(
                manage_messages=True, pin_messages=True),
            guild.me: discord.PermissionOverwrite(
                send_messages=True, manage_messages=True),
        }
        personal_ch = await guild.create_text_channel(
            f"{twitch.lower()}-chat",
            category=category,
            overwrites=overwrites,
            topic=f"Chat for {twitch} | Twitch: twitch.tv/{twitch}",
        )

        streamer_role = discord.utils.get(guild.roles, name="Streamer")
        if streamer_role:
            try:
                await member.add_roles(streamer_role, reason="ModSuite: Streamer added via dashboard")
            except discord.Forbidden:
                log.warning(f"Action #{action_id}: could not grant Streamer role to {user_id}.")

        db.add_streamer(
            guild_id=guild_id,
            user_id=user_id,
            twitch_username=twitch,
            channel_id=str(personal_ch.id),
        )
        db.add_mod_log(
            guild_id=guild_id,
            action="STREAMER_ADDED",
            target_id=user_id,
            target_username=str(member),
            actor_id="dashboard",
            actor_username="Dashboard",
            reason=f"Twitch: {twitch}",
        )

        row = db.get_streamer(guild_id, user_id)
        try:
            await _update_pinned_info(self, guild, row)
        except Exception as e:
            log.warning(f"Action #{action_id}: pinned card failed: {e}")

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: added streamer {twitch} ({user_id}).")

    async def _action_streamer_remove(self, guild, action_id: int, payload: dict):
        """
        Tear down a streamer: delete their channel and strip the Streamer role.
        The DB row is already gone by the time this runs.
        Payload: { user_id, channel_id, twitch_username }

        Deliberately tolerant: a streamer who has left the guild still needs
        their channel deleted, which was the bug that made this page necessary.
        """
        user_id = str(payload["user_id"])
        channel_id = payload.get("channel_id")

        if channel_id:
            ch = guild.get_channel(int(channel_id))
            if ch:
                try:
                    await ch.delete(reason="ModSuite: Streamer removed via dashboard")
                except discord.Forbidden:
                    log.warning(f"Action #{action_id}: no permission to delete channel {channel_id}.")
                except discord.NotFound:
                    pass

        member = guild.get_member(int(user_id))
        if member is not None:
            streamer_role = discord.utils.get(guild.roles, name="Streamer")
            if streamer_role and streamer_role in member.roles:
                try:
                    await member.remove_roles(streamer_role, reason="ModSuite: Streamer removed via dashboard")
                except discord.Forbidden:
                    log.warning(f"Action #{action_id}: no permission to remove Streamer role from {user_id}.")
        else:
            log.info(f"Action #{action_id}: {user_id} has left the guild -- role removal skipped.")

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: removed streamer {user_id}.")

    async def _action_streamer_edit(self, guild, action_id: int, payload: dict):
        """
        Rename a streamer's channel to match a new Twitch username and refresh
        the pinned card. The DB row was already updated by the API.
        Payload: { user_id, twitch_username }
        """
        from cogs.streamer import _update_pinned_info

        user_id = str(payload["user_id"])
        twitch = payload["twitch_username"]
        row = db.get_streamer(str(guild.id), user_id)
        if row is None:
            log.error(f"Action #{action_id}: no streamer row for {user_id}.")
            db.fail_action(action_id)
            return

        ch = guild.get_channel(int(row["channel_id"])) if row.get("channel_id") else None
        if ch:
            try:
                await ch.edit(
                    name=f"{twitch.lower()}-chat",
                    topic=f"Chat for {twitch} | Twitch: twitch.tv/{twitch}",
                )
            except discord.Forbidden:
                log.warning(f"Action #{action_id}: no permission to rename channel.")
            except discord.HTTPException as e:
                # Channel renames are heavily rate limited (2 per 10 minutes).
                log.warning(f"Action #{action_id}: channel rename deferred: {e}")

        try:
            await _update_pinned_info(self, guild, row)
        except Exception as e:
            log.warning(f"Action #{action_id}: pinned card failed: {e}")

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: updated streamer {user_id} to {twitch}.")

    async def _action_streamer_refresh_card(self, guild, action_id: int, payload: dict):
        """Rebuild the pinned info card after a links change. Payload: { user_id }"""
        from cogs.streamer import _update_pinned_info

        row = db.get_streamer(str(guild.id), str(payload["user_id"]))
        if row is None:
            db.fail_action(action_id)
            return
        try:
            await _update_pinned_info(self, guild, row)
        except Exception as e:
            log.warning(f"Action #{action_id}: pinned card refresh failed: {e}")
        db.complete_action(action_id)

    # ── Moderation actions (dashboard) ───────────────────────────────────────
    #
    # The API queues these with the authenticated staff member's Discord ID in
    # the payload. Hierarchy is re-checked here rather than in the API, because
    # only the bot process has the member objects and role cache needed to
    # evaluate it. A dashboard action therefore cannot do anything the same
    # person could not do with a slash command.

    async def _mod_actor(self, guild, payload: dict):
        """
        Resolve the staff member who requested the action.

        Returns (member_or_None, display_name). None means the action was
        issued without a resolvable Discord identity, which is treated as an
        automated action -- utils.can_moderate already allows everything except
        acting on the server owner in that case.
        """
        actor_id = payload.get("actor_id")
        name = payload.get("actor_name") or "Dashboard"
        if not actor_id or str(actor_id) == "0":
            return None, name
        member = guild.get_member(int(actor_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(actor_id))
            except Exception:
                member = None
        return member, (member.display_name if member else name)

    async def _mod_target(self, guild, payload: dict):
        """Resolve the target. Never fails for a well-formed ID."""
        from utils import resolve_user
        return await resolve_user(self, guild, str(payload["user_id"]))

    def _mod_denied(self, action_id: int, why: str):
        log.warning(f"Action #{action_id}: refused -- {why}")
        db.fail_action(action_id)

    async def _action_moderation(self, guild, action_id: int, payload: dict, action: str):
        """
        Shared entry point for every mod_* action.
        Payload: { user_id, reason, duration, delete_days, notify,
                   actor_id, actor_name }
        """
        from utils import can_moderate
        from cogs.moderation import parse_duration, _fmt_td, _post_modlog

        reason = payload.get("reason") or "No reason provided."
        notify = bool(payload.get("notify", True))
        cfg = db.get_config(guild.id) or {}

        actor, actor_name = await self._mod_actor(guild, payload)
        try:
            target, in_guild = await self._mod_target(guild, payload)
        except ValueError as e:
            return self._mod_denied(action_id, str(e))

        audit = f"{actor_name} via dashboard -- {reason}"

        # Hierarchy re-check. Only meaningful when both sides are present.
        if in_guild and not can_moderate(actor, target, cfg):
            return self._mod_denied(
                action_id,
                f"{actor_name} may not act on {target} (permission hierarchy).",
            )

        duration = payload.get("duration")
        td = parse_duration(duration) if duration else None
        if duration and td is None:
            return self._mod_denied(action_id, f"unrecognised duration '{duration}'.")

        # DM before the action, while we can still reach them.
        if notify and in_guild and action in {"kick", "ban", "mute"}:
            try:
                await target.send(embed=discord.Embed(
                    description=(
                        f"You have been {action}ed in **{guild.name}**.\n"
                        f"Reason: {reason}"
                        + (f"\nDuration: {_fmt_td(td)}" if td else "")
                    ),
                    color=discord.Color.red(),
                ))
            except Exception:
                pass

        log_action = action.upper()
        extra = ""

        try:
            if action == "warn":
                db.add_warn(guild.id, target.id,
                            int(actor.id) if actor else self.user.id,
                            actor_name, reason)

            elif action == "kick":
                await guild.kick(discord.Object(id=target.id), reason=audit)

            elif action == "ban":
                await guild.ban(
                    discord.Object(id=target.id),
                    reason=audit,
                    delete_message_days=max(0, min(7, payload.get("delete_days") or 0)),
                )
                if td:
                    unban_at = datetime.now(timezone.utc) + td
                    db.add_timed_ban(guild.id, target.id, unban_at, reason)
                    log_action = "TEMPBAN"
                    extra = f" (auto-unban in {_fmt_td(td)})"

            elif action == "unban":
                try:
                    await guild.unban(discord.Object(id=target.id), reason=audit)
                except discord.NotFound:
                    return self._mod_denied(action_id, f"{target.id} is not on the ban list.")
                db.remove_timed_ban(guild.id, target.id)

            elif action == "mute":
                span = td or timedelta(days=28)
                await target.timeout(
                    datetime.now(timezone.utc) + min(span, timedelta(days=28)),
                    reason=audit,
                )
                db.add_mute(guild.id, target.id,
                            datetime.now(timezone.utc) + span, reason)
                extra = f" for {_fmt_td(span)}"

            elif action == "unmute":
                try:
                    await target.timeout(None, reason=audit)
                except discord.Forbidden:
                    pass
                db.remove_mute(guild.id, target.id)

            elif action == "jail":
                from cogs.jail import do_jail
                if db.get_jail(guild.id, target.id):
                    return self._mod_denied(action_id, f"{target} is already jailed.")
                end = (datetime.utcnow() + td) if td else None
                await do_jail(guild, target, actor, reason, notify, self, jail_end_time=end)
                if td:
                    extra = f" for {_fmt_td(td)}"

            elif action == "unjail":
                from cogs.jail import do_unjail
                ok, msg = await do_unjail(guild, target, actor, self, is_member=in_guild)
                if not ok:
                    return self._mod_denied(action_id, msg)
                if not in_guild:
                    extra = " (they had already left; record and channel cleared)"

            else:
                return self._mod_denied(action_id, f"unknown action '{action}'.")

        except discord.Forbidden:
            return self._mod_denied(
                action_id,
                f"the bot lacks permission to {action} {target}.",
            )
        except discord.HTTPException as e:
            return self._mod_denied(action_id, f"Discord rejected the {action}: {e}")

        # jail and unjail write their own mod_log rows.
        if action not in {"jail", "unjail"}:
            db.add_mod_log(
                guild_id=str(guild.id),
                action=log_action,
                target_id=str(target.id),
                target_username=str(target),
                actor_id=str(actor.id) if actor else "0",
                actor_username=actor_name,
                reason=reason,
            )

            embed = discord.Embed(
                title=f"{log_action.title()} (from dashboard)",
                color=discord.Color.orange(),
                timestamp=datetime.utcnow(),
            )
            embed.add_field(name="User", value=f"{target} (`{target.id}`)", inline=True)
            embed.add_field(name="By", value=actor.mention if actor else actor_name, inline=True)
            if not in_guild:
                embed.add_field(name="Note", value="Not in the server", inline=True)
            embed.add_field(name="Reason", value=reason, inline=False)
            try:
                await _post_modlog(guild, cfg, embed)
            except Exception:
                pass

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: {log_action} {target.id} by {actor_name}{extra}.")

    # ── React-role message actions (dashboard) ───────────────────────────────
    #
    # The browser composes the message and the bot posts it. Unlike the
    # /createreactmessage draft flow there is no intermediate draft message in
    # a channel, because the dashboard form already serves that purpose.

    async def _action_react_publish(self, guild, action_id: int, payload: dict):
        """
        Post or update a react-role message and sync its reactions.
        Payload: { category_id, channel_id, message_id?, title, intro_text, roles }

        The database rows are already written by the API, so this is purely the
        Discord side: render the embed, put it in the channel, and make the
        reactions on the message match the mappings exactly.
        """
        from cogs.reactmessage import _build_published_embed

        category_id = int(payload["category_id"])
        channel_id = payload.get("channel_id")
        roles = payload.get("roles") or []

        if not channel_id:
            log.error(f"Action #{action_id}: no channel for react message #{category_id}.")
            db.fail_action(action_id)
            return

        channel = guild.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.fetch_channel(int(channel_id))
            except Exception:
                log.error(f"Action #{action_id}: channel {channel_id} unreachable.")
                db.fail_action(action_id)
                return

        embed = _build_published_embed(
            {"title": payload.get("title") or "Roles",
             "intro_text": payload.get("intro_text") or ""},
            roles,
        )

        msg = None
        existing_id = payload.get("message_id")
        if existing_id:
            try:
                msg = await channel.fetch_message(int(existing_id))
                await msg.edit(embed=embed)
            except discord.NotFound:
                # Someone deleted it out from under us. Fall through and post
                # a fresh one rather than failing the whole action.
                log.info(f"Action #{action_id}: message {existing_id} is gone, reposting.")
                msg = None
            except discord.Forbidden:
                log.error(f"Action #{action_id}: no permission to edit in #{channel}.")
                db.fail_action(action_id)
                return

        if msg is None:
            try:
                msg = await channel.send(embed=embed)
            except discord.Forbidden:
                log.error(f"Action #{action_id}: no permission to post in #{channel}.")
                db.fail_action(action_id)
                return
            db.update_selfrole_category(
                category_id,
                message_id=str(msg.id),
                channel_id=str(channel.id),
            )

        # Sync reactions to the mappings. Only touch what actually differs, so
        # members who already reacted keep their roles instead of being cleared
        # and forced to re-react on every edit.
        wanted = [r["emoji"] for r in roles]
        present = []
        for reaction in msg.reactions:
            present.append(str(reaction.emoji))

        for emoji in present:
            if emoji not in wanted:
                try:
                    await msg.clear_reaction(emoji)
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass

        for emoji in wanted:
            if emoji not in present:
                try:
                    await msg.add_reaction(emoji)
                except discord.HTTPException as e:
                    # Almost always a custom emoji from a server the bot is not
                    # in. Log which one rather than failing silently.
                    log.warning(f"Action #{action_id}: could not add reaction {emoji}: {e}")

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: published react message #{category_id} "
                 f"to #{channel} with {len(roles)} mapping(s).")

    async def _action_react_delete(self, guild, action_id: int, payload: dict):
        """Delete a published react-role message. Payload: { channel_id, message_id }"""
        channel_id = payload.get("channel_id")
        message_id = payload.get("message_id")
        if not (channel_id and message_id):
            db.complete_action(action_id)
            return

        channel = guild.get_channel(int(channel_id))
        if channel is not None:
            try:
                msg = await channel.fetch_message(int(message_id))
                await msg.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

        db.complete_action(action_id)
        log.info(f"Action #{action_id}: removed react message {message_id}.")

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
