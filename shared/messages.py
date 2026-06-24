"""Shared message schemas for agent-relay communication."""

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
from datetime import datetime


# --- Enums ---

class CommandType(str, Enum):
    CREATE_REMINDER = "create_reminder"
    LIST_REMINDERS = "list_reminders"
    COMPLETE_REMINDER = "complete_reminder"
    # Outlook Email
    SEARCH_EMAILS = "search_emails"
    GET_EMAIL = "get_email"
    GET_THREAD = "get_thread"
    CREATE_DRAFT = "create_draft"
    UPDATE_DRAFT = "update_draft"
    SEND_DRAFT = "send_draft"
    SEND_EMAIL = "send_email"
    SCHEDULE_SEND = "schedule_send"
    CANCEL_SCHEDULED_SEND = "cancel_scheduled_send"
    ARCHIVE_EMAIL = "archive_email"
    # Outlook Calendar
    LIST_EVENTS = "list_events"
    CREATE_EVENT = "create_event"
    UPDATE_EVENT = "update_event"
    CANCEL_EVENT = "cancel_event"
    FIND_AVAILABLE_SLOTS = "find_available_slots"
    # Voice Memos
    LIST_RECORDINGS = "list_recordings"
    TRANSCRIBE_RECORDING = "transcribe_recording"
    # Apple Notes
    SEARCH_NOTES = "search_notes"
    GET_NOTE = "get_note"
    CREATE_NOTE = "create_note"
    LIST_NOTE_FOLDERS = "list_note_folders"
    PING = "ping"


class Priority(int, Enum):
    NONE = 0
    LOW = 1
    MEDIUM = 5
    HIGH = 9


class Status(str, Enum):
    SUCCESS = "success"
    ERROR = "error"


# --- Command Payloads ---

class CreateReminderPayload(BaseModel):
    title: str
    notes: str | None = None
    due_date: datetime | None = None
    list_name: str | None = None
    priority: Priority = Priority.NONE


class ListRemindersPayload(BaseModel):
    list_name: str | None = None
    include_completed: bool = False


class CompleteReminderPayload(BaseModel):
    reminder_id: str


# --- Outlook Email Payloads ---

class SearchEmailsPayload(BaseModel):
    query: str
    folder: str | None = None
    top: int = 10


class GetEmailPayload(BaseModel):
    message_id: str


class GetThreadPayload(BaseModel):
    conversation_id: str
    top: int = 25


class CreateDraftPayload(BaseModel):
    subject: str
    body: str
    to: list[str]
    cc: list[str] | None = None
    body_type: str = "HTML"


class UpdateDraftPayload(BaseModel):
    message_id: str
    subject: str | None = None
    body: str | None = None
    to: list[str] | None = None
    cc: list[str] | None = None
    body_type: str = "HTML"


class SendDraftPayload(BaseModel):
    message_id: str


class SendEmailPayload(BaseModel):
    subject: str
    body: str
    to: list[str]
    cc: list[str] | None = None
    body_type: str = "HTML"


class ScheduleSendPayload(BaseModel):
    subject: str
    body: str
    to: list[str]
    send_at: datetime
    cc: list[str] | None = None
    body_type: str = "HTML"


class CancelScheduledSendPayload(BaseModel):
    message_id: str


class ArchiveEmailPayload(BaseModel):
    message_id: str


# --- Outlook Calendar Payloads ---

class ListEventsPayload(BaseModel):
    start: datetime | None = None
    end: datetime | None = None
    top: int = 20


class CreateEventPayload(BaseModel):
    subject: str
    start: datetime
    end: datetime
    location: str | None = None
    body: str | None = None
    attendees: list[str] | None = None
    is_all_day: bool = False
    timezone_name: str = "Europe/London"


class UpdateEventPayload(BaseModel):
    event_id: str
    subject: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    location: str | None = None
    body: str | None = None
    attendees: list[str] | None = None
    timezone_name: str = "Europe/London"


class CancelEventPayload(BaseModel):
    event_id: str
    comment: str | None = None


class FindAvailableSlotsPayload(BaseModel):
    start: datetime
    end: datetime
    duration_minutes: int = 30


# --- Apple Notes Payloads ---

class ListRecordingsPayload(BaseModel):
    date: str | None = None
    top: int = 10


class TranscribeRecordingPayload(BaseModel):
    filename: str | None = None
    date: str | None = None


class SearchNotesPayload(BaseModel):
    query: str
    folder: str | None = None
    top: int = 20


class GetNotePayload(BaseModel):
    note_id: str


class CreateNotePayload(BaseModel):
    title: str
    body: str
    folder: str | None = None
    body_is_html: bool = False


class ListNoteFoldersPayload(BaseModel):
    pass


# --- Messages ---

class Command(BaseModel):
    """Message sent from relay to agent."""
    id: str = Field(description="Unique command ID for tracking")
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)


class Response(BaseModel):
    """Message sent from agent back to relay."""
    command_id: str = Field(description="ID of the command this responds to")
    status: Status
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AgentRegistration(BaseModel):
    """Sent by agent on WebSocket connect."""
    agent_name: str
    machine_name: str
    capabilities: list[CommandType]
