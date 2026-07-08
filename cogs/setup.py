"""
setup.py — ModSuite v2.5

/setup opens the ModSuite Configuration Hub — a full menu-driven UI covering
every persisted setting the bot has. Admins never need to touch a slash command
to change roles, channels, thresholds, message templates, or AutoMod filters.

Structure:
  ConfigHubView            — top-level menu
    GeneralPanel           — role & channel pickers
    MessagesPanel          — edit any bot-message template
    WarnsPanel             — warn thresholds
    RaidPanel              — raid trigger + response
    SpamPanel              — AutoMod spam settings
    LinksPanel             — AutoMod link whitelist/blacklist
    InvitesPanel           — AutoMod invite filter
    ImmunePanel            — AutoMod immune roles

  ConfirmSetupView         — install / re-install flow (unchanged from v1.5)

Branding footer: ModSuite · Hammond Digital Studios
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


# =============================================================================
# ── Config Hub (v2.5) ──────────────────────────────────────────────────────
# =============================================================================
#
# The new /setup opens a full configuration hub. Admins can:
#   - Change any config value via dropdowns, role/channel pickers, or modals
#   - Toggle any boolean feature
#   - Edit any bot message template
#   - Trigger install / re-install
#
# Every persisted field in guild_config is reachable from menus. No CLI needed.
# =============================================================================

import json as _json


def _fmt_id(v):
    """Render a role/channel ID as a mention, or '(not set)'."""
    if not v:
        return "*(not set)*"
    return f"<@&{v}>" if isinstance(v, (int, str)) and str(v).isdigit() else str(v)


def _fmt_ch(v):
    if not v:
        return "*(not set)*"
    return f"<#{v}>" if isinstance(v, (int, str)) and str(v).isdigit() else str(v)


def _yn(v):
    return "🟢 On" if v else "🔴 Off"


def _dur_mins(v):
    if v is None or v == "":
        return "—"
    try:
        return f"{int(v)}m"
    except Exception:
        return str(v)


# ── Bot-message slot metadata ────────────────────────────────────────────────
# Keys align with cfg columns / db.get_bot_message()
MSG_SLOTS = [
    ("selfroles_msg",     "Self-Roles Message",  ["{role_lines}"],           True,  1800),
    ("welcome_msg",       "Welcome Message",     ["{user}", "{server}", "{selfroles_ch}"], True, 800),
    ("modmail_open_msg",  "ModMail Opening",     ["{user}"],                 True,  800),
    ("warn_dm",           "Warn DM",             ["{user}", "{reason}"],     True,  800),
    ("mute_dm",           "Mute DM",             ["{user}", "{reason}", "{duration}"], True, 800),
    ("ban_dm",            "Ban DM",              ["{user}", "{reason}"],     True,  800),
    ("jail_dm",           "Jail DM",             ["{user}", "{reason}", "{duration}"], True, 800),
    ("unjail_dm",         "Unjail DM",           ["{user}"],                 True,  800),
]


# ─────────────────────────────────────────────────────────────────────────────
# Hub root
# ─────────────────────────────────────────────────────────────────────────────

def _hub_embed(guild: discord.Guild, cfg: dict) -> discord.Embed:
    setup_done = bool(cfg and cfg.get("setup_complete"))
    color = 0x2ECC71 if setup_done else 0xF39C12
    embed = discord.Embed(
        title="🛠️ ModSuite · Configuration Hub",
        description=(
            f"**Server:** {guild.name}\n"
            f"**Status:** {'✅ Set up' if setup_done else '⚠️ Not yet set up'}\n\n"
            "Pick a section below. Every setting has a menu — no commands required."
        ),
        color=color,
    )
    if cfg:
        # Snapshot of the most important state
        embed.add_field(
            name="Core roles / channels",
            value=(
                f"Owner: {_fmt_id(cfg.get('owner_role_id'))}\n"
                f"Moderator: {_fmt_id(cfg.get('mod_role_id'))}\n"
                f"Mod-Log: {_fmt_ch(cfg.get('modlog_ch_id'))}\n"
                f"ModMail: {_fmt_ch(cfg.get('modmail_ch_id'))}"
            ),
            inline=True,
        )
        embed.add_field(
            name="AutoMod",
            value=(
                f"Spam: {_yn(cfg.get('spam_enabled'))}\n"
                f"Links: {_yn(cfg.get('link_filter_enabled'))}\n"
                f"Invites: {_yn(cfg.get('invite_filter_enabled'))}"
            ),
            inline=True,
        )
        embed.add_field(
            name="Raid",
            value=(
                f"Trigger: **{cfg.get('raid_join_count', 10)}** in **{cfg.get('raid_join_seconds', 10)}s**\n"
                f"Cooldown: **{cfg.get('raid_lockdown_cooldown_min', 5)}m**\n"
                f"Auto-verify: {_yn(cfg.get('raid_auto_verification'))}"
            ),
            inline=True,
        )
    embed.set_footer(text=FOOTER_BRAND)
    return embed


class ConfigHubView(discord.ui.View):
    """The main /setup menu."""

    def __init__(self, guild: discord.Guild, invoker: discord.Member):
        super().__init__(timeout=600)
        self.guild   = guild
        self.invoker = invoker
        cfg = db.get_config(guild.id) or {}
        self._setup_done = bool(cfg.get("setup_complete"))
        # Change the install button label depending on state
        if self._setup_done:
            self.install_btn.label = "🔁 Re-run install"
            self.install_btn.style = discord.ButtonStyle.secondary
        else:
            self.install_btn.label = "🚀 Run install now"
            self.install_btn.style = discord.ButtonStyle.success

    async def _guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return False
        return True

    async def _open(self, interaction: discord.Interaction, PanelClass):
        if not await self._guard(interaction):
            return
        panel = PanelClass(self.guild, self.invoker)
        await interaction.response.edit_message(embed=panel.embed(), view=panel)

    # Row 0: primary categories
    @discord.ui.button(label="👥 Roles & Channels", style=discord.ButtonStyle.primary, row=0)
    async def general_btn(self, interaction, button):
        await self._open(interaction, GeneralPanel)

    @discord.ui.button(label="💬 Bot Messages", style=discord.ButtonStyle.primary, row=0)
    async def messages_btn(self, interaction, button):
        await self._open(interaction, MessagesPanel)

    @discord.ui.button(label="⚠️ Warns", style=discord.ButtonStyle.primary, row=0)
    async def warns_btn(self, interaction, button):
        await self._open(interaction, WarnsPanel)

    # Row 1: AutoMod categories
    @discord.ui.button(label="🚨 Raid", style=discord.ButtonStyle.primary, row=1)
    async def raid_btn(self, interaction, button):
        await self._open(interaction, RaidPanel)

    @discord.ui.button(label="🛡️ AutoMod · Spam", style=discord.ButtonStyle.primary, row=1)
    async def spam_btn(self, interaction, button):
        await self._open(interaction, SpamPanel)

    @discord.ui.button(label="🔗 AutoMod · Links", style=discord.ButtonStyle.primary, row=1)
    async def links_btn(self, interaction, button):
        await self._open(interaction, LinksPanel)

    # Row 2
    @discord.ui.button(label="📮 AutoMod · Invites", style=discord.ButtonStyle.primary, row=2)
    async def invites_btn(self, interaction, button):
        await self._open(interaction, InvitesPanel)

    @discord.ui.button(label="🎫 Immune Roles", style=discord.ButtonStyle.primary, row=2)
    async def immune_btn(self, interaction, button):
        await self._open(interaction, ImmunePanel)

    # Row 3: install / done
    @discord.ui.button(label="🚀 Run install", style=discord.ButtonStyle.success, row=3)
    async def install_btn(self, interaction, button):
        if not await self._guard(interaction):
            return
        cfg = db.get_config(self.guild.id) or {}
        configured, to_create, status = _inventory(cfg)
        confirm_embed = _build_confirmation_embed(configured, to_create, status)
        confirm_view  = ConfirmSetupView(self.guild, self.invoker, to_create)
        await interaction.response.edit_message(embed=confirm_embed, view=confirm_view)

    @discord.ui.button(label="Done", style=discord.ButtonStyle.secondary, row=3)
    async def done_btn(self, interaction, button):
        if not await self._guard(interaction):
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="✅ Configuration closed",
                description="Reopen anytime with `/setup`.",
                color=0x95A5A6,
            ),
            view=None,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Shared panel base — Back button + boilerplate
# ─────────────────────────────────────────────────────────────────────────────

class _BasePanel(discord.ui.View):
    """Base class every category panel extends."""

    TITLE = "Panel"
    DESCRIPTION = ""
    COLOR = 0x3498DB

    def __init__(self, guild: discord.Guild, invoker: discord.Member):
        super().__init__(timeout=600)
        self.guild   = guild
        self.invoker = invoker

    async def guard(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message("Not your panel.", ephemeral=True)
            return False
        return True

    def cfg(self) -> dict:
        return db.get_config(self.guild.id) or {}

    def save(self, **fields):
        db.upsert_config(self.guild.id, **fields)

    def refresh(self):
        """Rebuild the view — subclasses should override to reflect updated state."""
        # Default is to rebuild an instance and steal its items
        new = self.__class__(self.guild, self.invoker)
        self.clear_items()
        for item in new.children:
            self.add_item(item)

    async def repaint(self, interaction: discord.Interaction):
        """Reload state and re-render this panel with fresh values."""
        self.refresh()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    def embed(self) -> discord.Embed:
        e = discord.Embed(title=self.TITLE, description=self.DESCRIPTION, color=self.COLOR)
        e.set_footer(text=FOOTER_BRAND)
        return e

    # A back button all panels share
    @discord.ui.button(label="← Back to hub", style=discord.ButtonStyle.secondary, row=4)
    async def back_btn(self, interaction, button):
        if not await self.guard(interaction):
            return
        view = ConfigHubView(self.guild, self.invoker)
        cfg  = db.get_config(self.guild.id) or {}
        await interaction.response.edit_message(embed=_hub_embed(self.guild, cfg), view=view)


# ─────────────────────────────────────────────────────────────────────────────
# General panel — roles + channels
# ─────────────────────────────────────────────────────────────────────────────

class _RoleSelect(discord.ui.RoleSelect):
    def __init__(self, panel, field_key: str, placeholder: str, row: int):
        super().__init__(placeholder=placeholder, min_values=0, max_values=1, row=row)
        self.panel = panel
        self.field_key = field_key

    async def callback(self, interaction: discord.Interaction):
        if not await self.panel.guard(interaction):
            return
        rid = self.values[0].id if self.values else None
        self.panel.save(**{self.field_key: rid})
        await self.panel.repaint(interaction)


class _ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, panel, field_key: str, placeholder: str, row: int):
        super().__init__(
            placeholder=placeholder,
            channel_types=[discord.ChannelType.text],
            min_values=0, max_values=1, row=row,
        )
        self.panel = panel
        self.field_key = field_key

    async def callback(self, interaction: discord.Interaction):
        if not await self.panel.guard(interaction):
            return
        cid = self.values[0].id if self.values else None
        self.panel.save(**{self.field_key: cid})
        await self.panel.repaint(interaction)


class GeneralPanel(_BasePanel):
    TITLE = "👥 Roles & Channels"
    DESCRIPTION = "Pick the roles and channels ModSuite uses. Leave empty to clear."
    COLOR = 0x3498DB

    # Row 0-1: pick one section to configure via the selects below
    def __init__(self, guild, invoker):
        super().__init__(guild, invoker)
        # Because Discord allows 5 rows and 25 items total, we use 2 panels:
        # Section select tells us which pair of Role/Channel dropdowns to render.
        self._section = "roles"
        self._render()

    def _render(self):
        # Rebuild children
        # Preserve the Back button (last)
        self.clear_items()
        # Section toggle
        self.add_item(_SectionSelect(self))
        cfg = self.cfg()
        if self._section == "roles":
            self.add_item(_RoleSelect(self, "owner_role_id",    f"Owner role — {_fmt_id(cfg.get('owner_role_id'))}",       row=1))
            self.add_item(_RoleSelect(self, "mod_role_id",      f"Moderator role — {_fmt_id(cfg.get('mod_role_id'))}",     row=2))
            self.add_item(_RoleSelect(self, "verified_role_id", f"Verified role — {_fmt_id(cfg.get('verified_role_id'))}", row=3))
            self.add_item(_RoleSelect(self, "auto_role_id",     f"Auto-role — {_fmt_id(cfg.get('auto_role_id'))}",         row=4))
        else:
            self.add_item(_ChannelSelect(self, "modmail_ch_id",   f"ModMail — {_fmt_ch(cfg.get('modmail_ch_id'))}",       row=1))
            self.add_item(_ChannelSelect(self, "modlog_ch_id",    f"Mod-Log — {_fmt_ch(cfg.get('modlog_ch_id'))}",        row=2))
            self.add_item(_ChannelSelect(self, "closed_ch_id",    f"Closed tickets — {_fmt_ch(cfg.get('closed_ch_id'))}", row=3))
            self.add_item(_ChannelSelect(self, "selfroles_ch_id", f"Self-Roles — {_fmt_ch(cfg.get('selfroles_ch_id'))}",  row=4))

    def refresh(self):
        self._render()

    def embed(self):
        cfg = self.cfg()
        e = discord.Embed(title=self.TITLE, color=self.COLOR)
        e.description = (
            "**Roles**\n"
            f"Owner: {_fmt_id(cfg.get('owner_role_id'))}\n"
            f"Moderator: {_fmt_id(cfg.get('mod_role_id'))}\n"
            f"Verified: {_fmt_id(cfg.get('verified_role_id'))}\n"
            f"Auto-role on join: {_fmt_id(cfg.get('auto_role_id'))}\n"
            "\n**Channels**\n"
            f"ModMail: {_fmt_ch(cfg.get('modmail_ch_id'))}\n"
            f"Mod-Log: {_fmt_ch(cfg.get('modlog_ch_id'))}\n"
            f"Closed tickets: {_fmt_ch(cfg.get('closed_ch_id'))}\n"
            f"Self-Roles: {_fmt_ch(cfg.get('selfroles_ch_id'))}"
        )
        e.set_footer(text=f"{FOOTER_BRAND} — showing: {self._section.capitalize()}")
        return e


class _SectionSelect(discord.ui.Select):
    def __init__(self, panel):
        super().__init__(
            placeholder="Switch between: Roles / Channels…",
            options=[
                discord.SelectOption(label="Roles",    value="roles",    emoji="👥"),
                discord.SelectOption(label="Channels", value="channels", emoji="📁"),
            ],
            row=0,
        )
        self.panel = panel

    async def callback(self, interaction):
        if not await self.panel.guard(interaction):
            return
        self.panel._section = self.values[0]
        self.panel._render()   # _render adds selects + Back button
        await interaction.response.edit_message(embed=self.panel.embed(), view=self.panel)


# The clear/render approach nukes the Back button; add it back after _render.
_orig_general_render = GeneralPanel._render
def _general_render_with_back(self):
    _orig_general_render(self)
    # Add the shared Back button as a plain button, since we can't reference
    # a bound decorator instance cleanly.
    back = discord.ui.Button(label="← Back to hub", style=discord.ButtonStyle.secondary, row=4)
    async def back_callback(interaction: discord.Interaction):
        if not await self.guard(interaction):
            return
        view = ConfigHubView(self.guild, self.invoker)
        cfg  = db.get_config(self.guild.id) or {}
        await interaction.response.edit_message(embed=_hub_embed(self.guild, cfg), view=view)
    back.callback = back_callback
    self.add_item(back)
GeneralPanel._render = _general_render_with_back


# ─────────────────────────────────────────────────────────────────────────────
# Messages panel — edit any bot-message template
# ─────────────────────────────────────────────────────────────────────────────

class _MessageEditModal(discord.ui.Modal):
    text = discord.ui.TextInput(
        label="Message text",
        style=discord.TextStyle.long,
        required=False,
        max_length=1800,
    )

    def __init__(self, panel: "MessagesPanel", slot_key: str, slot_label: str, vars_list, current: str):
        super().__init__(title=f"Edit: {slot_label}"[:45])
        self.panel = panel
        self.slot_key = slot_key
        self.text.default = current or ""
        self.text.placeholder = "Placeholders: " + ", ".join(vars_list) if vars_list else "Text template"

    async def on_submit(self, interaction: discord.Interaction):
        new_text = (self.text.value or "").strip()
        self.panel.save(**{self.slot_key: new_text})
        await self.panel.repaint(interaction)


class _MessageSelect(discord.ui.Select):
    def __init__(self, panel: "MessagesPanel"):
        options = []
        for slot_key, slot_label, _vars, _long, _mx in MSG_SLOTS:
            options.append(discord.SelectOption(
                label=slot_label,
                value=slot_key,
                description=f"Placeholders: {slot_key}",
            ))
        super().__init__(placeholder="Pick a message to edit…", options=options[:25], row=0)
        self.panel = panel

    async def callback(self, interaction):
        if not await self.panel.guard(interaction):
            return
        key = self.values[0]
        slot = next((s for s in MSG_SLOTS if s[0] == key), None)
        if slot is None:
            return await interaction.response.send_message("Unknown slot.", ephemeral=True)
        current = self.panel.cfg().get(key) or ""
        modal = _MessageEditModal(self.panel, key, slot[1], slot[2], current)
        await interaction.response.send_modal(modal)


class _MessageResetSelect(discord.ui.Select):
    def __init__(self, panel: "MessagesPanel"):
        options = [
            discord.SelectOption(label=lbl, value=key, description=f"Reset {key} to default")
            for (key, lbl, *_rest) in MSG_SLOTS
        ][:25]
        super().__init__(placeholder="…or reset a message to its default", options=options, row=1)
        self.panel = panel

    async def callback(self, interaction):
        if not await self.panel.guard(interaction):
            return
        key = self.values[0]
        # Store empty string → the bot's get_bot_message() falls back to default
        self.panel.save(**{key: ""})
        await self.panel.repaint(interaction)


class MessagesPanel(_BasePanel):
    TITLE = "💬 Bot Messages"
    DESCRIPTION = "Every message the bot sends. Pick one to edit, or reset one to its default."
    COLOR = 0x9B59B6

    def __init__(self, guild, invoker):
        super().__init__(guild, invoker)
        self.clear_items()
        self.add_item(_MessageSelect(self))
        self.add_item(_MessageResetSelect(self))
        # Reattach back button
        back = discord.ui.Button(label="← Back to hub", style=discord.ButtonStyle.secondary, row=4)
        async def back_cb(interaction):
            if not await self.guard(interaction):
                return
            view = ConfigHubView(self.guild, self.invoker)
            cfg  = db.get_config(self.guild.id) or {}
            await interaction.response.edit_message(embed=_hub_embed(self.guild, cfg), view=view)
        back.callback = back_cb
        self.add_item(back)

    def embed(self):
        cfg = self.cfg()
        e = discord.Embed(title=self.TITLE, description=self.DESCRIPTION, color=self.COLOR)
        for slot_key, slot_label, vars_list, _l, _m in MSG_SLOTS:
            val = (cfg.get(slot_key) or "").strip()
            if val:
                preview = val if len(val) <= 90 else val[:87] + "…"
                status = f"✏️ Custom: `{preview}`"
            else:
                status = "🔧 Using default"
            e.add_field(name=slot_label, value=status, inline=False)
        e.set_footer(text=FOOTER_BRAND)
        return e


# ─────────────────────────────────────────────────────────────────────────────
# Warns panel
# ─────────────────────────────────────────────────────────────────────────────

class _WarnsModal(discord.ui.Modal, title="Warn thresholds"):
    warn_mute  = discord.ui.TextInput(label="Warns before auto-jail", placeholder="e.g. 3", required=False, max_length=3)
    mute_dur   = discord.ui.TextInput(label="Auto-mute duration (hours)", placeholder="e.g. 24", required=False, max_length=4)
    warn_ban   = discord.ui.TextInput(label="Warns before auto-ban",  placeholder="e.g. 5", required=False, max_length=3)
    jail_dur   = discord.ui.TextInput(label="Auto-jail duration (e.g. 1d, 6h)", placeholder="e.g. 1d", required=False, max_length=10)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        cfg = panel.cfg()
        self.warn_mute.default = str(cfg.get("warn_mute_threshold")   or "")
        self.mute_dur.default  = str(cfg.get("warn_mute_duration_hrs") or "")
        self.warn_ban.default  = str(cfg.get("warn_ban_threshold")    or "")
        self.jail_dur.default  = str(cfg.get("auto_jail_duration")    or "")

    async def on_submit(self, interaction):
        def si(v, default=None):
            try: return max(1, int(v.strip()))
            except: return default
        updates = {}
        if self.warn_mute.value.strip(): updates["warn_mute_threshold"]   = si(self.warn_mute.value, 3)
        if self.mute_dur.value.strip():  updates["warn_mute_duration_hrs"] = si(self.mute_dur.value, 24)
        if self.warn_ban.value.strip():  updates["warn_ban_threshold"]    = si(self.warn_ban.value, 5)
        if self.jail_dur.value.strip():  updates["auto_jail_duration"]    = self.jail_dur.value.strip()
        if updates:
            self.panel.save(**updates)
        await self.panel.repaint(interaction)


class WarnsPanel(_BasePanel):
    TITLE = "⚠️ Warns & auto-escalation"
    DESCRIPTION = "Thresholds that trigger automatic jail / ban."
    COLOR = 0xE67E22

    def embed(self):
        cfg = self.cfg()
        e = discord.Embed(title=self.TITLE, color=self.COLOR)
        e.description = (
            f"**Auto-jail at:** {cfg.get('warn_mute_threshold', 3)} warns\n"
            f"**Auto-jail duration:** {cfg.get('auto_jail_duration', '1d')}\n"
            f"**Auto-mute duration:** {cfg.get('warn_mute_duration_hrs', 24)}h\n"
            f"**Auto-ban at:** {cfg.get('warn_ban_threshold', 5)} warns"
        )
        e.set_footer(text=FOOTER_BRAND)
        return e

    @discord.ui.button(label="✏️ Edit thresholds", style=discord.ButtonStyle.primary, row=0)
    async def edit_btn(self, interaction, button):
        if not await self.guard(interaction):
            return
        await interaction.response.send_modal(_WarnsModal(self))


# ─────────────────────────────────────────────────────────────────────────────
# Raid panel
# ─────────────────────────────────────────────────────────────────────────────

class _RaidNumbersModal(discord.ui.Modal, title="Raid trigger settings"):
    joins    = discord.ui.TextInput(label="Joins to trigger",       placeholder="e.g. 10", required=False, max_length=4)
    seconds  = discord.ui.TextInput(label="Trigger window (secs)",  placeholder="e.g. 10", required=False, max_length=4)
    age_days = discord.ui.TextInput(label="Flag accounts younger than (days, 0=off)", placeholder="e.g. 7", required=False, max_length=4)
    cooldown = discord.ui.TextInput(label="Auto-unlock after (mins, 0=manual)", placeholder="e.g. 5", required=False, max_length=4)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        cfg = panel.cfg()
        self.joins.default    = str(cfg.get("raid_join_count") or "")
        self.seconds.default  = str(cfg.get("raid_join_seconds") or "")
        self.age_days.default = str(cfg.get("raid_min_account_age_days") or "")
        self.cooldown.default = str(cfg.get("raid_lockdown_cooldown_min") or "")

    async def on_submit(self, interaction):
        def si(v, default):
            try: return max(0, int(v.strip()))
            except: return default
        updates = {
            "raid_join_count":           max(3, si(self.joins.value,    10)),
            "raid_join_seconds":         max(5, si(self.seconds.value,  10)),
            "raid_min_account_age_days": si(self.age_days.value,        0),
            "raid_lockdown_cooldown_min":si(self.cooldown.value,        5),
        }
        self.panel.save(**updates)
        await self.panel.repaint(interaction)


class RaidPanel(_BasePanel):
    TITLE = "🚨 Raid Response"
    DESCRIPTION = "How ModSuite detects raids and what it does when one fires."
    COLOR = 0xE74C3C

    def embed(self):
        cfg = self.cfg()
        e = discord.Embed(title=self.TITLE, color=self.COLOR)
        e.description = (
            f"**Trigger:** {cfg.get('raid_join_count', 10)} joins in {cfg.get('raid_join_seconds', 10)}s\n"
            f"**Account age gate:** {cfg.get('raid_min_account_age_days', 0)} days (0 = off)\n"
            f"**During raid:** {cfg.get('raid_active_action', 'kick').capitalize()} new joiners\n"
            f"**Auto-verification bump:** {_yn(cfg.get('raid_auto_verification'))}\n"
            f"**Auto-unlock cooldown:** {cfg.get('raid_lockdown_cooldown_min', 5)}m"
        )
        e.set_footer(text=FOOTER_BRAND)
        return e

    @discord.ui.button(label="✏️ Edit thresholds", style=discord.ButtonStyle.primary, row=0)
    async def edit_btn(self, interaction, button):
        if not await self.guard(interaction):
            return
        await interaction.response.send_modal(_RaidNumbersModal(self))

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.secondary, row=1)
    async def kick_btn(self, interaction, button):
        if not await self.guard(interaction):
            return
        self.save(raid_active_action="kick")
        await self.repaint(interaction)

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.secondary, row=1)
    async def ban_btn(self, interaction, button):
        if not await self.guard(interaction):
            return
        self.save(raid_active_action="ban")
        await self.repaint(interaction)

    @discord.ui.button(label="Toggle auto-verification", style=discord.ButtonStyle.secondary, row=2)
    async def verify_btn(self, interaction, button):
        if not await self.guard(interaction):
            return
        cfg = self.cfg()
        self.save(raid_auto_verification=0 if cfg.get("raid_auto_verification") else 1)
        await self.repaint(interaction)


# ─────────────────────────────────────────────────────────────────────────────
# AutoMod · Spam panel
# ─────────────────────────────────────────────────────────────────────────────

class _SpamModal(discord.ui.Modal, title="Spam thresholds"):
    msg_limit = discord.ui.TextInput(label="Messages allowed in window",     placeholder="e.g. 5",  required=False, max_length=3)
    window    = discord.ui.TextInput(label="Window (seconds)",               placeholder="e.g. 8",  required=False, max_length=3)
    dup_limit = discord.ui.TextInput(label="Duplicate messages allowed",     placeholder="e.g. 3",  required=False, max_length=2)
    mentions  = discord.ui.TextInput(label="Mentions per message",           placeholder="e.g. 5",  required=False, max_length=3)
    emojis    = discord.ui.TextInput(label="Emojis per message",             placeholder="e.g. 15", required=False, max_length=3)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        cfg = panel.cfg()
        self.msg_limit.default = str(cfg.get("spam_msg_limit")     or "")
        self.window.default    = str(cfg.get("spam_window_sec")    or "")
        self.dup_limit.default = str(cfg.get("spam_dup_limit")     or "")
        self.mentions.default  = str(cfg.get("spam_mention_limit") or "")
        self.emojis.default    = str(cfg.get("spam_emoji_limit")   or "")

    async def on_submit(self, interaction):
        def si(v, default):
            try: return max(1, int(v.strip()))
            except: return default
        self.panel.save(
            spam_msg_limit     = max(2, si(self.msg_limit.value, 5)),
            spam_window_sec    = max(3, si(self.window.value, 8)),
            spam_dup_limit     = max(2, si(self.dup_limit.value, 3)),
            spam_mention_limit = max(2, si(self.mentions.value, 5)),
            spam_emoji_limit   = max(3, si(self.emojis.value, 15)),
        )
        await self.panel.repaint(interaction)


class _SpamMuteDurModal(discord.ui.Modal, title="Spam mute duration"):
    minutes = discord.ui.TextInput(label="Mute duration (minutes)", placeholder="e.g. 10", required=True, max_length=5)

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.minutes.default = str(panel.cfg().get("spam_mute_minutes") or "10")

    async def on_submit(self, interaction):
        try: v = max(1, int(self.minutes.value.strip()))
        except: v = 10
        self.panel.save(spam_mute_minutes=v)
        await self.panel.repaint(interaction)


class _ActionSelect(discord.ui.Select):
    """Reusable action select for delete/mute/kick/ban."""
    def __init__(self, panel, field_key: str, placeholder: str, row: int = 3):
        options = [
            discord.SelectOption(label="Delete only",             value="delete", emoji="🗑️"),
            discord.SelectOption(label="Delete + mute (timeout)", value="mute",   emoji="🔇"),
            discord.SelectOption(label="Delete + kick",           value="kick",   emoji="👢"),
            discord.SelectOption(label="Delete + ban",            value="ban",    emoji="🔨"),
        ]
        super().__init__(placeholder=placeholder, options=options, row=row)
        self.panel = panel
        self.field_key = field_key

    async def callback(self, interaction):
        if not await self.panel.guard(interaction):
            return
        self.panel.save(**{self.field_key: self.values[0]})
        await self.panel.repaint(interaction)


class SpamPanel(_BasePanel):
    TITLE = "🛡️ AutoMod · Spam"
    DESCRIPTION = "Message-velocity, duplicate, mention, and emoji flood detection."
    COLOR = 0xF39C12

    def __init__(self, guild, invoker):
        super().__init__(guild, invoker)
        self.clear_items()
        self.add_item(_ActionSelect(self, "spam_action", "Set spam action…", row=0))
        # Buttons on rows 1-3
        for item in self._build_buttons():
            self.add_item(item)
        back = discord.ui.Button(label="← Back to hub", style=discord.ButtonStyle.secondary, row=4)
        async def back_cb(interaction):
            if not await self.guard(interaction):
                return
            view = ConfigHubView(self.guild, self.invoker)
            cfg  = db.get_config(self.guild.id) or {}
            await interaction.response.edit_message(embed=_hub_embed(self.guild, cfg), view=view)
        back.callback = back_cb
        self.add_item(back)

    def _build_buttons(self):
        cfg = self.cfg()
        # Toggle
        toggle = discord.ui.Button(
            label=f"Spam detection: {'ON' if cfg.get('spam_enabled') else 'OFF'} — click to toggle",
            style=discord.ButtonStyle.success if cfg.get('spam_enabled') else discord.ButtonStyle.danger,
            row=1,
        )
        async def toggle_cb(i):
            if not await self.guard(i): return
            self.save(spam_enabled=0 if cfg.get('spam_enabled') else 1)
            await self.repaint(i)
        toggle.callback = toggle_cb

        # Numbers modal
        numbers = discord.ui.Button(label="✏️ Edit thresholds", style=discord.ButtonStyle.primary, row=2)
        async def numbers_cb(i):
            if not await self.guard(i): return
            await i.response.send_modal(_SpamModal(self))
        numbers.callback = numbers_cb

        # Mute duration
        mute_dur = discord.ui.Button(label=f"🔇 Mute duration: {cfg.get('spam_mute_minutes', 10)}m", style=discord.ButtonStyle.secondary, row=2)
        async def mute_cb(i):
            if not await self.guard(i): return
            await i.response.send_modal(_SpamMuteDurModal(self))
        mute_dur.callback = mute_cb

        return [toggle, numbers, mute_dur]

    def refresh(self):
        self.__init__(self.guild, self.invoker)

    def embed(self):
        cfg = self.cfg()
        e = discord.Embed(title=self.TITLE, description=self.DESCRIPTION, color=self.COLOR)
        e.add_field(
            name="Status",
            value=f"{_yn(cfg.get('spam_enabled'))} — action: **{cfg.get('spam_action', 'mute')}**",
            inline=False,
        )
        e.add_field(
            name="Thresholds",
            value=(
                f"Velocity: **{cfg.get('spam_msg_limit', 5)}** msgs / **{cfg.get('spam_window_sec', 8)}s**\n"
                f"Duplicates: **{cfg.get('spam_dup_limit', 3)}**\n"
                f"Mentions per msg: **{cfg.get('spam_mention_limit', 5)}**\n"
                f"Emojis per msg: **{cfg.get('spam_emoji_limit', 15)}**"
            ),
            inline=False,
        )
        e.add_field(name="Mute duration", value=f"**{cfg.get('spam_mute_minutes', 10)}m**", inline=False)
        e.set_footer(text=FOOTER_BRAND)
        return e


# ─────────────────────────────────────────────────────────────────────────────
# AutoMod · Links panel
# ─────────────────────────────────────────────────────────────────────────────

def _append_domain_fields_setup(embed: "discord.Embed", label: str, domains: list) -> None:
    """
    Append one or more embed fields listing every domain.
    Splits into multiple fields if the list would exceed Discord's 1024-char
    per-field limit. Mirrors the helper in cogs/automod.py — duplicated here
    to avoid a cross-cog import.
    """
    if not domains:
        embed.add_field(name=f"{label} (0)", value="*(empty)*", inline=False)
        return
    chunks: list[list[str]] = [[]]
    running_len = 0
    for d in domains:
        piece = f"`{d}`\n"
        if running_len + len(piece) > 1000:
            chunks.append([])
            running_len = 0
        chunks[-1].append(piece)
        running_len += len(piece)
    total = len(domains)
    for i, chunk in enumerate(chunks):
        name = f"{label} ({total})" if i == 0 else f"{label} (cont. {i + 1})"
        embed.add_field(name=name, value="".join(chunk) or "*(empty)*", inline=False)

class _DomainAddModal(discord.ui.Modal, title="Add domain"):
    domain = discord.ui.TextInput(label="Domain (e.g. example.com)", placeholder="example.com", required=True, max_length=100)

    def __init__(self, panel, list_field: str, list_label: str):
        super().__init__(title=f"Add domain to {list_label}"[:45])
        self.panel = panel
        self.list_field = list_field

    async def on_submit(self, interaction):
        d = self.domain.value.strip().lower()
        for prefix in ("http://", "https://", "www."):
            if d.startswith(prefix):
                d = d[len(prefix):]
        d = d.split("/")[0]
        if not d or "." not in d:
            return await interaction.response.send_message("❌ That doesn't look like a domain.", ephemeral=True)
        cfg = self.panel.cfg()
        try:
            current = _json.loads(cfg.get(self.list_field) or "[]")
            if not isinstance(current, list):
                current = []
        except Exception:
            current = []
        if d not in current:
            current.append(d)
            self.panel.save(**{self.list_field: _json.dumps(current)})
        await self.panel.repaint(interaction)


class _DomainRemoveSelect(discord.ui.Select):
    def __init__(self, panel, list_field: str, list_label: str, row: int):
        cfg = panel.cfg()
        try:
            current = _json.loads(cfg.get(list_field) or "[]")
            if not isinstance(current, list):
                current = []
        except Exception:
            current = []
        options = [discord.SelectOption(label=d, value=d) for d in current[:25]]
        if not options:
            options = [discord.SelectOption(label="(empty)", value="_empty", default=True)]
        super().__init__(
            placeholder=f"Remove a domain from {list_label}…",
            options=options,
            disabled=(not current),
            row=row,
        )
        self.panel = panel
        self.list_field = list_field

    async def callback(self, interaction):
        if not await self.panel.guard(interaction):
            return
        d = self.values[0]
        if d == "_empty":
            return await self.panel.repaint(interaction)
        cfg = self.panel.cfg()
        try:
            current = _json.loads(cfg.get(self.list_field) or "[]")
            if not isinstance(current, list):
                current = []
        except Exception:
            current = []
        if d in current:
            current.remove(d)
            self.panel.save(**{self.list_field: _json.dumps(current)})
        await self.panel.repaint(interaction)


class LinksPanel(_BasePanel):
    TITLE = "🔗 AutoMod · Links"
    DESCRIPTION = "Whitelist or blacklist domains. Whitelist blocks everything not on the list."
    COLOR = 0x1ABC9C

    def __init__(self, guild, invoker):
        super().__init__(guild, invoker)
        self.clear_items()
        self.add_item(_ActionSelect(self, "link_action", "Set link action…", row=0))
        self.add_item(_DomainRemoveSelect(self, "link_whitelist", "whitelist", row=1))
        self.add_item(_DomainRemoveSelect(self, "link_blacklist", "blacklist", row=2))
        cfg = self.cfg()

        # Toggle + mode + add-domain buttons on row 3
        toggle = discord.ui.Button(
            label=f"Filter: {'ON' if cfg.get('link_filter_enabled') else 'OFF'}",
            style=discord.ButtonStyle.success if cfg.get('link_filter_enabled') else discord.ButtonStyle.danger,
            row=3,
        )
        async def toggle_cb(i):
            if not await self.guard(i): return
            self.save(link_filter_enabled=0 if cfg.get('link_filter_enabled') else 1)
            await self.repaint(i)
        toggle.callback = toggle_cb
        self.add_item(toggle)

        mode_swap = discord.ui.Button(
            label=f"Mode: {cfg.get('link_mode', 'whitelist')} — swap",
            style=discord.ButtonStyle.secondary,
            row=3,
        )
        async def mode_cb(i):
            if not await self.guard(i): return
            cur = cfg.get("link_mode", "whitelist")
            self.save(link_mode="blacklist" if cur == "whitelist" else "whitelist")
            await self.repaint(i)
        mode_swap.callback = mode_cb
        self.add_item(mode_swap)

        add_wl = discord.ui.Button(label="+ Whitelist domain", style=discord.ButtonStyle.primary, row=3)
        async def add_wl_cb(i):
            if not await self.guard(i): return
            await i.response.send_modal(_DomainAddModal(self, "link_whitelist", "whitelist"))
        add_wl.callback = add_wl_cb
        self.add_item(add_wl)

        add_bl = discord.ui.Button(label="+ Blacklist domain", style=discord.ButtonStyle.primary, row=3)
        async def add_bl_cb(i):
            if not await self.guard(i): return
            await i.response.send_modal(_DomainAddModal(self, "link_blacklist", "blacklist"))
        add_bl.callback = add_bl_cb
        self.add_item(add_bl)

        # View-all — shows every domain (handles overflow beyond the panel's preview limit)
        view_all = discord.ui.Button(label="📋 View all domains", style=discord.ButtonStyle.secondary, row=3)
        async def view_all_cb(i):
            if not await self.guard(i): return
            cfg = self.cfg()
            try: wl = _json.loads(cfg.get("link_whitelist") or "[]")
            except Exception: wl = []
            try: bl = _json.loads(cfg.get("link_blacklist") or "[]")
            except Exception: bl = []
            if not isinstance(wl, list): wl = []
            if not isinstance(bl, list): bl = []

            e = discord.Embed(
                title="🔗 Link Lists — full listing",
                color=0x1ABC9C,
                description=(
                    f"Filter: **{'on' if cfg.get('link_filter_enabled') else 'off'}** · "
                    f"Mode: **{cfg.get('link_mode', 'whitelist')}** · "
                    f"Action: **{cfg.get('link_action', 'delete')}**"
                ),
            )
            _append_domain_fields_setup(e, "✅ Whitelist", wl)
            _append_domain_fields_setup(e, "⛔ Blacklist", bl)
            e.set_footer(text=FOOTER_BRAND)
            await i.response.send_message(embed=e, ephemeral=True)
        view_all.callback = view_all_cb
        self.add_item(view_all)

        back = discord.ui.Button(label="← Back to hub", style=discord.ButtonStyle.secondary, row=4)
        async def back_cb(interaction):
            if not await self.guard(interaction):
                return
            view = ConfigHubView(self.guild, self.invoker)
            cfg2 = db.get_config(self.guild.id) or {}
            await interaction.response.edit_message(embed=_hub_embed(self.guild, cfg2), view=view)
        back.callback = back_cb
        self.add_item(back)

    def refresh(self):
        self.__init__(self.guild, self.invoker)

    def embed(self):
        cfg = self.cfg()
        try: wl = _json.loads(cfg.get("link_whitelist") or "[]")
        except Exception: wl = []
        try: bl = _json.loads(cfg.get("link_blacklist") or "[]")
        except Exception: bl = []
        e = discord.Embed(title=self.TITLE, description=self.DESCRIPTION, color=self.COLOR)
        e.add_field(name="Status", value=f"{_yn(cfg.get('link_filter_enabled'))} — mode: **{cfg.get('link_mode', 'whitelist')}** — action: **{cfg.get('link_action', 'delete')}**", inline=False)
        e.add_field(name=f"Whitelist ({len(wl)})", value=", ".join(f"`{d}`" for d in wl[:15]) or "*(empty)*", inline=False)
        e.add_field(name=f"Blacklist ({len(bl)})", value=", ".join(f"`{d}`" for d in bl[:15]) or "*(empty)*", inline=False)
        e.set_footer(text=FOOTER_BRAND)
        return e


# ─────────────────────────────────────────────────────────────────────────────
# AutoMod · Invites panel
# ─────────────────────────────────────────────────────────────────────────────

class InvitesPanel(_BasePanel):
    TITLE = "📮 AutoMod · Invites"
    DESCRIPTION = "Block Discord invite links independently of the general link filter."
    COLOR = 0x1F8B4C

    def __init__(self, guild, invoker):
        super().__init__(guild, invoker)
        self.clear_items()
        self.add_item(_ActionSelect(self, "invite_action", "Set invite action…", row=0))
        cfg = self.cfg()
        toggle = discord.ui.Button(
            label=f"Filter: {'ON' if cfg.get('invite_filter_enabled') else 'OFF'} — click to toggle",
            style=discord.ButtonStyle.success if cfg.get('invite_filter_enabled') else discord.ButtonStyle.danger,
            row=1,
        )
        async def toggle_cb(i):
            if not await self.guard(i): return
            self.save(invite_filter_enabled=0 if cfg.get('invite_filter_enabled') else 1)
            await self.repaint(i)
        toggle.callback = toggle_cb
        self.add_item(toggle)

        back = discord.ui.Button(label="← Back to hub", style=discord.ButtonStyle.secondary, row=4)
        async def back_cb(interaction):
            if not await self.guard(interaction):
                return
            view = ConfigHubView(self.guild, self.invoker)
            cfg2 = db.get_config(self.guild.id) or {}
            await interaction.response.edit_message(embed=_hub_embed(self.guild, cfg2), view=view)
        back.callback = back_cb
        self.add_item(back)

    def refresh(self):
        self.__init__(self.guild, self.invoker)

    def embed(self):
        cfg = self.cfg()
        e = discord.Embed(title=self.TITLE, description=self.DESCRIPTION, color=self.COLOR)
        e.add_field(name="Status", value=f"{_yn(cfg.get('invite_filter_enabled'))} — action: **{cfg.get('invite_action', 'delete')}**", inline=False)
        e.set_footer(text=FOOTER_BRAND)
        return e


# ─────────────────────────────────────────────────────────────────────────────
# Immune Roles panel
# ─────────────────────────────────────────────────────────────────────────────

class _ImmuneRolePicker(discord.ui.RoleSelect):
    def __init__(self, panel):
        super().__init__(
            placeholder="Add a role to the immune list…",
            min_values=0, max_values=1, row=0,
        )
        self.panel = panel

    async def callback(self, interaction):
        if not await self.panel.guard(interaction):
            return
        if not self.values:
            return await self.panel.repaint(interaction)
        rid = self.values[0].id
        try:
            current = _json.loads(self.panel.cfg().get("automod_immune_roles") or "[]")
            if not isinstance(current, list):
                current = []
        except Exception:
            current = []
        current = [int(x) for x in current if str(x).isdigit()]
        if rid in current:
            current.remove(rid)   # toggle
        else:
            current.append(rid)
        self.panel.save(automod_immune_roles=_json.dumps(current))
        await self.panel.repaint(interaction)


class _ImmuneRoleRemoveSelect(discord.ui.Select):
    def __init__(self, panel):
        try:
            current = _json.loads(panel.cfg().get("automod_immune_roles") or "[]")
        except Exception:
            current = []
        options = []
        for rid in current[:25]:
            role = panel.guild.get_role(int(rid)) if str(rid).isdigit() else None
            label = role.name if role else f"Role {rid}"
            options.append(discord.SelectOption(label=label[:100], value=str(rid)))
        if not options:
            options = [discord.SelectOption(label="(empty)", value="_empty", default=True)]
        super().__init__(
            placeholder="Remove from immune list…",
            options=options,
            disabled=(not current),
            row=1,
        )
        self.panel = panel

    async def callback(self, interaction):
        if not await self.panel.guard(interaction):
            return
        val = self.values[0]
        if val == "_empty":
            return await self.panel.repaint(interaction)
        try:
            current = _json.loads(self.panel.cfg().get("automod_immune_roles") or "[]")
            if not isinstance(current, list):
                current = []
        except Exception:
            current = []
        current = [str(x) for x in current if str(x) != val]
        self.panel.save(automod_immune_roles=_json.dumps(current))
        await self.panel.repaint(interaction)


class ImmunePanel(_BasePanel):
    TITLE = "🎫 AutoMod Immune Roles"
    DESCRIPTION = "Members with any of these roles bypass every AutoMod filter."
    COLOR = 0x95A5A6

    def __init__(self, guild, invoker):
        super().__init__(guild, invoker)
        self.clear_items()
        self.add_item(_ImmuneRolePicker(self))
        self.add_item(_ImmuneRoleRemoveSelect(self))
        back = discord.ui.Button(label="← Back to hub", style=discord.ButtonStyle.secondary, row=4)
        async def back_cb(interaction):
            if not await self.guard(interaction):
                return
            view = ConfigHubView(self.guild, self.invoker)
            cfg2 = db.get_config(self.guild.id) or {}
            await interaction.response.edit_message(embed=_hub_embed(self.guild, cfg2), view=view)
        back.callback = back_cb
        self.add_item(back)

    def refresh(self):
        self.__init__(self.guild, self.invoker)

    def embed(self):
        cfg = self.cfg()
        try:
            immune = _json.loads(cfg.get("automod_immune_roles") or "[]")
            if not isinstance(immune, list):
                immune = []
        except Exception:
            immune = []
        e = discord.Embed(title=self.TITLE, description=self.DESCRIPTION, color=self.COLOR)
        if immune:
            e.add_field(
                name=f"Immune roles ({len(immune)})",
                value="\n".join(f"• <@&{rid}>" for rid in immune[:15]),
                inline=False,
            )
        else:
            e.add_field(name="Immune roles", value="*(none — every member is subject to AutoMod)*", inline=False)
        e.set_footer(text=FOOTER_BRAND)
        return e


# ─────────────────────────────────────────────────────────────────────────────
# Cog
# ─────────────────────────────────────────────────────────────────────────────

class Setup(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Open the ModSuite configuration hub.")
    async def setup(self, interaction: discord.Interaction):
        import traceback
        try:
            if not interaction.user.guild_permissions.administrator:
                return await interaction.response.send_message(
                    "❌ Administrator permission required.", ephemeral=True
                )
            cfg = db.get_config(interaction.guild.id) or {}
            view = ConfigHubView(interaction.guild, interaction.user)
            await interaction.response.send_message(
                embed=_hub_embed(interaction.guild, cfg), view=view, ephemeral=True
            )
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
