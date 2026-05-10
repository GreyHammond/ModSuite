import discord
from discord import app_commands
from discord.ext import commands
import database as db
import config


class SetupMessagesModal(discord.ui.Modal, title="Customise Bot Messages"):
    selfroles_msg = discord.ui.TextInput(
        label="Self-Roles Channel Message",
        style=discord.TextStyle.long,
        placeholder="Use {role_lines} where the emoji list goes.",
        required=False, max_length=1800,
    )
    welcome_msg = discord.ui.TextInput(
        label="Welcome Message",
        style=discord.TextStyle.long,
        placeholder="Use {user}, {server}, {selfroles_ch}",
        required=False, max_length=800,
    )
    modmail_open_msg = discord.ui.TextInput(
        label="ModMail Opening Message",
        style=discord.TextStyle.long,
        placeholder="Sent to users when they open a ticket.",
        required=False, max_length=800,
    )

    def __init__(self, guild_id: int, view):
        super().__init__()
        self.guild_id = guild_id
        self._view = view

    async def on_submit(self, interaction: discord.Interaction):
        db.upsert_config(
            self.guild_id,
            selfroles_msg=self.selfroles_msg.value.strip() or config.DEFAULT_SELFROLES_MSG,
            welcome_msg=self.welcome_msg.value.strip() or config.DEFAULT_WELCOME_MSG,
            modmail_open_msg=self.modmail_open_msg.value.strip() or config.DEFAULT_MODMAIL_OPEN_MSG,
        )
        await interaction.response.send_message("✅ Messages saved!", ephemeral=True)


class SetupThresholdsModal(discord.ui.Modal, title="Warn & Raid Thresholds"):
    warn_mute = discord.ui.TextInput(
        label="Warns before auto-mute",
        placeholder="Default: 3", required=False, max_length=3,
    )
    warn_ban = discord.ui.TextInput(
        label="Warns before auto-ban",
        placeholder="Default: 5", required=False, max_length=3,
    )
    raid_joins = discord.ui.TextInput(
        label="Raid: joins to trigger lockdown",
        placeholder="Default: 10", required=False, max_length=3,
    )
    raid_seconds = discord.ui.TextInput(
        label="Raid: within how many seconds",
        placeholder="Default: 10", required=False, max_length=3,
    )

    def __init__(self, guild_id: int):
        super().__init__()
        self.guild_id = guild_id

    async def on_submit(self, interaction: discord.Interaction):
        def safe_int(val, default):
            try: return max(1, int(val.strip()))
            except: return default

        db.upsert_config(
            self.guild_id,
            warn_mute_threshold=safe_int(self.warn_mute.value, config.DEFAULT_WARN_MUTE_AT),
            warn_ban_threshold=safe_int(self.warn_ban.value, config.DEFAULT_WARN_BAN_AT),
            raid_join_count=safe_int(self.raid_joins.value, config.DEFAULT_RAID_JOINS),
            raid_join_seconds=safe_int(self.raid_seconds.value, config.DEFAULT_RAID_SECONDS),
        )
        await interaction.response.send_message("✅ Thresholds saved!", ephemeral=True)


class SetupView(discord.ui.View):
    def __init__(self, guild: discord.Guild, invoker: discord.Member):
        super().__init__(timeout=300)
        self.guild = guild
        self.invoker = invoker

    @discord.ui.button(label="✏️ Customise Messages", style=discord.ButtonStyle.secondary, row=0)
    async def customise_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message("Not your panel.", ephemeral=True)
        await interaction.response.send_modal(SetupMessagesModal(self.guild.id, self))

    @discord.ui.button(label="⚙️ Warn & Raid Settings", style=discord.ButtonStyle.secondary, row=0)
    async def customise_thresholds(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message("Not your panel.", ephemeral=True)
        await interaction.response.send_modal(SetupThresholdsModal(self.guild.id))

    @discord.ui.button(label="🚀 Run Setup", style=discord.ButtonStyle.success, row=1)
    async def run_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invoker.id:
            return await interaction.response.send_message("Not your panel.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        cfg = db.get_config(self.guild.id) or {}
        sr_msg = cfg.get("selfroles_msg") or config.DEFAULT_SELFROLES_MSG
        wm     = cfg.get("welcome_msg")   or config.DEFAULT_WELCOME_MSG
        mm_msg = cfg.get("modmail_open_msg") or config.DEFAULT_MODMAIL_OPEN_MSG

        status = []
        try:
            existing_roles = {r.name: r for r in self.guild.roles}

            # Color roles
            color_role_map = {}
            for name, color_hex, emoji in config.COLOR_ROLES:
                role = existing_roles.get(name) or await self.guild.create_role(
                    name=name, color=discord.Color(color_hex),
                    mentionable=False, reason="CommunityBot /setup"
                )
                color_role_map[emoji] = role.id
            status.append("✅ Color roles")

            # Owner & Mod roles
            owner_role = existing_roles.get(config.OWNER_ROLE_NAME) or await self.guild.create_role(
                name=config.OWNER_ROLE_NAME, color=discord.Color(config.OWNER_ROLE_COLOR),
                hoist=True, mentionable=True, permissions=discord.Permissions.all(),
                reason="CommunityBot /setup"
            )
            mod_role = existing_roles.get(config.MOD_ROLE_NAME) or await self.guild.create_role(
                name=config.MOD_ROLE_NAME, color=discord.Color(config.MOD_ROLE_COLOR),
                hoist=True, mentionable=True, reason="CommunityBot /setup"
            )
            if owner_role not in self.invoker.roles:
                await self.invoker.add_roles(owner_role, reason="CommunityBot /setup: invoker is owner")
            status.append("✅ Owner & Moderator roles")

            bot_member = self.guild.me
            everyone   = self.guild.default_role

            # ModMail category
            mm_cat_ow = {
                everyone:   discord.PermissionOverwrite(read_messages=False),
                owner_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
                mod_role:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
                bot_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
            }
            mm_cat = discord.utils.get(self.guild.categories, name=config.MODMAIL_CATEGORY_NAME)
            if mm_cat is None:
                mm_cat = await self.guild.create_category(config.MODMAIL_CATEGORY_NAME, overwrites=mm_cat_ow, reason="CommunityBot /setup")
            else:
                await mm_cat.edit(overwrites=mm_cat_ow)

            def _get_or_create_ch(cat, name):
                return discord.utils.get(cat.channels, name=name)

            mm_ch      = _get_or_create_ch(mm_cat, config.MODMAIL_CHANNEL_NAME)
            modlog_ch  = _get_or_create_ch(mm_cat, config.MODLOG_CHANNEL_NAME)
            closed_ch  = _get_or_create_ch(mm_cat, config.CLOSED_CHANNEL_NAME)
            panel_ch   = _get_or_create_ch(mm_cat, config.PANEL_CHANNEL_NAME)

            if mm_ch is None:
                mm_ch = await mm_cat.create_text_channel(config.MODMAIL_CHANNEL_NAME, reason="CommunityBot /setup")
            if modlog_ch is None:
                modlog_ch = await mm_cat.create_text_channel(config.MODLOG_CHANNEL_NAME, reason="CommunityBot /setup")
            if closed_ch is None:
                closed_ch = await mm_cat.create_text_channel(config.CLOSED_CHANNEL_NAME, reason="CommunityBot /setup")
            if panel_ch is None:
                panel_ch = await mm_cat.create_text_channel(config.PANEL_CHANNEL_NAME, reason="CommunityBot /setup")

            reports_ch = _get_or_create_ch(mm_cat, config.REPORTS_CHANNEL_NAME)
            if reports_ch is None:
                reports_ch = await mm_cat.create_text_channel(config.REPORTS_CHANNEL_NAME, reason="CommunityBot /setup")
            status.append("✅ ModMail category & channels")

            # Jail category
            jail_cat_ow = {
                everyone:   discord.PermissionOverwrite(read_messages=False),
                owner_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
                mod_role:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
                bot_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
            }
            jail_cat = discord.utils.get(self.guild.categories, name=config.JAIL_CATEGORY_NAME)
            if jail_cat is None:
                jail_cat = await self.guild.create_category(config.JAIL_CATEGORY_NAME, overwrites=jail_cat_ow, reason="CommunityBot /setup")
            else:
                await jail_cat.edit(overwrites=jail_cat_ow)
            status.append("✅ Jail category")

            # Self-roles channel
            sr_ow = {
                everyone:   discord.PermissionOverwrite(read_messages=True, send_messages=False, add_reactions=True,
                                                        create_public_threads=False, attach_files=False, embed_links=False),
                bot_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True, add_reactions=True),
            }
            sr_ch = discord.utils.get(self.guild.text_channels, name=config.SELFROLES_CHANNEL_NAME)
            if sr_ch is None:
                sr_ch = await self.guild.create_text_channel(config.SELFROLES_CHANNEL_NAME, overwrites=sr_ow, reason="CommunityBot /setup")
            else:
                await sr_ch.edit(overwrites=sr_ow)
            status.append("✅ #self-roles channel")

            # Self-roles message
            role_lines = "\n".join(f"{emoji}  →  **{name}**" for name, _, emoji in config.COLOR_ROLES)
            sr_msg_body = sr_msg.replace("{role_lines}", role_lines)

            saved_cfg = db.get_config(self.guild.id) or {}
            existing_msg_id = saved_cfg.get("selfroles_msg_id")
            selfroles_msg_obj = None
            if existing_msg_id:
                try:
                    selfroles_msg_obj = await sr_ch.fetch_message(existing_msg_id)
                    await selfroles_msg_obj.edit(content=sr_msg_body)
                except discord.NotFound:
                    selfroles_msg_obj = None
            if selfroles_msg_obj is None:
                selfroles_msg_obj = await sr_ch.send(sr_msg_body)
            for _, _, emoji in config.COLOR_ROLES:
                try:
                    await selfroles_msg_obj.add_reaction(emoji)
                except discord.HTTPException:
                    pass
            status.append("✅ Self-roles message")

            # Save config
            db.upsert_config(
                self.guild.id,
                owner_role_id=owner_role.id,
                mod_role_id=mod_role.id,
                modmail_cat_id=mm_cat.id,
                modmail_ch_id=mm_ch.id,
                selfroles_ch_id=sr_ch.id,
                modlog_ch_id=modlog_ch.id,
                closed_ch_id=closed_ch.id,
                panel_ch_id=panel_ch.id,
                reports_ch_id=reports_ch.id,
                jail_cat_id=jail_cat.id,
                selfroles_msg_id=selfroles_msg_obj.id,
                color_roles=color_role_map,
                welcome_msg=wm,
                selfroles_msg=sr_msg_body,
                modmail_open_msg=mm_msg,
                setup_complete=1,
            )
            status.append("✅ Configuration saved")
            status.append("")
            status.append("🎉 **Setup complete!** Run `/panel` in any staff channel to post the Mod Panel.")

            for child in self.children:
                child.disabled = True
            await interaction.edit_original_response(content="\n".join(status), view=self)

        except Exception as exc:
            await interaction.edit_original_response(
                content=f"❌ Setup failed: `{exc}`\nCheck bot permissions and try again.", view=self
            )
            raise


class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Set up CommunityBot for this server.")
    async def setup(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
        view = SetupView(interaction.guild, interaction.user)
        await interaction.response.send_message(
            "## 🛠️ CommunityBot Setup\n"
            "**Optional:** Customise messages and thresholds first.\n"
            "**Then:** Click **Run Setup** to build everything automatically.\n\n"
            "> ⚠️ Bot needs **Administrator** permission to create roles and channels.",
            view=view, ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Setup(bot))
