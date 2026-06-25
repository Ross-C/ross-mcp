"""OAuth2 authentication for Google APIs (Gmail, Calendar).

Handles browser-based login, token storage, and background refresh.
Same pattern as outlook_auth.py.
"""

import asyncio
import json
import logging
import os
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlencode

import httpx
from aiohttp import web

logger = logging.getLogger("agent.google_auth")

# Google OAuth2 endpoints
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar",
]

# Token file lives alongside .env in project root
TOKEN_DIR = Path(__file__).resolve().parent.parent.parent
TOKEN_FILE = TOKEN_DIR / ".google_tokens.json"

# Refresh token proactively every 3 days
REFRESH_INTERVAL = 3 * 24 * 60 * 60


class GoogleAuth:
    """Manages OAuth2 tokens for Google APIs."""

    def __init__(self):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
        self.redirect_port = int(os.getenv("GOOGLE_REDIRECT_PORT", "9877"))
        self.redirect_uri = f"http://localhost:{self.redirect_port}/callback"

        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0
        self._refresh_task: asyncio.Task | None = None

        self._load_tokens()

    @property
    def is_authenticated(self) -> bool:
        return self._refresh_token is not None

    @property
    async def access_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if time.time() >= self._expires_at - 60:
            await self._refresh_access_token()
        return self._access_token

    def _load_tokens(self):
        """Load saved tokens from disk."""
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                self._access_token = data.get("access_token")
                self._refresh_token = data.get("refresh_token")
                self._expires_at = data.get("expires_at", 0)
                logger.info("Loaded saved Google tokens")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load tokens: {e}")

    def _save_tokens(self):
        """Persist tokens to disk."""
        TOKEN_FILE.write_text(json.dumps({
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at,
        }))
        TOKEN_FILE.chmod(0o600)

    def _update_from_response(self, data: dict):
        """Update tokens from an OAuth token response."""
        self._access_token = data["access_token"]
        self._refresh_token = data.get("refresh_token", self._refresh_token)
        self._expires_at = time.time() + data.get("expires_in", 3600)
        self._save_tokens()

    async def authorize(self) -> bool:
        """Run the interactive OAuth2 flow. Opens browser for consent."""
        if not self.client_id or not self.client_secret:
            logger.error("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set.")
            return False

        if self.is_authenticated:
            try:
                await self._refresh_access_token()
                logger.info("Existing Google tokens are valid")
                return True
            except Exception:
                logger.info("Saved tokens expired, starting fresh login")

        auth_code_future: asyncio.Future = asyncio.get_event_loop().create_future()

        app = web.Application()

        async def callback_handler(request: web.Request):
            code = request.query.get("code")
            error = request.query.get("error")
            if error:
                auth_code_future.set_exception(
                    Exception(f"Auth error: {error}")
                )
                return web.Response(
                    text="<h2>Authentication failed.</h2><p>You can close this tab.</p>",
                    content_type="text/html",
                )
            if code:
                auth_code_future.set_result(code)
                return web.Response(
                    text="<h2>Google authentication successful!</h2><p>You can close this tab.</p>",
                    content_type="text/html",
                )
            return web.Response(text="Missing code parameter", status=400)

        app.router.add_get("/callback", callback_handler)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", self.redirect_port)
        await site.start()

        try:
            params = urlencode({
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.redirect_uri,
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",
            })
            auth_url = f"{AUTH_URL}?{params}"
            logger.info("Opening browser for Google login...")
            webbrowser.open(auth_url)

            code = await asyncio.wait_for(auth_code_future, timeout=120)

            async with httpx.AsyncClient() as client:
                resp = await client.post(TOKEN_URL, data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                })
                resp.raise_for_status()
                self._update_from_response(resp.json())

            logger.info("Google OAuth2 login successful")
            return True

        except asyncio.TimeoutError:
            logger.error("OAuth login timed out (120s)")
            return False
        except Exception as e:
            logger.error(f"OAuth login failed: {e}")
            return False
        finally:
            await runner.cleanup()

    async def _refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            raise Exception("No refresh token available")

        async with httpx.AsyncClient() as client:
            resp = await client.post(TOKEN_URL, data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            })
            resp.raise_for_status()
            self._update_from_response(resp.json())
            logger.info("Google access token refreshed")

    async def start_background_refresh(self):
        """Start a background task that refreshes the token every 3 days."""
        if self._refresh_task and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self):
        """Periodically refresh the token to keep it alive."""
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)
            try:
                await self._refresh_access_token()
                logger.info("Background Google token refresh completed")
            except Exception as e:
                logger.error(f"Background Google token refresh failed: {e}")

    async def get_headers(self) -> dict:
        """Get Authorization headers for Google API calls."""
        token = await self.access_token
        return {"Authorization": f"Bearer {token}"}
