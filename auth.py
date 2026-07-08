"""
auth.py -- Discord OAuth2 authentication for ModSuite dashboard.
Protects the API so only staff with the right Discord roles can access it.
Zero cost, no Cloudflare, no third-party services.
"""

import hashlib
import logging
import os
import secrets
import time
from typing import Optional

import httpx
from fastapi import Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

log = logging.getLogger("ModSuite.Auth")

# ---------------------------------------------------------------------------
# Config -- pulled from environment variables (set in .env)
# ---------------------------------------------------------------------------

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv("DISCORD_REDIRECT_URI", "")
MODSUITE_GUILD_ID = os.getenv("MODSUITE_GUILD_ID", "")
ALLOWED_ROLE_NAMES = [
    r.strip()
    for r in os.getenv("DASHBOARD_ALLOWED_ROLES", "Owner,Moderator").split(",")
    if r.strip()
]

SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

# ---------------------------------------------------------------------------
# In-memory session store  (good enough for a single-process bot)
# ---------------------------------------------------------------------------

_sessions: dict[str, dict] = {}


def _create_session(user_data: dict) -> str:
    token = secrets.token_urlsafe(48)
    _sessions[token] = {
        "user": user_data,
        "created": time.time(),
    }
    return token


def _get_session(token: str) -> Optional[dict]:
    sess = _sessions.get(token)
    if sess is None:
        return None
    if time.time() - sess["created"] > SESSION_MAX_AGE:
        _sessions.pop(token, None)
        return None
    return sess


def _delete_session(token: str):
    _sessions.pop(token, None)


# ---------------------------------------------------------------------------
# Discord API helpers
# ---------------------------------------------------------------------------

DISCORD_API = "https://discord.com/api/v10"


async def _exchange_code(code: str) -> Optional[dict]:
    """Exchange an OAuth2 code for an access token."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            log.warning(f"Token exchange failed: {resp.status_code} {resp.text}")
            return None
        return resp.json()


async def _get_user(access_token: str) -> Optional[dict]:
    """Fetch the authenticated user's profile."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DISCORD_API}/users/@me",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            return None
        return resp.json()


async def _get_guild_member(access_token: str, guild_id: str) -> Optional[dict]:
    """Fetch the user's membership in the target guild (requires guilds.members.read scope)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{DISCORD_API}/users/@me/guilds/{guild_id}/member",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            return None
        return resp.json()


# ---------------------------------------------------------------------------
# OAuth2 route handlers  (registered on the FastAPI app by register_auth)
# ---------------------------------------------------------------------------

# We need the bot reference to resolve role IDs to names
_bot_ref = None


def register_auth(app, bot_ref=None):
    """
    Register the /auth/* routes and the session-checking middleware on `app`.
    Call this AFTER app is created but BEFORE the static mount.
    """
    global _bot_ref
    _bot_ref = bot_ref

    # ---- Login page ----

    @app.get("/auth/login")
    async def login_page():
        scope = "identify guilds.members.read"
        state = secrets.token_urlsafe(16)
        url = (
            f"https://discord.com/oauth2/authorize"
            f"?client_id={DISCORD_CLIENT_ID}"
            f"&redirect_uri={DISCORD_REDIRECT_URI}"
            f"&response_type=code"
            f"&scope={scope}"
            f"&state={state}"
        )
        return _login_html(url)

    # ---- OAuth2 callback ----

    @app.get("/auth/callback")
    async def auth_callback(code: str = "", error: str = ""):
        if error or not code:
            return RedirectResponse("/auth/login")

        token_data = await _exchange_code(code)
        if token_data is None:
            return _error_html("Discord login failed. Try again.")

        access_token = token_data.get("access_token")
        if not access_token:
            return _error_html("No access token received.")

        user = await _get_user(access_token)
        if user is None:
            return _error_html("Could not fetch your Discord profile.")

        guild_id = MODSUITE_GUILD_ID
        member = await _get_guild_member(access_token, guild_id)
        if member is None:
            return _error_html("You are not a member of this server.")

        # Check roles -- resolve IDs to names using the bot's guild cache
        member_role_ids = member.get("roles", [])
        has_allowed_role = False

        guild_obj = None
        if _bot_ref and _bot_ref.guilds:
            guild_obj = _bot_ref.get_guild(int(guild_id))

        if guild_obj:
            for role_id in member_role_ids:
                role = guild_obj.get_role(int(role_id))
                if role and role.name in ALLOWED_ROLE_NAMES:
                    has_allowed_role = True
                    break
        else:
            # Fallback: can't resolve names without the bot cache
            log.warning("Bot guild cache not available for role check.")

        if not has_allowed_role:
            return _error_html(
                "Access denied. You need one of these roles: "
                + ", ".join(ALLOWED_ROLE_NAMES)
            )

        # Build session
        session_token = _create_session({
            "id": user["id"],
            "username": user.get("global_name") or user.get("username"),
            "avatar": user.get("avatar"),
            "discriminator": user.get("discriminator", "0"),
        })

        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            key="modsuite_session",
            value=session_token,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response

    # ---- Session info (for the frontend to show who's logged in) ----

    @app.get("/auth/me")
    async def auth_me(request: Request):
        token = request.cookies.get("modsuite_session")
        sess = _get_session(token) if token else None
        if sess is None:
            return JSONResponse({"authenticated": False}, status_code=401)
        return {"authenticated": True, "user": sess["user"]}

    # ---- Logout ----

    @app.get("/auth/logout")
    async def logout(request: Request):
        token = request.cookies.get("modsuite_session")
        if token:
            _delete_session(token)
        response = RedirectResponse("/auth/login", status_code=302)
        response.delete_cookie("modsuite_session")
        return response

    # ---- Middleware: protect everything except /auth/* and /docs ----

    app.add_middleware(AuthMiddleware)

    # ---- Mount static files AFTER auth so /auth/* routes take priority ----

    import os as _os_mount
    _web_dir = _os_mount.path.join(_os_mount.path.dirname(__file__), "web")
    if _os_mount.path.isdir(_web_dir):
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

# Paths that don't require authentication
_PUBLIC_PATHS = {"/auth/login", "/auth/callback", "/auth/logout", "/docs", "/openapi.json", "/redoc"}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Let auth routes through
        if path in _PUBLIC_PATHS or path.startswith("/auth/"):
            return await call_next(request)

        # Check session cookie
        token = request.cookies.get("modsuite_session")
        sess = _get_session(token) if token else None

        if sess is None:
            # API calls get a 401 JSON; browser requests get redirected
            accept = request.headers.get("accept", "")
            if "text/html" in accept or not accept:
                return RedirectResponse("/auth/login", status_code=302)
            return JSONResponse(
                {"error": "Not authenticated. Go to /auth/login"},
                status_code=401,
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# HTML templates (inline so there's no extra file to manage)
# ---------------------------------------------------------------------------


def _login_html(oauth_url: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ModSuite - Staff Login</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #14141C;
    color: #E2E2EE;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .card {{
    background: #1C1C26;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    padding: 48px 40px;
    text-align: center;
    max-width: 380px;
    width: 90%;
  }}
  .brand {{
    color: #D4A843;
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-bottom: 8px;
  }}
  h1 {{
    font-size: 22px;
    font-weight: 600;
    margin-bottom: 8px;
  }}
  .sub {{
    color: #8888A0;
    font-size: 14px;
    margin-bottom: 32px;
    line-height: 1.5;
  }}
  .btn {{
    display: inline-flex;
    align-items: center;
    gap: 10px;
    background: #5865F2;
    color: #fff;
    text-decoration: none;
    padding: 14px 32px;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 600;
    transition: background 0.2s;
  }}
  .btn:hover {{ background: #4752C4; }}
  .btn svg {{ width: 20px; height: 20px; fill: #fff; }}
  .footer {{
    margin-top: 32px;
    color: #8888A0;
    font-size: 12px;
  }}
</style>
</head>
<body>
<div class="card">
  <div class="brand">Hammond Digital Studios</div>
  <h1>ModSuite Dashboard</h1>
  <p class="sub">Staff access only. Log in with your Discord account to continue.</p>
  <a href="{oauth_url}" class="btn">
    <svg viewBox="0 0 24 24"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z"/></svg>
    Log in with Discord
  </a>
  <p class="footer">ModSuite v2.5</p>
</div>
</body>
</html>""")


def _error_html(message: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ModSuite - Access Denied</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #14141C;
    color: #E2E2EE;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
  }}
  .card {{
    background: #1C1C26;
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    padding: 48px 40px;
    text-align: center;
    max-width: 420px;
    width: 90%;
  }}
  h1 {{
    font-size: 20px;
    font-weight: 600;
    color: #E05555;
    margin-bottom: 12px;
  }}
  .msg {{
    color: #8888A0;
    font-size: 14px;
    line-height: 1.6;
    margin-bottom: 28px;
  }}
  a {{
    color: #D4A843;
    text-decoration: none;
    font-size: 14px;
    font-weight: 500;
  }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<div class="card">
  <h1>Access Denied</h1>
  <p class="msg">{message}</p>
  <a href="/auth/login">Try again</a>
</div>
</body>
</html>""", status_code=403)
