"""
RSS feeds -- new articles into Discord.

Any RSS or Atom feed works: Substack, WordPress, YouTube channel feeds, most
CMS output, and the agenda feeds many municipal sites publish.

Parsing uses the standard library rather than adding feedparser. Python's
ElementTree does not fetch external entities, so a hostile feed cannot use an
XXE to read local files; it can still be malformed, which is caught and
recorded against the feed rather than killing the poll for every other feed.

Each new item posts an embed and, optionally, opens a thread on it, so
discussion of a story lives with the story instead of scattering into general.
"""
import asyncio
import html
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

import database as db
from config import FOOTER_BRAND, BRAND_COLOR

log = logging.getLogger("ModSuite.rss")

# Substack and most Cloudflare-fronted hosts reject non-browser User-Agents
# with a 403 before the feed is ever served. A polite self-identifying UA is
# the well-mannered choice and it simply does not work here.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

FEED_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9",
}

NS = {
    "atom":    "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "media":   "http://search.yahoo.com/mrss/",
    "dc":      "http://purl.org/dc/elements/1.1/",
}


def _strip_html(raw: str, limit: int = 400) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _first_image(raw: str) -> str | None:
    m = re.search(r'<img[^>]+src="([^"]+)"', raw or "")
    return m.group(1) if m else None


def parse_feed(xml_text: str) -> list[dict]:
    """
    Return items newest-first. Handles RSS 2.0 and Atom, which covers Substack,
    WordPress, YouTube channel feeds, and most municipal CMS output.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"Malformed feed: {e}") from e

    items: list[dict] = []

    # RSS 2.0
    for node in root.findall(".//item"):
        body = (node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                or node.findtext("description") or "")
        link = node.findtext("link") or ""
        guid = node.findtext("guid") or link
        image = None
        enc = node.find("enclosure")
        if enc is not None and (enc.get("type") or "").startswith("image"):
            image = enc.get("url")
        if image is None:
            thumb = node.find("media:thumbnail", NS) or node.find("media:content", NS)
            if thumb is not None:
                image = thumb.get("url")
        items.append({
            "guid": guid.strip(),
            "title": (node.findtext("title") or "Untitled").strip(),
            "link": link.strip(),
            "summary": _strip_html(body),
            "image": image or _first_image(body),
            "author": (node.findtext("{http://purl.org/dc/elements/1.1/}creator")
                       or node.findtext("author") or "").strip(),
            "published": (node.findtext("pubDate") or "").strip(),
        })

    # Atom
    if not items:
        for node in root.findall("atom:entry", NS):
            link_el = node.find("atom:link", NS)
            link = link_el.get("href") if link_el is not None else ""
            body = (node.findtext("atom:content", "", NS)
                    or node.findtext("atom:summary", "", NS) or "")
            items.append({
                "guid": (node.findtext("atom:id", "", NS) or link).strip(),
                "title": (node.findtext("atom:title", "Untitled", NS) or "Untitled").strip(),
                "link": (link or "").strip(),
                "summary": _strip_html(body),
                "image": _first_image(body),
                "author": (node.findtext("atom:author/atom:name", "", NS) or "").strip(),
                "published": (node.findtext("atom:published", "", NS) or "").strip(),
            })
    return items


async def _fetch_via_curl(url: str) -> str:
    """
    Fetch through the system curl binary.

    Cloudflare fingerprints the TLS handshake, not just the headers. Python's
    ssl module produces a different ClientHello than curl does, so Substack
    returns 403 to aiohttp and 200 to curl even when every header is identical.
    No header change fixes that; a different TLS stack does.
    """
    proc = await asyncio.create_subprocess_exec(
        "curl", "-sL", "--max-time", "25", "--compressed",
        "-H", f"Accept: {FEED_HEADERS['Accept']}",
        "-H", f"Accept-Language: {FEED_HEADERS['Accept-Language']}",
        "-A", UA, url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        detail = (err or b"").decode().strip()
        # -s suppresses curl's own error text, so map the common exit codes
        # rather than raising a blank message.
        codes = {6: "could not resolve host", 7: "could not connect",
                 28: "timed out", 35: "TLS handshake failed",
                 60: "certificate verification failed"}
        raise ValueError(
            f"curl failed: {detail or codes.get(proc.returncode, f'exit {proc.returncode}')}")
    body = out.decode("utf-8", errors="replace")
    if not body.strip():
        raise ValueError("Empty response body.")
    return body


async def fetch_feed(url: str) -> list[dict]:
    timeout = aiohttp.ClientTimeout(total=25)
    async with aiohttp.ClientSession(timeout=timeout,
                                     headers=FEED_HEADERS) as s:
        async with s.get(url, allow_redirects=True) as r:
            if r.status in (403, 503):
                # Almost certainly TLS fingerprinting rather than a real
                # refusal. Retry through curl before giving up.
                try:
                    return parse_feed(await _fetch_via_curl(url))
                except (ValueError, FileNotFoundError, OSError) as e:
                    raise ValueError(
                        f"HTTP {r.status} and the curl fallback also failed "
                        f"({e}). The host may be blocking this server's IP."
                    ) from e
            if r.status == 404:
                raise ValueError(
                    "HTTP 404 -- no feed at that URL. Substack feeds end in "
                    "/feed; YouTube uses /feeds/videos.xml?channel_id=UC...")
            if r.status != 200:
                raise ValueError(f"HTTP {r.status}")
            # Some hosts serve feeds as text/html; read the body regardless
            # rather than trusting the content type.
            return parse_feed(await r.text(errors="replace"))


class RSS(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll_feeds.start()

    def cog_unload(self):
        self.poll_feeds.cancel()

    feed_group = app_commands.Group(name="feed", description="RSS feeds into Discord.")

    @tasks.loop(minutes=15)
    async def poll_feeds(self):
        for feed in db.get_feeds(enabled_only=True):
            try:
                await self._check_feed(feed)
            except Exception as e:
                log.warning(f"Feed '{feed['name']}' failed: {e}")
                db.update_feed(feed["id"], last_error=str(e)[:300],
                               last_checked=datetime.now(timezone.utc).isoformat())
            await asyncio.sleep(2)  # be polite to the host

    @poll_feeds.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def _check_feed(self, feed: dict, announce: bool = True) -> int:
        items = await fetch_feed(feed["url"])
        db.update_feed(feed["id"], last_error="",
                       last_checked=datetime.now(timezone.utc).isoformat())
        if not items:
            return 0

        channel = self.bot.get_channel(int(feed["channel_id"]))
        if channel is None:
            return 0

        # Oldest first so a backlog posts in reading order
        new = [i for i in items if not db.feed_item_seen(feed["id"], i["guid"])]
        new.reverse()

        # First run: record everything without posting, or enabling a feed
        # would dump the entire archive into the channel.
        first_run = not db.recent_feed_items(feed["id"], limit=1)
        posted = 0
        for item in new:
            if first_run or not announce:
                db.mark_feed_item(feed["id"], item["guid"], item["title"])
                continue
            if await self._post_item(channel, feed, item):
                posted += 1
            db.mark_feed_item(feed["id"], item["guid"], item["title"])
            await asyncio.sleep(1)
        return posted

    async def _post_item(self, channel, feed: dict, item: dict) -> bool:
        embed = discord.Embed(
            title=item["title"][:250],
            url=item["link"] or None,
            description=item["summary"] or None,
            colour=BRAND_COLOR,
            timestamp=datetime.now(timezone.utc),
        )
        if item.get("author"):
            embed.set_author(name=item["author"][:200])
        if item.get("image"):
            embed.set_image(url=item["image"])
        embed.set_footer(text=f"{feed['name']} · {FOOTER_BRAND}")

        content = ""
        if feed.get("ping_role_id"):
            content = f"<@&{feed['ping_role_id']}>"

        try:
            msg = await channel.send(content=content or None, embed=embed)
        except discord.HTTPException as e:
            log.warning(f"Feed post failed: {e}")
            return False

        if feed.get("make_threads"):
            try:
                await msg.create_thread(name=item["title"][:95],
                                        auto_archive_duration=10080)
            except discord.HTTPException:
                pass  # forum channels and permissions vary; posting still worked
        return True

    # ── Commands ─────────────────────────────────────────────────────────────
    @feed_group.command(name="add", description="Watch an RSS feed and post new items.")
    @app_commands.describe(name="Label shown on each post",
                           url="Feed URL, e.g. https://example.com/feed",
                           channel="Where new items post",
                           make_threads="Open a discussion thread on each item",
                           ping_role="Role to notify")
    async def feed_add(self, interaction: discord.Interaction, name: str, url: str,
                       channel: discord.TextChannel, make_threads: bool = True,
                       ping_role: discord.Role = None):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        try:
            items = await fetch_feed(url)
        except (ValueError, aiohttp.ClientError) as e:
            return await interaction.followup.send(
                f"Could not read that feed: {e}", ephemeral=True)
        if not items:
            return await interaction.followup.send(
                "That URL parsed but contained no items.", ephemeral=True)

        fid = db.add_feed(str(interaction.guild_id), name, url, str(channel.id),
                          make_threads, str(ping_role.id) if ping_role else "")
        feed = next(f for f in db.get_feeds(str(interaction.guild_id)) if f["id"] == fid)
        await self._check_feed(feed, announce=False)  # seed without spamming

        await interaction.followup.send(
            f"Watching **{name}** in {channel.mention}. Found {len(items)} existing "
            f"item(s), newest *{items[0]['title'][:80]}*. Those are marked as seen, "
            f"so only items published from now on will post.",
            ephemeral=True)

    @feed_group.command(name="list", description="Show watched feeds.")
    async def feed_list(self, interaction: discord.Interaction):
        feeds = db.get_feeds(str(interaction.guild_id))
        if not feeds:
            return await interaction.response.send_message(
                "No feeds. Add one with `/feed add`.", ephemeral=True)
        e = discord.Embed(title="Feeds", colour=BRAND_COLOR)
        for f in feeds:
            status = "on" if f["enabled"] else "off"
            line = f"<#{f['channel_id']}> · {status}"
            if f.get("last_error"):
                line += f"\n⚠ {f['last_error'][:120]}"
            elif f.get("last_checked"):
                line += f"\nchecked {f['last_checked'][:16]}"
            e.add_field(name=f"#{f['id']} {f['name']}", value=line, inline=False)
        e.set_footer(text=FOOTER_BRAND)
        await interaction.response.send_message(embed=e, ephemeral=True)

    @feed_group.command(name="check", description="Poll a feed right now.")
    @app_commands.describe(id="Feed id from /feed list")
    async def feed_check(self, interaction: discord.Interaction, id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        feed = next((f for f in db.get_feeds(str(interaction.guild_id))
                     if f["id"] == id), None)
        if not feed:
            return await interaction.response.send_message(f"No feed #{id}.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            n = await self._check_feed(feed)
        except (ValueError, aiohttp.ClientError) as e:
            return await interaction.followup.send(f"Failed: {e}", ephemeral=True)
        await interaction.followup.send(
            f"Posted {n} new item(s)." if n else "Nothing new.", ephemeral=True)

    @feed_group.command(name="remove", description="Stop watching a feed.")
    @app_commands.describe(id="Feed id from /feed list")
    async def feed_remove(self, interaction: discord.Interaction, id: int):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("Administrator only.", ephemeral=True)
        ok = db.delete_feed(str(interaction.guild_id), id)
        await interaction.response.send_message(
            f"Feed #{id} removed." if ok else f"No feed #{id}.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(RSS(bot))
