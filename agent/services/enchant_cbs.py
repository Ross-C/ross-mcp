"""Enchant API service for CBS support tickets.

Identity: Ross Calvert (r.calvert@cbsnw.uk) on the cbsnw Enchant helpdesk.
This service is scoped exclusively to CBS — a separate service will handle
other Enchant instances to avoid cross-identity issues.
"""

import logging
import os

import httpx

logger = logging.getLogger("agent.enchant_cbs")


class EnchantCBSService:
    def __init__(self):
        self.api_key = os.getenv("ENCHANT_CBS_API_KEY", "")
        self.site = os.getenv("ENCHANT_CBS_SITE", "")
        self.user_id = os.getenv("ENCHANT_CBS_USER_ID", "")
        self.base_url = f"https://{self.site}.enchant.com/api/v1" if self.site else ""

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.site and self.user_id)

    async def list_tickets(
        self,
        state: str = "open",
        per_page: int = 20,
    ) -> dict:
        """List CBS support tickets filtered by state."""
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
                            "reply_to": t.get("reply_to", ""),
                            "assigned_to": _format_user(t.get("user")),
                            "state": t.get("state"),
                            "updated_at": t.get("updated_at"),
                            "summary": (t.get("summary") or "")[:200],
                        }
                        for t in tickets
                    ],
                    "count": len(tickets),
                    "state_filter": state,
                }
        except httpx.HTTPStatusError as e:
            return {"error": f"Enchant API error: {e.response.status_code} {e.response.text[:200]}"}
        except Exception as e:
            return {"error": f"Failed to list CBS tickets: {e}"}

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
            return {"error": f"Failed to get CBS ticket: {e}"}

    async def reply_ticket(self, ticket_id: str, body: str) -> dict:
        """Send an outbound reply on a CBS ticket as Ross Calvert."""
        try:
            async with httpx.AsyncClient(auth=(self.api_key, "X"), timeout=15) as client:
                payload = {
                    "type": "reply",
                    "direction": "out",
                    "body": body,
                    "htmlized": False,
                    "user_id": self.user_id,
                }
                resp = await client.post(
                    f"{self.base_url}/tickets/{ticket_id}/messages",
                    json=payload,
                )
                resp.raise_for_status()
                result = resp.json()

                return {
                    "status": "sent",
                    "ticket_id": ticket_id,
                    "message_id": result.get("id"),
                    "sent_as": "Ross Calvert (CBS)",
                }
        except httpx.HTTPStatusError as e:
            return {"error": f"Enchant API error: {e.response.status_code} {e.response.text[:200]}"}
        except Exception as e:
            return {"error": f"Failed to reply to CBS ticket: {e}"}


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
