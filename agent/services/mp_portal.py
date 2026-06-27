"""MP Portal API service — development task management."""

import logging
import os

import httpx

logger = logging.getLogger("agent.mp_portal")


class MPPortalService:
    def __init__(self):
        self.base_url = os.getenv("MP_PORTAL_API_URL", "").rstrip("/")
        self.api_token = os.getenv("MP_PORTAL_API_TOKEN", "")
        self.api_base = f"{self.base_url}/api/portal/v1"

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_token)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

    async def list_projects(self) -> dict:
        """List all projects with id, name, prefix, and customer."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.api_base}/projects", headers=self._headers())
            resp.raise_for_status()
            return resp.json()

    async def match_project(self, alias: str) -> dict:
        """Match a project by folder alias or fuzzy name."""
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{self.api_base}/projects/match",
                headers=self._headers(),
                json={"alias": alias},
            )
            resp.raise_for_status()
            return resp.json()

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
                          due_date: str | None = None, chargeable: bool = False) -> dict:
        """Create a new development task on a project."""
        payload: dict = {"project_id": project_id, "title": title}
        if description:
            payload["description"] = description
        if due_date:
            payload["due_date"] = due_date
        if chargeable:
            payload["chargeable"] = True
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
