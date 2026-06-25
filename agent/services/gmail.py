"""Gmail service via Google Gmail API.

Supports: search, read, create draft, archive. No sending.
"""

import base64
import logging
from email.mime.text import MIMEText

import httpx

from agent.services.google_auth import GoogleAuth

logger = logging.getLogger("agent.gmail")

GMAIL_URL = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailService:
    """Gmail operations via Google API."""

    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    async def search_emails(
        self,
        query: str,
        max_results: int = 10,
    ) -> dict:
        """Search Gmail messages.

        Args:
            query: Gmail search query (same syntax as Gmail search box)
            max_results: Max results to return
        """
        headers = await self.auth.get_headers()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GMAIL_URL}/messages",
                headers=headers,
                params={"q": query, "maxResults": max_results},
            )
            resp.raise_for_status()
            data = resp.json()

        message_ids = [m["id"] for m in data.get("messages", [])]
        if not message_ids:
            return {"emails": [], "count": 0}

        # Fetch metadata for each message
        messages = []
        async with httpx.AsyncClient(timeout=30) as client:
            for msg_id in message_ids:
                resp = await client.get(
                    f"{GMAIL_URL}/messages/{msg_id}",
                    headers=headers,
                    params={"format": "metadata", "metadataHeaders": "Subject,From,To,Date"},
                )
                resp.raise_for_status()
                msg = resp.json()
                headers_list = msg.get("payload", {}).get("headers", [])
                header_map = {h["name"].lower(): h["value"] for h in headers_list}
                messages.append({
                    "id": msg["id"],
                    "thread_id": msg.get("threadId", ""),
                    "subject": header_map.get("subject", "(no subject)"),
                    "from": header_map.get("from", ""),
                    "to": header_map.get("to", ""),
                    "date": header_map.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                    "label_ids": msg.get("labelIds", []),
                })

        return {"emails": messages, "count": len(messages)}

    async def get_email(self, message_id: str) -> dict:
        """Get full email content by ID."""
        headers = await self.auth.get_headers()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GMAIL_URL}/messages/{message_id}",
                headers=headers,
                params={"format": "full"},
            )
            resp.raise_for_status()
            msg = resp.json()

        headers_list = msg.get("payload", {}).get("headers", [])
        header_map = {h["name"].lower(): h["value"] for h in headers_list}

        body = self._extract_body(msg.get("payload", {}))

        return {
            "id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "subject": header_map.get("subject", "(no subject)"),
            "from": header_map.get("from", ""),
            "to": header_map.get("to", ""),
            "cc": header_map.get("cc", ""),
            "date": header_map.get("date", ""),
            "body": body,
            "snippet": msg.get("snippet", ""),
            "label_ids": msg.get("labelIds", []),
        }

    async def get_thread(self, thread_id: str) -> dict:
        """Get all messages in a Gmail thread."""
        headers = await self.auth.get_headers()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GMAIL_URL}/threads/{thread_id}",
                headers=headers,
                params={"format": "full"},
            )
            resp.raise_for_status()
            thread = resp.json()

        messages = []
        for msg in thread.get("messages", []):
            headers_list = msg.get("payload", {}).get("headers", [])
            header_map = {h["name"].lower(): h["value"] for h in headers_list}
            body = self._extract_body(msg.get("payload", {}))
            messages.append({
                "id": msg["id"],
                "subject": header_map.get("subject", "(no subject)"),
                "from": header_map.get("from", ""),
                "to": header_map.get("to", ""),
                "date": header_map.get("date", ""),
                "body": body,
                "snippet": msg.get("snippet", ""),
            })

        return {"messages": messages, "count": len(messages)}

    async def create_draft(
        self,
        subject: str,
        body: str,
        to: list[str],
        cc: list[str] | None = None,
        body_type: str = "html",
    ) -> dict:
        """Create a Gmail draft. NEVER sends."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        subtype = "html" if body_type.lower() == "html" else "plain"
        mime = MIMEText(body, subtype)
        mime["to"] = ", ".join(to)
        mime["subject"] = subject
        if cc:
            mime["cc"] = ", ".join(cc)

        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GMAIL_URL}/drafts",
                headers=headers,
                json={"message": {"raw": raw}},
            )
            resp.raise_for_status()
            draft = resp.json()

        return {
            "id": draft["id"],
            "message_id": draft.get("message", {}).get("id", ""),
            "status": "draft_created",
        }

    async def archive_email(self, message_id: str) -> dict:
        """Archive a Gmail message (remove from Inbox)."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GMAIL_URL}/messages/{message_id}/modify",
                headers=headers,
                json={"removeLabelIds": ["INBOX"]},
            )
            resp.raise_for_status()

        return {"id": message_id, "status": "archived"}

    async def list_labels(self) -> dict:
        """List all Gmail labels."""
        headers = await self.auth.get_headers()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{GMAIL_URL}/labels", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        labels = [
            {"id": l["id"], "name": l["name"], "type": l.get("type", "")}
            for l in data.get("labels", [])
        ]
        return {"labels": labels, "count": len(labels)}

    @staticmethod
    def _extract_body(payload: dict) -> str:
        """Extract the body text from a Gmail message payload."""
        # Try direct body
        body_data = payload.get("body", {}).get("data")
        if body_data:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

        # Try multipart
        for part in payload.get("parts", []):
            mime_type = part.get("mimeType", "")
            if mime_type == "text/html":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if mime_type == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            # Nested multipart
            if part.get("parts"):
                result = GmailService._extract_body(part)
                if result:
                    return result

        return ""
