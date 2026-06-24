"""Outlook email service via Microsoft Graph API."""

import asyncio
import json
import logging
from datetime import datetime, timezone

import httpx

from agent.services.outlook_auth import OutlookAuth

logger = logging.getLogger("agent.outlook_mail")

GRAPH_URL = "https://graph.microsoft.com/v1.0"


class OutlookMailService:
    """Email operations via Microsoft Graph."""

    def __init__(self, auth: OutlookAuth):
        self.auth = auth
        self._scheduled_sends: dict[str, asyncio.Task] = {}

    async def search_emails(
        self,
        query: str,
        folder: str | None = None,
        top: int = 10,
    ) -> dict:
        """Search emails using Microsoft Graph $search or $filter.

        Args:
            query: Search query (searches subject, body, sender, etc.)
            folder: Optional folder name (inbox, sentitems, drafts, archive, etc.)
            top: Max results to return.
        """
        headers = await self.auth.get_headers()
        headers["ConsistencyLevel"] = "eventual"

        base = f"{GRAPH_URL}/me"
        if folder:
            base += f"/mailFolders/{folder}"
        url = f"{base}/messages"

        params = {
            "$search": f'"{query}"',
            "$top": str(top),
            "$select": "id,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead,hasAttachments",
            "$orderby": "receivedDateTime desc",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        messages = []
        for msg in data.get("value", []):
            messages.append({
                "id": msg["id"],
                "subject": msg.get("subject", "(no subject)"),
                "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                "to": [r["emailAddress"]["address"] for r in msg.get("toRecipients", [])],
                "date": msg.get("receivedDateTime", ""),
                "preview": msg.get("bodyPreview", ""),
                "is_read": msg.get("isRead", False),
                "has_attachments": msg.get("hasAttachments", False),
            })

        return {"emails": messages, "count": len(messages)}

    async def get_email(self, message_id: str) -> dict:
        """Get full email content by ID."""
        headers = await self.auth.get_headers()
        url = f"{GRAPH_URL}/me/messages/{message_id}"
        params = {
            "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,isRead,hasAttachments,conversationId",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            msg = resp.json()

        return {
            "id": msg["id"],
            "subject": msg.get("subject", "(no subject)"),
            "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
            "to": [r["emailAddress"]["address"] for r in msg.get("toRecipients", [])],
            "cc": [r["emailAddress"]["address"] for r in msg.get("ccRecipients", [])],
            "date": msg.get("receivedDateTime", ""),
            "body": msg.get("body", {}).get("content", ""),
            "body_type": msg.get("body", {}).get("contentType", "text"),
            "is_read": msg.get("isRead", False),
            "has_attachments": msg.get("hasAttachments", False),
            "conversation_id": msg.get("conversationId", ""),
        }

    async def get_thread(self, conversation_id: str, top: int = 25) -> dict:
        """Get all emails in a conversation thread for summarisation."""
        headers = await self.auth.get_headers()
        url = f"{GRAPH_URL}/me/messages"
        params = {
            "$filter": f"conversationId eq '{conversation_id}'",
            "$top": str(top),
            "$select": "id,subject,from,toRecipients,receivedDateTime,bodyPreview,body",
            "$orderby": "receivedDateTime asc",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        messages = []
        for msg in data.get("value", []):
            messages.append({
                "id": msg["id"],
                "subject": msg.get("subject", "(no subject)"),
                "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
                "to": [r["emailAddress"]["address"] for r in msg.get("toRecipients", [])],
                "date": msg.get("receivedDateTime", ""),
                "preview": msg.get("bodyPreview", ""),
                "body": msg.get("body", {}).get("content", ""),
            })

        return {"messages": messages, "count": len(messages)}

    async def create_draft(
        self,
        subject: str,
        body: str,
        to: list[str],
        cc: list[str] | None = None,
        body_type: str = "HTML",
    ) -> dict:
        """Create a draft email."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        email_data = {
            "subject": subject,
            "body": {"contentType": body_type, "content": body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        }
        if cc:
            email_data["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_URL}/me/messages",
                headers=headers,
                json=email_data,
            )
            resp.raise_for_status()
            msg = resp.json()

        return {
            "id": msg["id"],
            "subject": msg.get("subject", ""),
            "status": "draft_created",
        }

    async def send_draft(self, message_id: str) -> dict:
        """Send an existing draft."""
        headers = await self.auth.get_headers()

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_URL}/me/messages/{message_id}/send",
                headers=headers,
            )
            resp.raise_for_status()

        return {"id": message_id, "status": "sent"}

    async def send_email(
        self,
        subject: str,
        body: str,
        to: list[str],
        cc: list[str] | None = None,
        body_type: str = "HTML",
    ) -> dict:
        """Create and send an email in one step."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        message = {
            "subject": subject,
            "body": {"contentType": body_type, "content": body},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        }
        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_URL}/me/sendMail",
                headers=headers,
                json={"message": message},
            )
            resp.raise_for_status()

        return {"status": "sent", "subject": subject}

    async def schedule_send(
        self,
        subject: str,
        body: str,
        to: list[str],
        send_at: datetime,
        cc: list[str] | None = None,
        body_type: str = "HTML",
    ) -> dict:
        """Schedule an email to be sent at a future time.

        Creates a draft and schedules a background task to send it.
        """
        draft = await self.create_draft(subject, body, to, cc, body_type)
        message_id = draft["id"]

        # Calculate delay
        now = datetime.now(timezone.utc)
        send_at_utc = send_at if send_at.tzinfo else send_at.replace(tzinfo=timezone.utc)
        delay = (send_at_utc - now).total_seconds()

        if delay <= 0:
            # Send immediately if time has passed
            return await self.send_draft(message_id)

        # Schedule the send
        task = asyncio.create_task(self._delayed_send(message_id, delay))
        self._scheduled_sends[message_id] = task

        return {
            "id": message_id,
            "status": "scheduled",
            "send_at": send_at_utc.isoformat(),
            "subject": subject,
        }

    async def _delayed_send(self, message_id: str, delay: float):
        """Wait and then send a draft."""
        try:
            await asyncio.sleep(delay)
            await self.send_draft(message_id)
            logger.info(f"Scheduled email sent: {message_id}")
        except asyncio.CancelledError:
            logger.info(f"Scheduled send cancelled: {message_id}")
        except Exception as e:
            logger.error(f"Failed to send scheduled email {message_id}: {e}")
        finally:
            self._scheduled_sends.pop(message_id, None)

    async def cancel_scheduled_send(self, message_id: str) -> dict:
        """Cancel a scheduled email send. Draft is kept."""
        task = self._scheduled_sends.pop(message_id, None)
        if task:
            task.cancel()
            return {"id": message_id, "status": "cancelled", "draft_kept": True}
        return {"error": f"No scheduled send found for {message_id}"}

    async def archive_email(self, message_id: str) -> dict:
        """Move an email to the Archive folder."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_URL}/me/messages/{message_id}/move",
                headers=headers,
                json={"destinationId": "archive"},
            )
            resp.raise_for_status()
            msg = resp.json()

        return {"id": msg["id"], "status": "archived"}

    async def update_draft(
        self,
        message_id: str,
        subject: str | None = None,
        body: str | None = None,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        body_type: str = "HTML",
    ) -> dict:
        """Update an existing draft email."""
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        update_data = {}
        if subject is not None:
            update_data["subject"] = subject
        if body is not None:
            update_data["body"] = {"contentType": body_type, "content": body}
        if to is not None:
            update_data["toRecipients"] = [{"emailAddress": {"address": addr}} for addr in to]
        if cc is not None:
            update_data["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.patch(
                f"{GRAPH_URL}/me/messages/{message_id}",
                headers=headers,
                json=update_data,
            )
            resp.raise_for_status()
            msg = resp.json()

        return {
            "id": msg["id"],
            "subject": msg.get("subject", ""),
            "status": "draft_updated",
        }
