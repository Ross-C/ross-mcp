"""REST endpoints with full OpenAPI docs for ChatGPT Custom GPT Actions.

Each tool gets its own endpoint with typed request/response models,
giving ChatGPT complete parameter visibility via the OpenAPI spec.
"""

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, BeforeValidator, Field


def _coerce_to_list(v: Any) -> list[str]:
    """Accept a comma-separated string or a list for email address fields."""
    if isinstance(v, str):
        return [addr.strip() for addr in v.split(",") if addr.strip()]
    return v


EmailList = Annotated[list[str], BeforeValidator(_coerce_to_list)]
OptionalEmailList = Annotated[list[str] | None, BeforeValidator(lambda v: _coerce_to_list(v) if isinstance(v, str) else v)]


def _format_email_body(body: str) -> str:
    """Ensure email body is properly formatted HTML with Aptos font and sign-off."""
    body = body.strip()
    # If already wrapped in our font div, return as-is
    if "font-family:" in body and "Aptos" in body:
        return body
    # If it's plain text (no HTML tags), convert to HTML
    if "<" not in body or "<p" not in body.lower():
        paragraphs = body.split("\n\n") if "\n\n" in body else body.split("\n")
        html_parts = [f"<p>{p.strip()}</p>" for p in paragraphs if p.strip()]
        body = "".join(html_parts)
    # Add sign-off if not present
    if "kind regards" not in body.lower():
        body += "<p>Kind regards<br>Ross</p>"
    # Wrap in Aptos font div
    return f'<div style="font-family:Aptos,Arial,Helvetica,sans-serif;font-size:12pt;color:rgb(0,0,0)">{body}</div>'


def _all_recipients_allowed(recipients: list[str]) -> bool:
    """Check if all recipients are allowed."""
    from relay.dashboard import is_allowed_recipient
    return all(is_allowed_recipient(email) for email in recipients)

router = APIRouter(prefix="/api/tools", tags=["Tools"])
_security = HTTPBearer()

# Will be injected by relay.py
_execute_command = None


def init(execute_command, verify_api_key):
    global _execute_command
    _execute_command = execute_command


def _get_api_key(credentials: HTTPAuthorizationCredentials = Depends(_security)) -> str:
    api_key = os.getenv("RELAY_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="Server API key not configured")
    if credentials.credentials != api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return credentials.credentials


async def _run(command_type: str, payload: dict = {}) -> dict:
    import json as _json
    from shared.messages import CommandType
    try:
        result = await _execute_command(CommandType(command_type), payload)
        # Check for agent-level errors
        if result.get("status") == "error" and result.get("error"):
            from relay.dashboard import record_failed_request
            record_failed_request(
                endpoint=f"/api/tools/{command_type.replace('_', '-')}",
                payload=_json.dumps(payload),
                error=result["error"],
                source="agent",
            )
        return result.get("data", result)
    except HTTPException as e:
        from relay.dashboard import record_failed_request
        record_failed_request(
            endpoint=f"/api/tools/{command_type.replace('_', '-')}",
            payload=_json.dumps(payload),
            error=f"HTTP {e.status_code}: {e.detail}",
            source="relay",
        )
        raise


def _auth():
    return Depends(_verify_api_key)


# --- Response model ---

class ToolResponse(BaseModel):
    status: str = Field(description="success or error")
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


# =====================
# Apple Reminders
# =====================

class CreateReminderRequest(BaseModel):
    title: str = Field(description="The reminder title")
    notes: str | None = Field(default=None, description="Optional notes/description")
    due_date: str | None = Field(default=None, description="Due date in ISO format, e.g. 2026-06-25T09:00:00")
    list_name: str | None = Field(default=None, description="Reminder list name (defaults to Reminders)")
    priority: int = Field(default=0, description="Priority: 0=none, 1=low, 5=medium, 9=high")


@router.post("/create-reminder", summary="Create an Apple Reminder")
async def create_reminder(req: CreateReminderRequest, _=Depends(_get_api_key)):
    payload = {"title": req.title}
    if req.notes: payload["notes"] = req.notes
    if req.due_date: payload["due_date"] = req.due_date
    if req.list_name: payload["list_name"] = req.list_name
    if req.priority: payload["priority"] = req.priority
    return await _run("create_reminder", payload)


class ListRemindersRequest(BaseModel):
    list_name: str | None = Field(default=None, description="Filter by reminder list name")
    include_completed: bool = Field(default=False, description="Include completed reminders")


@router.post("/list-reminders", summary="List Apple Reminders")
async def list_reminders(req: ListRemindersRequest, _=Depends(_get_api_key)):
    payload = {}
    if req.list_name: payload["list_name"] = req.list_name
    if req.include_completed: payload["include_completed"] = True
    return await _run("list_reminders", payload)


class CompleteReminderRequest(BaseModel):
    reminder_id: str = Field(description="The reminder ID to complete")


@router.post("/complete-reminder", summary="Mark a reminder as completed")
async def complete_reminder(req: CompleteReminderRequest, _=Depends(_get_api_key)):
    return await _run("complete_reminder", {"reminder_id": req.reminder_id})


# =====================
# Outlook Email
# =====================

class SearchEmailsRequest(BaseModel):
    query: str = Field(default="", description="Search query (matches subject, body, sender). Leave empty to list recent emails.")
    folder: str | None = Field(default=None, description="Folder: inbox, sentitems, drafts, archive. IMPORTANT: Default to 'inbox' when asked about new emails, what's in my inbox, etc. Only omit when explicitly searching across all folders.")
    top: int = Field(default=10, description="Max results")


@router.post("/search-emails", summary="Search Outlook emails. When asked about new emails or 'what's in my inbox', set folder to 'inbox'. Give brief summaries: sender and subject only, then ask if Ross wants details.")
async def search_emails(req: SearchEmailsRequest, _=Depends(_get_api_key)):
    payload: dict = {"query": req.query, "top": req.top}
    if req.folder: payload["folder"] = req.folder
    return await _run("search_emails", payload)


class GetEmailRequest(BaseModel):
    message_id: str = Field(description="Email message ID from search results")


@router.post("/get-email", summary="Get full email content by ID")
async def get_email(req: GetEmailRequest, _=Depends(_get_api_key)):
    return await _run("get_email", {"message_id": req.message_id})


class GetThreadRequest(BaseModel):
    conversation_id: str = Field(description="Conversation ID from get-email")
    top: int = Field(default=25, description="Max messages to return")


@router.post("/get-email-thread", summary="Get all emails in a conversation thread")
async def get_email_thread(req: GetThreadRequest, _=Depends(_get_api_key)):
    return await _run("get_thread", {"conversation_id": req.conversation_id, "top": req.top})


class CreateDraftRequest(BaseModel):
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body in HTML. Wrap in Aptos font div. Use <p> tags for paragraphs. Always enrich and polish the user's input, never parrot verbatim. No em dashes or hyphens joining clauses. Sign off Kind regards / Ross.")
    to: EmailList = Field(description="Recipient email addresses (list or comma-separated string)")
    cc: OptionalEmailList = Field(default=None, description="CC addresses")
    body_type: str = Field(default="HTML", description="Always use HTML")


@router.post("/create-draft", summary="Create an Outlook email draft. Enrich the user's input into a polished email in Ross's style.")
async def create_draft(req: CreateDraftRequest, _=Depends(_get_api_key)):
    body = _format_email_body(req.body)
    if _all_recipients_allowed(req.to):
        payload: dict = {"subject": req.subject, "body": body, "to": req.to, "body_type": "HTML"}
        if req.cc: payload["cc"] = req.cc
        result = await _run("send_email", payload)
        result["note"] = "Sent directly (all recipients are allowed)"
        return result
    payload: dict = {"subject": req.subject, "body": body, "to": req.to, "body_type": "HTML"}
    if req.cc: payload["cc"] = req.cc
    return await _run("create_draft", payload)


class DraftReplyRequest(BaseModel):
    message_id: str = Field(description="Message ID of the email to reply to")
    body: str = Field(description="Reply body in HTML. Wrap in Aptos font div. Use <p> tags for paragraphs. Always enrich and polish the user's input, never parrot verbatim. No em dashes or hyphens joining clauses. Sign off Kind regards / Ross.")
    cc: OptionalEmailList = Field(default=None, description="CC addresses to add")
    body_type: str = Field(default="HTML", description="Always use HTML")


@router.post("/draft-a-reply", summary="Create a draft reply to an existing email (in-thread). Enrich the user's input into a polished reply in Ross's style.")
async def draft_a_reply(req: DraftReplyRequest, _=Depends(_get_api_key)):
    payload: dict = {"message_id": req.message_id, "body": req.body, "body_type": req.body_type}
    if req.cc: payload["cc"] = req.cc
    return await _run("draft_reply", payload)


class UpdateDraftRequest(BaseModel):
    message_id: str = Field(description="Draft message ID")
    subject: str | None = Field(default=None, description="New subject")
    body: str | None = Field(default=None, description="New body")
    to: OptionalEmailList = Field(default=None, description="New recipients")
    cc: OptionalEmailList = Field(default=None, description="New CC list")
    body_type: str = Field(default="HTML", description="HTML or Text")


@router.post("/update-draft", summary="Update an existing email draft")
async def update_draft(req: UpdateDraftRequest, _=Depends(_get_api_key)):
    payload: dict = {"message_id": req.message_id, "body_type": req.body_type}
    if req.subject is not None: payload["subject"] = req.subject
    if req.body is not None: payload["body"] = req.body
    if req.to is not None: payload["to"] = req.to
    if req.cc is not None: payload["cc"] = req.cc
    return await _run("update_draft", payload)


class SendDraftRequest(BaseModel):
    message_id: str = Field(description="Draft message ID to send")


@router.post("/send-draft", summary="Send an existing email draft")
async def send_draft(req: SendDraftRequest, _=Depends(_get_api_key)):
    return await _run("send_draft", {"message_id": req.message_id})


class SendEmailRequest(BaseModel):
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body (HTML by default)")
    to: EmailList = Field(description="Recipient email addresses (list or comma-separated string)")
    cc: OptionalEmailList = Field(default=None, description="CC addresses")
    body_type: str = Field(default="HTML", description="HTML or Text")


@router.post("/send-email", summary="Send an email immediately")
async def send_email(req: SendEmailRequest, _=Depends(_get_api_key)):
    payload: dict = {"subject": req.subject, "body": req.body, "to": req.to, "body_type": req.body_type}
    if req.cc: payload["cc"] = req.cc
    return await _run("send_email", payload)


class ScheduleEmailRequest(BaseModel):
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body (HTML by default)")
    to: EmailList = Field(description="Recipient email addresses (list or comma-separated string)")
    send_at: str = Field(description="When to send in ISO format, e.g. 2026-06-25T09:00:00")
    cc: OptionalEmailList = Field(default=None, description="CC addresses")
    body_type: str = Field(default="HTML", description="HTML or Text")


@router.post("/schedule-email", summary="Schedule an email for future sending")
async def schedule_email(req: ScheduleEmailRequest, _=Depends(_get_api_key)):
    payload: dict = {"subject": req.subject, "body": req.body, "to": req.to, "send_at": req.send_at, "body_type": req.body_type}
    if req.cc: payload["cc"] = req.cc
    return await _run("schedule_send", payload)


class CancelScheduledRequest(BaseModel):
    message_id: str = Field(description="Scheduled email message ID")


@router.post("/cancel-scheduled-email", summary="Cancel a scheduled email (draft kept)")
async def cancel_scheduled_email(req: CancelScheduledRequest, _=Depends(_get_api_key)):
    return await _run("cancel_scheduled_send", {"message_id": req.message_id})


class ArchiveEmailRequest(BaseModel):
    message_id: str = Field(description="Email message ID to archive")


@router.post("/archive-email", summary="Move an email to Archive")
async def archive_email(req: ArchiveEmailRequest, _=Depends(_get_api_key)):
    return await _run("archive_email", {"message_id": req.message_id})


# =====================
# Outlook Calendar
# =====================

class ListEventsRequest(BaseModel):
    start: str | None = Field(default=None, description="Start date in ISO format (defaults to now)")
    end: str | None = Field(default=None, description="End date in ISO format (defaults to 7 days from start)")
    top: int = Field(default=20, description="Max events to return")


@router.post("/list-events", summary="List Outlook calendar events")
async def list_events(req: ListEventsRequest, _=Depends(_get_api_key)):
    payload: dict = {"top": req.top}
    if req.start: payload["start"] = req.start
    if req.end: payload["end"] = req.end
    return await _run("list_events", payload)


class CreateEventRequest(BaseModel):
    subject: str = Field(description="Event title")
    start: str = Field(description="Start time in ISO format, e.g. 2026-06-25T14:00:00")
    end: str = Field(description="End time in ISO format, e.g. 2026-06-25T15:00:00")
    location: str | None = Field(default=None, description="Location")
    body: str | None = Field(default=None, description="Description (HTML)")
    attendees: list[str] | None = Field(default=None, description="Attendee email addresses")
    is_all_day: bool = Field(default=False, description="All-day event")
    timezone_name: str = Field(default="Europe/London", description="Timezone")


@router.post("/create-event", summary="Create a calendar event")
async def create_event(req: CreateEventRequest, _=Depends(_get_api_key)):
    payload: dict = {"subject": req.subject, "start": req.start, "end": req.end, "timezone_name": req.timezone_name, "is_all_day": req.is_all_day}
    if req.location: payload["location"] = req.location
    if req.body: payload["body"] = req.body
    if req.attendees: payload["attendees"] = req.attendees
    return await _run("create_event", payload)


class UpdateEventRequest(BaseModel):
    event_id: str = Field(description="Event ID from list-events")
    subject: str | None = Field(default=None, description="New title")
    start: str | None = Field(default=None, description="New start time in ISO format")
    end: str | None = Field(default=None, description="New end time in ISO format")
    location: str | None = Field(default=None, description="New location")
    body: str | None = Field(default=None, description="New description")
    attendees: list[str] | None = Field(default=None, description="New attendee list")
    timezone_name: str = Field(default="Europe/London", description="Timezone")


@router.post("/update-event", summary="Update a calendar event")
async def update_event(req: UpdateEventRequest, _=Depends(_get_api_key)):
    payload: dict = {"event_id": req.event_id, "timezone_name": req.timezone_name}
    if req.subject is not None: payload["subject"] = req.subject
    if req.start is not None: payload["start"] = req.start
    if req.end is not None: payload["end"] = req.end
    if req.location is not None: payload["location"] = req.location
    if req.body is not None: payload["body"] = req.body
    if req.attendees is not None: payload["attendees"] = req.attendees
    return await _run("update_event", payload)


class CancelEventRequest(BaseModel):
    event_id: str = Field(description="Event ID to cancel")


@router.post("/cancel-event", summary="Cancel/delete a calendar event")
async def cancel_event(req: CancelEventRequest, _=Depends(_get_api_key)):
    return await _run("cancel_event", {"event_id": req.event_id})


class FindSlotsRequest(BaseModel):
    start: str = Field(description="Start of search range in ISO format")
    end: str = Field(description="End of search range in ISO format")
    duration_minutes: int = Field(default=30, description="Minimum slot duration in minutes")


@router.post("/find-available-slots", summary="Find free calendar slots")
async def find_available_slots(req: FindSlotsRequest, _=Depends(_get_api_key)):
    return await _run("find_available_slots", {"start": req.start, "end": req.end, "duration_minutes": req.duration_minutes})


class AddAttachmentRequest(BaseModel):
    message_id: str = Field(description="Draft message ID")
    file_path: str = Field(description="Absolute path to file on the agent's Mac")
    filename: str | None = Field(default=None, description="Display name for the attachment")


@router.post("/add-attachment", summary="Add a file attachment to an email draft")
async def add_attachment(req: AddAttachmentRequest, _=Depends(_get_api_key)):
    payload: dict = {"message_id": req.message_id, "file_path": req.file_path}
    if req.filename: payload["filename"] = req.filename
    return await _run("add_attachment", payload)


# =====================
# Gmail
# =====================

class GmailSearchRequest(BaseModel):
    query: str = Field(description="Gmail search query (e.g. 'from:someone subject:hello is:unread')")
    max_results: int = Field(default=10, description="Max results")


@router.post("/gmail-search", summary="Search Gmail emails")
async def gmail_search(req: GmailSearchRequest, _=Depends(_get_api_key)):
    return await _run("gmail_search", {"query": req.query, "max_results": req.max_results})


class GmailGetEmailRequest(BaseModel):
    message_id: str = Field(description="Gmail message ID from search results")


@router.post("/gmail-get-email", summary="Get full Gmail email content by ID")
async def gmail_get_email(req: GmailGetEmailRequest, _=Depends(_get_api_key)):
    return await _run("gmail_get_email", {"message_id": req.message_id})


class GmailGetThreadRequest(BaseModel):
    thread_id: str = Field(description="Gmail thread ID from get-email")


@router.post("/gmail-get-thread", summary="Get all emails in a Gmail thread")
async def gmail_get_thread(req: GmailGetThreadRequest, _=Depends(_get_api_key)):
    return await _run("gmail_get_thread", {"thread_id": req.thread_id})


class GmailCreateDraftRequest(BaseModel):
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body")
    to: EmailList = Field(description="Recipient email addresses")
    cc: OptionalEmailList = Field(default=None, description="CC addresses")
    body_type: str = Field(default="html", description="html or plain")


@router.post("/gmail-create-draft", summary="Create a Gmail draft. Does NOT send.")
async def gmail_create_draft(req: GmailCreateDraftRequest, _=Depends(_get_api_key)):
    payload: dict = {"subject": req.subject, "body": req.body, "to": req.to, "body_type": req.body_type}
    if req.cc: payload["cc"] = req.cc
    return await _run("gmail_create_draft", payload)


class GmailArchiveRequest(BaseModel):
    message_id: str = Field(description="Gmail message ID to archive")


@router.post("/gmail-archive", summary="Archive a Gmail email (remove from Inbox)")
async def gmail_archive(req: GmailArchiveRequest, _=Depends(_get_api_key)):
    return await _run("gmail_archive", {"message_id": req.message_id})


@router.post("/gmail-list-labels", summary="List all Gmail labels")
async def gmail_list_labels(_=Depends(_get_api_key)):
    return await _run("gmail_list_labels")


# =====================
# Google Calendar
# =====================

class GCalListEventsRequest(BaseModel):
    start: str | None = Field(default=None, description="Start date in ISO format (defaults to now)")
    end: str | None = Field(default=None, description="End date in ISO format (defaults to 7 days from start)")
    top: int = Field(default=20, description="Max events to return")


@router.post("/gcal-list-events", summary="List Google Calendar events")
async def gcal_list_events(req: GCalListEventsRequest, _=Depends(_get_api_key)):
    payload: dict = {"top": req.top}
    if req.start: payload["start"] = req.start
    if req.end: payload["end"] = req.end
    return await _run("gcal_list_events", payload)


class GCalCreateEventRequest(BaseModel):
    subject: str = Field(description="Event title")
    start: str = Field(description="Start time in ISO format")
    end: str = Field(description="End time in ISO format")
    location: str | None = Field(default=None, description="Location")
    body: str | None = Field(default=None, description="Description")
    attendees: list[str] | None = Field(default=None, description="Attendee email addresses")
    is_all_day: bool = Field(default=False, description="All-day event")
    timezone_name: str = Field(default="Europe/London", description="Timezone")


@router.post("/gcal-create-event", summary="Create a Google Calendar event")
async def gcal_create_event(req: GCalCreateEventRequest, _=Depends(_get_api_key)):
    payload: dict = {"subject": req.subject, "start": req.start, "end": req.end, "timezone_name": req.timezone_name, "is_all_day": req.is_all_day}
    if req.location: payload["location"] = req.location
    if req.body: payload["body"] = req.body
    if req.attendees: payload["attendees"] = req.attendees
    return await _run("gcal_create_event", payload)


# =====================
# iCloud Calendar (Personal)
# =====================

@router.post("/ical-list-calendars", summary="List all iCloud/Apple calendars")
async def ical_list_calendars(_=Depends(_get_api_key)):
    return await _run("ical_list_calendars")


class ICalListEventsRequest(BaseModel):
    start: str | None = Field(default=None, description="Start date in ISO format (defaults to now)")
    end: str | None = Field(default=None, description="End date in ISO format (defaults to 7 days from start)")
    calendar_name: str | None = Field(default=None, description="Calendar name filter")
    top: int = Field(default=50, description="Max events to return")


@router.post("/ical-list-events", summary="List personal iCloud calendar events (birthdays, holidays, personal)")
async def ical_list_events(req: ICalListEventsRequest, _=Depends(_get_api_key)):
    payload: dict = {"top": req.top}
    if req.start: payload["start"] = req.start
    if req.end: payload["end"] = req.end
    if req.calendar_name: payload["calendar_name"] = req.calendar_name
    return await _run("ical_list_events", payload)


class ICalCreateEventRequest(BaseModel):
    title: str = Field(description="Event title")
    start: str = Field(description="Start time in ISO format")
    end: str = Field(description="End time in ISO format")
    calendar_name: str | None = Field(default=None, description="Which calendar to create on")
    location: str | None = Field(default=None, description="Location")
    notes: str | None = Field(default=None, description="Notes/description")
    is_all_day: bool = Field(default=False, description="All-day event (use for birthdays)")
    timezone_name: str = Field(default="Europe/London", description="Timezone")


@router.post("/ical-create-event", summary="Create a personal iCloud calendar event")
async def ical_create_event(req: ICalCreateEventRequest, _=Depends(_get_api_key)):
    payload: dict = {"title": req.title, "start": req.start, "end": req.end, "is_all_day": req.is_all_day, "timezone_name": req.timezone_name}
    if req.calendar_name: payload["calendar_name"] = req.calendar_name
    if req.location: payload["location"] = req.location
    if req.notes: payload["notes"] = req.notes
    return await _run("ical_create_event", payload)


# =====================
# Support Tickets (read-only)
# =====================

class CBSListTicketsRequest(BaseModel):
    state: str = Field(default="open", description="Ticket state: open, hold, closed, snoozed, archived")
    per_page: int = Field(default=20, description="Max tickets to return")


@router.post("/cbs-list-tickets", summary="List CBS support tickets. Give a brief one-sentence summary per ticket, then ask if Ross wants more details on any.")
async def cbs_list_tickets(req: CBSListTicketsRequest, _=Depends(_get_api_key)):
    return await _run("cbs_list_tickets", {"state": req.state, "per_page": req.per_page})


class CBSGetTicketRequest(BaseModel):
    ticket_id: str = Field(description="Ticket ID from cbs-list-tickets")


@router.post("/cbs-get-ticket", summary="Get CBS ticket details and messages")
async def cbs_get_ticket(req: CBSGetTicketRequest, _=Depends(_get_api_key)):
    return await _run("cbs_get_ticket", {"ticket_id": req.ticket_id})


class CBSCloseTicketRequest(BaseModel):
    ticket_id: str = Field(description="Ticket ID to close")


@router.post("/cbs-close-ticket", summary="Close a CBS support ticket")
async def cbs_close_ticket(req: CBSCloseTicketRequest, _=Depends(_get_api_key)):
    return await _run("cbs_close_ticket", {"ticket_id": req.ticket_id})


class RCSCListTicketsRequest(BaseModel):
    state: str = Field(default="open", description="Ticket state: open, hold, closed, snoozed, archived")
    per_page: int = Field(default=20, description="Max tickets to return")


@router.post("/rcsc-list-tickets", summary="List RCSC support tickets. Give a brief one-sentence summary per ticket, then ask if Ross wants more details on any.")
async def rcsc_list_tickets(req: RCSCListTicketsRequest, _=Depends(_get_api_key)):
    return await _run("rcsc_list_tickets", {"state": req.state, "per_page": req.per_page})


class RCSCGetTicketRequest(BaseModel):
    ticket_id: str = Field(description="Ticket ID from rcsc-list-tickets")


@router.post("/rcsc-get-ticket", summary="Get RCSC ticket details and messages")
async def rcsc_get_ticket(req: RCSCGetTicketRequest, _=Depends(_get_api_key)):
    return await _run("rcsc_get_ticket", {"ticket_id": req.ticket_id})


class RCSCCloseTicketRequest(BaseModel):
    ticket_id: str = Field(description="Ticket ID to close")


@router.post("/rcsc-close-ticket", summary="Close an RCSC support ticket")
async def rcsc_close_ticket(req: RCSCCloseTicketRequest, _=Depends(_get_api_key)):
    return await _run("rcsc_close_ticket", {"ticket_id": req.ticket_id})


# =====================
# Voice Memos
# =====================

class ListRecordingsRequest(BaseModel):
    date: str | None = Field(default=None, description="Date filter in YYYY-MM-DD format")
    top: int = Field(default=10, description="Max results")


@router.post("/list-recordings", summary="List voice memo recordings")
async def list_recordings(req: ListRecordingsRequest, _=Depends(_get_api_key)):
    payload: dict = {"top": req.top}
    if req.date: payload["date"] = req.date
    return await _run("list_recordings", payload)


class TranscribeRequest(BaseModel):
    filename: str | None = Field(default=None, description="Exact filename in Meeting Recordings folder")
    date: str | None = Field(default=None, description="Date to find most recent recording (YYYY-MM-DD)")


@router.post("/transcribe-recording", summary="Transcribe a voice memo with speaker diarization")
async def transcribe_recording(req: TranscribeRequest, _=Depends(_get_api_key)):
    payload: dict = {}
    if req.filename: payload["filename"] = req.filename
    if req.date: payload["date"] = req.date
    return await _run("transcribe_recording", payload)


# =====================
# Apple Notes
# =====================

class SearchNotesRequest(BaseModel):
    query: str = Field(description="Search term (matches title or body)")
    folder: str | None = Field(default=None, description="Folder name to search within")
    top: int = Field(default=20, description="Max results")


@router.post("/search-notes", summary="Search Apple Notes")
async def search_notes(req: SearchNotesRequest, _=Depends(_get_api_key)):
    payload: dict = {"query": req.query, "top": req.top}
    if req.folder: payload["folder"] = req.folder
    return await _run("search_notes", payload)


class GetNoteRequest(BaseModel):
    note_id: str = Field(description="Note ID from search results")


@router.post("/get-note", summary="Get full Apple Note content")
async def get_note(req: GetNoteRequest, _=Depends(_get_api_key)):
    return await _run("get_note", {"note_id": req.note_id})


class CreateNoteRequest(BaseModel):
    title: str = Field(description="Note title")
    body: str = Field(description="Note body (plain text, or HTML if body_is_html is true)")
    folder: str | None = Field(default=None, description="Folder name (defaults to Notes)")
    body_is_html: bool = Field(default=False, description="If true, body is treated as raw HTML")


@router.post("/create-note", summary="Create a new Apple Note")
async def create_note(req: CreateNoteRequest, _=Depends(_get_api_key)):
    payload: dict = {"title": req.title, "body": req.body, "body_is_html": req.body_is_html}
    if req.folder: payload["folder"] = req.folder
    return await _run("create_note", payload)


@router.post("/list-note-folders", summary="List all Apple Notes folders")
async def list_note_folders(_=Depends(_get_api_key)):
    return await _run("list_note_folders")


# =====================
# Document Conversion
# =====================

class ConvertMdToPdfRequest(BaseModel):
    md_path: str = Field(description="Absolute path to the .md file on the agent's Mac")
    output_path: str | None = Field(default=None, description="Output path (defaults to same name with .pdf)")


@router.post("/convert-md-to-pdf", summary="Convert Markdown to PDF")
async def convert_md_to_pdf(req: ConvertMdToPdfRequest, _=Depends(_get_api_key)):
    payload: dict = {"md_path": req.md_path}
    if req.output_path: payload["output_path"] = req.output_path
    return await _run("convert_md_to_pdf", payload)


class ConvertMdToDocxRequest(BaseModel):
    md_path: str = Field(description="Absolute path to the .md file on the agent's Mac")
    output_path: str | None = Field(default=None, description="Output path (defaults to same name with .docx)")


@router.post("/convert-md-to-docx", summary="Convert Markdown to DOCX")
async def convert_md_to_docx(req: ConvertMdToDocxRequest, _=Depends(_get_api_key)):
    payload: dict = {"md_path": req.md_path}
    if req.output_path: payload["output_path"] = req.output_path
    return await _run("convert_md_to_docx", payload)


# =====================
# Daily Brief
# =====================

class DailyBriefRequest(BaseModel):
    date: str | None = Field(default=None, description="Date in YYYY-MM-DD format (defaults to today)")
    email_to: str | None = Field(default="r.calvert@rcsc.uk", description="Email address to send the brief to (defaults to r.calvert@rcsc.uk)")


@router.post("/daily-brief", summary="Generate Ross's daily brief PDF and email it. Gathers today's meetings and reminders into a printable tick-box PDF. Use for 'morning brief', 'daily brief', 'what's on today'.")
async def daily_brief(req: DailyBriefRequest, _=Depends(_get_api_key)):
    payload: dict = {}
    if req.date:
        payload["date"] = req.date
    if req.email_to:
        payload["email_to"] = req.email_to
    return await _run("daily_brief", payload)


# =====================
# Small Talk
# =====================

WMO_WEATHER = {
    0: "clear skies", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "icy fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "light showers", 81: "showers", 82: "heavy showers",
    95: "thunderstorms", 96: "thunderstorms with hail", 99: "heavy thunderstorms with hail",
}

# --- Cached weather (refreshed every 15 minutes in background) ---

@router.post("/local-weather", summary="DISABLED. Weather is currently turned off. Do not mention weather at all.", include_in_schema=False)
async def local_weather(_=Depends(_get_api_key)):
    return {"weather": None, "small_talk_level": "off", "message": "Weather is disabled. Do not mention weather."}


# =====================
# Feedback
# =====================

class SubmitFeedbackRequest(BaseModel):
    feedback: str = Field(description="The feedback Ross wants to record")
    source: str = Field(default="voice", description="Where the feedback came from")


@router.post("/submit-feedback", summary="Record feedback from Ross for later review and processing")
async def submit_feedback(req: SubmitFeedbackRequest, _=Depends(_get_api_key)):
    from relay.dashboard import record_feedback
    record_feedback(feedback=req.feedback, source=req.source)
    return {"status": "recorded", "message": "Feedback saved"}


# =====================
# Contacts
# =====================

class LookupContactRequest(BaseModel):
    name: str = Field(description="Contact name to look up (partial match)")


@router.post("/lookup-contact", summary="Look up a contact by name to get their email address")
async def lookup_contact(req: LookupContactRequest, _=Depends(_get_api_key)):
    from relay.dashboard import lookup_contact as _lookup
    contacts = _lookup(req.name)
    if not contacts:
        return {"contacts": [], "message": f"No contacts found matching '{req.name}'"}
    return {"contacts": [{"name": c["name"], "email": c["email"], "company": c.get("company", ""), "allowed_recipient": bool(c["allowed_recipient"])} for c in contacts]}


# =====================
# MP Portal (Development Tasks)
# =====================


@router.post("/mp-list-projects", summary="List all projects in the MP Portal")
async def mp_list_projects(_=Depends(_get_api_key)):
    return await _run("mp_list_projects")


class MPMatchProjectRequest(BaseModel):
    alias: str = Field(description="Folder name or alias to match against projects")


@router.post("/mp-match-project", summary="Match a project by folder name or alias")
async def mp_match_project(req: MPMatchProjectRequest, _=Depends(_get_api_key)):
    return await _run("mp_match_project", {"alias": req.alias})


@router.post("/mp-list-aliases", summary="List all saved project folder aliases")
async def mp_list_aliases(_=Depends(_get_api_key)):
    return await _run("mp_list_aliases")


class MPSaveAliasRequest(BaseModel):
    project_id: int = Field(description="The project ID")
    alias: str = Field(description="The folder name to associate with this project")


@router.post("/mp-save-alias", summary="Save a folder alias for a project")
async def mp_save_alias(req: MPSaveAliasRequest, _=Depends(_get_api_key)):
    return await _run("mp_save_alias", {"project_id": req.project_id, "alias": req.alias})


class MPDeleteAliasRequest(BaseModel):
    alias_id: int = Field(description="The alias ID to delete")


@router.post("/mp-delete-alias", summary="Delete a project folder alias")
async def mp_delete_alias(req: MPDeleteAliasRequest, _=Depends(_get_api_key)):
    return await _run("mp_delete_alias", {"alias_id": req.alias_id})


class MPCreateTaskRequest(BaseModel):
    title: str = Field(description="Task title (short summary)")
    description: str = Field(description="What needs to be done")
    project_name: str | None = Field(default=None, description="Project name, prefix, or partial match (e.g. ACHL, VSS)")
    project_id: int | None = Field(default=None, description="Project ID if already known")
    due_date: str | None = Field(default=None, description="Due date in YYYY-MM-DD format")
    chargeable: bool = Field(default=False, description="Whether this task is billable")
    estimated_hours: float | None = Field(default=None, description="Estimated hours for the task")


@router.post("/mp-create-task", summary="Create a new development task. Ask for title, description, and optionally hours. Auto-sets to in-progress and creates a reminder to upload files.")
async def mp_create_task(req: MPCreateTaskRequest, _=Depends(_get_api_key)):
    payload: dict = {"title": req.title, "description": req.description, "chargeable": req.chargeable}
    if req.project_name:
        payload["project_name"] = req.project_name
    if req.project_id:
        payload["project_id"] = req.project_id
    if req.due_date:
        payload["due_date"] = req.due_date
    if req.estimated_hours is not None:
        payload["estimated_hours"] = req.estimated_hours
    return await _run("mp_create_task", payload)


class MPUpdateTaskStatusRequest(BaseModel):
    status: str = Field(description="New status: in_progress, completed, or deployed")
    ref: str | None = Field(default=None, description="Task reference (e.g. EL-0186) or title")
    task_id: int | None = Field(default=None, description="Numeric task ID if known")
    chargeable: bool | None = Field(default=None, description="Set true to mark as billable (for deployed)")


@router.post("/mp-update-task-status", summary="Update a task's status. Use ref (e.g. EL-0186) or title, not numeric ID.")
async def mp_update_task_status(req: MPUpdateTaskStatusRequest, _=Depends(_get_api_key)):
    payload: dict = {"status": req.status}
    if req.ref:
        payload["ref"] = req.ref
    if req.task_id:
        payload["task_id"] = req.task_id
    if req.chargeable is not None:
        payload["chargeable"] = req.chargeable
    return await _run("mp_update_task_status", payload)


class MPGetTaskRequest(BaseModel):
    ref: str | None = Field(default=None, description="Task reference (e.g. EL-0186) or title")
    task_id: int | None = Field(default=None, description="Numeric task ID if known")


@router.post("/mp-get-task", summary="Get full details of a task. Use ref (e.g. EL-0186) or title.")
async def mp_get_task(req: MPGetTaskRequest, _=Depends(_get_api_key)):
    payload: dict = {}
    if req.ref:
        payload["ref"] = req.ref
    if req.task_id:
        payload["task_id"] = req.task_id
    return await _run("mp_get_task", payload)


class MPUpdateTaskRequest(BaseModel):
    ref: str | None = Field(default=None, description="Task reference (e.g. EL-0186) or title")
    task_id: int | None = Field(default=None, description="Numeric task ID if known")
    hours_taken: float | None = Field(default=None, description="Hours spent on the task")
    customer_due_date: str | None = Field(default=None, description="Due date YYYY-MM-DD")
    chargeable: bool | None = Field(default=None, description="Whether billable")
    title: str | None = Field(default=None, description="Updated title")
    description: str | None = Field(default=None, description="Updated description")


@router.post("/mp-update-task", summary="Update task fields. Use ref (e.g. EL-0186) or title, not numeric ID.")
async def mp_update_task(req: MPUpdateTaskRequest, _=Depends(_get_api_key)):
    payload: dict = {}
    if req.ref:
        payload["ref"] = req.ref
    if req.task_id:
        payload["task_id"] = req.task_id
    if req.hours_taken is not None:
        payload["hours_taken"] = req.hours_taken
    if req.customer_due_date is not None:
        payload["customer_due_date"] = req.customer_due_date
    if req.chargeable is not None:
        payload["chargeable"] = req.chargeable
    if req.title is not None:
        payload["title"] = req.title
    if req.description is not None:
        payload["description"] = req.description
    return await _run("mp_update_task", payload)


class MPSearchTasksRequest(BaseModel):
    query: str = Field(description="Search term (matches title or task reference like ACME-0042)")


@router.post("/mp-search-tasks", summary="Search active tasks by title or task ID")
async def mp_search_tasks(req: MPSearchTasksRequest, _=Depends(_get_api_key)):
    return await _run("mp_search_tasks", {"query": req.query})


@router.post("/mp-in-progress-tasks", summary="List all tasks currently in progress")
async def mp_in_progress_tasks(_=Depends(_get_api_key)):
    return await _run("mp_in_progress_tasks")


@router.post("/mp-my-tasks", summary="Get outstanding tasks assigned to Ross")
async def mp_my_tasks(_=Depends(_get_api_key)):
    return await _run("mp_my_tasks")


@router.post("/mp-overdue-tasks", summary="Get tasks past their due date")
async def mp_overdue_tasks(_=Depends(_get_api_key)):
    return await _run("mp_overdue_tasks")


@router.post("/mp-recent-tasks", summary="Get recently created or updated tasks")
async def mp_recent_tasks(_=Depends(_get_api_key)):
    return await _run("mp_recent_tasks")


@router.post("/mp-outstanding-summary", summary="Get total outstanding task count with status breakdown")
async def mp_outstanding_summary(_=Depends(_get_api_key)):
    return await _run("mp_outstanding_summary")


@router.post("/mp-outstanding-by-project", summary="Get outstanding task counts by project")
async def mp_outstanding_by_project(_=Depends(_get_api_key)):
    return await _run("mp_outstanding_by_project")


@router.post("/mp-billable-summary", summary="Get billable tasks summary with hours and amounts")
async def mp_billable_summary(_=Depends(_get_api_key)):
    return await _run("mp_billable_summary")


@router.post("/mp-activity-recent", summary="Get recent activity log across all projects")
async def mp_activity_recent(_=Depends(_get_api_key)):
    return await _run("mp_activity_recent")


class MPListCustomersRequest(BaseModel):
    q: str | None = Field(default=None, description="Optional search term (company, name, email or postcode)")


@router.post("/mp-list-customers", summary="List or search MP Portal customers. Use to find an existing customer before creating one.")
async def mp_list_customers(req: MPListCustomersRequest, _=Depends(_get_api_key)):
    payload = {"q": req.q} if req.q else {}
    return await _run("mp_list_customers", payload)


class MPGetCustomerRequest(BaseModel):
    customer_id: int = Field(description="The portal customer id")


@router.post("/mp-get-customer", summary="Get one MP Portal customer with full site and invoice address")
async def mp_get_customer(req: MPGetCustomerRequest, _=Depends(_get_api_key)):
    return await _run("mp_get_customer", {"customer_id": req.customer_id})


class MPCreateCustomerRequest(BaseModel):
    name: str = Field(description="Customer/company name (required)")
    company_name: str | None = Field(default=None, description="Company name if different from name")
    address_line_1: str | None = Field(default=None, description="Site address line 1")
    address_line_2: str | None = Field(default=None, description="Site address line 2")
    city: str | None = Field(default=None, description="Site town/city")
    county: str | None = Field(default=None, description="Site county")
    postcode: str | None = Field(default=None, description="Site postcode")
    invoice_same_as_site: bool = Field(default=True, description="True if the invoice address matches the site address")
    invoice_address_line_1: str | None = Field(default=None, description="Invoice address line 1 (only if different)")
    invoice_address_line_2: str | None = Field(default=None, description="Invoice address line 2")
    invoice_city: str | None = Field(default=None, description="Invoice town/city")
    invoice_county: str | None = Field(default=None, description="Invoice county")
    invoice_postcode: str | None = Field(default=None, description="Invoice postcode")
    email: str | None = Field(default=None, description="Contact email")
    phone: str | None = Field(default=None, description="Contact phone")
    website: str | None = Field(default=None, description="Website")
    notes: str | None = Field(default=None, description="Free-text notes")


@router.post("/mp-create-customer", summary="Create a new MP Portal customer with full address. Confirm the full details with Ross before calling — this inserts a customer.")
async def mp_create_customer(req: MPCreateCustomerRequest, _=Depends(_get_api_key)):
    payload = {k: v for k, v in req.model_dump().items() if v is not None}
    return await _run("mp_create_customer", payload)


# =====================
# Agent Management
# =====================

class UpdateAgentRequest(BaseModel):
    agent_name: str | None = Field(default=None, description="Agent name to update (updates first available if omitted)")


@router.post("/update-agent", summary="Update agent — git pull, install deps, restart")
async def update_agent(req: UpdateAgentRequest, _=Depends(_get_api_key)):
    payload: dict = {}
    if req.agent_name: payload["agent_name"] = req.agent_name
    return await _run("update_agent", payload)
