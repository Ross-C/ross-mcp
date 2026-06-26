"""Base Enchant API service — shared logic for all Enchant helpdesk instances.

Each concrete service (CBS, RCSC, etc.) subclasses this with its own
API key, site, and user identity.
"""

import httpx


class EnchantBaseService:
    def __init__(self, api_key: str, site: str, user_id: str, label: str):
        self.api_key = api_key
        self.site = site
        self.user_id = user_id
        self.label = label
        self.base_url = f"https://{site}.enchant.com/api/v1" if site else ""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.site)

    async def list_tickets(self, state: str = "open", per_page: int = 20) -> dict:
        """List support tickets filtered by state."""
        try:
            async with httpx.AsyncClient(auth=(self.api_key, "X"), timeout=15) as client:
                params = {
                    "state": state,
                    "sort": "-updated_at",
                    "per_page": per_page,
                    "embed": "customer,user",
                }
                resp = await client.get(f"{self.base_url}/tickets", params=params)
                resp.raise_for_status()
                tickets = resp.json()

                return {
                    "tickets": [
                        {
                            "id": t["id"],
                            "subject": t.get("subject", ""),
                            "customer": _format_customer(t.get("customer")),
                            "state": t.get("state"),
                        }
                        for t in tickets
                    ],
                    "count": len(tickets),
                    "state_filter": state,
                }
        except httpx.HTTPStatusError as e:
            return {"error": f"Enchant API error: {e.response.status_code} {e.response.text[:200]}"}
        except Exception as e:
            return {"error": f"Failed to list {self.label} tickets: {e}"}

    async def close_ticket(self, ticket_id: str) -> dict:
        """Close a support ticket."""
        try:
            async with httpx.AsyncClient(auth=(self.api_key, "X"), timeout=15) as client:
                resp = await client.patch(
                    f"{self.base_url}/tickets/{ticket_id}",
                    json={"state": "closed"},
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                return {"id": ticket_id, "status": "closed"}
        except httpx.HTTPStatusError as e:
            return {"error": f"Enchant API error: {e.response.status_code} {e.response.text[:200]}"}
        except Exception as e:
            return {"error": f"Failed to close {self.label} ticket: {e}"}

    async def get_ticket(self, ticket_id: str) -> dict:
        """Get full ticket details including messages."""
        try:
            async with httpx.AsyncClient(auth=(self.api_key, "X"), timeout=15) as client:
                resp = await client.get(
                    f"{self.base_url}/tickets/{ticket_id}",
                    params={"embed": "customer,user,messages,labels"},
                )
                resp.raise_for_status()
                t = resp.json()

                messages = []
                for m in t.get("messages", []):
                    messages.append({
                        "id": m.get("id"),
                        "type": m.get("type"),
                        "direction": m.get("direction"),
                        "from": m.get("from") or m.get("from_name"),
                        "body": m.get("body", ""),
                        "created_at": m.get("created_at"),
                    })

                return {
                    "id": t["id"],
                    "subject": t.get("subject", ""),
                    "customer": _format_customer(t.get("customer")),
                    "reply_to": t.get("reply_to", ""),
                    "reply_cc": t.get("reply_cc", ""),
                    "assigned_to": _format_user(t.get("user")),
                    "state": t.get("state"),
                    "updated_at": t.get("updated_at"),
                    "messages": messages,
                }
        except httpx.HTTPStatusError as e:
            return {"error": f"Enchant API error: {e.response.status_code} {e.response.text[:200]}"}
        except Exception as e:
            return {"error": f"Failed to get {self.label} ticket: {e}"}


def _format_customer(customer: dict | None) -> str | None:
    if not customer:
        return None
    name = customer.get("name") or ""
    email = customer.get("email") or ""
    if name and email:
        return f"{name} <{email}>"
    return name or email or None


def _format_user(user: dict | None) -> str | None:
    if not user:
        return "Unassigned"
    first = user.get("first_name", "")
    last = user.get("last_name", "")
    return f"{first} {last}".strip() or None
