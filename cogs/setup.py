"""
setup.py — ModSuite v1.5

/setup flow:
  1. Admin invokes /setup → sees SetupView (customise messages, thresholds, Run Setup)
  2. "Run Setup" → inventories existing resources, shows confirmation embed
  3. "Confirm" → creates ONLY missing resources
  4. "Cancel" → dismisses, nothing changed

Branding footer: ModSuite · Hammond Digital Studios
NOTE FOR PANEL.PY: The persistent Mod Panel (posted via /panel in cogs/panel.py)
also needs footer text "ModSuite · Hammond Digital Studios" added to its embed.
That file is outside this agent's scope and must be updated separately.
"""
import discord
from discord import app_commands
from discord.ext import commands
import database as db
import config

FOOTER_BRAND = "ModSuite · Hammond Digital Studios"

# ── New role definitions ─────────────────────────────────────────────────────
# (cfg_key, display_name)  — no special perms or forced color per spec
DM_PREF_ROLES = [
    ("role_dm_open",   "DM Open"),
    ("role_dm_closed", "DM Closed"),
    ("role_ask_to_dm", "Ask to DM"),
]

PRONOUN_ROLES = [
    ("role_he_him",       "He/Him"),
    ("role_she_her",      "She/Her"),
    ("role_they_them",    "They/Them"),
    ("role_xe_xer",       "Xe/Xer"),
    ("role_it_its",       "It/Its"),
    ("role_any_all",      "Any/All"),
    ("role_ask_pronouns", "Ask My Pronouns"),
]

DM_PREFS_EMOJIS   = ["✅", "🚫", "❓"]
PRONOUN_EMOJIS    = ["🔵", "🔴", "🟣", "🟡", "🟢", "🌈", "💬"]


# ── Inventory ────────────────────────────────────────────────────────────────

def _inventory(cfg: dict) -> tuple[list[str], list[str], str]:
    """
    Inspect guild_config and return:
      configured  — list of human-readable labels for resources that exist
      to_create   — list of human-readable labels for resources that are missing
      status      — one of 'fresh', 'update', 'complete'
    """
    configured: list[str] = []
    to_create:  list[str] = []

    def check(label: str, present: bool):
        (configured if present else to_create).append(label)

    # ── v1.0 resources ────────────────────────────────────────────────────────
    check("Color roles",
          bool(cfg.get("color_roles")))
    check("Owner & Moderator roles",
          bool(cfg.get("owner_role_id") and cfg.get("mod_role_id")))
    check("ModMail category & channels",
          bool(cfg.get("modmail_cat_id")))
    check("Jail category",
          bool(cfg.get("jail_cat_id")))
    check("Self-roles channel (#self-roles)",
          bool(cfg.get("selfroles_ch_id")))
    check("Color roles message",
          bool(cfg.get("selfroles_msg_id")))

    # ── v1.5 resources ────────────────────────────────────────────────────────
    dm_roles_present = all(cfg.get(k) for k, _ in DM_PREF_ROLES)
    check("DM Preference roles (DM Open, DM Closed, Ask to DM)", dm_roles_present)

    check("DM Preferences self-roles message",
          bool(cfg.get("selfroles_dm_message_id")))

    pronoun_roles_present = all(cfg.get(k) for k, _ in PRONOUN_ROLES)
    check("Pronoun roles (He/Him, She/Her, They/Them, Xe/Xer, It/Its, Any/All, Ask My Pronouns)",
          pronoun_roles_present)

    check("Pronouns self-roles message",
          bool(cfg.get("selfroles_pronouns_message_id")))

    if not configured:
        status = "fresh"
    elif not to_create:
        status = "complete"
    else:
        status = "update"

    return configured, to_create, status


def _build_confirmation_embed(
    configured: list[str], to_create: list[str], status: str
) -> discord.Embed:
    status_labels = {
        "fresh":    "Fresh Installation",
        "update":   "Existing Installation — Update Available",
        "complete": "Everything is already configured",
    }
    embed = discord.Embed(
        title="🔧 ModSuite Setup — Review Before Continuing",
        color=0x3498DB,
    )
    embed.description = f"**Detected:** {status_labels[status]}"

    if configured:
        embed.add_field(
            name="✅ Already configured (will not be changed)",
            value="\n".join(f"• {item}" for item in configured),
            inline=False,
        )

    if to_create:
        embed.add_field(
            name="🆕 Will be created",
            value="\n".join(f"• {item}" for item in to_create),
            inline=False,
        )
    else:
        embed.add_field(
            name="🆕 Will be created",
            value="Nothing to do — server is fully up to date.",
            inline=False,
        )

    embed.set_footer(text=FOOTER_BRAND)
    return embed


# ── Confirm / Cancel View ────────────────────────────────────────────────────

class ConfirmSetupView(discord.ui.View):
    def __init__(self, guild: discord.Guild, invoker: discord.Member, to_create: list[str]):
        super().__init__(timeout=180)
        self.guild    = guild
        self.invoker  = invoker
        self.to_create = to_create

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ Confirm Setup", style=discord.ButtonStyle.success, row=0)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        await interaction.response.defer()  # type 6 — defers update, allows edit_original_response

        cfg = db.get_config(self.guild.id) or {}
        created: list[str] = []

        try:
            existing_roles = {r.name: r for r in self.guild.roles}
            bot_member     = self.guild.me
            everyone       = self.guild.default_role

            # ── Color roles ───────────────────────────────────────────────────
            if not cfg.get("color_roles"):
                color_role_map = {}
                for name, color_hex, emoji in config.COLOR_ROLES:
                    role = existing_roles.get(name) or await self.guild.create_role(
                        name=name, color=discord.Color(color_hex),
                        mentionable=False, reason="ModSuite /setup"
                    )
                    color_role_map[emoji] = role.id
                db.upsert_config(self.guild.id, color_roles=color_role_map)
                cfg = db.get_config(self.guild.id) or {}
                created.append("Color roles")

            # ── Owner & Mod roles ─────────────────────────────────────────────
            owner_role = (
                self.guild.get_role(cfg["owner_role_id"]) if cfg.get("owner_role_id") else None
            ) or existing_roles.get(config.OWNER_ROLE_NAME)
            mod_role = (
                self.guild.get_role(cfg["mod_role_id"]) if cfg.get("mod_role_id") else None
            ) or existing_roles.get(config.MOD_ROLE_NAME)

            roles_created = False
            if owner_role is None:
                owner_role = await self.guild.create_role(
                    name=config.OWNER_ROLE_NAME, color=discord.Color(config.OWNER_ROLE_COLOR),
                    hoist=True, mentionable=True, permissions=discord.Permissions.all(),
                    reason="ModSuite /setup"
                )
                roles_created = True
            if mod_role is None:
                mod_role = await self.guild.create_role(
                    name=config.MOD_ROLE_NAME, color=discord.Color(config.MOD_ROLE_COLOR),
                    hoist=True, mentionable=True, reason="ModSuite /setup"
                )
                roles_created = True
            if owner_role not in self.invoker.roles:
                await self.invoker.add_roles(owner_role, reason="ModSuite /setup: invoker is owner")
            if roles_created or not cfg.get("owner_role_id") or not cfg.get("mod_role_id"):
                db.upsert_config(self.guild.id, owner_role_id=owner_role.id, mod_role_id=mod_role.id)
                cfg = db.get_config(self.guild.id) or {}
                if roles_created:
                    created.append("Owner & Moderator roles")

            # ── ModMail category & channels ───────────────────────────────────
            if not cfg.get("modmail_cat_id"):
                mm_cat_ow = {
                    everyone:   discord.PermissionOverwrite(read_messages=False),
                    owner_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
                    mod_role:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    bot_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
                }
                mm_cat = discord.utils.get(self.guild.categories, name=config.MODMAIL_CATEGORY_NAME)
                if mm_cat is None:
                    mm_cat = await self.guild.create_category(
                        config.MODMAIL_CATEGORY_NAME, overwrites=mm_cat_ow, reason="ModSuite /setup"
                    )
                else:
                    await mm_cat.edit(overwrites=mm_cat_ow)

                def _get_or_create_ch_ref(cat, name):
                    return discord.utils.get(cat.channels, name=name)

                async def _ensure_ch(cat, name):
                    ch = _get_or_create_ch_ref(cat, name)
                    if ch is None:
                        ch = await cat.create_text_channel(name, reason="ModSuite /setup")
                    return ch

                mm_ch      = await _ensure_ch(mm_cat, config.MODMAIL_CHANNEL_NAME)
                modlog_ch  = await _ensure_ch(mm_cat, config.MODLOG_CHANNEL_NAME)
                closed_ch  = await _ensure_ch(mm_cat, config.CLOSED_CHANNEL_NAME)
                panel_ch   = await _ensure_ch(mm_cat, config.PANEL_CHANNEL_NAME)
                reports_ch = await _ensure_ch(mm_cat, config.REPORTS_CHANNEL_NAME)

                db.upsert_config(
                    self.guild.id,
                    modmail_cat_id=mm_cat.id,
                    modmail_ch_id=mm_ch.id,
                    modlog_ch_id=modlog_ch.id,
                    closed_ch_id=closed_ch.id,
                    panel_ch_id=panel_ch.id,
                    reports_ch_id=reports_ch.id,
                )
                cfg = db.get_config(self.guild.id) or {}
                created.append("ModMail category & channels")

            # ── Jail category ─────────────────────────────────────────────────
            if not cfg.get("jail_cat_id"):
                jail_cat_ow = {
                    everyone:   discord.PermissionOverwrite(read_messages=False),
                    owner_role: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
                    mod_role:   discord.PermissionOverwrite(read_messages=True, send_messages=True),
                    bot_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True),
                }
                jail_cat = discord.utils.get(self.guild.categories, name=config.JAIL_CATEGORY_NAME)
                if jail_cat is None:
                    jail_cat = await self.guild.create_category(
                        config.JAIL_CATEGORY_NAME, overwrites=jail_cat_ow, reason="ModSuite /setup"
                    )
                else:
                    await jail_cat.edit(overwrites=jail_cat_ow)
                db.upsert_config(self.guild.id, jail_cat_id=jail_cat.id)
                cfg = db.get_config(self.guild.id) or {}
                created.append("Jail category")

            # ── Self-roles channel ────────────────────────────────────────────
            sr_ch = None
            if cfg.get("selfroles_ch_id"):
                sr_ch = self.guild.get_channel(cfg["selfroles_ch_id"])

            if sr_ch is None:
                sr_ow = {
                    everyone:   discord.PermissionOverwrite(
                        read_messages=True, send_messages=False, add_reactions=True,
                        create_public_threads=False, attach_files=False, embed_links=False,
                    ),
                    bot_member: discord.PermissionOverwrite(
                        read_messages=True, send_messages=True, manage_messages=True, add_reactions=True,
                    ),
                }
                sr_ch = discord.utils.get(self.guild.text_channels, name=config.SELFROLES_CHANNEL_NAME)
                if sr_ch is None:
                    sr_ch = await self.guild.create_text_channel(
                        config.SELFROLES_CHANNEL_NAME, overwrites=sr_ow, reason="ModSuite /setup"
                    )
                else:
                    await sr_ch.edit(overwrites=sr_ow)
                db.upsert_config(self.guild.id, selfroles_ch_id=sr_ch.id)
                cfg = db.get_config(self.guild.id) or {}
                created.append("Self-roles channel (#self-roles)")
            else:
                # Channel already exists — make sure we have a reference for message posting below
                pass

            # ── Color roles message (never reposted if already stored) ─────────
            if not cfg.get("selfroles_msg_id"):
                sr_msg_text = cfg.get("selfroles_msg") or config.DEFAULT_SELFROLES_MSG
                role_lines  = "\n".join(f"{emoji}  →  **{name}**" for name, _, emoji in config.COLOR_ROLES)
                sr_msg_body = sr_msg_text.replace("{role_lines}", role_lines)
                sr_msg_obj  = await sr_ch.send(sr_msg_body)
                for _, _, emoji in config.COLOR_ROLES:
                    try:
                        await sr_msg_obj.add_reaction(emoji)
                    except discord.HTTPException:
                        pass
                db.upsert_config(self.guild.id, selfroles_msg_id=sr_msg_obj.id)
                cfg = db.get_config(self.guild.id) or {}
                created.append("Color roles message")

            # ── DM Preference roles ───────────────────────────────────────────
            dm_roles_missing = [
                (cfg_key, name) for cfg_key, name in DM_PREF_ROLES if not cfg.get(cfg_key)
            ]
            if dm_roles_missing:
                dm_updates = {}
                for cfg_key, name in dm_roles_missing:
                    role = existing_roles.get(name) or await self.guild.create_role(
                        name=name, reason="ModSuite /setup"
                    )
                    dm_updates[cfg_key] = role.id
                db.upsert_config(self.guild.id, **dm_updates)
                cfg = db.get_config(self.guild.id) or {}
                created.append("DM Preference roles (DM Open, DM Closed, Ask to DM)")

            # ── DM Preferences message ────────────────────────────────────────
            if not cfg.get("selfroles_dm_message_id"):
                dm_lines = "\n".join(
                    f"{emoji}  →  **{name}**"
                    for emoji, (_, name) in zip(DM_PREFS_EMOJIS, DM_PREF_ROLES)
                )
                dm_embed = discord.Embed(
                    title="✉️ DM Preferences",
                    description=(
                        "Let others know your DM preferences. **Pick one.**\n\n"
                        + dm_lines
                    ),
                    color=discord.Color.blurple(),
                )
                dm_embed.set_footer(text="Remove your reaction to unassign the role.")
                dm_msg = await sr_ch.send(embed=dm_embed)
                for emoji in DM_PREFS_EMOJIS:
                    try:
                        await dm_msg.add_reaction(emoji)
                    except discord.HTTPException:
                        pass
                db.upsert_config(self.guild.id, selfroles_dm_message_id=dm_msg.id)
                cfg = db.get_config(self.guild.id) or {}
                created.append("DM Preferences self-roles message")

            # ── Pronoun roles ─────────────────────────────────────────────────
            pronoun_roles_missing = [
                (cfg_key, name) for cfg_key, name in PRONOUN_ROLES if not cfg.get(cfg_key)
            ]
            if pronoun_roles_missing:
                pronoun_updates = {}
                for cfg_key, name in pronoun_roles_missing:
                    role = existing_roles.get(name) or await self.guild.create_role(
                        name=name, reason="ModSuite /setup"
                    )
                    pronoun_updates[cfg_key] = role.id
                db.upsert_config(self.guild.id, **pronoun_updates)
                cfg = db.get_config(self.guild.id) or {}
                created.append("Pronoun roles (He/Him, She/Her, They/Them, Xe/Xer, It/Its, Any/All, Ask My Pronouns)")

            # ── Pronouns message ──────────────────────────────────────────────
            if not cfg.get("selfroles_pronouns_message_id"):
                pronoun_lines = "\n".join(
                    f"{emoji}  →  **{name}**"
                    for emoji, (_, name) in zip(PRONOUN_EMOJIS, PRONOUN_ROLES)
                )
                pronoun_embed = discord.Embed(
                    title="🏷️ Pronouns",
                    description=(
                        "Select any that apply. **You can pick multiple.**\n\n"
                        + pronoun_lines
                    ),
                    color=discord.Color.purple(),
                )
                pronoun_embed.set_footer(text="Remove your reaction to unassign the role.")
                pronoun_msg = await sr_ch.send(embed=pronoun_embed)
                for emoji in PRONOUN_EMOJIS:
                    try:
                        await pronoun_msg.add_reaction(emoji)
                    except discord.HTTPException:
                        pass
                db.upsert_config(self.guild.id, selfroles_pronouns_message_id=pronoun_msg.id)
                cfg = db.get_config(self.guild.id) or {}
                created.append("Pronouns self-roles message")

            # ── Finalise ──────────────────────────────────────────────────────
            db.upsert_config(self.guild.id, setup_complete=1)

            # Seed bot_messages defaults for any slots not yet present, then
            # migrate the three built-in selfrole categories to the new tables.
            # Both operations are idempotent — safe to call on re-runs.
            from utils import DEFAULTS
            db.seed_bot_messages(str(self.guild.id), DEFAULTS)
            db.migrate_builtin_selfrole_categories(self.guild.id)

            for child in self.children:
                child.disabled = True

            if created:
                result_embed = discord.Embed(
                    title="✅ Setup Complete",
                    description="The following resources were created:\n" + "\n".join(f"• {c}" for c in created),
                    color=discord.Color.green(),
                )
                result_embed.add_field(
                    name="Next step",
                    value="Run `/panel` in any staff channel to post the Mod Panel.",
                    inline=False,
                )
            else:
                result_embed = discord.Embed(
                    title="✅ Already Up to Date",
                    description="Server is fully configured — nothing needed to be created.",
                    color=discord.Color.green(),
                )
            result_embed.set_footer(text=FOOTER_BRAND)
            await interaction.edit_original_response(embed=result_embed, view=self)

        except Exception as exc:
            err_embed = discord.Embed(
                title="❌ Setup Failed",
                description=f"`{exc}`\n\nCheck bot permissions and try again.",
                color=discord.Color.red(),
            )
            err_embed.set_footer(text=FOOTER_BRAND)
            await interaction.edit_original_response(embed=err_embed, view=self)
            raise

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary, row=0)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction):
            return
        for child in self.children:
            child.disabled = True
        cancel_embed = discord.Embed(
            description="Setup cancelled. Nothing was changed.",
            color=discord.Color.greyple(),
        )
        cancel_embed.set_footer(text=FOOTER_BRAND)
        await interaction.response.edit_message(embed=cancel_embed, view=self)


# ── Main SetupView ────────────────────────────────────────────────────────────

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
        self._view    = view

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
        label="Warns before auto-jail",
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
        self.guild   = guild
        self.invoker = invoker

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✏️ Customise Messages", style=discord.ButtonStyle.secondary, row=0)
    async def customise_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction): return
        await interaction.response.send_modal(SetupMessagesModal(self.guild.id, self))

    @discord.ui.button(label="⚙️ Warn & Raid Settings", style=discord.ButtonStyle.secondary, row=0)
    async def customise_thresholds(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction): return
        await interaction.response.send_modal(SetupThresholdsModal(self.guild.id))

    @discord.ui.button(label="🚀 Run Setup", style=discord.ButtonStyle.success, row=1)
    async def run_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard(interaction): return

        cfg = db.get_config(self.guild.id) or {}
        configured, to_create, status = _inventory(cfg)
        confirm_embed = _build_confirmation_embed(configured, to_create, status)
        confirm_view  = ConfirmSetupView(self.guild, self.invoker, to_create)

        await interaction.response.edit_message(embed=confirm_embed, view=confirm_view)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Set up ModSuite for this server.")
    async def setup(self, interaction: discord.Interaction):
        import traceback
        try:
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message(
                    "❌ Administrator permission required.", ephemeral=True
                )
            intro_embed = discord.Embed(
                title="🛠️ ModSuite Setup",
                description=(
                    "**Optional:** Customise messages and thresholds first.\n"
                    "**Then:** Click **Run Setup** to review what will be created and confirm.\n\n"
                    "> ⚠️ Bot needs **Administrator** permission to create roles and channels."
                ),
                color=0x3498DB,
            )
            intro_embed.set_footer(text=FOOTER_BRAND)
            view = SetupView(interaction.guild, interaction.user)
            await interaction.response.send_message(embed=intro_embed, view=view, ephemeral=True)
        except Exception as exc:
            traceback.print_exc()
            msg = f"❌ Setup error: `{type(exc).__name__}: {exc}`"
            try:
                await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                try:
                    await interaction.followup.send(msg, ephemeral=True)
                except Exception:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Setup(bot))
