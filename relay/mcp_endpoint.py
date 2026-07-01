"""Remote MCP endpoint — exposes tools over streamable-http on the relay.

Mounted at /mcp on the relay. Uses Bearer token auth (same RELAY_API_KEY).
Tools call execute_command() directly — no HTTP round-trip to self.
"""

import json
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import Response as StarletteResponse
from starlette.types import ASGIApp, Receive, Scope, Send

API_KEY = os.getenv("RELAY_API_KEY", "")


# --- Auth middleware ---

class BearerTokenMiddleware:
    """ASGI middleware that checks Bearer token on HTTP requests.

    Passes through lifespan events to the inner app unchanged.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "lifespan":
            # Forward lifespan events (startup/shutdown) to inner app
            await self.app(scope, receive, send)
            return

        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()

            if not API_KEY:
                response = StarletteResponse("Server API key not configured", status_code=500)
                await response(scope, receive, send)
                return

            if not auth.startswith("Bearer ") or auth[7:] != API_KEY:
                response = StarletteResponse("Unauthorized", status_code=401)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)


# --- MCP Server ---

RELAY_HOST = os.getenv("RELAY_PUBLIC_HOST", "ross-mcp-relay.fly.dev")

mcp = FastMCP(
    "Ross Life Admin",
    instructions=(
        "Manage Apple Reminders, Outlook Email & Calendar, Gmail, Google Calendar, "
        "iCloud Calendar (personal), support tickets, and development tasks via local Mac agents.\n\n"
        "EMAIL STYLE (applies to ALL drafts and replies):\n"
        "- Always enrich and polish what the user asks for. Never parrot their words back verbatim. "
        "Take the intent and key points, then write a well-worded, natural email that sounds like "
        "Ross wrote it carefully. Add appropriate context, smooth transitions, and proper phrasing.\n"
        "- Greeting: 'Hi [Name]' for one, 'Hi [Name]/[Name]' for two, 'Hi all' for 3+.\n"
        "- Tone: conversational and direct, not corporate.\n"
        "- NEVER use em dashes or hyphens to join clauses. Use commas or full stops. Dashes look AI-generated.\n"
        "- One thought per paragraph, keep paragraphs short.\n"
        "- UK date format (DD/MM/YYYY).\n"
        "- Sign off: 'Kind regards' then 'Ross' on the next line.\n"
        "- Always use HTML body_type. Wrap in: <div style=\"font-family:Aptos,Arial,Helvetica,sans-serif;"
        "font-size:12pt;color:rgb(0,0,0)\">...</div>. Use <p> tags for paragraphs.\n"
        "- NEVER send emails. Only create drafts. Ross sends manually."
    ),
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[RELAY_HOST, "localhost", "127.0.0.1"],
    ),
)


_execute_command = None
_agents_ref = None


def set_execute_command(fn):
    """Called by relay.py to inject its execute_command function."""
    global _execute_command
    _execute_command = fn


def set_agents(agents_dict):
    """Called by relay.py to inject the agents registry."""
    global _agents_ref
    _agents_ref = agents_dict


async def _send(command_type: str, payload: dict = {}) -> dict:
    """Execute a command via the relay's internal routing."""
    if _execute_command is None:
        raise RuntimeError("execute_command not registered — call set_execute_command first")
    from shared.messages import CommandType
    cmd_type = CommandType(command_type)
    return await _execute_command(cmd_type, payload)


# --- Reminder Tools ---


@mcp.tool()
async def create_reminder(
    title: str,
    notes: str | None = None,
    due_date: str | None = None,
    list_name: str | None = None,
    priority: int = 0,
) -> str:
    """Create an Apple Reminder.

    Args:
        title: The reminder title
        notes: Optional notes/description
        due_date: Optional due date in ISO format (e.g. 2026-06-25T09:00:00)
        list_name: Optional reminder list name (defaults to 'Reminders')
        priority: Priority level: 0=none, 1=low, 5=medium, 9=high
    """
    payload = {"title": title}
    if notes:
        payload["notes"] = notes
    if due_date:
        payload["due_date"] = due_date
    if list_name:
        payload["list_name"] = list_name
    if priority:
        payload["priority"] = priority
    result = await _send("create_reminder", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_reminders(
    list_name: str | None = None,
    include_completed: bool = False,
) -> str:
    """List Apple Reminders.

    Args:
        list_name: Optional filter by reminder list name
        include_completed: Whether to include completed reminders
    """
    payload = {}
    if list_name:
        payload["list_name"] = list_name
    if include_completed:
        payload["include_completed"] = True
    result = await _send("list_reminders", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def complete_reminder(reminder_id: str) -> str:
    """Mark an Apple Reminder as completed.

    Args:
        reminder_id: The ID of the reminder to complete (from list_reminders)
    """
    result = await _send("complete_reminder", {"reminder_id": reminder_id})
    return json.dumps(result, indent=2)


# --- Outlook Email Tools ---


@mcp.tool()
async def search_emails(
    query: str = "",
    folder: str | None = None,
    top: int = 10,
) -> str:
    """Search Outlook emails. If query is empty, lists recent emails.

    IMPORTANT: When asked about new emails, inbox, or "what's in my inbox", always set folder to "inbox".
    Only search all folders when explicitly searching for something specific.

    Args:
        query: Search query (matches subject, body, sender, etc.). Leave empty to list recent emails.
        folder: Folder to search (inbox, sentitems, drafts, archive). Default to "inbox" for new/unread email requests.
        top: Max results (default 10)
    """
    payload: dict = {"query": query, "top": top}
    if folder:
        payload["folder"] = folder
    result = await _send("search_emails", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_email(message_id: str) -> str:
    """Get full content of an Outlook email by ID.

    Args:
        message_id: The email message ID (from search_emails)
    """
    result = await _send("get_email", {"message_id": message_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_email_thread(conversation_id: str, top: int = 25) -> str:
    """Get all emails in a conversation thread (for summarisation).

    Args:
        conversation_id: The conversation ID (from get_email)
        top: Max messages to return (default 25)
    """
    result = await _send("get_thread", {"conversation_id": conversation_id, "top": top})
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_email_draft(
    subject: str,
    body: str,
    to: list[str],
    cc: list[str] | None = None,
    body_type: str = "HTML",
) -> str:
    """Create an Outlook email draft. Always enrich and polish the user's input into a well-worded email in Ross's style. Never use em dashes or hyphens to join clauses. Use HTML with Aptos font wrapper and <p> tags. Sign off with Kind regards / Ross.

    Args:
        subject: Email subject
        body: Email body in HTML. Wrap in <div style="font-family:Aptos,Arial,Helvetica,sans-serif;font-size:12pt;color:rgb(0,0,0)">. Use <p> tags for paragraphs.
        to: List of recipient email addresses
        cc: Optional list of CC addresses
        body_type: Content type — always use HTML
    """
    payload: dict = {"subject": subject, "body": body, "to": to, "body_type": body_type}
    if cc:
        payload["cc"] = cc
    result = await _send("create_draft", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def draft_a_reply(
    message_id: str,
    body: str,
    cc: list[str] | None = None,
    body_type: str = "HTML",
) -> str:
    """Create a draft reply to an existing Outlook email, keeping it in the same thread. Always enrich and polish the user's input into a well-worded reply in Ross's style. Never use em dashes or hyphens to join clauses. Use HTML with Aptos font wrapper and <p> tags. Sign off with Kind regards / Ross.

    The reply is pre-populated with the original recipients and subject.
    You only need to provide the reply body. Does NOT send.

    Args:
        message_id: The message ID of the email to reply to (from search_emails or get_email)
        body: Reply body in HTML. Wrap in <div style="font-family:Aptos,Arial,Helvetica,sans-serif;font-size:12pt;color:rgb(0,0,0)">. Use <p> tags for paragraphs.
        cc: Optional list of CC addresses to add
        body_type: Content type — always use HTML
    """
    payload: dict = {"message_id": message_id, "body": body, "body_type": body_type}
    if cc:
        payload["cc"] = cc
    result = await _send("draft_reply", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_email_draft(
    message_id: str,
    subject: str | None = None,
    body: str | None = None,
    to: list[str] | None = None,
    cc: list[str] | None = None,
    body_type: str = "HTML",
) -> str:
    """Update an existing Outlook email draft.

    Args:
        message_id: The draft message ID
        subject: New subject (optional)
        body: New body (optional)
        to: New recipients (optional)
        cc: New CC list (optional)
        body_type: Content type — HTML (default) or Text
    """
    payload: dict = {"message_id": message_id, "body_type": body_type}
    if subject is not None:
        payload["subject"] = subject
    if body is not None:
        payload["body"] = body
    if to is not None:
        payload["to"] = to
    if cc is not None:
        payload["cc"] = cc
    result = await _send("update_draft", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def send_email_draft(message_id: str) -> str:
    """Send an existing Outlook email draft.

    Args:
        message_id: The draft message ID to send
    """
    result = await _send("send_draft", {"message_id": message_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def send_email(
    subject: str,
    body: str,
    to: list[str],
    cc: list[str] | None = None,
    body_type: str = "HTML",
) -> str:
    """Send an Outlook email immediately. Only works if ALL recipients are in the allowed recipients list (managed on the dashboard Contacts tab). If any recipient is not allowed, use create_email_draft instead.

    Args:
        subject: Email subject
        body: Email body (HTML by default)
        to: List of recipient email addresses
        cc: Optional list of CC addresses
        body_type: Content type — HTML (default) or Text
    """
    from relay.dashboard import is_allowed_recipient
    blocked = [addr for addr in to if not is_allowed_recipient(addr)]
    if blocked:
        return json.dumps({"error": f"Cannot send directly to: {', '.join(blocked)}. Use create_email_draft instead. To allow direct sending, add them as allowed recipients on the dashboard."})
    payload: dict = {"subject": subject, "body": body, "to": to, "body_type": body_type}
    if cc:
        payload["cc"] = cc
    result = await _send("send_email", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def schedule_email(
    subject: str,
    body: str,
    to: list[str],
    send_at: str,
    cc: list[str] | None = None,
    body_type: str = "HTML",
) -> str:
    """Schedule an Outlook email to be sent at a future time.

    Args:
        subject: Email subject
        body: Email body (HTML by default)
        to: List of recipient email addresses
        send_at: When to send, in ISO format (e.g. 2026-06-25T09:00:00)
        cc: Optional list of CC addresses
        body_type: Content type — HTML (default) or Text
    """
    payload: dict = {"subject": subject, "body": body, "to": to, "send_at": send_at, "body_type": body_type}
    if cc:
        payload["cc"] = cc
    result = await _send("schedule_send", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def cancel_scheduled_email(message_id: str) -> str:
    """Cancel a scheduled email send. The draft is kept.

    Args:
        message_id: The scheduled email's message ID
    """
    result = await _send("cancel_scheduled_send", {"message_id": message_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def archive_email(message_id: str) -> str:
    """Move an Outlook email to the Archive folder.

    Args:
        message_id: The email message ID to archive
    """
    result = await _send("archive_email", {"message_id": message_id})
    return json.dumps(result, indent=2)


# --- Outlook Calendar Tools ---


@mcp.tool()
async def list_calendar_events(
    start: str | None = None,
    end: str | None = None,
    top: int = 20,
) -> str:
    """List Outlook calendar events. Defaults to next 7 days if no range given.

    Args:
        start: Start date in ISO format (e.g. 2026-06-24T00:00:00)
        end: End date in ISO format
        top: Max events to return (default 20)
    """
    payload: dict = {"top": top}
    if start:
        payload["start"] = start
    if end:
        payload["end"] = end
    result = await _send("list_events", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_calendar_event(
    subject: str,
    start: str,
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    is_all_day: bool = False,
    timezone_name: str = "Europe/London",
) -> str:
    """Create an Outlook calendar event.

    Args:
        subject: Event title
        start: Start time in ISO format (e.g. 2026-06-25T14:00:00)
        end: End time in ISO format (e.g. 2026-06-25T15:00:00)
        location: Optional location
        body: Optional description (HTML)
        attendees: Optional list of attendee email addresses
        is_all_day: Whether this is an all-day event
        timezone_name: Timezone (default Europe/London)
    """
    payload: dict = {"subject": subject, "start": start, "end": end, "timezone_name": timezone_name, "is_all_day": is_all_day}
    if location:
        payload["location"] = location
    if body:
        payload["body"] = body
    if attendees:
        payload["attendees"] = attendees
    result = await _send("create_event", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_calendar_event(
    event_id: str,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    timezone_name: str = "Europe/London",
) -> str:
    """Update an existing Outlook calendar event.

    Args:
        event_id: The event ID (from list_calendar_events)
        subject: New title (optional)
        start: New start time in ISO format (optional)
        end: New end time in ISO format (optional)
        location: New location (optional)
        body: New description (optional)
        attendees: New attendee list (optional)
        timezone_name: Timezone (default Europe/London)
    """
    payload: dict = {"event_id": event_id, "timezone_name": timezone_name}
    if subject is not None:
        payload["subject"] = subject
    if start is not None:
        payload["start"] = start
    if end is not None:
        payload["end"] = end
    if location is not None:
        payload["location"] = location
    if body is not None:
        payload["body"] = body
    if attendees is not None:
        payload["attendees"] = attendees
    result = await _send("update_event", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def cancel_calendar_event(event_id: str) -> str:
    """Cancel/delete an Outlook calendar event.

    Args:
        event_id: The event ID to cancel
    """
    result = await _send("cancel_event", {"event_id": event_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def find_available_slots(
    start: str,
    end: str,
    duration_minutes: int = 30,
) -> str:
    """Find free time slots in the Outlook calendar.

    Args:
        start: Start of search range in ISO format
        end: End of search range in ISO format
        duration_minutes: Minimum slot duration in minutes (default 30)
    """
    result = await _send("find_available_slots", {
        "start": start,
        "end": end,
        "duration_minutes": duration_minutes,
    })
    return json.dumps(result, indent=2)


@mcp.tool()
async def add_email_attachment(
    message_id: str,
    file_path: str,
    filename: str | None = None,
) -> str:
    """Add a file attachment to an Outlook email draft.

    Args:
        message_id: The draft message ID
        file_path: Absolute path to the file on disk
        filename: Optional display name (defaults to the file's name)
    """
    payload: dict = {"message_id": message_id, "file_path": file_path}
    if filename:
        payload["filename"] = filename
    result = await _send("add_attachment", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def download_email_attachment(
    message_id: str,
    attachment_index: int = 0,
) -> str:
    """Download an attachment from an Outlook email. Returns the file as base64.

    Args:
        message_id: The email message ID (from search_emails or get_email)
        attachment_index: Zero-based index of the attachment to download (default 0, i.e. the first attachment)
    """
    payload: dict = {"message_id": message_id, "attachment_index": attachment_index}
    result = await _send("download_attachment", payload)
    return json.dumps(result, indent=2)


# --- Gmail Tools ---


@mcp.tool()
async def gmail_search(query: str, max_results: int = 10) -> str:
    """Search Gmail emails. Uses Gmail search syntax (e.g. 'from:someone subject:hello is:unread').

    Args:
        query: Gmail search query
        max_results: Max results to return (default 10)
    """
    result = await _send("gmail_search", {"query": query, "max_results": max_results})
    return json.dumps(result, indent=2)


@mcp.tool()
async def gmail_get_email(message_id: str) -> str:
    """Get full content of a Gmail email by ID.

    Args:
        message_id: The Gmail message ID (from gmail_search)
    """
    result = await _send("gmail_get_email", {"message_id": message_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def gmail_get_thread(thread_id: str) -> str:
    """Get all emails in a Gmail thread.

    Args:
        thread_id: The Gmail thread ID (from gmail_get_email)
    """
    result = await _send("gmail_get_thread", {"thread_id": thread_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def gmail_create_draft(
    subject: str,
    body: str,
    to: list[str],
    cc: list[str] | None = None,
    body_type: str = "html",
) -> str:
    """Create a Gmail email draft. Does NOT send.

    Args:
        subject: Email subject
        body: Email body
        to: List of recipient email addresses
        cc: Optional list of CC addresses
        body_type: Content type — html (default) or plain
    """
    payload: dict = {"subject": subject, "body": body, "to": to, "body_type": body_type}
    if cc:
        payload["cc"] = cc
    result = await _send("gmail_create_draft", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def gmail_archive(message_id: str) -> str:
    """Archive a Gmail email (remove from Inbox).

    Args:
        message_id: The Gmail message ID to archive
    """
    result = await _send("gmail_archive", {"message_id": message_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def gmail_list_labels() -> str:
    """List all Gmail labels."""
    result = await _send("gmail_list_labels")
    return json.dumps(result, indent=2)


# --- Google Calendar Tools ---


@mcp.tool()
async def gcal_list_events(
    start: str | None = None,
    end: str | None = None,
    top: int = 20,
) -> str:
    """List Google Calendar events. Defaults to next 7 days if no range given.

    Args:
        start: Start date in ISO format (e.g. 2026-06-24T00:00:00)
        end: End date in ISO format
        top: Max events to return (default 20)
    """
    payload: dict = {"top": top}
    if start:
        payload["start"] = start
    if end:
        payload["end"] = end
    result = await _send("gcal_list_events", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def gcal_create_event(
    subject: str,
    start: str,
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    is_all_day: bool = False,
    timezone_name: str = "Europe/London",
) -> str:
    """Create a Google Calendar event.

    Args:
        subject: Event title
        start: Start time in ISO format (e.g. 2026-06-25T14:00:00)
        end: End time in ISO format (e.g. 2026-06-25T15:00:00)
        location: Optional location
        body: Optional description
        attendees: Optional list of attendee email addresses
        is_all_day: Whether this is an all-day event
        timezone_name: Timezone (default Europe/London)
    """
    payload: dict = {"subject": subject, "start": start, "end": end, "timezone_name": timezone_name, "is_all_day": is_all_day}
    if location:
        payload["location"] = location
    if body:
        payload["body"] = body
    if attendees:
        payload["attendees"] = attendees
    result = await _send("gcal_create_event", payload)
    return json.dumps(result, indent=2)


# --- iCloud Calendar Tools (Personal Calendar) ---


@mcp.tool()
async def ical_list_calendars() -> str:
    """List all available iCloud/Apple calendars on the Mac."""
    result = await _send("ical_list_calendars")
    return json.dumps(result, indent=2)


@mcp.tool()
async def ical_list_events(
    start: str | None = None,
    end: str | None = None,
    calendar_name: str | None = None,
    top: int = 50,
) -> str:
    """List events from Ross's personal iCloud calendar. Use when asked about personal events, birthdays, or holidays. Defaults to next 7 days if no range given.

    Args:
        start: Start date in ISO format (e.g. 2026-06-24T00:00:00)
        end: End date in ISO format
        calendar_name: Optional calendar name filter (e.g. 'Personal', 'Home')
        top: Max events to return (default 50)
    """
    payload: dict = {"top": top}
    if start:
        payload["start"] = start
    if end:
        payload["end"] = end
    if calendar_name:
        payload["calendar_name"] = calendar_name
    result = await _send("ical_list_events", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def ical_create_event(
    title: str,
    start: str,
    end: str,
    calendar_name: str | None = None,
    location: str | None = None,
    notes: str | None = None,
    is_all_day: bool = False,
    timezone_name: str = "Europe/London",
) -> str:
    """Create an event on Ross's personal iCloud calendar. Use for personal events, birthdays, holidays.

    Args:
        title: Event title
        start: Start time in ISO format (e.g. 2026-06-25T14:00:00)
        end: End time in ISO format (e.g. 2026-06-25T15:00:00)
        calendar_name: Which calendar to create on (defaults to the Mac's default calendar)
        location: Optional location
        notes: Optional notes/description
        is_all_day: Whether this is an all-day event (use for birthdays)
        timezone_name: Timezone (default Europe/London)
    """
    payload: dict = {"title": title, "start": start, "end": end, "is_all_day": is_all_day, "timezone_name": timezone_name}
    if calendar_name:
        payload["calendar_name"] = calendar_name
    if location:
        payload["location"] = location
    if notes:
        payload["notes"] = notes
    result = await _send("ical_create_event", payload)
    return json.dumps(result, indent=2)


# --- Support Ticket Tools (read-only) ---
# Two separate systems: CBS and RCSC. When the user asks generically about
# "support tickets" without specifying which, call BOTH list tools and
# summarise the results together.


@mcp.tool()
async def cbs_list_tickets(
    state: str = "open",
    per_page: int = 20,
) -> str:
    """List CBS support tickets. Use when asked about CBS tickets, or when asked generically about "support tickets" (call both cbs_list_tickets and rcsc_list_tickets and summarise together).

    Present a brief one-sentence summary for each ticket, then ask if the user wants more details on any specific ticket.

    Args:
        state: Ticket state filter: open, hold, closed, snoozed, archived (default: open)
        per_page: Max tickets to return (default 20)
    """
    result = await _send("cbs_list_tickets", {"state": state, "per_page": per_page})
    return json.dumps(result, indent=2)


@mcp.tool()
async def cbs_get_ticket(ticket_id: str) -> str:
    """Get full details and message history for a CBS support ticket.

    Args:
        ticket_id: The ticket ID (from cbs_list_tickets)
    """
    result = await _send("cbs_get_ticket", {"ticket_id": ticket_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def cbs_close_ticket(ticket_id: str) -> str:
    """Close a CBS support ticket.

    Args:
        ticket_id: The ticket ID (from cbs_list_tickets or cbs_get_ticket)
    """
    result = await _send("cbs_close_ticket", {"ticket_id": ticket_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def rcsc_list_tickets(
    state: str = "open",
    per_page: int = 20,
) -> str:
    """List RCSC support tickets. Use when asked about RCSC tickets, or when asked generically about "support tickets" (call both cbs_list_tickets and rcsc_list_tickets and summarise together).

    Present a brief one-sentence summary for each ticket, then ask if the user wants more details on any specific ticket.

    Args:
        state: Ticket state filter: open, hold, closed, snoozed, archived (default: open)
        per_page: Max tickets to return (default 20)
    """
    result = await _send("rcsc_list_tickets", {"state": state, "per_page": per_page})
    return json.dumps(result, indent=2)


@mcp.tool()
async def rcsc_get_ticket(ticket_id: str) -> str:
    """Get full details and message history for an RCSC support ticket.

    Args:
        ticket_id: The ticket ID (from rcsc_list_tickets)
    """
    result = await _send("rcsc_get_ticket", {"ticket_id": ticket_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def rcsc_close_ticket(ticket_id: str) -> str:
    """Close an RCSC support ticket.

    Args:
        ticket_id: The ticket ID (from rcsc_list_tickets or rcsc_get_ticket)
    """
    result = await _send("rcsc_close_ticket", {"ticket_id": ticket_id})
    return json.dumps(result, indent=2)


# --- Daily Brief ---


@mcp.tool()
async def daily_brief(date: str | None = None, email_to: str | None = "r.calvert@rcsc.uk") -> str:
    """Generate Ross's daily brief as a printable PDF and email it to him. Gathers today's meetings (Outlook + iCloud) and reminders scheduled for today into a tick-box PDF. Use when Ross asks for a "daily brief", "morning brief", "print my day", or "what's on today".

    Args:
        date: Optional date in YYYY-MM-DD format (defaults to today)
        email_to: Email address to send the brief to (defaults to r.calvert@rcsc.uk)
    """
    payload: dict = {}
    if date:
        payload["date"] = date
    if email_to:
        payload["email_to"] = email_to
    result = await _send("daily_brief", payload)
    return json.dumps(result, indent=2)


# --- Document Tools ---


@mcp.tool()
async def convert_md_to_pdf(md_path: str, output_path: str | None = None) -> str:
    """Convert a Markdown file to PDF.

    Args:
        md_path: Absolute path to the .md file
        output_path: Optional output path (defaults to same name with .pdf)
    """
    payload: dict = {"md_path": md_path}
    if output_path:
        payload["output_path"] = output_path
    result = await _send("convert_md_to_pdf", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def convert_md_to_docx(md_path: str, output_path: str | None = None) -> str:
    """Convert a Markdown file to DOCX (Word).

    Args:
        md_path: Absolute path to the .md file
        output_path: Optional output path (defaults to same name with .docx)
    """
    payload: dict = {"md_path": md_path}
    if output_path:
        payload["output_path"] = output_path
    result = await _send("convert_md_to_docx", payload)
    return json.dumps(result, indent=2)


# --- Voice Memo Tools ---


@mcp.tool()
async def list_recordings(
    date: str | None = None,
    top: int = 10,
) -> str:
    """List voice memo recordings in the Meeting Recordings folder.

    Args:
        date: Optional date filter in YYYY-MM-DD format
        top: Max results (default 10)
    """
    payload: dict = {"top": top}
    if date:
        payload["date"] = date
    result = await _send("list_recordings", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def transcribe_recording(
    filename: str | None = None,
    date: str | None = None,
) -> str:
    """Transcribe a voice memo using Deepgram with speaker diarization.

    Finds the recording by filename or date (most recent on that date).
    Returns the transcript with speaker labels.

    Args:
        filename: Exact filename in Meeting Recordings folder (optional)
        date: Date to find the most recent recording, YYYY-MM-DD (optional)
    """
    payload: dict = {}
    if filename:
        payload["filename"] = filename
    if date:
        payload["date"] = date
    result = await _send("transcribe_recording", payload)
    return json.dumps(result, indent=2)


# --- Apple Notes Tools ---


@mcp.tool()
async def search_notes(
    query: str,
    folder: str | None = None,
    top: int = 20,
) -> str:
    """Search Apple Notes by title or body content.

    Args:
        query: Search term (case-insensitive, matches title or body)
        folder: Optional folder name to search within
        top: Max results (default 20)
    """
    payload: dict = {"query": query, "top": top}
    if folder:
        payload["folder"] = folder
    result = await _send("search_notes", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_note(note_id: str) -> str:
    """Get the full content of an Apple Note by ID.

    Args:
        note_id: The note ID (from search_notes)
    """
    result = await _send("get_note", {"note_id": note_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_note(
    title: str,
    body: str,
    folder: str | None = None,
    body_is_html: bool = False,
) -> str:
    """Create a new Apple Note.

    Args:
        title: The note title
        body: The note body (plain text, or HTML if body_is_html is True)
        folder: Optional folder name (defaults to Notes)
        body_is_html: If True, body is treated as raw HTML for rich formatting
    """
    payload: dict = {"title": title, "body": body, "body_is_html": body_is_html}
    if folder:
        payload["folder"] = folder
    result = await _send("create_note", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_note_folders() -> str:
    """List all Apple Notes folders."""
    result = await _send("list_note_folders")
    return json.dumps(result, indent=2)


# --- MP Portal Tools (Development Task Management) ---


@mcp.tool()
async def mp_list_projects() -> str:
    """List all projects in the MP Portal with id, name, prefix, and customer."""
    result = await _send("mp_list_projects")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_match_project(alias: str) -> str:
    """Match a project by folder name or alias. Use the current working directory name as the alias.

    Args:
        alias: Folder name or alias to match against projects
    """
    result = await _send("mp_match_project", {"alias": alias})
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_list_aliases() -> str:
    """List all saved project folder aliases."""
    result = await _send("mp_list_aliases")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_save_alias(project_id: int, alias: str) -> str:
    """Save a folder alias for a project so future tasks auto-match.

    Args:
        project_id: The project ID (from mp_list_projects or mp_match_project)
        alias: The folder name to associate with this project
    """
    result = await _send("mp_save_alias", {"project_id": project_id, "alias": alias})
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_delete_alias(alias_id: int) -> str:
    """Delete a project folder alias.

    Args:
        alias_id: The alias ID to delete (from mp_list_aliases)
    """
    result = await _send("mp_delete_alias", {"alias_id": alias_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_create_task(
    title: str,
    description: str,
    project_name: str | None = None,
    project_id: int | None = None,
    due_date: str | None = None,
    chargeable: bool = False,
    estimated_hours: float | None = None,
) -> str:
    """Create a new development task. Always ask Ross for both a title and description. Optionally ask how many hours he thinks it will take. The task is automatically set to in-progress and a reminder is created to upload associated files.

    You can provide project_name (e.g. 'ACHL', 'VSS Portal') and it will fuzzy-match. If the match is ambiguous, candidates are returned for Ross to choose from.

    Args:
        title: Task title (short summary)
        description: Task description (what needs to be done)
        project_name: Project name, prefix, or partial match (e.g. 'ACHL', 'VSS'). Use this instead of project_id.
        project_id: Project ID if already known (optional, use project_name instead)
        due_date: Optional due date in YYYY-MM-DD format
        chargeable: Whether this task is billable (default false)
        estimated_hours: Optional estimated hours for the task
    """
    payload: dict = {"title": title, "chargeable": chargeable}
    if project_name:
        payload["project_name"] = project_name
    if project_id:
        payload["project_id"] = project_id
    if description:
        payload["description"] = description
    if due_date:
        payload["due_date"] = due_date
    if estimated_hours is not None:
        payload["estimated_hours"] = estimated_hours
    result = await _send("mp_create_task", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_update_task_status(
    status: str,
    ref: str | None = None,
    task_id: int | None = None,
    chargeable: bool | None = None,
) -> str:
    """Update a task's status. Use the task reference (e.g. 'EL-0186') or title. Never ask Ross for a numeric ID. Use 'deployed' to mark as deployed. Say 'deployed and bill it' to also set chargeable=true.

    Args:
        status: New status: in_progress, completed, or deployed
        ref: Task reference (e.g. 'EL-0186') or title to search for
        task_id: Numeric task ID if already known (prefer ref instead)
        chargeable: Set to true to mark as billable (only relevant for deployed)
    """
    payload: dict = {"status": status}
    if ref:
        payload["ref"] = ref
    if task_id:
        payload["task_id"] = task_id
    if chargeable is not None:
        payload["chargeable"] = chargeable
    result = await _send("mp_update_task_status", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_get_task(
    ref: str | None = None,
    task_id: int | None = None,
) -> str:
    """Get full details of a task. Use the task reference (e.g. 'EL-0186') or search by title. Never ask Ross for a numeric ID.

    Args:
        ref: Task reference (e.g. 'EL-0186') or title to search for
        task_id: Numeric task ID if already known (prefer ref instead)
    """
    payload: dict = {}
    if ref:
        payload["ref"] = ref
    if task_id:
        payload["task_id"] = task_id
    result = await _send("mp_get_task", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_update_task(
    ref: str | None = None,
    task_id: int | None = None,
    hours_taken: float | None = None,
    customer_due_date: str | None = None,
    chargeable: bool | None = None,
    title: str | None = None,
    description: str | None = None,
) -> str:
    """Update a task's fields (hours, due date, description, etc.). Use the task reference (e.g. 'EL-0186') or title. Never ask Ross for a numeric ID.

    Args:
        ref: Task reference (e.g. 'EL-0186') or title to search for
        task_id: Numeric task ID if already known (prefer ref instead)
        hours_taken: Hours spent on the task
        customer_due_date: Due date in YYYY-MM-DD format
        chargeable: Whether this task is billable
        title: Updated task title
        description: Updated task description
    """
    payload: dict = {}
    if ref:
        payload["ref"] = ref
    if task_id:
        payload["task_id"] = task_id
    if hours_taken is not None:
        payload["hours_taken"] = hours_taken
    if customer_due_date is not None:
        payload["customer_due_date"] = customer_due_date
    if chargeable is not None:
        payload["chargeable"] = chargeable
    if title is not None:
        payload["title"] = title
    if description is not None:
        payload["description"] = description
    result = await _send("mp_update_task", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_search_tasks(query: str) -> str:
    """Search active tasks in the MP Portal by title or task ID (e.g. 'ACME-0042').

    Args:
        query: Search term (matches title or task reference)
    """
    result = await _send("mp_search_tasks", {"query": query})
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_in_progress_tasks() -> str:
    """List all tasks currently in progress across all projects."""
    result = await _send("mp_in_progress_tasks")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_my_tasks() -> str:
    """Get outstanding tasks assigned to Ross. Use for 'what should I work on' or 'what's on my plate'."""
    result = await _send("mp_my_tasks")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_overdue_tasks() -> str:
    """Get tasks past their due date that haven't been deployed yet."""
    result = await _send("mp_overdue_tasks")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_recent_tasks() -> str:
    """Get recently created or updated tasks (last 7 days)."""
    result = await _send("mp_recent_tasks")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_outstanding_summary() -> str:
    """Get total count of outstanding tasks across all projects, with breakdown by status (Backlog, In Progress, etc.)."""
    result = await _send("mp_outstanding_summary")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_outstanding_by_project() -> str:
    """Get outstanding task counts broken down by project, sorted by highest first. Use when asked 'which projects are busiest' or 'outstanding by project'."""
    result = await _send("mp_outstanding_by_project")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_billable_summary() -> str:
    """Get billable tasks summary — number of billable tasks, total hours outstanding, hourly rate, and total amount outstanding in GBP. Use for 'what can I bill', 'billable summary', or 'invoice amounts'."""
    result = await _send("mp_billable_summary")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_activity_recent() -> str:
    """Get recent activity log across all projects — task creations, status changes, updates. Use for 'what happened recently' or 'recent activity'."""
    result = await _send("mp_activity_recent")
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_list_customers(q: str | None = None) -> str:
    """List or search customers in the MP Portal (id, name, company, city, postcode, email, phone). Pass q to search by company, name, email or postcode. Use this to find an existing customer before creating one.

    Args:
        q: Optional search term.
    """
    payload: dict = {}
    if q:
        payload["q"] = q
    result = await _send("mp_list_customers", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_get_customer(customer_id: int) -> str:
    """Look up one MP Portal customer by id, with full site and invoice address, phone, email and website.

    Args:
        customer_id: The portal customer id.
    """
    result = await _send("mp_get_customer", {"customer_id": customer_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_create_customer(
    name: str,
    company_name: str | None = None,
    address_line_1: str | None = None,
    address_line_2: str | None = None,
    city: str | None = None,
    county: str | None = None,
    postcode: str | None = None,
    invoice_same_as_site: bool = True,
    invoice_address_line_1: str | None = None,
    invoice_address_line_2: str | None = None,
    invoice_city: str | None = None,
    invoice_county: str | None = None,
    invoice_postcode: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    website: str | None = None,
    notes: str | None = None,
) -> str:
    """Create a new customer in the MP Portal with full site and invoice address. ALWAYS read the full details back to Ross and get his explicit agreement before calling — this inserts a customer record. Run mp_list_customers first to avoid duplicates. Provide the site address; set invoice_same_as_site false and supply invoice_* fields only if the billing address differs.

    Args:
        name: Customer/company name (required).
        company_name: Company name if different from name.
        address_line_1: Site address line 1.
        address_line_2: Site address line 2.
        city: Site town/city.
        county: Site county.
        postcode: Site postcode.
        invoice_same_as_site: True if the invoice address matches the site address (default true).
        invoice_address_line_1: Invoice address line 1 (only if different).
        invoice_address_line_2: Invoice address line 2.
        invoice_city: Invoice town/city.
        invoice_county: Invoice county.
        invoice_postcode: Invoice postcode.
        email: Contact email.
        phone: Contact phone.
        website: Website.
        notes: Free-text notes.
    """
    payload: dict = {"name": name, "invoice_same_as_site": invoice_same_as_site}
    for key, value in {
        "company_name": company_name,
        "address_line_1": address_line_1,
        "address_line_2": address_line_2,
        "city": city,
        "county": county,
        "postcode": postcode,
        "invoice_address_line_1": invoice_address_line_1,
        "invoice_address_line_2": invoice_address_line_2,
        "invoice_city": invoice_city,
        "invoice_county": invoice_county,
        "invoice_postcode": invoice_postcode,
        "email": email,
        "phone": phone,
        "website": website,
        "notes": notes,
    }.items():
        if value is not None:
            payload[key] = value
    result = await _send("mp_create_customer", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_create_project(
    customer_id: int,
    name: str,
    prefix: str,
    description: str | None = None,
    production_url: str | None = None,
    git_repository: str | None = None,
    git_branch: str | None = None,
    deployment_location: str | None = None,
    notes: str | None = None,
) -> str:
    """Create a new project under a customer in the MP Portal. ALWAYS read the full details back to Ross and get his explicit agreement before calling — this inserts a project record. Run mp_list_projects first to avoid duplicates, and mp_list_customers to confirm the customer_id. The prefix is the short task code (e.g. 'WTS' gives task ids like WTS-0001) and must be unique; it is stored uppercased.

    Args:
        customer_id: Portal customer id the project belongs to (required).
        name: Project name, e.g. 'WTS Portal' (required).
        prefix: Short unique task prefix, e.g. 'WTS' (required).
        description: What the project is.
        production_url: Live URL, e.g. https://wts.portal-app.uk.
        git_repository: Repo, e.g. 'RCSC-NW/wts.portal-app.uk'.
        git_branch: Default branch, e.g. 'main'.
        deployment_location: Where it's hosted/deployed.
        notes: Free-text notes.
    """
    payload: dict = {"customer_id": customer_id, "name": name, "prefix": prefix}
    for key, value in {
        "description": description,
        "production_url": production_url,
        "git_repository": git_repository,
        "git_branch": git_branch,
        "deployment_location": deployment_location,
        "notes": notes,
    }.items():
        if value is not None:
            payload[key] = value
    result = await _send("mp_create_project", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_log_activity(
    customer_id: int,
    title: str,
    description: str | None = None,
    project_id: int | None = None,
    task_id: int | None = None,
    source: str | None = None,
) -> str:
    """Append ONE granular software-development work item to a customer's activity audit trail. Call this for each discrete thing done when the work relates to a portal customer. `title` is a short headline (the feature name or task description); `description` is the expandable detail of what actually changed (files, behaviour, fixes). customer_id is required; pass project_id when the work belongs to a project and task_id when it relates to an existing task (there is often no task — that's fine). This is a customer audit trail, NOT the personal task system.

    Args:
        customer_id: Portal customer id (required).
        title: Short headline — the feature name or task description.
        description: Expandable detail: what actually changed (files, behaviour, fixes).
        project_id: Portal project id, if the work belongs to a project.
        task_id: Portal task id, if the work relates to an existing task.
        source: Where it came from, e.g. 'Claude Code — Mac Mini'.
    """
    payload: dict = {"customer_id": customer_id, "title": title}
    for key, value in {
        "description": description,
        "project_id": project_id,
        "task_id": task_id,
        "source": source,
    }.items():
        if value is not None:
            payload[key] = value
    result = await _send("mp_log_activity", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def mp_list_activities(customer_id: int | None = None, project_id: int | None = None) -> str:
    """Read the software-development activity audit trail. Pass customer_id for a customer's whole trail, or project_id for one project's trail.

    Args:
        customer_id: Portal customer id (for the customer's whole trail).
        project_id: Portal project id (for one project's trail).
    """
    payload: dict = {}
    if customer_id:
        payload["customer_id"] = customer_id
    if project_id:
        payload["project_id"] = project_id
    result = await _send("mp_list_activities", payload)
    return json.dumps(result, indent=2)


# --- QuickBooks Tools ---


@mcp.tool()
async def qb_list_companies() -> str:
    """List all QuickBooks companies connected to Ross's account. Returns realm IDs needed for other QB operations.
    """
    result = await _send("qb_list_companies")
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_get_company_info(realm_id: str) -> str:
    """Get company information from QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID (from qb_list_companies)
    """
    result = await _send("qb_get_company_info", {"realm_id": realm_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_customers(
    realm_id: str,
    active_only: bool = True,
    max_results: int = 100,
) -> str:
    """List customers in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        active_only: Only return active customers (default true)
        max_results: Max customers to return (default 100)
    """
    result = await _send("qb_list_customers", {"realm_id": realm_id, "active_only": active_only, "max_results": max_results})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_get_customer(realm_id: str, customer_id: str) -> str:
    """Get a specific QuickBooks customer by ID.

    Args:
        realm_id: The QuickBooks company/realm ID
        customer_id: The customer ID (from qb_list_customers)
    """
    result = await _send("qb_get_customer", {"realm_id": realm_id, "customer_id": customer_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_search_customers(realm_id: str, name: str) -> str:
    """Search QuickBooks customers by display name.

    Args:
        realm_id: The QuickBooks company/realm ID
        name: Name to search for (partial match)
    """
    result = await _send("qb_search_customers", {"realm_id": realm_id, "name": name})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_create_customer(
    realm_id: str,
    display_name: str,
    email: str | None = None,
    phone: str | None = None,
    company_name: str | None = None,
) -> str:
    """Create a new customer in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        display_name: Customer display name
        email: Customer email address
        phone: Customer phone number
        company_name: Company name
    """
    payload: dict = {"realm_id": realm_id, "display_name": display_name}
    if email:
        payload["email"] = email
    if phone:
        payload["phone"] = phone
    if company_name:
        payload["company_name"] = company_name
    result = await _send("qb_create_customer", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_invoices(
    realm_id: str,
    max_results: int = 20,
    status: str | None = None,
) -> str:
    """List invoices in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        max_results: Max invoices to return (default 20)
        status: Filter by status: paid, unpaid, or overdue (optional)
    """
    payload: dict = {"realm_id": realm_id, "max_results": max_results}
    if status:
        payload["status"] = status
    result = await _send("qb_list_invoices", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_get_invoice(realm_id: str, invoice_id: str) -> str:
    """Get a specific QuickBooks invoice with line items.

    Args:
        realm_id: The QuickBooks company/realm ID
        invoice_id: The invoice ID (from qb_list_invoices)
    """
    result = await _send("qb_get_invoice", {"realm_id": realm_id, "invoice_id": invoice_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_create_invoice(
    realm_id: str,
    customer_id: str,
    line_items: list[dict],
    due_date: str | None = None,
    invoice_number: str | None = None,
    memo: str | None = None,
) -> str:
    """Create a new invoice in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        customer_id: Customer ID to invoice
        line_items: List of line items, each with: description, amount, quantity (default 1), item_id (optional), tax_code_id (optional)
        due_date: Due date in YYYY-MM-DD format
        invoice_number: Custom invoice number
        memo: Customer memo on the invoice
    """
    payload: dict = {"realm_id": realm_id, "customer_id": customer_id, "line_items": line_items}
    if due_date:
        payload["due_date"] = due_date
    if invoice_number:
        payload["invoice_number"] = invoice_number
    if memo:
        payload["memo"] = memo
    result = await _send("qb_create_invoice", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_payments(realm_id: str, max_results: int = 20) -> str:
    """List recent payments in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        max_results: Max payments to return (default 20)
    """
    result = await _send("qb_list_payments", {"realm_id": realm_id, "max_results": max_results})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_get_payment(realm_id: str, payment_id: str) -> str:
    """Get a specific QuickBooks payment by ID.

    Args:
        realm_id: The QuickBooks company/realm ID
        payment_id: The payment ID (from qb_list_payments)
    """
    result = await _send("qb_get_payment", {"realm_id": realm_id, "payment_id": payment_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_create_payment(
    realm_id: str,
    customer_id: str,
    total_amount: float,
    invoice_id: str | None = None,
    payment_date: str | None = None,
    payment_method: str | None = None,
) -> str:
    """Record a payment in QuickBooks against a customer (and optionally an invoice).

    Args:
        realm_id: The QuickBooks company/realm ID
        customer_id: Customer ID
        total_amount: Payment amount
        invoice_id: Invoice ID to apply payment to (optional)
        payment_date: Payment date in YYYY-MM-DD format (optional)
        payment_method: Payment method (optional)
    """
    payload: dict = {"realm_id": realm_id, "customer_id": customer_id, "total_amount": total_amount}
    if invoice_id:
        payload["invoice_id"] = invoice_id
    if payment_date:
        payload["payment_date"] = payment_date
    if payment_method:
        payload["payment_method"] = payment_method
    result = await _send("qb_create_payment", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_bills(
    realm_id: str,
    max_results: int = 20,
    unpaid_only: bool = False,
) -> str:
    """List bills (supplier invoices) in QuickBooks. Use for VAT return purchase tracking.

    Args:
        realm_id: The QuickBooks company/realm ID
        max_results: Max bills to return (default 20)
        unpaid_only: Only return unpaid bills (default false)
    """
    result = await _send("qb_list_bills", {"realm_id": realm_id, "max_results": max_results, "unpaid_only": unpaid_only})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_get_bill(realm_id: str, bill_id: str) -> str:
    """Get a specific QuickBooks bill (supplier invoice) with line items.

    Args:
        realm_id: The QuickBooks company/realm ID
        bill_id: The bill ID (from qb_list_bills)
    """
    result = await _send("qb_get_bill", {"realm_id": realm_id, "bill_id": bill_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_create_bill(
    realm_id: str,
    vendor_id: str,
    line_items: list[dict],
    due_date: str | None = None,
    memo: str | None = None,
) -> str:
    """Create a bill (expense from a supplier) in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        vendor_id: Vendor/supplier ID
        line_items: List of line items, each with: description, amount, account_id (expense account), tax_code_id (optional)
        due_date: Due date in YYYY-MM-DD format
        memo: Private note on the bill
    """
    payload: dict = {"realm_id": realm_id, "vendor_id": vendor_id, "line_items": line_items}
    if due_date:
        payload["due_date"] = due_date
    if memo:
        payload["memo"] = memo
    result = await _send("qb_create_bill", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_create_expense(
    realm_id: str,
    account_id: str,
    line_items: list[dict],
    vendor_id: str | None = None,
    payment_type: str = "Cash",
    memo: str | None = None,
    txn_date: str | None = None,
) -> str:
    """Create an expense (purchase) in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        account_id: Payment account ID (e.g. bank account)
        line_items: List of line items, each with: description, amount, expense_account_id (category), tax_code_id (optional)
        vendor_id: Vendor/supplier ID (optional)
        payment_type: Cash, Check, or CreditCard (default Cash)
        memo: Private note
        txn_date: Transaction date in YYYY-MM-DD format
    """
    payload: dict = {"realm_id": realm_id, "account_id": account_id, "line_items": line_items, "payment_type": payment_type}
    if vendor_id:
        payload["vendor_id"] = vendor_id
    if memo:
        payload["memo"] = memo
    if txn_date:
        payload["txn_date"] = txn_date
    result = await _send("qb_create_expense", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_accounts(
    realm_id: str,
    account_type: str | None = None,
    max_results: int = 100,
) -> str:
    """List accounts from the QuickBooks chart of accounts.

    Args:
        realm_id: The QuickBooks company/realm ID
        account_type: Filter by type: Expense, Income, Bank, Asset (optional)
        max_results: Max accounts to return (default 100)
    """
    payload: dict = {"realm_id": realm_id, "max_results": max_results}
    if account_type:
        payload["account_type"] = account_type
    result = await _send("qb_list_accounts", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_items(realm_id: str, max_results: int = 100) -> str:
    """List items/services in QuickBooks (things you sell or buy).

    Args:
        realm_id: The QuickBooks company/realm ID
        max_results: Max items to return (default 100)
    """
    result = await _send("qb_list_items", {"realm_id": realm_id, "max_results": max_results})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_get_item(realm_id: str, item_id: str) -> str:
    """Get a specific QuickBooks item/service by ID.

    Args:
        realm_id: The QuickBooks company/realm ID
        item_id: The item ID (from qb_list_items)
    """
    result = await _send("qb_get_item", {"realm_id": realm_id, "item_id": item_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_create_item(
    realm_id: str,
    name: str,
    item_type: str = "Service",
    income_account_id: str | None = None,
    expense_account_id: str | None = None,
    unit_price: float | None = None,
    description: str | None = None,
) -> str:
    """Create an item/service in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        name: Item name
        item_type: Service, Inventory, or NonInventory (default Service)
        income_account_id: Income account for sales
        expense_account_id: Expense account for purchases
        unit_price: Default unit price
        description: Item description
    """
    payload: dict = {"realm_id": realm_id, "name": name, "item_type": item_type}
    if income_account_id:
        payload["income_account_id"] = income_account_id
    if expense_account_id:
        payload["expense_account_id"] = expense_account_id
    if unit_price is not None:
        payload["unit_price"] = unit_price
    if description:
        payload["description"] = description
    result = await _send("qb_create_item", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_tax_codes(realm_id: str) -> str:
    """List all VAT/tax codes in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
    """
    result = await _send("qb_list_tax_codes", {"realm_id": realm_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_tax_rates(realm_id: str) -> str:
    """List all tax rates in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
    """
    result = await _send("qb_list_tax_rates", {"realm_id": realm_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_list_vendors(
    realm_id: str,
    active_only: bool = True,
    max_results: int = 100,
) -> str:
    """List vendors (suppliers) in QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        active_only: Only return active vendors (default true)
        max_results: Max vendors to return (default 100)
    """
    result = await _send("qb_list_vendors", {"realm_id": realm_id, "active_only": active_only, "max_results": max_results})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_search_vendors(realm_id: str, name: str) -> str:
    """Search QuickBooks vendors by display name.

    Args:
        realm_id: The QuickBooks company/realm ID
        name: Vendor name to search for (partial match)
    """
    result = await _send("qb_search_vendors", {"realm_id": realm_id, "name": name})
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_profit_and_loss(
    realm_id: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> str:
    """Get a profit and loss report from QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        start_date: Report start date in YYYY-MM-DD format (optional)
        end_date: Report end date in YYYY-MM-DD format (optional)
    """
    payload: dict = {"realm_id": realm_id}
    if start_date:
        payload["start_date"] = start_date
    if end_date:
        payload["end_date"] = end_date
    result = await _send("qb_profit_and_loss", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def qb_balance_sheet(
    realm_id: str,
    report_date: str | None = None,
) -> str:
    """Get a balance sheet report from QuickBooks.

    Args:
        realm_id: The QuickBooks company/realm ID
        report_date: Report as-of date in YYYY-MM-DD format (optional, defaults to today)
    """
    payload: dict = {"realm_id": realm_id}
    if report_date:
        payload["report_date"] = report_date
    result = await _send("qb_balance_sheet", payload)
    return json.dumps(result, indent=2)


# --- Agent Management Tools ---


@mcp.tool()
async def update_agent(agent_name: str | None = None) -> str:
    """Update a local Mac agent — pulls latest code from git, installs deps, and restarts.

    Args:
        agent_name: Optional agent name to update (updates first available if omitted)
    """
    payload: dict = {}
    if agent_name:
        payload["agent_name"] = agent_name
    result = await _send("update_agent", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def agent_status() -> str:
    """Check which local Mac agents are connected and their capabilities."""
    # This is handled directly by the relay, not routed to an agent
    agents = _agents_ref or {}
    status = {}
    for name, agent in agents.items():
        status[name] = {
            "machine": agent.registration.machine_name,
            "capabilities": [c.value for c in agent.registration.capabilities],
            "connected_at": agent.connected_at.isoformat(),
            "last_seen": agent.last_seen.isoformat(),
        }
    return json.dumps({"agents": status}, indent=2)


# --- Feedback Tool ---


@mcp.tool()
async def submit_feedback(feedback: str) -> str:
    """Record feedback from Ross for later review and processing. Use when Ross says he has feedback or wants to note something for improvement.

    Args:
        feedback: The feedback to record
    """
    from relay.dashboard import record_feedback
    record_feedback(feedback=feedback, source="mcp")
    return json.dumps({"status": "recorded", "message": "Feedback saved"})


# --- Contact Lookup Tool ---


@mcp.tool()
async def lookup_contact(name: str) -> str:
    """Look up a contact by name to get their email address. Use when Ross wants to email someone by name. Confirm the email address with Ross before proceeding.

    Args:
        name: Contact name to search for (partial match, case-insensitive)
    """
    from relay.dashboard import lookup_contact as _lookup
    contacts = _lookup(name)
    if not contacts:
        return json.dumps({"contacts": [], "message": f"No contacts found matching '{name}'"})
    return json.dumps({"contacts": [{"name": c["name"], "email": c["email"], "company": c.get("company", ""), "allowed_sender": bool(c["allowed_sender"])} for c in contacts]}, indent=2)


def create_mcp_app() -> BearerTokenMiddleware:
    """Create the MCP Starlette app with Bearer token auth.

    IMPORTANT: After creating the app, you must call start_session_manager()
    during the host app's lifespan startup, since sub-app lifespans don't
    run automatically under FastAPI's mount().
    """
    starlette_app = mcp.streamable_http_app()
    return BearerTokenMiddleware(starlette_app)


def get_session_manager():
    """Return the MCP session manager for lifespan management."""
    return mcp._session_manager
