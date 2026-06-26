"""Outlook email service via Microsoft Graph API."""

import asyncio
import base64
import json
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

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

        base = f"{GRAPH_URL}/me"
        if folder:
            base += f"/mailFolders/{folder}"
        url = f"{base}/messages"

        params = {
            "$top": str(top),
            "$select": "id,subject,from,toRecipients,receivedDateTime,bodyPreview,isRead,hasAttachments",
        }
        q = query.strip()
        if q:
            # Detect date-based queries and use $filter instead of $search
            import re
            date_match = re.search(r"received\s*(ge|le|gt|lt|eq)\s*['\"]?(\d{4}-\d{2}-\d{2})", q, re.IGNORECASE)
            if date_match:
                op = date_match.group(1)
                date_val = date_match.group(2)
                params["$filter"] = f"receivedDateTime {op} {date_val}T00:00:00Z"
                params["$orderby"] = "receivedDateTime desc"
            else:
                headers["ConsistencyLevel"] = "eventual"
                params["$search"] = f'"{q}"'
        else:
            params["$orderby"] = "receivedDateTime desc"

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

    async def draft_reply(
        self,
        message_id: str,
        body: str,
        cc: list[str] | None = None,
        body_type: str = "HTML",
    ) -> dict:
        """Create a draft reply to an existing email.

        Uses Graph API createReply to keep the reply in-thread,
        then prepends the supplied body to the quoted original message.
        """
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        # Step 1: Create reply draft (Graph populates subject, recipients, thread + quoted body)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_URL}/me/messages/{message_id}/createReply",
                headers=headers,
                json={},
            )
            resp.raise_for_status()
            draft = resp.json()

        draft_id = draft["id"]

        # Step 2: Prepend our reply body to the quoted original (preserves threading)
        quoted_body = draft.get("body", {}).get("content", "")
        combined_body = body + quoted_body

        update_data: dict = {
            "body": {"contentType": body_type, "content": combined_body},
        }
        if cc is not None:
            update_data["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.patch(
                f"{GRAPH_URL}/me/messages/{draft_id}",
                headers=headers,
                json=update_data,
            )
            resp.raise_for_status()
            msg = resp.json()

        return {
            "id": msg["id"],
            "subject": msg.get("subject", ""),
            "to": [r["emailAddress"]["address"] for r in msg.get("toRecipients", [])],
            "status": "reply_draft_created",
        }

    async def send_draft(self, message_id: str) -> dict:
        """Send an existing draft email."""
        headers = await self.auth.get_headers()
        url = f"{GRAPH_URL}/me/messages/{message_id}/send"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers)
            resp.raise_for_status()
        return {"status": "sent", "message_id": message_id}

    async def send_email(
        self,
        subject: str,
        body: str,
        to: list[str],
        cc: list[str] | None = None,
        body_type: str = "HTML",
    ) -> dict:
        """Send an email immediately. Only called when recipients are pre-approved."""
        headers = await self.auth.get_headers()
        email_data: dict = {
            "message": {
                "subject": subject,
                "body": {"contentType": body_type, "content": body},
                "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
            }
        }
        if cc:
            email_data["message"]["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]

        url = f"{GRAPH_URL}/me/sendMail"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, headers=headers, json=email_data)
            resp.raise_for_status()
        return {"status": "sent", "subject": subject, "to": to}

    async def add_attachment(
        self,
        message_id: str,
        file_path: str,
        filename: str | None = None,
    ) -> dict:
        """Add a file attachment to a draft email.

        Args:
            message_id: The draft message ID
            file_path: Absolute path to the file on disk
            filename: Optional display name (defaults to the file's name)
        """
        path = Path(file_path)
        if not path.exists():
            return {"error": f"File not found: {file_path}"}

        if not filename:
            filename = path.name

        content_bytes = base64.b64encode(path.read_bytes()).decode("utf-8")
        # Force octet-stream for uncommon types that email clients can't preview
        guessed = mimetypes.guess_type(str(path))[0]
        safe_types = {"application/pdf", "image/png", "image/jpeg", "image/gif",
                      "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                      "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                      "text/plain", "text/csv"}
        content_type = guessed if guessed in safe_types else "application/octet-stream"

        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        attachment_data = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": filename,
            "contentType": content_type,
            "contentBytes": content_bytes,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_URL}/me/messages/{message_id}/attachments",
                headers=headers,
                json=attachment_data,
            )
            resp.raise_for_status()
            data = resp.json()

        return {
            "id": data.get("id", ""),
            "name": filename,
            "size_bytes": path.stat().st_size,
            "status": "attached",
        }

    async def schedule_send(self, **kwargs) -> dict:
        """BLOCKED — sending is disabled. Use create_draft instead."""
        return {"error": "Sending is disabled. Use create_draft to create a draft, then send manually from Outlook."}

    async def cancel_scheduled_send(self, message_id: str) -> dict:
        """Cancel a scheduled email send. Draft is kept."""
        task = self._scheduled_sends.pop(message_id, None)
        if task:
            task.cancel()
            return {"id": message_id, "status": "cancelled", "draft_kept": True}
        return {"error": f"No scheduled send found for {message_id}"}

    async def move_email(self, message_id: str, destination: str) -> dict:
        """Move an email to a folder.

        Args:
            message_id: The email message ID
            destination: Folder name (inbox, archive, deleteditems, junkemail, etc.)
        """
        headers = await self.auth.get_headers()
        headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_URL}/me/messages/{message_id}/move",
                headers=headers,
                json={"destinationId": destination},
            )
            resp.raise_for_status()
            msg = resp.json()

        return {"id": msg["id"], "status": f"moved_to_{destination}"}

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
            if resp.status_code == 400:
                return {"id": message_id, "status": "already_archived", "message": "Message may have already been archived or deleted"}
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
