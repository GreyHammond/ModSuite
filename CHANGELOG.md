# Changelog

All notable changes to ModSuite are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), with SemVer.

---

## [4.1.0] -- 2026-08-21

### Added -- legacy booster rewards

Discord removes its own booster role the instant someone stops boosting, so
every perk hanging off it disappears with it. This grants a **separate,
permanent role** on a member's first boost: boost once, keep the perks forever.

- `/booster setup role:` names the permanent role. Refuses Discord's own
  booster role, since that is the exact thing being worked around, and refuses
  a role positioned above the bot, which it could never assign.
- `/booster sync` backfills everyone already boosting, and restores the role to
  anyone whose record exists but whose role was removed by hand.
- `/booster grant` and `/booster revoke` for manual cases. Revocation is
  recorded with an actor and reason and written to the mod log rather than
  deleting the row.
- `/booster list` shows who earned it, who is still boosting, and who is
  keeping perks without boosting.
- `/booster off` stops future grants without touching anything already earned.

**The database row is the source of truth, not the Discord role.** Roles are
lost when a member leaves the server, so a record-free implementation would
quietly break the promise for anyone who left and came back. `on_member_join`
re-applies the role to a returning member who earned it.

Verified: first boost grants and records; stopping boosting changes nothing;
re-boosting does not create a duplicate; leaving and rejoining restores the
role; a revoked member is not restored on rejoin; a disabled guild does nothing.

**Dashboard**: new config section, plus `GET /boosters`, `POST /boosters/sync`,
and `DELETE /boosters/{user_id}`.

---

## [4.0.0] -- 2026-08-11

The release that makes the dashboard a first-class administration surface
rather than a companion to the bot.

### Added -- unified audit trail

- Every state-changing dashboard request **and** every slash command lands in
  one timeline with actor, target, payload, status code, and IP.
- Implemented as API middleware plus a global `on_app_command_completion`
  listener rather than per-route or per-cog, so a route or command added later
  cannot forget to log.
- **Failures and refusals are recorded**, including permission-denied commands.
  A refused `/ban` is often the more interesting entry.
- Read-only commands are flagged rather than dropped, so "who looked this up"
  remains answerable.
- Secrets (`token`, `secret`, `password`, `client_secret`, `api_key`) are
  redacted before storage.
- `/audit purge` enforces a 7-day floor, so the trail cannot be cleared to hide
  a recent action.
- Auditing never affects the response: a write failure is logged and swallowed.

### Changed -- dashboard parity

- **Every editable `guild_config` column now has an editor**, verified
  programmatically against the schema rather than by eye. 96 keys across 23
  sections.
- New `textarea` field type for long-form text.
- New pages: Blueprints, Archive, Audit Trail, Requests, Feeds & Events.
- `patch()` helper added to `web/api.js`, which was missing entirely.

### Changed -- branding is configurable

- `PRODUCT_NAME`, `ORG_NAME`, `FOOTER_BRAND`, and `BRAND_COLOR` are read from
  the environment, so a deployment can be white-labelled without touching code.

### Fixed

- **The dashboard version was hardcoded** in `web/pages/setup.js` and had read
  `v2.0.0` for four releases. There is now one `VERSION` constant in `api.py`,
  returned by `/health` and read by the dashboard at load, so it cannot drift
  again.
- **Dashboard routes attributed actions to a literal "Dashboard"** rather than
  the authenticated user, so the mod log could not say who applied a blueprint.
- **Private channels could be created publicly visible.** Discord only syncs a
  new channel to its category when no `overwrites` argument is passed; passing
  one replaces the entire set, silently stripping the category's `@everyone
  deny view_channel`. Category overwrites are now merged in as the base layer
  with the channel's own flags on top.
- **Explicit `send_messages` allows defeated the mute role.** Discord resolves
  an allow on any role over a deny on any other regardless of role position, so
  a muted member holding a role with an explicit allow kept posting. Blueprints
  no longer grant it; send falls through to the server default, which a deny
  wins.
- **Blueprint previews reported a false failure for every permission
  overwrite**, because the roles they reference do not exist during a dry run.
  Planned role names are now tracked, so only overwrites naming a role the
  blueprint never defines are flagged.
- `create_voice_channel` and `create_stage_channel` do not accept a `topic`
  argument; passing one raised a `TypeError` mid-run.
- `DEPLOY.md` rewritten. It had been the v2.5 guide, four majors stale.

---

## [3.9.0] -- 2026-08-10

### Added -- multi-platform stream alerts

Stream alerts were Twitch-only, with the platform baked into the schema, the
poll loop, and every embed. New `platforms.py` puts a provider interface in
front of each service so the cog asks one question -- who is live -- and does
not care who hosts it.

- **Twitch** via the Helix API, unchanged.
- **YouTube**, no credentials required. Live status is read from the channel's
  `/live` page rather than the Data API, whose search endpoint costs 100 quota
  units per call against a 10,000/day allowance -- polling a single channel
  every 90 seconds would exceed the daily quota about tenfold. Upcoming
  premieres carry a live marker and are excluded.
- **Kick** via the public v2 channel endpoint.
- **Rumble** by page check; no status API exists, so it is best effort.
- Every provider swallows its own errors and returns empty, so a platform being
  down, rate limited, or blocking datacenter IPs reads as "nobody is live"
  rather than taking down the poll for the others.
- `streamers` gains a `platform` column defaulting to `twitch`, by migration.

### Added -- RSS feeds

- Watch any RSS 2.0 or Atom feed and post new items as an embed, optionally
  opening a discussion thread on each so replies stay with the item.
- Parsed with the standard library rather than adding `feedparser`.
  ElementTree does not fetch external entities, so a hostile feed cannot use an
  XXE to read local files.
- **Adding a feed does not dump the archive**: existing items are recorded as
  seen without posting.
- **TLS fallback.** Cloudflare-fronted hosts fingerprint the handshake, not just
  the headers, and return 403 to Python clients while serving curl a 200 for an
  identical request. On 403 or 503 the fetch retries through the system `curl`
  binary.

### Added -- recurring events

- Reminders for events that follow a rule (nth weekday, last weekday, weekly,
  day of month) or an explicit list of approved dates.
- The date-list mode exists because real bodies rarely follow a clean rule: one
  council's published 2026 calendar matched "2nd and 4th Tuesday" in only 4 of
  12 months.
- Two pings per event, the morning of and an hour before, to a role rather than
  everyone. Reminder state is keyed by occurrence date, so a restart cannot
  re-send.
- `/meeting cancel`, `move`, and `restore` operate on a single occurrence.
  Exceptions are stored apart from the schedule, so cancelling one night never
  edits the calendar and is always reversible. Cross-month moves resolve
  correctly.

### Added -- membership roster

- Publishes a list of everyone holding a chosen role, grouped by the
  organization they represent, and republishes automatically when the role is
  granted or removed.
- The post is edited in place rather than reposted, so it keeps a permanent
  citable link.
- Role name, channel name, and intro text are configurable per guild.
- The dashboard flags drift both ways: role holders with no organization
  recorded, and stored records for people who no longer hold the role.

---

## [3.8.0] -- 2026-08-10

### Fixed -- permanent mute did not work

`/mute` clamped every duration with `min(td, timedelta(days=28))` because
Discord's native timeout caps there. A mute recorded in the database as
permanent silently lapsed at day 28 and the member resumed posting with nobody
notified. The mute **role** is now the enforcement authority:

- New `mutes.py` creates the `Muted` role and applies deny overwrites for
  messages, threads, reactions, attachments, embeds, and voice across every
  category. Jail is skipped deliberately, since a muted member has to be able to
  answer you in the channel where you talk it through.
- `/mute duration:permanent` never expires. Timed mutes still receive a native
  timeout when they fit inside 28 days, because that takes effect instantly.
- `/mute-setup` creates the role and syncs every overwrite in one command.
- **Leaving and rejoining was a one-click mute bypass.** `on_member_join` now
  re-applies the role and notes it in the mod log.
- `/unmute` and the expiry sweep both strip the role.

### Added -- public moderation log

- `/public-modlog #channel` posts every mute, unmute, jail, release, kick, and
  ban with a reason to a channel members can read. Warnings stay private, since
  publicly pillorying someone for a first misstep is a different thing from
  being transparent about silencing.
- Display names only, no user IDs.
- Posting failures are swallowed, so a broken log channel can never roll back
  the moderation action itself.

### Added -- records request tracker

- `/foia file` computes a response deadline in business days, skipping weekends
  and a configurable holiday calendar.
- `/foia extend` applies an extension; `/foia list` shows business days
  remaining or how far overdue; `/foia status` records acknowledgement, fee
  quotes, denial, and appeal.
- A twice-daily loop warns one business day out, on the due date, and once
  overdue. Warnings fire once per stage per request, so restarts do not spam.
- Response window, extension length, and holiday set (US federal, Michigan, or
  none) are configurable per guild.

---

## [3.7.0] -- 2026-08-09

### Added -- message archive

A forensic archive of public messages, off by default.

- Messages, edits, and deletions are recorded to SQLite with an index on guild,
  author, and deleted state. Edits keep full revision history rather than
  overwriting.
- Deleted messages are reposted to a private channel with their attachments.
  `on_bulk_message_delete` is handled too, so a moderator purging a channel
  cannot erase the record the archive exists to keep.
- Attachments are copied to a vault directory and served from
  `GET /archive/vault/{filename}`, behind the dashboard's existing
  authentication, with a path-traversal guard that rejects any filename
  containing a separator.
- A `tasks.loop` enforces retention, deleting expired rows and their vault
  files together -- files first, so a crash orphans data rather than stranding
  rows that point at nothing.
- **Scope defaults to public channels only.** ModMail, staff categories, and any
  channel `@everyone` cannot view are excluded. A bulk archive of private
  deliberation carries legal exposure and offers the least value.
  `/archive setup scope:all` opts in and warns.

**Commands**: `/archive setup`, `off`, `status`, `exclude`, `purge`.
**API**: `GET /archive`, `/archive/stats`, `/archive/vault/{filename}`.
**Dashboard**: new Archive page with text and author search and a deleted-only
filter.

---

## [3.6.0] -- 2026-08-09

### Added -- Server blueprints

**Blueprint engine** (new cog: `cogs/blueprint.py`):
- A blueprint is a JSON file describing a server's roles, categories, and
  channels. Files live in `blueprints/` and are loaded into the DB on boot,
  so a server layout becomes a versionable artifact you can diff and reuse.
- `/blueprint preview` runs the whole plan and changes nothing, reporting
  exactly what would be created, what already exists, and what would fail.
- `/blueprint apply` requires `confirm:True` and refuses to run if the bot is
  missing Manage Roles or Manage Channels.
- `/blueprint export` snapshots a live server into a blueprint and returns the
  JSON as a file attachment, so an existing server can seed a new one.
- `/blueprint list` and `/blueprint delete` round out the command group.
- Administrator-only, deliberately stricter than the `_is_staff` check used by
  other cogs, since blueprints create roles and rewrite permissions.

**Behaviour**:
- Fully additive and idempotent. Roles and channels are matched by name;
  anything that already exists is skipped, never modified or deleted. Applying
  the same blueprint twice creates nothing the second time.
- Roles are created in reverse file order so the first entry ends up highest,
  working with Discord's habit of inserting each new role at position 1.
- Category-level permission overwrites let child channels inherit, so a locked
  category is defined once rather than per channel.
- `update_existing:True` opts in to refreshing colors and permissions on things
  that already exist, and backfills channel topics onto channels that were
  created by hand. Without it, existing channels are never modified.
- Permission flag names are validated against `discord.Permissions.VALID_FLAGS`;
  an overwrite naming a role the blueprint never defines is reported as an error
  rather than silently dropped.

**Bundled blueprint**: `blueprints/cfj.json` -- 34 roles, 8 categories,
38 channels. Public civic channels, a members-only Round Table for community
leaders with candidates read-only in the main discussion channel, and private
contributor and newsroom categories.

**Dashboard** (`web/pages/blueprints.js`): new Blueprints page. Preview renders
the colour-coded plan inline, and the Apply button only appears after a preview
has run. Includes server export and a run history table.

**API**: `GET /blueprints`, `GET /blueprints/{name}`, `PUT /blueprints/{name}`,
`DELETE /blueprints/{name}`, `POST /blueprints/{name}/apply` (defaults to
`dry_run: true`, so a bare POST is always safe), `POST /blueprints/export`,
`GET /blueprint-runs`.

**Database**: two new tables, `blueprints` and `blueprint_runs`. Every preview
and apply is recorded with actor, counts, and the full log.

**Mod log**: applying a blueprint writes a `BLUEPRINT` entry to `mod_logs`.

### Fixed (pre-release, found during testing)

- **Private channels could be created publicly visible.** Discord only syncs a
  new channel to its category when no `overwrites` argument is passed; passing
  one replaces the entire set. Any channel declaring its own overwrites inside
  a locked category therefore lost the category's `@everyone deny
  view_channel`. Category overwrites are now merged in as the base layer, with
  the channel's own flags layered on top. In `cfj.json` this affected four
  Round Table channels.
- Preview reported a false failure for every permission overwrite, because the
  roles it references do not exist during a dry run. Planned role names are now
  tracked, so only overwrites naming a role the blueprint never defines are
  flagged.
- `create_voice_channel` and `create_stage_channel` do not accept a `topic`
  argument; passing one raised a `TypeError`. Topics are now only sent for
  text, forum, and announcement channels.

---

## [3.5.2] -- 2026-08-08

### Fixed

- `requirements.txt` was missing `httpx`, `pydantic`, and `starlette`. All three
  are imported directly -- `httpx` by `auth.py` for the Discord OAuth2
  endpoints, `pydantic` by `api.py` for its request models, and
  `starlette.middleware.base` by the auth layer. Existing installs only worked
  because FastAPI had pulled them in transitively; a clean venv crashed on
  startup with `ModuleNotFoundError`. Declaring them also means a FastAPI major
  bump cannot silently change the versions underneath the models.

---

## [3.5.1] -- 2026-08-07

### Fixed

**ModMail dropped every attachment users sent.** The DM relay replaced message
content with the literal string `[attachment / embed]` and discarded
`message.attachments` entirely, so staff could see that a file had been sent
but never received the file. Screenshots, which are the single most common
thing a user attaches to a support ticket, never arrived.

Attachments are now downloaded and re-uploaded into the ticket channel. Copying
rather than linking is deliberate: Discord signs CDN attachment URLs with a
roughly 24 hour expiry, so a ticket storing only links would have dead media by
the time anyone reviewed the transcript.

- The first image is promoted into the embed so it renders inline; any further
  files are listed with their names and sizes
- A message containing only an image and no text now relays correctly instead
  of producing an empty embed
- Files above the guild's upload limit, and files Discord refuses to serve
  back, are reported in-channel by name with the reason and the original link,
  rather than vanishing
- The guild's real `filesize_limit` is used, so boosted servers get their
  higher ceiling instead of a hardcoded 10 MB

**Staff could not send media to users at all.** `/reply` now takes an optional
`attachment`. DM channels are capped at 10 MB regardless of the server's boost
tier, so that limit is checked separately and explained when exceeded.

**Transcripts referenced files nobody could open.** Closing a ticket deletes its
channel, which took the re-uploaded media with it. `_close_ticket` now
downloads every attachment into a `media/` folder inside the transcript zip
before the channel is deleted, and the text log marks which files were
archived. If the bundled archive exceeds the upload limit, the text log is
posted on its own rather than the whole transcript being lost.

**Dashboard ticket transcripts now show attachments.** Images render as
thumbnails linking to the full file, other files as labelled download chips.

### Added (database)

- `modmail_messages.attachments` -- JSON list of
  `{filename, size, content_type, url, relayed_url}`, added by auto-migration.
  Existing rows default to `[]` and continue to render normally.
- `log_message()` and `get_ticket_messages()` handle attachment metadata

---

## [3.5.0] -- 2026-08-07

Completes dashboard parity. Every ModSuite feature is now manageable from the
browser except the handful of commands that are inherently in-channel actions.

### Added

**Dashboard: Starboards page.** Create and delete boards, change the target
channel, threshold, and NSFW-only flag, and manage trigger emojis.
- Endpoints: `GET|POST /starboards`, `PUT|DELETE /starboards/{id}`,
  `POST /starboards/{id}/emojis`, `DELETE /starboards/{id}/emojis/{emoji}`
- Two silent failure modes are now visible: a board pointing at a deleted
  channel is flagged, and removing a board's last trigger emoji is refused
  rather than leaving a board that can never fire
- Registering an emoji already owned by another board is refused, since
  `get_board_for_emoji` resolves by emoji alone and the winner would otherwise
  depend on row order

**Dashboard: Reminders page.** Guild-wide view of everything scheduled through
`/remindme`, with cancellation. Surfaces reminders whose owner has left the
server, and flags any more than ten minutes past due, which indicates the
bot's reminder loop is not running.
- Endpoints: `GET /reminders`, `DELETE /reminders/{id}`

**Dashboard: React Roles page.** Map existing roles to emojis and publish a
self-assign message, with a live preview of the embed as it will appear.
- Endpoints: `GET /react-messages`, `GET /react-messages/roles`,
  `POST /react-messages`, `PUT /react-messages/{id}`,
  `DELETE /react-messages/{id}`
- New bot actions: `react_publish`, `react_delete`
- Not a port of the `/createreactmessage` draft flow. That flow needs a live
  draft message in a channel to render previews into; the browser form already
  is the preview, so composing and publishing happens in one step with no
  draft round trip.
- Distinct from the Self Roles page, which creates brand new Discord roles from
  names. Both write `selfrole_categories`, so the same reaction handler drives
  them.
- The role picker only offers roles the bot can actually assign, excluding
  `@everyone`, integration-managed roles, and anything above the bot's own top
  role. Offering one of those would produce a message that looks correct and
  silently fails on every reaction.
- Editing syncs reactions rather than clearing them: only emojis that were
  added or removed are touched, so members who already reacted keep their roles
  instead of having to react again after every edit.
- If the published message was deleted in Discord, an edit reposts it instead
  of failing.

### Added (database)

- `update_starboard()` -- `update_starboard_threshold()` only ever covered the
  threshold, so a board's channel and NSFW flag could be set at creation and
  never changed
- `get_guild_reminders()` and `delete_reminder_by_id()` -- the existing
  functions are keyed on `user_id`, which is right for self-service `/remindme`
  but made staff visibility and cleanup impossible
- `get_starboard_by_id()`, `count_starboard_entries()`

---

## [3.4.0] -- 2026-08-07

### Added

**Dashboard: AutoMod page.** Word lists and severity profiles, the last two
AutoMod features that were reachable only through slash commands. Previously
you could enable word filtering from the Configuration page without being able
to see or edit what it filtered.

*Word lists*
- Create and delete lists, add and remove words, all inline
- Words are normalised to lowercase and deduplicated on save, since matching is
  case-insensitive anyway
- Single words and multi-word phrases are visually distinguished, because they
  match differently: a single word matches whole words only, a phrase matches
  as a substring anywhere in the message
- `POST /word-lists/test` checks a sample message against every list using the
  exact matching rules from `cogs/automod.py`, and reports which entry matched
  and what would happen. The filter deletes silently, so without this the only
  way to discover an over-matching entry was for it to hit a real member.
- Endpoints: `POST /word-lists`, `PUT /word-lists/{name}`,
  `POST /word-lists/{name}/words`, `DELETE /word-lists/{name}/words/{word}`,
  `DELETE /word-lists/{name}`, `POST /word-lists/test`

*Severity profiles*
- One-click switching with the active profile marked
- Snapshot the guild's current settings into a named profile
- Overrides are validated against the same `OVERRIDABLE_KEYS` the bot honours,
  so a profile can no longer be saved with a key that would be silently ignored
  at runtime
- Built-in profiles are read-only, guaranteeing a known-good baseline
- Deleting is refused for the active profile, and for the profile queued for
  restore after a raid lockdown, either of which would have stranded AutoMod
- Endpoints: `POST /profiles`, `POST /profiles/{name}/snapshot`,
  `DELETE /profiles/{name}`, `GET /profiles/keys`

**Profile switches are attributed to the logged-in staff member.**
`PUT /profiles/active` previously logged an anonymous "Dashboard" actor and did
not record what the previous profile was. It now records both.

### Fixed

**`Request` was imported below its first use in `api.py`.** The annotation on
`PUT /profiles/active` could not be resolved at decoration time, so FastAPI
treated `request` as a required query parameter and every switch returned 422.

---

## [3.3.0] -- 2026-08-07

### Added

**Dashboard: Moderation page.** Warn, mute, unmute, kick, jail, unjail, ban,
unban, and clear violations, all from the browser and all keyed on numeric user
ID. Three tabs: take action, everything currently in force (mutes, jails,
pending auto-unbans), and an audit log of dashboard actions including failures.

- `POST /moderation/{action}`, `GET /moderation/active`,
  `DELETE /moderation/violations/{user_id}`, `GET /bot-actions`
- New bot action family `mod_*`, dispatched through one shared handler
- Ban, unban, unjail, and clearing violations work on members who have left.
  Kick, mute, and jail are disabled in the UI with the reason shown, and
  refused server-side as well.
- A duration on a ban makes it a temporary ban with automatic unban.

**Dashboard actions are attributed to the logged-in staff member.** The auth
middleware now attaches the session identity to each request, and moderation
endpoints record that Discord ID and username in both `bot_actions` and
`mod_logs`. Previously these were logged as an anonymous "Dashboard" actor,
which made the mod-log unable to answer who did what. When OAuth is not
configured the actor is recorded as "Dashboard (unauthenticated)" so it can
never be mistaken for a real person.

**Permission hierarchy is enforced on dashboard actions.** The bot re-checks
`utils.can_moderate` against the requesting staff member before executing, so
nothing is possible from the browser that would not be possible from a slash
command. The check runs in the bot process because only it has the member and
role cache needed to evaluate it.

### Fixed

**`can_moderate` blocked the server owner from acting on administrators.** The
documented permission table has always said the server owner outranks admins,
but the admin-versus-admin rule caught the owner as well, since the owner also
holds administrator permissions. Affects every moderation command, not just the
dashboard.

---

## [3.2.0] -- 2026-08-07

### Fixed

**Commands targeting a member now accept a numeric user ID.**
Most staff commands declared their target as `discord.Member`. Discord will not
populate that parameter for anyone who has left the guild, so the command was
unusable against a departed member regardless of what the bot code did. Affected
commands now take a string and resolve it through `utils.resolve_user`, which
accepts a mention, a numeric user ID, an exact username or display name, or an
unambiguous name prefix:

`/streamer add`, `/streamer remove`, `/streamer edit`, `/streamer links add|remove|list`,
`/jail`, `/unjail`, `/tempjail`, `/kick`, `/mute`, `/unmute`, `/softban`, `/unban`,
`/verify`, `/unverify`, `/violations check`, `/violations clear`, `/move`.

- `/streamer remove` now deletes the channel and clears the database row even
  when the streamer has left, and reports each step separately instead of
  failing silently.
- `/unjail` now releases a departed member: the transcript is archived, the jail
  channel is deleted, and the row is cleared. Role restoration and the DM are
  skipped because there is nobody to apply them to.
- Auto-unjail previously dropped the database row for a member who left without
  deleting their jail channel, orphaning the channel permanently. It now runs
  the full release path.
- `/unban` accepts mentions, distinguishes "not on the ban list" from "no
  permission", works on deleted accounts, and clears any pending auto-unban row.
- Commands that genuinely require presence (kick, mute, timeout, role grants)
  now explain why and point at the right alternative.

**`warn_mute_duration_hrs` was never a real column.** It was referenced by
`/setup` and the dashboard config schema since v2.0 but absent from
`GUILD_CONFIG_COLUMNS`, so writes to it went nowhere and auto-mute duration was
never configurable. Added with auto-migration and a 24h default.

### Added

**Dashboard: Streamers page.** Full CRUD over streamers, keyed on user ID so
departed streamers can be edited and removed from the browser. Streamers who
have left the server are flagged individually and counted in a banner. Profile
links are editable inline. Discord-side work is queued through `bot_actions`.

- `GET|POST /streamers`, `PUT|DELETE /streamers/{id}`,
  `GET|POST /streamers/{id}/links`, `DELETE /streamers/{id}/links/{label}`
- New bot actions: `streamer_add`, `streamer_remove`, `streamer_edit`,
  `streamer_refresh_card`
- `/streamer list` slash command, which marks streamers who have left

**Dashboard: complete configuration coverage.** `CONFIG_SECTIONS` listed only
part of the config table, and `PUT /config` silently discards any key not listed
there. Every remaining setting is now exposed, taking the editor from 45 to 65
fields across 15 sections. Newly reachable: anti-phishing, message length,
all-caps, bot slowmode, word list master switch, violation engine thresholds,
name filter, verification gate, honeypot channels, role persistence, reports
channel, ModMail and jail categories, and the mod panel channel.

---

## [3.1.0] -- 2026-07-09

### Autoresponses

**Trigger-based automatic replies** (new cog: `cogs/autoresponse.py`):
- Admins define trigger words/phrases and the bot auto-replies when detected in any message
- Three match modes: contains (trigger appears anywhere), exact (full message match), startswith (message begins with trigger)
- Case-insensitive matching; only the first matched trigger fires per message
- Enable/disable individual autoresponses without deleting them
- Staff and bot messages are excluded from triggering

**Dashboard page** (`web/pages/autoresponses.js`):
- New "Autoresponses" page in the sidebar navigation
- Create, edit, toggle, and delete autoresponses from the web dashboard
- Expandable cards show full response text and inline editing
- Match mode selector and enable/disable toggle per entry

**REST API** (new endpoints in `api.py`):
- `GET /autoresponses` -- list all autoresponses for the guild
- `POST /autoresponses` -- create a new trigger/response pair
- `PUT /autoresponses/{id}` -- update trigger, response, match mode, or enabled state
- `DELETE /autoresponses/{id}` -- remove an autoresponse

**Slash commands**:
- `/autoresponse add <trigger> <response> [match_mode]` -- add a new autoresponse
- `/autoresponse remove <trigger>` -- remove by trigger text
- `/autoresponse list` -- list all autoresponses for the server

**Database**:
- New `autoresponses` table with auto-migration on startup
- Unique constraint on (guild_id, trigger) prevents duplicates

---

## [3.0.0] -- 2026-07-08

### Phase 4: Name filtering, verification gate, all-caps filter

**Username/nickname filtering** (new cog: `cogs/namefilter.py`):
- Checks display names on join (`on_member_join`) and on nickname change (`on_member_update`)
- Configurable word list for blocked name patterns stored in `name_filter_words` config
- Unicode confusable character normalization (Cyrillic lookalikes, l33tspeak, fullwidth chars) mapped to ASCII equivalents before matching -- catches evasion attempts
- Actions: log (flag in #mod-log), kick, or ban
- `/namefilter toggle` / `action` / `confusables` / `add` / `remove` / `list` -- 6 slash commands
- Name Filter panel in `/setup` with toggle, confusables toggle, and action selector
- NAME_FILTER action type in mod_logs, /history, and dashboard activity feed

**Verification gate**:
- New members must react to a verification message to gain a configured role
- Until verified, members lack the gate role (server permissions control access)
- Reaction listener grants the role and logs VERIFIED_GATE to mod_logs
- `/verifygate toggle` / `role` / `channel` / `post` / `status` -- 5 slash commands
- Verify Gate panel in `/setup` with toggle, role picker, and channel picker
- VERIFIED_GATE action type in mod_logs, /history, and dashboard activity feed

**All-caps filter**:
- Configurable percentage threshold (default 70%) of uppercase alphabetic characters
- Minimum character length before checking (default 10 alpha chars, ignores short messages)
- Feeds into the violation engine like all other automod triggers
- `/automod allcaps` / `allcaps_threshold` -- 2 slash commands
- Toggle and threshold in `/setup` > Content Filters panel
- Shown in `/automod status` and dashboard AutoMod card

**Setup hub**:
- 2 new panels: Name Filter, Verify Gate (15 total hub buttons across 5 rows)
- Hub embed shows all-caps, name filter, and verify gate status
- Content Filters panel now includes all-caps toggle and threshold

**Dashboard**:
- AutoMod card shows all-caps, name filter, and verify gate status (13 rows total)
- Activity feed icons and verbs for name_filter, verified_gate, phishing

**API**:
- `/automod/summary` now includes allcaps, name_filter, verify_gate fields
- API version bumped to 3.0.0

---

## [2.9.0] -- 2026-07-08

### Phase 3: Severity profiles (toggleable automod presets)

**Profile system**:
- Named sets of automod thresholds that override guild config values on the fly
- Three built-in profiles ship with every guild:
  - **normal** -- baseline thresholds (default on every server)
  - **strict** -- lower thresholds, faster violation escalation
  - **raid** -- aggressive settings; all filters enabled, very low thresholds
- Custom profiles can be created by snapshotting the current config
- Switching profiles takes effect instantly (no restart, no re-sync)
- Profile overrides are merged onto guild_config via `db.get_effective_config()`

**Slash commands** (`/profile` group):
- `/profile switch <name>` -- activate a profile
- `/profile list` -- view all available profiles with override previews
- `/profile view <name>` -- see full override details for a profile
- `/profile create <name>` -- snapshot current settings into a new custom profile
- `/profile delete <name>` -- remove a custom profile (built-ins cannot be deleted)

**Automatic raid profile activation**:
- When lockdown triggers (auto or manual), the bot switches to the "raid" profile
- The previous profile name is saved in `profile_before_raid`
- When lockdown lifts (auto or manual), the previous profile is restored
- Lockdown and unlock embeds now show profile switch information

**Setup hub**:
- New Profiles panel with a dropdown to switch the active profile
- Shows all profiles with override previews and active indicator
- Hub embed now shows the active profile name in the Raid section

**API**:
- `GET /profiles` -- list all profiles with active indicator
- `PUT /profiles/active` -- switch the active profile from the dashboard
- `/automod/summary` now includes `active_profile`

**Dashboard**:
- AutoMod card shows the active profile name
- PROFILE_SWITCH action in activity feed

**Automod pipeline**:
- `on_message` now reads config via `get_effective_config()` which merges profile overrides
- `/automod status` shows the active profile

---

## [2.8.0] -- 2026-07-08

### Phase 2: Staff utility (timed bans, advanced purge)

**Timed bans**:
- `/tempban @user 7d [reason]` -- temporarily ban a member with automatic unban
- New `timed_bans` table tracks guild_id, user_id, unban_at, reason, banned_by
- Auto-unban loop checks every 60 seconds for expired bans
- Timed bans clear saved roles so unbanned users get a fresh start (no role restore)
- TempBan button added to the mod panel (GeneralPanelView) with a modal for username, duration, reason
- `GET /timed-bans` API endpoint for dashboard display
- TEMPBAN and auto-UNBAN actions logged to mod_logs and #mod-log channel
- `/history` shows TEMPBAN entries with the duration icon

**Advanced purge**:
- `/purge` upgraded with four optional filters that stack:
  - `user` -- only delete messages from a specific member
  - `contains` -- only delete messages containing specific text (case-insensitive)
  - `bots_only` -- only delete messages from bots
  - `max_age` -- only delete messages newer than a duration (e.g. 1h, 30m, 2d)
- Scan limit raised from 100 to 200 messages
- Filter summary shown in the confirmation message

---

## [2.7.0] -- 2026-07-08

### Phase 1: Content pipeline (anti-phishing, message length, slowmode)

All new filters feed into the violation engine from v2.6.

**Anti-phishing link scanning**:
- Every URL in a message is checked against the SinkingYachts phishing database (free API, no key required)
- Phishing links are deleted immediately and record a "phishing" violation
- Enabled by default; toggle with `/automod antiphish` or `/setup` > Content Filters
- Uses a single aiohttp session per check with host deduplication
- Fails open on API timeout (message is not blocked if the API is down)

**Message length filter**:
- Configurable min and max character thresholds per guild
- Messages outside the range are deleted and record a "message_length" violation
- Empty messages (attachments only) skip the min-length check
- `/automod max_length` / `/automod min_length` slash commands
- Configurable via `/setup` > Content Filters panel

**Per-channel slowmode enforcement**:
- Bot-enforced rate limiting: 1 message per user per channel every N seconds
- Independent of Discord's built-in slowmode (bot-level enforcement)
- Can target specific channels or apply to all channels
- `/automod slowmode` / `slowmode_interval` / `slowmode_channel` slash commands
- Configurable via `/setup` > Content Filters panel

**Setup hub**:
- New Content Filters panel with toggles for anti-phishing, slowmode, and threshold editor
- Hub embed now shows anti-phishing and slowmode status

**Dashboard**:
- AutoMod card now shows anti-phishing, message length, and slowmode status

**`/automod status` updated**:
- Now shows anti-phishing, message length limits, and slowmode settings

---

## [2.6.0] -- 2026-07-08

### Phase 0: Foundation (violation engine, role persistence, word lists, timed bans, advanced purge)

**Violation counter engine** (the foundation everything else plugs into):
- New `violations` table tracks named violations per user with timestamps
- Configurable threshold + sliding window: e.g. 5 violations in 60 minutes = auto-jail
- All automod triggers (spam, links, invites, word lists) now feed violations instead of punishing directly
- Violations escalate to jail. Only raids escalate to ban.
- `/violations check @user` -- view a user's active violation count and recent history
- `/violations clear @user` -- clear all violations for a user
- `/violations threshold` / `/violations duration` -- configure escalation settings
- Violations panel added to `/setup` configuration hub
- `GET /violations/summary` and `GET /violations/{user_id}` API endpoints
- Cleanup loop removes violation records older than 30 days

**Word list filtering**:
- New `word_lists` table with named lists of banned words per guild
- Whole-word matching for single words, substring matching for multi-word phrases
- `/automod wordlist` -- toggle word list filtering on/off
- `/automod wordlist_add` / `wordlist_remove` / `wordlist_view` / `wordlist_delete` -- manage lists
- `GET /word-lists` API endpoint
- Word list violations feed into the violation engine

**Role persistence**:
- New `member_roles` table snapshots every member's roles on leave (`on_member_remove`)
- On rejoin, roles are automatically restored for kicks, voluntary leaves, and softbans
- Banned users get a fresh start: no role restore after unban + rejoin
- Configurable via `/setup` > Violations panel or `role_persist_enabled` config key
- Replaces and extends the previous softban-only role restore

**Timed bans**:
- `/tempban @user 7d` -- temporarily ban a member with auto-unban
- New `timed_bans` table with auto-unban loop (checks every 60 seconds)
- Timed bans clear saved roles so unbanned users start fresh
- `GET /timed-bans` API endpoint
- All timed ban/unban actions logged to mod-log and mod_logs table

**Advanced purge**:
- `/purge` now supports filters: `user`, `contains`, `bots_only`, `max_age`
- Scan limit raised from 100 to 200 messages
- Filters stack (e.g. purge 50 messages from @user containing "spam" newer than 1h)

**Raid default changed to ban**:
- `raid_active_action` default changed from `kick` to `ban`
- Raid joiners are now banned by default (configurable back to kick via `/raidcfg action` or `/setup`)
- Raid bans now logged to mod_logs DB for role persistence ban detection

**Automod rewired to violation pipeline**:
- Spam detection, link filter, invite filter all now record violations instead of directly muting/kicking
- Message deletion still happens immediately; punishment is handled by the violation engine
- All automod actions logged as VIOLATION entries in mod_logs for dashboard visibility

**Dashboard + API**:
- Automod summary endpoint now includes word list status, violation thresholds, and role persistence
- New violations summary and per-user violation detail endpoints
- Timed bans endpoint for dashboard display

**Setup hub**:
- New Violations panel with threshold editor and role persistence toggle
- AutoMod summary in hub now shows word list status

---

## [2.5.0] -- 2026-07-08

### Added -- Dashboard becomes fully operational

Previously the dashboard was mostly a read-only monitor. In v2.5 every existing page gained operational depth and the API grew to support it.

**Backend -- 13 new endpoints:**
- `GET  /health` -- bot uptime, latency, memory, guild count, member total, ready state.
- `GET  /warns/trends?days=30` -- warns per day for the last N days (chart data).
- `GET  /top-offenders?limit=5` -- users with the most active warns.
- `GET  /automod/summary` -- quick AutoMod on/off dashboard tile.
- `GET  /config-schema` -- sectioned form definition for the editor.
- `GET  /config` -- full guild_config as a flat dict.
- `PUT  /config` -- partial update over any editable columns (validated).
- `POST /warns` -- queues an `add_warn` action.
- `PUT  /notes/{note_id}` -- edit note content in place.
- `GET  /users/search?q=` -- quick member lookup for filters and add-modals.
- `GET  /tickets/{ticket_id}` -- full ticket detail.
- `GET  /tickets/{ticket_id}/transcript` -- messages list for inline viewer.
- `POST /tickets/{ticket_id}/reply` -- queues a `ticket_reply` action.
- `POST /tickets/{ticket_id}/close` -- queues a `close_ticket` action.

**Backend -- 3 new action handlers in `bot.py`:**
- `add_warn` -- insert warn row, DM user, log to `#mod-log`.
- `ticket_reply` -- DM the ticket opener + echo to the ticket channel + log to DB.
- `close_ticket` -- invokes the existing `_close_ticket` helper so behaviour matches the `/close` slash command.

**Frontend -- page rewrites:**
- **Dashboard** -- added 30-day warns trend line chart, top offenders card, AutoMod status tile, and a bot health card (uptime / latency / memory / guilds).
- **Configuration** -- sectioned editor with tabs across 7 groups covering ~60 fields with proper labels, hints, and typed inputs (text / number / bool toggle / select / json list). Save/discard flow with dirty-change tracking. Bot Messages editor and Post-as-Bot composer preserved.
- **Warns** -- search box, active-only toggle, `+ Add warn` modal with type-ahead user search.
- **Notes** -- search box, `+ Add note` modal, inline **Edit** button per note with save/cancel.
- **Mod Logs** -- Action / User contains / From / To filter grid, expandable detail rows with full metadata, **Export CSV** button.
- **Tickets** -- click any open ticket to view inline transcript. Reply (anonymous or named) from the web. Close from the web.
- **Self-Roles** -- category builder with live preview (unchanged).
- **Setup** -- guided mirror of `/setup` (unchanged).

---

## [2.2.0] -- 2026-07-05

### Added
- Honeypot channels: `/honeypot add`, `remove`, `list`
- Auto-ban on any non-staff message in a honeypot channel

---

## [2.1.0] -- 2026-07-04

### Added
- Full AutoMod system: spam, links, invites, immune roles
- Raid detection and lockdown

---

## [2.0.0] -- 2026-07-03

### Added
- Web dashboard with REST API
- Starboard, streamer alerts, react-role messages, reminders, forum threads

---

## [1.9.0] -- 2026-07-02

### Added
- Initial release: setup wizard, modmail, moderation, warns, jail, notes, reports, self-roles
