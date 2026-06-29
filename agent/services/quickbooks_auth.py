"""OAuth2 authentication for QuickBooks Online API.

Handles browser-based login, token storage, and background refresh.
Supports multiple companies (realm IDs) with separate token sets.
Same pattern as google_auth.py.
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

logger = logging.getLogger("agent.quickbooks_auth")

# QuickBooks OAuth2 endpoints
AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

SCOPES = ["com.intuit.quickbooks.accounting"]

# Token file lives alongside .env in project root
TOKEN_DIR = Path(__file__).resolve().parent.parent.parent
TOKEN_FILE = TOKEN_DIR / ".quickbooks_tokens.json"

# Refresh token proactively every 3 days (access tokens last 1 hour)
REFRESH_INTERVAL = 3 * 24 * 60 * 60

# API base URLs
SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com"
PRODUCTION_BASE = "https://quickbooks.api.intuit.com"


class QuickBooksAuth:
    """Manages OAuth2 tokens for QuickBooks Online API.

    Supports multiple companies. Each company is identified by its realm_id.
    Tokens are stored per-company in a single JSON file.
    """

    def __init__(self):
        self.client_id = os.getenv("QB_CLIENT_ID", "")
        self.client_secret = os.getenv("QB_CLIENT_SECRET", "")
        self.redirect_port = int(os.getenv("QB_REDIRECT_PORT", "9878"))
        self.redirect_uri = f"http://localhost:{self.redirect_port}/callback"
        self.sandbox = os.getenv("QB_SANDBOX", "true").lower() == "true"

        # {realm_id: {access_token, refresh_token, expires_at, company_name}}
        self._companies: dict[str, dict] = {}
        self._refresh_task: asyncio.Task | None = None

        self._load_tokens()

    @property
    def api_base(self) -> str:
        return SANDBOX_BASE if self.sandbox else PRODUCTION_BASE

    @property
    def is_authenticated(self) -> bool:
        return len(self._companies) > 0 and any(
            c.get("refresh_token") for c in self._companies.values()
        )

    def get_realm_ids(self) -> list[str]:
        """Get all authenticated realm IDs."""
        return list(self._companies.keys())

    def get_company_name(self, realm_id: str) -> str:
        """Get the friendly name for a company."""
        return self._companies.get(realm_id, {}).get("company_name", realm_id)

    def list_companies(self) -> list[dict]:
        """List all authenticated companies."""
        return [
            {"realm_id": rid, "company_name": data.get("company_name", rid)}
            for rid, data in self._companies.items()
        ]

    def _load_tokens(self):
        """Load saved tokens from disk."""
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                self._companies = data.get("companies", {})
                logger.info(f"Loaded QuickBooks tokens for {len(self._companies)} company(ies)")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to load QB tokens: {e}")

    def _save_tokens(self):
        """Persist tokens to disk."""
        TOKEN_FILE.write_text(json.dumps({"companies": self._companies}, indent=2))
        TOKEN_FILE.chmod(0o600)

    def _update_from_response(self, realm_id: str, data: dict, company_name: str | None = None):
        """Update tokens from an OAuth token response."""
        existing = self._companies.get(realm_id, {})
        self._companies[realm_id] = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", existing.get("refresh_token")),
            "expires_at": time.time() + data.get("expires_in", 3600),
            "company_name": company_name or existing.get("company_name", realm_id),
        }
        self._save_tokens()

    async def authorize(self) -> bool:
        """Run the interactive OAuth2 flow. Opens browser for consent."""
        if not self.client_id or not self.client_secret:
            logger.error("QB_CLIENT_ID and QB_CLIENT_SECRET must be set.")
            return False

        auth_result: asyncio.Future = asyncio.get_event_loop().create_future()

        app = web.Application()

        async def callback_handler(request: web.Request):
            code = request.query.get("code")
            realm_id = request.query.get("realmId")
            error = request.query.get("error")
            if error:
                auth_result.set_exception(Exception(f"Auth error: {error}"))
                return web.Response(
                    text="<h2>QuickBooks authentication failed.</h2><p>You can close this tab.</p>",
                    content_type="text/html",
                )
            if code and realm_id:
                auth_result.set_result((code, realm_id))
                return web.Response(
                    text="<h2>QuickBooks authentication successful!</h2><p>You can close this tab.</p>",
                    content_type="text/html",
                )
            return web.Response(text="Missing code or realmId parameter", status=400)

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
                "state": "quickbooks_auth",
            })
            auth_url = f"{AUTH_URL}?{params}"
            logger.info("Opening browser for QuickBooks login...")
            webbrowser.open(auth_url)

            code, realm_id = await asyncio.wait_for(auth_result, timeout=120)

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    TOKEN_URL,
                    headers={"Accept": "application/json"},
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.redirect_uri,
                    },
                    auth=(self.client_id, self.client_secret),
                )
                resp.raise_for_status()
                token_data = resp.json()

            # Fetch company name
            company_name = await self._fetch_company_name(realm_id, token_data["access_token"])
            self._update_from_response(realm_id, token_data, company_name)

            logger.info(f"QuickBooks OAuth2 login successful for {company_name} (realm {realm_id})")
            return True

        except asyncio.TimeoutError:
            logger.error("OAuth login timed out (120s)")
            return False
        except Exception as e:
            logger.error(f"OAuth login failed: {e}")
            return False
        finally:
            await runner.cleanup()

    async def _fetch_company_name(self, realm_id: str, access_token: str) -> str:
        """Fetch the company name from QuickBooks after auth."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{self.api_base}/v3/company/{realm_id}/companyinfo/{realm_id}",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                return resp.json().get("CompanyInfo", {}).get("CompanyName", realm_id)
        except Exception as e:
            logger.warning(f"Could not fetch company name: {e}")
            return realm_id

    async def get_access_token(self, realm_id: str) -> str:
        """Get a valid access token for a specific company, refreshing if needed."""
        company = self._companies.get(realm_id)
        if not company:
            raise Exception(f"No tokens for realm {realm_id}")

        if time.time() >= company.get("expires_at", 0) - 60:
            await self._refresh_access_token(realm_id)

        return self._companies[realm_id]["access_token"]

    async def get_headers(self, realm_id: str) -> dict:
        """Get Authorization headers for QuickBooks API calls."""
        token = await self.get_access_token(realm_id)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _refresh_access_token(self, realm_id: str):
        """Refresh the access token using the refresh token."""
        company = self._companies.get(realm_id, {})
        refresh_token = company.get("refresh_token")
        if not refresh_token:
            raise Exception(f"No refresh token for realm {realm_id}")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                },
                auth=(self.client_id, self.client_secret),
            )
            resp.raise_for_status()
            self._update_from_response(realm_id, resp.json())
            logger.info(f"QuickBooks access token refreshed for realm {realm_id}")

    async def start_background_refresh(self):
        """Start a background task that refreshes tokens for all companies."""
        if self._refresh_task and not self._refresh_task.done():
            return
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    async def _refresh_loop(self):
        """Periodically refresh tokens for all companies."""
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)
            for realm_id in list(self._companies.keys()):
                try:
                    await self._refresh_access_token(realm_id)
                    logger.info(f"Background QB token refresh completed for realm {realm_id}")
                except Exception as e:
                    logger.error(f"Background QB token refresh failed for realm {realm_id}: {e}")
