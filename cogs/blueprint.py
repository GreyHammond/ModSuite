"""
Blueprint cog -- build a server's roles, categories, and channels from a
declarative JSON file, and export an existing server back out to one.

The point is that a server layout becomes a versionable artifact. You keep the
JSON next to the code, you can diff it, and you can rebuild the same structure
on a second server without clicking through Discord for an hour.

Everything is additive and idempotent. Existing roles and channels are matched
by name and left alone unless `update_existing` is set. Nothing is ever deleted.
"""
import json
import os
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

import database as db
from config import FOOTER_BRAND



BLUEPRINT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "blueprints")

# Channel type strings accepted in a blueprint file
CHANNEL_TYPES = {
    "text":         discord.ChannelType.text,
    "voice":        discord.ChannelType.voice,
    "forum":        discord.ChannelType.forum,
    "stage":        discord.ChannelType.stage_voice,
    "announcement": discord.ChannelType.news,
}


def _is_admin(member: discord.Member, cfg: dict | None) -> bool:
    """
    Blueprints create roles and rewrite permissions, so this is deliberately
    stricter than the _is_staff check used elsewhere: administrator only.
    """
    return member.guild_permissions.administrator


def _parse_color(value) -> discord.Colour:
    if value is None:
        return discord.Colour.default()
    if isinstance(value, int):
        return discord.Colour(value)
    s = str(value).strip().lstrip("#")
    try:
        return discord.Colour(int(s, 16))
    except ValueError:
        return discord.Colour.default()


def _parse_permissions(names) -> discord.Permissions:
    """Build a Permissions object from a list of flag names, or 'administrator'."""
    perms = discord.Permissions.none()
    if not names:
        return perms
    if isinstance(names, str):
        names = [names]
    valid = set(discord.Permissions.VALID_FLAGS)
    for n in names:
        key = str(n).strip().lower()
        if key in valid:
            setattr(perms, key, True)
    return perms


def _overwrite_from_spec(spec: dict) -> discord.PermissionOverwrite:
    """Turn {"allow": [...], "deny": [...]} into a PermissionOverwrite."""
    ow = discord.PermissionOverwrite()
    valid = set(discord.Permissions.VALID_FLAGS)
    for name in spec.get("allow", []) or []:
        key = str(name).strip().lower()
        if key in valid:
            setattr(ow, key, True)
    for name in spec.get("deny", []) or []:
        key = str(name).strip().lower()
        if key in valid:
            setattr(ow, key, False)
    return ow


def load_bundled_blueprints() -> list[dict]:
    """Read every .json in blueprints/ off disk."""
    out = []
    if not os.path.isdir(BLUEPRINT_DIR):
        return out
    for fname in sorted(os.listdir(BLUEPRINT_DIR)):
        if not fname.endswith(".json"):
            continue
        path = os.path.join(BLUEPRINT_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data.setdefault("name", os.path.splitext(fname)[0])
            out.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return out


def seed_bundled_blueprints() -> list[str]:
    """
    Load every blueprint shipped on disk into the DB as a global blueprint.
    Called once on boot. Guild-owned blueprints with the same name still win.
    """
    seeded = []
    for data in load_bundled_blueprints():
        db.upsert_blueprint(
            None,
            data["name"],
            data,
            description=data.get("description", ""),
            source="bundled",
        )
        seeded.append(data["name"])
    return seeded


class BlueprintEngine:
    """
    Walks a blueprint and either reports what it would do (dry run) or does it.

    Kept separate from the cog so the API can drive the same code path without
    going through a slash command.
    """

    def __init__(self, guild: discord.Guild, blueprint: dict, dry_run: bool = True,
                 update_existing: bool = False):
        self.guild = guild
        self.bp = blueprint
        self.dry_run = dry_run
        self.update_existing = update_existing
        self.log: list[str] = []
        self.created = 0
        self.skipped = 0
        self.failed = 0
        self._roles: dict[str, discord.Role] = {}
        # Names the blueprint will have created by the time overwrites are
        # applied. In a dry run nothing is actually created, so without this a
        # preview would report a false failure for every overwrite in the file.
        self._planned: set[str] = set()

    def _note(self, symbol: str, text: str):
        self.log.append(f"{symbol} {text}")

    def _resolve_role(self, name: str) -> discord.Role | None:
        if name in ("@everyone", "everyone"):
            return self.guild.default_role
        if name in self._roles:
            return self._roles[name]
        found = discord.utils.get(self.guild.roles, name=name)
        if found:
            self._roles[name] = found
        return found

    # ── Roles ────────────────────────────────────────────────────────────────
    async def apply_roles(self):
        specs = self.bp.get("roles", []) or []
        if not specs:
            return

        # Discord puts each newly created role at position 1, so creating the
        # list in reverse leaves the blueprint's first entry sitting highest.
        for spec in reversed(specs):
            name = spec.get("name")
            if not name:
                continue

            existing = discord.utils.get(self.guild.roles, name=name)
            if existing:
                self._roles[name] = existing
                if not self.update_existing:
                    self.skipped += 1
                    self._note("=", f"Role `{name}` already exists")
                    continue
                if self.dry_run:
                    self._note("~", f"Would update role `{name}`")
                    self.created += 1
                    continue
                try:
                    await existing.edit(
                        colour=_parse_color(spec.get("color")),
                        hoist=bool(spec.get("hoist", False)),
                        mentionable=bool(spec.get("mentionable", False)),
                        reason="ModSuite blueprint",
                    )
                    self.created += 1
                    self._note("~", f"Updated role `{name}`")
                except discord.HTTPException as e:
                    self.failed += 1
                    self._note("!", f"Role `{name}` failed: {e.text or e}")
                continue

            if self.dry_run:
                self.created += 1
                self._planned.add(name)
                self._note("+", f"Would create role `{name}`")
                continue

            try:
                role = await self.guild.create_role(
                    name=name,
                    colour=_parse_color(spec.get("color")),
                    hoist=bool(spec.get("hoist", False)),
                    mentionable=bool(spec.get("mentionable", False)),
                    permissions=_parse_permissions(spec.get("permissions")),
                    reason="ModSuite blueprint",
                )
                self._roles[name] = role
                self.created += 1
                self._note("+", f"Created role `{name}`")
            except discord.Forbidden:
                self.failed += 1
                self._note("!", f"Role `{name}` failed: missing permissions")
            except discord.HTTPException as e:
                self.failed += 1
                self._note("!", f"Role `{name}` failed: {e.text or e}")

    # ── Overwrites ───────────────────────────────────────────────────────────
    def _build_overwrites(self, specs) -> dict:
        overwrites = {}
        for spec in specs or []:
            target_name = spec.get("role")
            if not target_name:
                continue
            target = self._resolve_role(target_name)
            if target is None:
                # During a preview the role has not been created yet; that is
                # expected, not an error. Only flag names the blueprint never
                # defines, since those are genuine mistakes in the file.
                if target_name not in self._planned:
                    self._note("!", f"Overwrite skipped: no role named `{target_name}`")
                continue
            overwrites[target] = _overwrite_from_spec(spec)
        return overwrites

    # ── Categories and channels ──────────────────────────────────────────────
    async def apply_structure(self):
        for cat_spec in self.bp.get("categories", []) or []:
            cat_name = cat_spec.get("name")
            if not cat_name:
                continue

            category = discord.utils.get(self.guild.categories, name=cat_name)
            overwrites = self._build_overwrites(cat_spec.get("overwrites"))

            if category is None:
                if self.dry_run:
                    self.created += 1
                    self._note("+", f"Would create category **{cat_name}**")
                else:
                    try:
                        category = await self.guild.create_category(
                            cat_name,
                            overwrites=overwrites or None,
                            reason="ModSuite blueprint",
                        )
                        self.created += 1
                        self._note("+", f"Created category **{cat_name}**")
                    except discord.Forbidden:
                        self.failed += 1
                        self._note("!", f"Category **{cat_name}** failed: missing permissions")
                        continue
                    except discord.HTTPException as e:
                        self.failed += 1
                        self._note("!", f"Category **{cat_name}** failed: {e.text or e}")
                        continue
            else:
                self.skipped += 1
                self._note("=", f"Category **{cat_name}** already exists")
                if self.update_existing and overwrites and not self.dry_run:
                    try:
                        await category.edit(overwrites=overwrites,
                                            reason="ModSuite blueprint")
                        self._note("~", f"Refreshed permissions on **{cat_name}**")
                    except discord.HTTPException as e:
                        self.failed += 1
                        self._note("!", f"Permissions on **{cat_name}** failed: {e.text or e}")

            await self._apply_channels(cat_spec, category, overwrites)

    async def _apply_channels(self, cat_spec: dict, category,
                              cat_overwrites: dict | None = None):
        cat_name = cat_spec.get("name")
        cat_overwrites = cat_overwrites or {}
        for ch_spec in cat_spec.get("channels", []) or []:
            ch_name = ch_spec.get("name")
            if not ch_name:
                continue

            existing = discord.utils.get(self.guild.channels, name=ch_name)
            if existing:
                self.skipped += 1
                self._note("=", f"Channel `#{ch_name}` already exists")
                # A channel created by hand almost never has a topic set.
                # update_existing backfills it from the blueprint without
                # touching anything else about the channel.
                wanted = (ch_spec.get("topic") or "").strip()[:1024]
                if (self.update_existing and wanted
                        and hasattr(existing, "topic")
                        and (existing.topic or "").strip() != wanted):
                    if self.dry_run:
                        self.created += 1
                        self._note("~", f"Would set topic on `#{ch_name}`")
                    else:
                        try:
                            await existing.edit(topic=wanted,
                                                reason="ModSuite blueprint")
                            self.created += 1
                            self._note("~", f"Set topic on `#{ch_name}`")
                        except discord.HTTPException as e:
                            self.failed += 1
                            self._note("!", f"Topic on `#{ch_name}` failed: {e.text or e}")
                continue

            kind = str(ch_spec.get("type", "text")).lower()
            if kind not in CHANNEL_TYPES:
                self.failed += 1
                self._note("!", f"Channel `#{ch_name}`: unknown type '{kind}'")
                continue

            if self.dry_run:
                self.created += 1
                label = "" if kind == "text" else f" ({kind})"
                self._note("+", f"Would create `#{ch_name}`{label} in **{cat_name}**")
                continue

            # Permission inheritance, carefully.
            #
            # Discord only syncs a new channel to its category when NO
            # overwrites argument is passed. Passing one replaces the whole
            # set, which would silently strip the category's `@everyone deny
            # view_channel` and publish a channel that is supposed to be
            # private. So when a channel declares its own overwrites, the
            # category's are merged in underneath as the base layer.
            ch_overwrites = None
            if ch_spec.get("overwrites"):
                merged = dict(cat_overwrites)  # category rules first
                for target, ow in self._build_overwrites(ch_spec["overwrites"]).items():
                    if target in merged:
                        # Layer the channel's explicit flags on top of the
                        # category's rather than discarding them
                        base = merged[target]
                        for flag, value in ow:
                            if value is not None:
                                setattr(base, flag, value)
                        merged[target] = base
                    else:
                        merged[target] = ow
                ch_overwrites = merged

            kwargs = {"reason": "ModSuite blueprint"}
            if category is not None:
                kwargs["category"] = category
            if ch_overwrites:
                kwargs["overwrites"] = ch_overwrites
            # create_voice_channel / create_stage_channel do not accept topic
            topic = (ch_spec.get("topic") or "")[:1024]
            if topic and kind in ("text", "forum", "announcement"):
                kwargs["topic"] = topic
            if ch_spec.get("slowmode") and kind == "text":
                kwargs["slowmode_delay"] = int(ch_spec["slowmode"])
            if ch_spec.get("nsfw"):
                kwargs["nsfw"] = True

            try:
                if kind == "voice":
                    await self.guild.create_voice_channel(ch_name, **kwargs)
                elif kind == "stage":
                    await self.guild.create_stage_channel(ch_name, **kwargs)
                elif kind == "forum":
                    await self.guild.create_forum(ch_name, **kwargs)
                else:
                    ch = await self.guild.create_text_channel(ch_name, **kwargs)
                    if kind == "announcement":
                        try:
                            await ch.edit(type=discord.ChannelType.news)
                        except discord.HTTPException:
                            pass
                self.created += 1
                self._note("+", f"Created `#{ch_name}` in **{cat_name}**")
            except discord.Forbidden:
                self.failed += 1
                self._note("!", f"Channel `#{ch_name}` failed: missing permissions")
            except discord.HTTPException as e:
                self.failed += 1
                self._note("!", f"Channel `#{ch_name}` failed: {e.text or e}")

    async def run(self):
        await self.apply_roles()
        await self.apply_structure()
        return {
            "created": self.created,
            "skipped": self.skipped,
            "failed": self.failed,
            "log": self.log,
        }


def export_guild(guild: discord.Guild, include_permissions: bool = False) -> dict:
    """Read a live server and produce a blueprint dict describing it."""
    roles = []
    for role in sorted(guild.roles, key=lambda r: r.position, reverse=True):
        if role.is_default() or role.managed:
            continue
        entry = {
            "name": role.name,
            "color": f"#{role.colour.value:06X}",
            "hoist": role.hoist,
            "mentionable": role.mentionable,
        }
        if include_permissions:
            entry["permissions"] = [
                flag for flag, on in role.permissions if on
            ]
        roles.append(entry)

    def _overwrites_for(channel) -> list:
        out = []
        for target, ow in channel.overwrites.items():
            if not isinstance(target, discord.Role):
                continue
            allow, deny = [], []
            for flag, value in ow:
                if value is True:
                    allow.append(flag)
                elif value is False:
                    deny.append(flag)
            if not allow and not deny:
                continue
            entry = {"role": "@everyone" if target.is_default() else target.name}
            if allow:
                entry["allow"] = allow
            if deny:
                entry["deny"] = deny
            out.append(entry)
        return out

    type_names = {v: k for k, v in CHANNEL_TYPES.items()}
    categories = []
    for category in sorted(guild.categories, key=lambda c: c.position):
        channels = []
        for ch in category.channels:
            spec = {
                "name": ch.name,
                "type": type_names.get(ch.type, "text"),
            }
            topic = getattr(ch, "topic", None)
            if topic:
                spec["topic"] = topic
            ows = _overwrites_for(ch)
            if ows:
                spec["overwrites"] = ows
            channels.append(spec)
        cat_entry = {"name": category.name, "channels": channels}
        cat_ows = _overwrites_for(category)
        if cat_ows:
            cat_entry["overwrites"] = cat_ows
        categories.append(cat_entry)

    # Channels sitting outside any category still belong in the export
    loose = [c for c in guild.channels
             if c.category is None and not isinstance(c, discord.CategoryChannel)]
    if loose:
        categories.append({
            "name": "Uncategorized",
            "channels": [
                {"name": c.name, "type": type_names.get(c.type, "text")}
                for c in loose
            ],
        })

    return {
        "name": guild.name.lower().replace(" ", "-"),
        "description": f"Exported from {guild.name} on {datetime.utcnow():%Y-%m-%d}",
        "roles": roles,
        "categories": categories,
    }


class Blueprint(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    blueprint_group = app_commands.Group(
        name="blueprint",
        description="Build server structure from a saved blueprint.",
    )

    def _lookup(self, guild_id: int, name: str) -> dict | None:
        record = db.get_blueprint(str(guild_id), name)
        if record:
            return record["data"]
        for data in load_bundled_blueprints():
            if data.get("name") == name:
                return data
        return None

    @blueprint_group.command(name="list", description="Show every available blueprint.")
    async def bp_list(self, interaction: discord.Interaction):
        cfg = db.get_config(interaction.guild_id)
        if not _is_admin(interaction.user, cfg):
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True
            )

        records = db.get_blueprints(str(interaction.guild_id))
        if not records:
            return await interaction.response.send_message(
                "No blueprints saved. Drop a JSON file in `blueprints/` and restart, "
                "or run `/blueprint export` to snapshot this server.",
                ephemeral=True,
            )

        e = discord.Embed(title="Blueprints", colour=0xD4A843)
        for r in records:
            data = r.get("data") or {}
            n_roles = len(data.get("roles", []) or [])
            cats = data.get("categories", []) or []
            n_channels = sum(len(c.get("channels", []) or []) for c in cats)
            scope = "global" if r["guild_id"] is None else "this server"
            e.add_field(
                name=r["name"],
                value=(
                    f"{r.get('description') or 'No description.'}\n"
                    f"{n_roles} roles · {len(cats)} categories · {n_channels} channels\n"
                    f"*{scope} · {r.get('source', 'custom')}*"
                ),
                inline=False,
            )
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @blueprint_group.command(
        name="preview",
        description="Show exactly what a blueprint would change. Changes nothing.",
    )
    @app_commands.describe(name="Blueprint name (see /blueprint list)")
    async def bp_preview(self, interaction: discord.Interaction, name: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_admin(interaction.user, cfg):
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True
            )

        data = self._lookup(interaction.guild_id, name)
        if data is None:
            return await interaction.response.send_message(
                f"No blueprint named `{name}`.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        engine = BlueprintEngine(interaction.guild, data, dry_run=True)
        result = await engine.run()

        db.add_blueprint_run(
            str(interaction.guild_id), name, str(interaction.user.id),
            str(interaction.user), True, result["created"], result["skipped"],
            result["failed"], result["log"],
        )
        await interaction.followup.send(
            embed=self._result_embed(name, result, dry_run=True), ephemeral=True
        )

    @blueprint_group.command(
        name="apply",
        description="Create everything in a blueprint that does not already exist.",
    )
    @app_commands.describe(
        name="Blueprint name (see /blueprint list)",
        confirm="Must be True. Preview first with /blueprint preview.",
        update_existing="Also refresh colors and permissions on things that already exist",
    )
    async def bp_apply(self, interaction: discord.Interaction, name: str,
                       confirm: bool = False, update_existing: bool = False):
        cfg = db.get_config(interaction.guild_id)
        if not _is_admin(interaction.user, cfg):
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True
            )

        data = self._lookup(interaction.guild_id, name)
        if data is None:
            return await interaction.response.send_message(
                f"No blueprint named `{name}`.", ephemeral=True
            )

        if not confirm:
            return await interaction.response.send_message(
                f"This will create roles and channels in **{interaction.guild.name}**.\n"
                f"Run `/blueprint preview name:{name}` first, then re-run with "
                f"`confirm:True` when the plan looks right.",
                ephemeral=True,
            )

        me = interaction.guild.me
        missing = []
        if not me.guild_permissions.manage_roles:
            missing.append("Manage Roles")
        if not me.guild_permissions.manage_channels:
            missing.append("Manage Channels")
        if missing:
            return await interaction.response.send_message(
                f"I am missing: {', '.join(missing)}. Grant those and try again.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        engine = BlueprintEngine(interaction.guild, data, dry_run=False,
                                 update_existing=update_existing)
        result = await engine.run()

        db.add_blueprint_run(
            str(interaction.guild_id), name, str(interaction.user.id),
            str(interaction.user), False, result["created"], result["skipped"],
            result["failed"], result["log"],
        )
        db.add_mod_log(
            guild_id=str(interaction.guild_id),
            action="BLUEPRINT",
            target_id=str(interaction.guild_id),
            target_username=interaction.guild.name,
            actor_id=str(interaction.user.id),
            actor_username=str(interaction.user),
            reason=(
                f"Applied blueprint '{name}': {result['created']} created, "
                f"{result['skipped']} skipped, {result['failed']} failed"
            ),
        )
        await interaction.followup.send(
            embed=self._result_embed(name, result, dry_run=False), ephemeral=True
        )

    @blueprint_group.command(
        name="export",
        description="Snapshot this server's structure into a reusable blueprint.",
    )
    @app_commands.describe(
        save_as="Name to save it under",
        include_permissions="Include each role's permission flags in the export",
    )
    async def bp_export(self, interaction: discord.Interaction, save_as: str,
                        include_permissions: bool = False):
        cfg = db.get_config(interaction.guild_id)
        if not _is_admin(interaction.user, cfg):
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        data = export_guild(interaction.guild, include_permissions=include_permissions)
        data["name"] = save_as.strip().lower().replace(" ", "-")

        db.upsert_blueprint(
            str(interaction.guild_id), data["name"], data,
            description=data.get("description", ""), source="export",
        )

        payload = json.dumps(data, indent=2)
        import io
        file = discord.File(
            io.BytesIO(payload.encode("utf-8")),
            filename=f"{data['name']}.json",
        )
        n_channels = sum(len(c.get("channels", []) or [])
                         for c in data.get("categories", []))
        await interaction.followup.send(
            f"Exported **{interaction.guild.name}**: "
            f"{len(data['roles'])} roles, {len(data['categories'])} categories, "
            f"{n_channels} channels.\n"
            f"Saved as `{data['name']}` and attached below. Drop the file into "
            f"`blueprints/` to keep it in version control.",
            file=file,
            ephemeral=True,
        )

    @blueprint_group.command(name="delete", description="Delete a saved blueprint.")
    @app_commands.describe(name="Blueprint name")
    async def bp_delete(self, interaction: discord.Interaction, name: str):
        cfg = db.get_config(interaction.guild_id)
        if not _is_admin(interaction.user, cfg):
            return await interaction.response.send_message(
                "Administrator only.", ephemeral=True
            )
        ok = db.delete_blueprint(str(interaction.guild_id), name)
        await interaction.response.send_message(
            f"Deleted blueprint `{name}`." if ok else
            f"No server-owned blueprint named `{name}`. Bundled blueprints "
            f"live in `blueprints/` and are removed by deleting the file.",
            ephemeral=True,
        )

    @staticmethod
    def _result_embed(name: str, result: dict, dry_run: bool) -> discord.Embed:
        title = f"Blueprint preview: {name}" if dry_run else f"Blueprint applied: {name}"
        colour = 0x5865F2 if dry_run else 0x2ECC71
        if result["failed"]:
            colour = 0xE67E22

        verb = "would change" if dry_run else "created"
        e = discord.Embed(
            title=title,
            description=(
                f"**{result['created']}** {verb} · "
                f"**{result['skipped']}** already existed · "
                f"**{result['failed']}** failed"
            ),
            colour=colour,
        )

        lines = result["log"]
        if not lines:
            e.add_field(name="Plan", value="Nothing to do.", inline=False)
        else:
            # Embed fields cap at 1024 chars, so chunk rather than truncate
            chunk, chunks = "", []
            for line in lines:
                if len(chunk) + len(line) + 1 > 1000:
                    chunks.append(chunk)
                    chunk = ""
                chunk += line + "\n"
            if chunk:
                chunks.append(chunk)
            for i, c in enumerate(chunks[:5]):
                e.add_field(
                    name="Plan" if i == 0 else f"Plan (cont. {i + 1})",
                    value=c,
                    inline=False,
                )
            if len(chunks) > 5:
                e.add_field(
                    name="Truncated",
                    value=f"{len(lines)} total lines. Full log is in the dashboard.",
                    inline=False,
                )

        if dry_run:
            e.set_footer(text=f"Nothing was changed · {FOOTER_BRAND}")
        else:
            e.set_footer(text=FOOTER_BRAND)
        return e


async def setup(bot: commands.Bot):
    await bot.add_cog(Blueprint(bot))
