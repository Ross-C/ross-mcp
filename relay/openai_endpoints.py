"""REST endpoints with full OpenAPI docs for ChatGPT Custom GPT Actions.

Each tool gets its own endpoint with typed request/response models,
giving ChatGPT complete parameter visibility via the OpenAPI spec.
"""

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

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
    from shared.messages import CommandType
    result = await _execute_command(CommandType(command_type), payload)
    return result.get("data", result)


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
    query: str = Field(description="Search query (matches subject, body, sender)")
    folder: str | None = Field(default=None, description="Folder: inbox, sentitems, drafts, archive")
    top: int = Field(default=10, description="Max results")


@router.post("/search-emails", summary="Search Outlook emails")
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
    to: list[str] = Field(description="Recipient email addresses")
    cc: list[str] | None = Field(default=None, description="CC addresses")
    body_type: str = Field(default="HTML", description="Always use HTML")


@router.post("/create-draft", summary="Create an Outlook email draft. Enrich the user's input into a polished email in Ross's style.")
async def create_draft(req: CreateDraftRequest, _=Depends(_get_api_key)):
    payload: dict = {"subject": req.subject, "body": req.body, "to": req.to, "body_type": req.body_type}
    if req.cc: payload["cc"] = req.cc
    return await _run("create_draft", payload)


class DraftReplyRequest(BaseModel):
    message_id: str = Field(description="Message ID of the email to reply to")
    body: str = Field(description="Reply body in HTML. Wrap in Aptos font div. Use <p> tags for paragraphs. Always enrich and polish the user's input, never parrot verbatim. No em dashes or hyphens joining clauses. Sign off Kind regards / Ross.")
    cc: list[str] | None = Field(default=None, description="CC addresses to add")
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
    to: list[str] | None = Field(default=None, description="New recipients")
    cc: list[str] | None = Field(default=None, description="New CC list")
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
    to: list[str] = Field(description="Recipient email addresses")
    cc: list[str] | None = Field(default=None, description="CC addresses")
    body_type: str = Field(default="HTML", description="HTML or Text")


@router.post("/send-email", summary="Send an email immediately")
async def send_email(req: SendEmailRequest, _=Depends(_get_api_key)):
    payload: dict = {"subject": req.subject, "body": req.body, "to": req.to, "body_type": req.body_type}
    if req.cc: payload["cc"] = req.cc
    return await _run("send_email", payload)


class ScheduleEmailRequest(BaseModel):
    subject: str = Field(description="Email subject")
    body: str = Field(description="Email body (HTML by default)")
    to: list[str] = Field(description="Recipient email addresses")
    send_at: str = Field(description="When to send in ISO format, e.g. 2026-06-25T09:00:00")
    cc: list[str] | None = Field(default=None, description="CC addresses")
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
# Gmail (disabled until Google OAuth is configured)
# =====================
# Uncomment when GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set in .env


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
# Agent Management
# =====================

class UpdateAgentRequest(BaseModel):
    agent_name: str | None = Field(default=None, description="Agent name to update (updates first available if omitted)")


@router.post("/update-agent", summary="Update agent — git pull, install deps, restart")
async def update_agent(req: UpdateAgentRequest, _=Depends(_get_api_key)):
    payload: dict = {}
    if req.agent_name: payload["agent_name"] = req.agent_name
    return await _run("update_agent", payload)
