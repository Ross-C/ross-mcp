"""MCP server for Ross's life admin — connects Claude to the relay API."""

import json
import os
import sys

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

RELAY_URL = os.getenv("MCP_RELAY_URL", "https://ross-mcp-relay.fly.dev")
API_KEY = os.getenv("RELAY_API_KEY", "")

mcp = FastMCP(
    "Ross Life Admin",
    instructions="Manage Apple Reminders, Calendar, and Email via local Mac agents",
)


async def _send_command(command_type: str, payload: dict = {}) -> dict:
    """Send a command to the relay and return the response."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{RELAY_URL}/api/command",
            json={"type": command_type, "payload": payload},
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        resp.raise_for_status()
        return resp.json()


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

    result = await _send_command("create_reminder", payload)
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

    result = await _send_command("list_reminders", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def complete_reminder(reminder_id: str) -> str:
    """Mark an Apple Reminder as completed.

    Args:
        reminder_id: The ID of the reminder to complete (from list_reminders)
    """
    result = await _send_command("complete_reminder", {"reminder_id": reminder_id})
    return json.dumps(result, indent=2)


# --- Outlook Email Tools ---


@mcp.tool()
async def search_emails(
    query: str,
    folder: str | None = None,
    top: int = 10,
) -> str:
    """Search Outlook emails.

    Args:
        query: Search query (matches subject, body, sender, etc.)
        folder: Optional folder (inbox, sentitems, drafts, archive)
        top: Max results (default 10)
    """
    payload = {"query": query, "top": top}
    if folder:
        payload["folder"] = folder
    result = await _send_command("search_emails", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_email(message_id: str) -> str:
    """Get full content of an Outlook email by ID.

    Args:
        message_id: The email message ID (from search_emails)
    """
    result = await _send_command("get_email", {"message_id": message_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_email_thread(conversation_id: str, top: int = 25) -> str:
    """Get all emails in a conversation thread (for summarisation).

    Args:
        conversation_id: The conversation ID (from get_email)
        top: Max messages to return (default 25)
    """
    result = await _send_command("get_thread", {"conversation_id": conversation_id, "top": top})
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_email_draft(
    subject: str,
    body: str,
    to: list[str],
    cc: list[str] | None = None,
    body_type: str = "HTML",
) -> str:
    """Create an Outlook email draft.

    Args:
        subject: Email subject
        body: Email body (HTML by default)
        to: List of recipient email addresses
        cc: Optional list of CC addresses
        body_type: Content type — HTML (default) or Text
    """
    payload: dict = {"subject": subject, "body": body, "to": to, "body_type": body_type}
    if cc:
        payload["cc"] = cc
    result = await _send_command("create_draft", payload)
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
    result = await _send_command("update_draft", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def send_email_draft(message_id: str) -> str:
    """Send an existing Outlook email draft.

    Args:
        message_id: The draft message ID to send
    """
    result = await _send_command("send_draft", {"message_id": message_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def send_email(
    subject: str,
    body: str,
    to: list[str],
    cc: list[str] | None = None,
    body_type: str = "HTML",
) -> str:
    """Compose and send an Outlook email immediately.

    Args:
        subject: Email subject
        body: Email body (HTML by default)
        to: List of recipient email addresses
        cc: Optional list of CC addresses
        body_type: Content type — HTML (default) or Text
    """
    payload: dict = {"subject": subject, "body": body, "to": to, "body_type": body_type}
    if cc:
        payload["cc"] = cc
    result = await _send_command("send_email", payload)
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

    Creates a draft and sends it automatically at the specified time.

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
    result = await _send_command("schedule_send", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def cancel_scheduled_email(message_id: str) -> str:
    """Cancel a scheduled email send. The draft is kept.

    Args:
        message_id: The scheduled email's message ID
    """
    result = await _send_command("cancel_scheduled_send", {"message_id": message_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def archive_email(message_id: str) -> str:
    """Move an Outlook email to the Archive folder.

    Args:
        message_id: The email message ID to archive
    """
    result = await _send_command("archive_email", {"message_id": message_id})
    return json.dumps(result, indent=2)


# --- Outlook Calendar Tools ---


@mcp.tool()
async def list_calendar_events(
    start: str | None = None,
    end: str | None = None,
    top: int = 20,
) -> str:
    """List Outlook calendar events.

    Defaults to the next 7 days if no date range given.

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
    result = await _send_command("list_events", payload)
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
    result = await _send_command("create_event", payload)
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
    result = await _send_command("update_event", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def cancel_calendar_event(event_id: str) -> str:
    """Cancel/delete an Outlook calendar event.

    Args:
        event_id: The event ID to cancel
    """
    result = await _send_command("cancel_event", {"event_id": event_id})
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
    result = await _send_command("find_available_slots", {
        "start": start,
        "end": end,
        "duration_minutes": duration_minutes,
    })
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
    result = await _send_command("search_notes", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_note(note_id: str) -> str:
    """Get the full content of an Apple Note by ID.

    Args:
        note_id: The note ID (from search_notes)
    """
    result = await _send_command("get_note", {"note_id": note_id})
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_note(
    title: str,
    body: str,
    folder: str | None = None,
) -> str:
    """Create a new Apple Note.

    Args:
        title: The note title
        body: The note body (plain text)
        folder: Optional folder name (defaults to Notes)
    """
    payload: dict = {"title": title, "body": body}
    if folder:
        payload["folder"] = folder
    result = await _send_command("create_note", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_note_folders() -> str:
    """List all Apple Notes folders."""
    result = await _send_command("list_note_folders")
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run()
