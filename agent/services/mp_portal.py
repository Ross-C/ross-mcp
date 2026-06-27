"""MP Portal API service — development task management."""

import json
import logging
import os
import time
from difflib import SequenceMatcher
from pathlib import Path

import httpx

logger = logging.getLogger("agent.mp_portal")

# Cache projects for 10 minutes in memory, persist to disk
CACHE_TTL = 600
CACHE_FILE = Path(__file__).resolve().parent.parent.parent / ".mp_projects_cache.json"


class MPPortalService:
    def __init__(self):
        self.base_url = os.getenv("MP_PORTAL_API_URL", "").rstrip("/")
        self.api_token = os.getenv("MP_PORTAL_API_TOKEN", "")
        self.api_base = f"{self.base_url}/api/portal/v1"
        self._project_cache: list[dict] = []
        self._cache_time: float = 0
        self._load_disk_cache()

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_token)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

    # --- Persistent project cache ---

    def _load_disk_cache(self):
        """Load project cache from disk on startup."""
        if CACHE_FILE.exists():
            try:
                data = json.loads(CACHE_FILE.read_text())
                self._project_cache = data.get("projects", [])
                self._cache_time = data.get("cached_at", 0)
                logger.info(f"Loaded {len(self._project_cache)} projects from disk cache")
            except Exception as e:
                logger.warning(f"Failed to load disk cache: {e}")

    def _save_disk_cache(self):
        """Persist project cache to disk."""
        try:
            CACHE_FILE.write_text(json.dumps({
                "projects": self._project_cache,
                "cached_at": self._cache_time,
            }, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save disk cache: {e}")

    async def _ensure_cache(self):
        """Refresh the project cache if stale. Falls back to disk cache."""
        if self._project_cache and (time.time() - self._cache_time) < CACHE_TTL:
            return
        try:
            data = await self.list_projects()
            projects = data.get("projects", data.get("data", []))
            if isinstance(projects, list) and projects:
                self._project_cache = projects
                self._cache_time = time.time()
                self._save_disk_cache()
                logger.info(f"Cached {len(projects)} projects from MP Portal API")
        except Exception as e:
            logger.warning(f"Failed to refresh project cache from API: {e}")
            if not self._project_cache:
                logger.warning("No cached projects available")

    def _fuzzy_match(self, query: str) -> list[dict]:
        """Match a query against cached projects by name, prefix, or similarity.

        Returns matches sorted by confidence (best first), each with a 'score' field.
        """
        if not self._project_cache:
            return []

        q = query.lower().strip()
        results = []

        for project in self._project_cache:
            name = (project.get("name") or "").lower()
            prefix = (project.get("prefix") or "").lower()
            cust_raw = project.get("customer", "")
            customer = (cust_raw.get("name") if isinstance(cust_raw, dict) else cust_raw or "").lower()

            score = 0.0

            # Exact match on prefix (e.g. "ACHL")
            if q == prefix:
                score = 1.0
            # Exact match on name
            elif q == name:
                score = 1.0
            # Prefix starts with query or query starts with prefix
            elif prefix and (prefix.startswith(q) or q.startswith(prefix)):
                score = 0.9
            # Name contains query
            elif q in name:
                score = 0.85
            # Query contains name
            elif name in q:
                score = 0.8
            # Customer name match
            elif q in customer:
                score = 0.7
            else:
                # Fuzzy similarity on name
                name_sim = SequenceMatcher(None, q, name).ratio()
                # Fuzzy similarity on prefix
                prefix_sim = SequenceMatcher(None, q, prefix).ratio() if prefix else 0
                # Fuzzy on customer
                cust_sim = SequenceMatcher(None, q, customer).ratio() if customer else 0
                score = max(name_sim, prefix_sim, cust_sim)

            if score >= 0.4:
                results.append({**project, "_score": score})

        results.sort(key=lambda x: x["_score"], reverse=True)
        return results

    async def find_project(self, query: str) -> dict:
        """Find a project by name, prefix, or fuzzy match.

        Returns the best match with confidence level, or candidates if ambiguous.
        """
        await self._ensure_cache()
        matches = self._fuzzy_match(query)

        if not matches:
            return {
                "match": None,
                "confidence": "none",
                "message": f"No projects matching '{query}'. Use mp_list_projects to see all available projects.",
            }

        best = matches[0]
        score = best.pop("_score", 0)

        if score >= 0.85:
            return {
                "match": best,
                "confidence": "high",
                "project_id": best.get("id"),
                "project_name": best.get("name"),
            }

        # Ambiguous — return top candidates
        candidates = []
        for m in matches[:5]:
            m.pop("_score", None)
            candidates.append(m)
        return {
            "match": None,
            "confidence": "low",
            "candidates": candidates,
            "message": f"Multiple possible matches for '{query}'. Which project did you mean?",
        }

    # --- API methods ---

    async def list_projects(self) -> dict:
        """List all projects with id, name, prefix, and customer."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/projects", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def match_project(self, alias: str) -> dict:
        """Match a project by folder alias or fuzzy name.

        First tries local cache fuzzy match, falls back to API.
        """
        # Try local fuzzy match first
        await self._ensure_cache()
        if self._project_cache:
            result = await self.find_project(alias)
            if result.get("confidence") == "high":
                return result

        # Fall back to API match
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.api_base}/projects/match",
                    headers=self._headers(),
                    json={"alias": alias},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception:
            # If API fails, return our fuzzy result
            if self._project_cache:
                return await self.find_project(alias)
            raise

    async def list_aliases(self) -> dict:
        """List all saved project aliases."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/projects/aliases", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def save_alias(self, project_id: int, alias: str) -> dict:
        """Save a folder alias for a project."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.api_base}/projects/{project_id}/aliases",
                headers=self._headers(),
                json={"alias": alias},
            )
            resp.raise_for_status()
            return resp.json()

    async def delete_alias(self, alias_id: int) -> dict:
        """Delete a project alias."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.delete(
                f"{self.api_base}/projects/aliases/{alias_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def create_task(self, project_id: int, title: str, description: str | None = None,
                          due_date: str | None = None, chargeable: bool = False,
                          estimated_hours: float | None = None) -> dict:
        """Create a new development task on a project."""
        payload: dict = {"project_id": project_id, "title": title}
        if description:
            payload["description"] = description
        if due_date:
            payload["due_date"] = due_date
        if chargeable:
            payload["chargeable"] = True
        if estimated_hours is not None:
            payload["estimated_hours"] = estimated_hours
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{self.api_base}/tasks", headers=self._headers(), json=payload)
            resp.raise_for_status()
            return resp.json()

    async def update_task_status(self, task_id: int, status: str, chargeable: bool | None = None) -> dict:
        """Update a task's status (in_progress, completed, deployed)."""
        payload: dict = {"status": status}
        if chargeable is not None:
            payload["chargeable"] = chargeable
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(
                f"{self.api_base}/tasks/{task_id}/status",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def resolve_task(self, ref: str) -> dict:
        """Resolve a task by project_task_id (e.g. EL-0186) or title search."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.api_base}/tasks/resolve",
                headers=self._headers(),
                json={"ref": ref},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_task(self, task_id: int) -> dict:
        """Get a single task with full details."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/tasks/{task_id}", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def update_task(self, task_id: int, **kwargs) -> dict:
        """Update task fields (hours, dates, description, etc.)."""
        payload = {k: v for k, v in kwargs.items() if v is not None}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.patch(
                f"{self.api_base}/tasks/{task_id}",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    async def search_tasks(self, query: str) -> dict:
        """Search active tasks by title or task ID."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{self.api_base}/tasks/search",
                headers=self._headers(),
                params={"q": query},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_in_progress_tasks(self) -> dict:
        """List tasks currently in progress."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/tasks/in-progress", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_my_tasks(self) -> dict:
        """Get outstanding tasks assigned to the current user."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/tasks/my", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_overdue_tasks(self) -> dict:
        """Get tasks past their due date that haven't been deployed."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/tasks/overdue", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_recent_tasks(self) -> dict:
        """Get recently created or updated tasks."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/tasks/recent", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_outstanding_summary(self) -> dict:
        """Get total outstanding task count with breakdown by status."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/summary/outstanding", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_outstanding_by_project(self) -> dict:
        """Get outstanding task counts broken down by project."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/summary/outstanding-by-project", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_billable_summary(self) -> dict:
        """Get billable tasks summary — count, hours, rate, and total outstanding."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/summary/billable", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def get_recent_activity(self) -> dict:
        """Get recent activity log across all projects."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/activity/recent", headers=self._headers())
            resp.raise_for_status()
            return resp.json()
