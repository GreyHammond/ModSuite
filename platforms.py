"""
Live-status providers.

The streamer cog was written against Twitch only, with the username column and
every embed hardcoded to it. This module puts a common interface in front of
each platform so the cog can ask one question -- "who is live?" -- without
caring who hosts the stream.

Every provider returns the same shape, keyed by lowercased username:

    {"title": str, "game": str, "url": str,
     "thumbnail": str | None, "viewers": int | None}

Providers fail closed. A platform being down, rate limited, or blocking us
returns an empty dict, which reads as "nobody is live" rather than raising and
killing the poll loop for every other platform.
"""
import json
import logging
import os
import re
from typing import Iterable

import aiohttp

log = logging.getLogger("ModSuite.platforms")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

PLATFORMS = ("twitch", "youtube", "kick", "rumble")

PLATFORM_LABELS = {
    "twitch":  "Twitch",
    "youtube": "YouTube",
    "kick":    "Kick",
    "rumble":  "Rumble",
}

PLATFORM_COLORS = {
    "twitch":  0x9146FF,
    "youtube": 0xFF0000,
    "kick":    0x53FC18,
    "rumble":  0x85C742,
}


def channel_url(platform: str, username: str) -> str:
    p = (platform or "twitch").lower()
    if p == "youtube":
        # Accept a handle, a UC... channel id, or a bare name
        if username.startswith("UC"):
            return f"https://www.youtube.com/channel/{username}"
        handle = username if username.startswith("@") else f"@{username}"
        return f"https://www.youtube.com/{handle}"
    if p == "kick":
        return f"https://kick.com/{username}"
    if p == "rumble":
        return f"https://rumble.com/c/{username}"
    return f"https://twitch.tv/{username}"


class BaseProvider:
    name = "base"

    async def get_live(self, usernames: Iterable[str]) -> dict[str, dict]:
        raise NotImplementedError


# ── Twitch ───────────────────────────────────────────────────────────────────

class TwitchProvider(BaseProvider):
    """Helix API. Needs TWITCH_CLIENT_ID and TWITCH_CLIENT_SECRET."""
    name = "twitch"

    def __init__(self):
        self._token: str | None = None
        self.client_id = os.getenv("TWITCH_CLIENT_ID", "")
        self.client_secret = os.getenv("TWITCH_CLIENT_SECRET", "")

    async def _get_token(self) -> str | None:
        if self._token:
            return self._token
        if not (self.client_id and self.client_secret):
            return None
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    "https://id.twitch.tv/oauth2/token",
                    params={"client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "grant_type": "client_credentials"},
                ) as r:
                    if r.status != 200:
                        return None
                    self._token = (await r.json()).get("access_token")
                    return self._token
        except aiohttp.ClientError as e:
            log.warning(f"Twitch token failed: {e}")
            return None

    async def get_live(self, usernames: Iterable[str]) -> dict[str, dict]:
        names = [u.lower() for u in usernames if u]
        if not names:
            return {}
        token = await self._get_token()
        if not token:
            return {}
        out: dict[str, dict] = {}
        try:
            async with aiohttp.ClientSession() as s:
                # Helix caps at 100 logins per call
                for i in range(0, len(names), 100):
                    chunk = names[i:i + 100]
                    async with s.get(
                        "https://api.twitch.tv/helix/streams",
                        params=[("user_login", n) for n in chunk],
                        headers={"Client-ID": self.client_id,
                                 "Authorization": f"Bearer {token}"},
                    ) as r:
                        if r.status == 401:
                            self._token = None
                            return {}
                        if r.status != 200:
                            continue
                        for st in (await r.json()).get("data", []):
                            login = st["user_login"].lower()
                            thumb = (st.get("thumbnail_url") or "").replace(
                                "{width}", "640").replace("{height}", "360")
                            out[login] = {
                                "title": st.get("title", ""),
                                "game": st.get("game_name", ""),
                                "url": f"https://twitch.tv/{login}",
                                "thumbnail": thumb or None,
                                "viewers": st.get("viewer_count"),
                            }
        except aiohttp.ClientError as e:
            log.warning(f"Twitch poll failed: {e}")
            return {}
        return out


# ── YouTube ──────────────────────────────────────────────────────────────────

class YouTubeProvider(BaseProvider):
    """
    Live detection without burning API quota.

    The Data API's search endpoint costs 100 quota units per call against a
    10,000/day allowance. Polling one channel every 90 seconds is roughly 960
    calls a day, so a single streamer would blow the daily quota ten times
    over. Instead the channel's /live page is fetched and checked for the live
    marker, which is free and unauthenticated. If YOUTUBE_API_KEY is set it is
    used for the title lookup only, where the cost is 1 unit.
    """
    name = "youtube"

    LIVE_MARKERS = ('"isLiveNow":true', '"isLive":true', 'hlsManifestUrl')

    async def get_live(self, usernames: Iterable[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        names = [u for u in usernames if u]
        if not names:
            return {}
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout,
                                             headers={"User-Agent": UA}) as s:
                for name in names:
                    url = channel_url("youtube", name).rstrip("/") + "/live"
                    try:
                        async with s.get(url, allow_redirects=True) as r:
                            if r.status != 200:
                                continue
                            html = await r.text()
                    except (aiohttp.ClientError, UnicodeDecodeError):
                        continue

                    if not any(m in html for m in self.LIVE_MARKERS):
                        continue

                    # An upcoming premiere also carries a live marker; exclude it
                    if '"isUpcoming":true' in html:
                        continue

                    title = ""
                    m = re.search(r'<meta name="title" content="([^"]+)"', html)
                    if m:
                        title = m.group(1)
                    thumb = None
                    m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
                    if m:
                        thumb = m.group(1)
                    watch = str(r.url)

                    out[name.lower()] = {
                        "title": title or "Live on YouTube",
                        "game": "",
                        "url": watch,
                        "thumbnail": thumb,
                        "viewers": None,
                    }
        except aiohttp.ClientError as e:
            log.warning(f"YouTube poll failed: {e}")
            return {}
        return out


# ── Kick ─────────────────────────────────────────────────────────────────────

class KickProvider(BaseProvider):
    """
    Public v2 channel endpoint. Kick sits behind Cloudflare and will
    intermittently return 403 to datacenter IPs; that is treated as offline
    rather than an error, so it never stalls the loop.
    """
    name = "kick"

    async def get_live(self, usernames: Iterable[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        names = [u for u in usernames if u]
        if not names:
            return {}
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout,
                                             headers={"User-Agent": UA,
                                                      "Accept": "application/json"}) as s:
                for name in names:
                    try:
                        async with s.get(
                            f"https://kick.com/api/v2/channels/{name.lower()}"
                        ) as r:
                            if r.status != 200:
                                continue
                            data = await r.json(content_type=None)
                    except (aiohttp.ClientError, json.JSONDecodeError):
                        continue

                    ls = (data or {}).get("livestream")
                    if not ls or not ls.get("is_live"):
                        continue
                    thumb = (ls.get("thumbnail") or {})
                    out[name.lower()] = {
                        "title": ls.get("session_title", ""),
                        "game": ((ls.get("categories") or [{}])[0]).get("name", ""),
                        "url": f"https://kick.com/{name.lower()}",
                        "thumbnail": thumb.get("url") if isinstance(thumb, dict) else thumb,
                        "viewers": ls.get("viewer_count"),
                    }
        except aiohttp.ClientError as e:
            log.warning(f"Kick poll failed: {e}")
            return {}
        return out


# ── Rumble ───────────────────────────────────────────────────────────────────

class RumbleProvider(BaseProvider):
    """
    Rumble has no public status API, so the channel page is checked for a live
    badge. Least reliable of the four; treat it as best effort.
    """
    name = "rumble"

    async def get_live(self, usernames: Iterable[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        names = [u for u in usernames if u]
        if not names:
            return {}
        timeout = aiohttp.ClientTimeout(total=15)
        try:
            async with aiohttp.ClientSession(timeout=timeout,
                                             headers={"User-Agent": UA}) as s:
                for name in names:
                    try:
                        async with s.get(channel_url("rumble", name)) as r:
                            if r.status != 200:
                                continue
                            html = await r.text()
                    except (aiohttp.ClientError, UnicodeDecodeError):
                        continue
                    if 'data-value="LIVE"' not in html and "videostream__badge--live" not in html:
                        continue
                    title = ""
                    m = re.search(r'<meta property="og:title" content="([^"]+)"', html)
                    if m:
                        title = m.group(1)
                    out[name.lower()] = {
                        "title": title or "Live on Rumble",
                        "game": "",
                        "url": channel_url("rumble", name),
                        "thumbnail": None,
                        "viewers": None,
                    }
        except aiohttp.ClientError as e:
            log.warning(f"Rumble poll failed: {e}")
            return {}
        return out


_PROVIDERS: dict[str, BaseProvider] = {
    "twitch":  TwitchProvider(),
    "youtube": YouTubeProvider(),
    "kick":    KickProvider(),
    "rumble":  RumbleProvider(),
}


def get_provider(platform: str) -> BaseProvider | None:
    return _PROVIDERS.get((platform or "twitch").lower())


async def poll_all(by_platform: dict[str, list[str]]) -> dict[str, dict[str, dict]]:
    """
    Query every platform that has streamers registered.

    Returns {platform: {username_lower: info}}. One platform failing does not
    affect the others, since each provider already swallows its own errors.
    """
    results: dict[str, dict[str, dict]] = {}
    for platform, names in by_platform.items():
        provider = get_provider(platform)
        if provider is None or not names:
            continue
        results[platform] = await provider.get_live(names)
    return results
