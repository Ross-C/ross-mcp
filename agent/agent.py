"""Local Mac agent — connects to relay via WebSocket, executes commands."""

import asyncio
import atexit
import json
import logging
import os
import platform
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import websockets
from aiohttp import web
from dotenv import load_dotenv

# Add project root to path for shared imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.messages import (
    AgentRegistration,
    Command,
    CommandType,
    Response,
    Status,
    CreateReminderPayload,
    ListRemindersPayload,
    CompleteReminderPayload,
    SearchEmailsPayload,
    GetEmailPayload,
    GetThreadPayload,
    CreateDraftPayload,
    DraftReplyPayload,
    UpdateDraftPayload,
    SendDraftPayload,
    SendEmailPayload,
    ScheduleSendPayload,
    CancelScheduledSendPayload,
    ArchiveEmailPayload,
    AddAttachmentPayload,
    ListEventsPayload,
    CreateEventPayload,
    UpdateEventPayload,
    CancelEventPayload,
    FindAvailableSlotsPayload,
    ConvertDocumentPayload,
    ListRecordingsPayload,
    TranscribeRecordingPayload,
    SearchNotesPayload,
    GetNotePayload,
    CreateNotePayload,
    ListNoteFoldersPayload,
    GmailSearchPayload,
    GmailGetEmailPayload,
    GmailGetThreadPayload,
    GmailCreateDraftPayload,
    GmailArchivePayload,
    GCalListEventsPayload,
    GCalCreateEventPayload,
    ICalListEventsPayload,
    ICalCreateEventPayload,
    CBSListTicketsPayload,
    CBSGetTicketPayload,
    CBSCloseTicketPayload,
    RCSCListTicketsPayload,
    RCSCGetTicketPayload,
    RCSCCloseTicketPayload,
    MPMatchProjectPayload,
    MPSaveAliasPayload,
    MPDeleteAliasPayload,
    MPCreateTaskPayload,
    MPUpdateTaskStatusPayload,
    MPGetTaskPayload,
    MPUpdateTaskPayload,
    MPSearchTasksPayload,
    MPListCustomersPayload,
    MPGetCustomerPayload,
    MPCreateCustomerPayload,
    DailyBriefPayload,
    UpdateAgentPayload,
)
from agent.services.reminders import RemindersService
from agent.services.outlook_auth import OutlookAuth
from agent.services.outlook_mail import OutlookMailService
from agent.services.outlook_calendar import OutlookCalendarService
from agent.services.google_auth import GoogleAuth
from agent.services.gmail import GmailService
from agent.services.google_calendar import GoogleCalendarService
from agent.services.apple_calendar import AppleCalendarService
from agent.services.notes import NotesService
from agent.services.voice_memos import VoiceMemosService
from agent.services.documents import DocumentService
from agent.services.enchant_cbs import EnchantCBSService
from agent.services.enchant_rcsc import EnchantRCSCService
from agent.services.mp_portal import MPPortalService
from agent.services.daily_brief import DailyBriefService

load_dotenv()
LOG_DIR = Path.home() / "Library/Logs/mcp-agent"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
# Rotating file handler so logs persist across restarts
from logging.handlers import RotatingFileHandler
_fh = RotatingFileHandler(LOG_DIR / "agent.log", maxBytes=2_000_000, backupCount=3)
_fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
logging.getLogger().addHandler(_fh)
logger = logging.getLogger("agent")


class Agent:
    def __init__(self):
        self.relay_url = os.getenv("RELAY_URL", "ws://localhost:8000/ws/agent")
        self.api_key = os.getenv("AGENT_API_KEY", "")
        self.agent_name = os.getenv("AGENT_NAME", platform.node())
        self.reminders = RemindersService()
        self.outlook_auth = OutlookAuth()
        self.mail = OutlookMailService(self.outlook_auth)
        self.calendar = OutlookCalendarService(self.outlook_auth)
        self.google_auth = GoogleAuth()
        self.gmail = GmailService(self.google_auth)
        self.gcal = GoogleCalendarService(self.google_auth)
        self.apple_calendar = AppleCalendarService()
        self.notes = NotesService()
        self.voice_memos = VoiceMemosService()
        self.documents = DocumentService()
        self.enchant_cbs = EnchantCBSService()
        self.enchant_rcsc = EnchantRCSCService()
        self.mp_portal = MPPortalService()
        self.daily_brief = DailyBriefService(
            reminders=self.reminders,
            calendar=self.calendar,
            apple_calendar=self.apple_calendar,
        )
        self._running = True
        self._version = self._get_git_version()

    @staticmethod
    def _get_git_version() -> str | None:
        """Get the current git commit hash."""
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=project_root, capture_output=True, text=True, timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    async def connect(self):
        """Connect to relay and process commands with exponential backoff."""
        headers = {"Authorization": f"Bearer {self.api_key}"}
        backoff = 5

        while self._running:
            try:
                logger.info(f"Connecting to relay at {self.relay_url}")
                async with websockets.connect(
                    self.relay_url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=10,
                    open_timeout=15,
                ) as ws:
                    # Register with relay
                    capabilities = [
                        CommandType.CREATE_REMINDER,
                        CommandType.LIST_REMINDERS,
                        CommandType.COMPLETE_REMINDER,
                        CommandType.CONVERT_MD_TO_PDF,
                        CommandType.CONVERT_MD_TO_DOCX,
                        CommandType.LIST_RECORDINGS,
                        CommandType.TRANSCRIBE_RECORDING,
                        CommandType.SEARCH_NOTES,
                        CommandType.GET_NOTE,
                        CommandType.CREATE_NOTE,
                        CommandType.LIST_NOTE_FOLDERS,
                        CommandType.DAILY_BRIEF,
                        CommandType.UPDATE_AGENT,
                    CommandType.PING,
                    ]
                    if self.apple_calendar._authorized:
                        capabilities.extend([
                            CommandType.ICAL_LIST_CALENDARS,
                            CommandType.ICAL_LIST_EVENTS,
                            CommandType.ICAL_CREATE_EVENT,
                        ])
                    if self.mp_portal.is_configured:
                        capabilities.extend([
                            CommandType.MP_LIST_PROJECTS,
                            CommandType.MP_MATCH_PROJECT,
                            CommandType.MP_LIST_ALIASES,
                            CommandType.MP_SAVE_ALIAS,
                            CommandType.MP_DELETE_ALIAS,
                            CommandType.MP_CREATE_TASK,
                            CommandType.MP_UPDATE_TASK_STATUS,
                            CommandType.MP_SEARCH_TASKS,
                            CommandType.MP_IN_PROGRESS_TASKS,
                            CommandType.MP_MY_TASKS,
                            CommandType.MP_OVERDUE_TASKS,
                            CommandType.MP_RECENT_TASKS,
                            CommandType.MP_GET_TASK,
                            CommandType.MP_UPDATE_TASK,
                            CommandType.MP_OUTSTANDING_SUMMARY,
                            CommandType.MP_OUTSTANDING_BY_PROJECT,
                            CommandType.MP_BILLABLE_SUMMARY,
                            CommandType.MP_ACTIVITY_RECENT,
                        ])
                    if self.enchant_cbs.is_configured:
                        capabilities.extend([
                            CommandType.CBS_LIST_TICKETS,
                            CommandType.CBS_GET_TICKET,
                            CommandType.CBS_CLOSE_TICKET,
                        ])
                    if self.enchant_rcsc.is_configured:
                        capabilities.extend([
                            CommandType.RCSC_LIST_TICKETS,
                            CommandType.RCSC_GET_TICKET,
                            CommandType.RCSC_CLOSE_TICKET,
                        ])
                    if self.google_auth.is_authenticated:
                        capabilities.extend([
                            CommandType.GMAIL_SEARCH,
                            CommandType.GMAIL_GET_EMAIL,
                            CommandType.GMAIL_GET_THREAD,
                            CommandType.GMAIL_CREATE_DRAFT,
                            CommandType.GMAIL_ARCHIVE,
                            CommandType.GMAIL_LIST_LABELS,
                            CommandType.GCAL_LIST_EVENTS,
                            CommandType.GCAL_CREATE_EVENT,
                        ])
                    if self.outlook_auth.is_authenticated:
                        capabilities.extend([
                            CommandType.SEARCH_EMAILS,
                            CommandType.GET_EMAIL,
                            CommandType.GET_THREAD,
                            CommandType.CREATE_DRAFT,
                            CommandType.DRAFT_REPLY,
                            CommandType.UPDATE_DRAFT,
                            CommandType.SEND_DRAFT,
                            CommandType.SEND_EMAIL,
                            CommandType.SCHEDULE_SEND,
                            CommandType.CANCEL_SCHEDULED_SEND,
                            CommandType.ARCHIVE_EMAIL,
                            CommandType.ADD_ATTACHMENT,
                            CommandType.LIST_EVENTS,
                            CommandType.CREATE_EVENT,
                            CommandType.UPDATE_EVENT,
                            CommandType.CANCEL_EVENT,
                            CommandType.FIND_AVAILABLE_SLOTS,
                        ])
                    reg = AgentRegistration(
                        agent_name=self.agent_name,
                        machine_name=platform.node(),
                        capabilities=capabilities,
                        version=self._version,
                    )
                    await ws.send(reg.model_dump_json())
                    logger.info(f"Registered as '{self.agent_name}' (version {self._version})")
                    backoff = 5  # Reset on successful connection

                    async for message in ws:
                        response = await self._handle_message(message)
                        await ws.send(response.model_dump_json())

            except websockets.ConnectionClosed:
                logger.warning(f"Connection to relay lost, reconnecting in {backoff}s...")
            except ConnectionRefusedError:
                logger.warning(f"Relay not available, retrying in {backoff}s...")
            except Exception as e:
                logger.error(f"Unexpected error: {e}, retrying in {backoff}s...")

            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)  # Back off up to 60s max

    async def _handle_message(self, raw: str) -> Response:
        """Parse and execute a command."""
        try:
            cmd = Command.model_validate_json(raw)
            logger.info(f"Received command: {cmd.type} (id={cmd.id})")

            match cmd.type:
                case CommandType.CREATE_REMINDER:
                    payload = CreateReminderPayload(**cmd.payload)
                    result = await asyncio.to_thread(
                        self.reminders.create_reminder,
                        title=payload.title,
                        notes=payload.notes,
                        due_date=payload.due_date,
                        list_name=payload.list_name,
                        priority=payload.priority,
                    )
                case CommandType.LIST_REMINDERS:
                    payload = ListRemindersPayload(**cmd.payload)
                    result = await asyncio.to_thread(
                        self.reminders.list_reminders,
                        list_name=payload.list_name,
                        include_completed=payload.include_completed,
                    )
                    result = {"reminders": result}
                case CommandType.COMPLETE_REMINDER:
                    payload = CompleteReminderPayload(**cmd.payload)
                    result = await asyncio.to_thread(
                        self.reminders.complete_reminder,
                        reminder_id=payload.reminder_id,
                    )
                # --- Outlook Email ---
                case CommandType.SEARCH_EMAILS:
                    p = SearchEmailsPayload(**cmd.payload)
                    result = await self.mail.search_emails(query=p.query, folder=p.folder, top=p.top)
                case CommandType.GET_EMAIL:
                    p = GetEmailPayload(**cmd.payload)
                    result = await self.mail.get_email(message_id=p.message_id)
                case CommandType.GET_THREAD:
                    p = GetThreadPayload(**cmd.payload)
                    result = await self.mail.get_thread(conversation_id=p.conversation_id, top=p.top)
                case CommandType.CREATE_DRAFT:
                    p = CreateDraftPayload(**cmd.payload)
                    result = await self.mail.create_draft(subject=p.subject, body=p.body, to=p.to, cc=p.cc, body_type=p.body_type)
                case CommandType.DRAFT_REPLY:
                    p = DraftReplyPayload(**cmd.payload)
                    result = await self.mail.draft_reply(message_id=p.message_id, body=p.body, cc=p.cc, body_type=p.body_type)
                case CommandType.UPDATE_DRAFT:
                    p = UpdateDraftPayload(**cmd.payload)
                    result = await self.mail.update_draft(message_id=p.message_id, subject=p.subject, body=p.body, to=p.to, cc=p.cc, body_type=p.body_type)
                case CommandType.SEND_DRAFT:
                    p = SendDraftPayload(**cmd.payload)
                    result = await self.mail.send_draft(message_id=p.message_id)
                case CommandType.SEND_EMAIL:
                    p = SendEmailPayload(**cmd.payload)
                    result = await self.mail.send_email(subject=p.subject, body=p.body, to=p.to, cc=p.cc, body_type=p.body_type)
                case CommandType.SCHEDULE_SEND:
                    p = ScheduleSendPayload(**cmd.payload)
                    result = await self.mail.schedule_send(subject=p.subject, body=p.body, to=p.to, send_at=p.send_at, cc=p.cc, body_type=p.body_type)
                case CommandType.CANCEL_SCHEDULED_SEND:
                    p = CancelScheduledSendPayload(**cmd.payload)
                    result = await self.mail.cancel_scheduled_send(message_id=p.message_id)
                case CommandType.ARCHIVE_EMAIL:
                    p = ArchiveEmailPayload(**cmd.payload)
                    result = await self.mail.archive_email(message_id=p.message_id)
                case CommandType.ADD_ATTACHMENT:
                    p = AddAttachmentPayload(**cmd.payload)
                    result = await self.mail.add_attachment(message_id=p.message_id, file_path=p.file_path, filename=p.filename)
                # --- Outlook Calendar ---
                case CommandType.LIST_EVENTS:
                    p = ListEventsPayload(**cmd.payload)
                    result = await self.calendar.list_events(start=p.start, end=p.end, top=p.top)
                case CommandType.CREATE_EVENT:
                    p = CreateEventPayload(**cmd.payload)
                    result = await self.calendar.create_event(
                        subject=p.subject, start=p.start, end=p.end, location=p.location,
                        body=p.body, attendees=p.attendees, is_all_day=p.is_all_day, timezone_name=p.timezone_name,
                    )
                case CommandType.UPDATE_EVENT:
                    p = UpdateEventPayload(**cmd.payload)
                    result = await self.calendar.update_event(
                        event_id=p.event_id, subject=p.subject, start=p.start, end=p.end,
                        location=p.location, body=p.body, attendees=p.attendees, timezone_name=p.timezone_name,
                    )
                case CommandType.CANCEL_EVENT:
                    p = CancelEventPayload(**cmd.payload)
                    result = await self.calendar.cancel_event(event_id=p.event_id, comment=p.comment)
                case CommandType.FIND_AVAILABLE_SLOTS:
                    p = FindAvailableSlotsPayload(**cmd.payload)
                    result = await self.calendar.find_available_slots(start=p.start, end=p.end, duration_minutes=p.duration_minutes)
                # --- Gmail ---
                case CommandType.GMAIL_SEARCH:
                    p = GmailSearchPayload(**cmd.payload)
                    result = await self.gmail.search_emails(query=p.query, max_results=p.max_results)
                case CommandType.GMAIL_GET_EMAIL:
                    p = GmailGetEmailPayload(**cmd.payload)
                    result = await self.gmail.get_email(message_id=p.message_id)
                case CommandType.GMAIL_GET_THREAD:
                    p = GmailGetThreadPayload(**cmd.payload)
                    result = await self.gmail.get_thread(thread_id=p.thread_id)
                case CommandType.GMAIL_CREATE_DRAFT:
                    p = GmailCreateDraftPayload(**cmd.payload)
                    result = await self.gmail.create_draft(subject=p.subject, body=p.body, to=p.to, cc=p.cc, body_type=p.body_type)
                case CommandType.GMAIL_ARCHIVE:
                    p = GmailArchivePayload(**cmd.payload)
                    result = await self.gmail.archive_email(message_id=p.message_id)
                case CommandType.GMAIL_LIST_LABELS:
                    result = await self.gmail.list_labels()
                # --- Google Calendar ---
                case CommandType.GCAL_LIST_EVENTS:
                    p = GCalListEventsPayload(**cmd.payload)
                    result = await self.gcal.list_events(start=p.start, end=p.end, top=p.top)
                case CommandType.GCAL_CREATE_EVENT:
                    p = GCalCreateEventPayload(**cmd.payload)
                    result = await self.gcal.create_event(
                        subject=p.subject, start=p.start, end=p.end, location=p.location,
                        body=p.body, attendees=p.attendees, is_all_day=p.is_all_day, timezone_name=p.timezone_name,
                    )
                # --- iCloud Calendar ---
                case CommandType.ICAL_LIST_CALENDARS:
                    result = await asyncio.to_thread(self.apple_calendar.list_calendars)
                case CommandType.ICAL_LIST_EVENTS:
                    p = ICalListEventsPayload(**cmd.payload)
                    result = await asyncio.to_thread(
                        self.apple_calendar.list_events,
                        start=p.start, end=p.end, calendar_name=p.calendar_name, top=p.top,
                    )
                case CommandType.ICAL_CREATE_EVENT:
                    p = ICalCreateEventPayload(**cmd.payload)
                    result = await asyncio.to_thread(
                        self.apple_calendar.create_event,
                        title=p.title, start=p.start, end=p.end, calendar_name=p.calendar_name,
                        location=p.location, notes=p.notes, is_all_day=p.is_all_day, timezone_name=p.timezone_name,
                    )
                # --- CBS Support (Enchant) ---
                case CommandType.CBS_LIST_TICKETS:
                    p = CBSListTicketsPayload(**cmd.payload)
                    result = await self.enchant_cbs.list_tickets(state=p.state, per_page=p.per_page)
                case CommandType.CBS_GET_TICKET:
                    p = CBSGetTicketPayload(**cmd.payload)
                    result = await self.enchant_cbs.get_ticket(ticket_id=p.ticket_id)
                case CommandType.CBS_CLOSE_TICKET:
                    p = CBSCloseTicketPayload(**cmd.payload)
                    result = await self.enchant_cbs.close_ticket(ticket_id=p.ticket_id)
                # --- RCSC Support (Enchant) ---
                case CommandType.RCSC_LIST_TICKETS:
                    p = RCSCListTicketsPayload(**cmd.payload)
                    result = await self.enchant_rcsc.list_tickets(state=p.state, per_page=p.per_page)
                case CommandType.RCSC_GET_TICKET:
                    p = RCSCGetTicketPayload(**cmd.payload)
                    result = await self.enchant_rcsc.get_ticket(ticket_id=p.ticket_id)
                case CommandType.RCSC_CLOSE_TICKET:
                    p = RCSCCloseTicketPayload(**cmd.payload)
                    result = await self.enchant_rcsc.close_ticket(ticket_id=p.ticket_id)
                # --- MP Portal ---
                case CommandType.MP_LIST_PROJECTS:
                    result = await self.mp_portal.list_projects()
                case CommandType.MP_MATCH_PROJECT:
                    p = MPMatchProjectPayload(**cmd.payload)
                    result = await self.mp_portal.match_project(alias=p.alias)
                case CommandType.MP_LIST_ALIASES:
                    result = await self.mp_portal.list_aliases()
                case CommandType.MP_SAVE_ALIAS:
                    p = MPSaveAliasPayload(**cmd.payload)
                    result = await self.mp_portal.save_alias(project_id=p.project_id, alias=p.alias)
                case CommandType.MP_DELETE_ALIAS:
                    p = MPDeleteAliasPayload(**cmd.payload)
                    result = await self.mp_portal.delete_alias(alias_id=p.alias_id)
                case CommandType.MP_CREATE_TASK:
                    p = MPCreateTaskPayload(**cmd.payload)
                    result = await self._handle_mp_create_task(p)
                case CommandType.MP_UPDATE_TASK_STATUS:
                    p = MPUpdateTaskStatusPayload(**cmd.payload)
                    tid = p.task_id or (await self._resolve_task_id(p.ref) if p.ref else None)
                    if not tid:
                        result = {"error": "Task not found. Provide a task reference (e.g. EL-0186) or title."}
                    else:
                        result = await self.mp_portal.update_task_status(
                            task_id=tid, status=p.status, chargeable=p.chargeable,
                        )
                case CommandType.MP_GET_TASK:
                    p = MPGetTaskPayload(**cmd.payload)
                    tid = p.task_id or (await self._resolve_task_id(p.ref) if p.ref else None)
                    if not tid:
                        result = {"error": "Task not found. Provide a task reference (e.g. EL-0186) or title."}
                    else:
                        result = await self.mp_portal.get_task(task_id=tid)
                case CommandType.MP_UPDATE_TASK:
                    p = MPUpdateTaskPayload(**cmd.payload)
                    tid = p.task_id or (await self._resolve_task_id(p.ref) if p.ref else None)
                    if not tid:
                        result = {"error": "Task not found. Provide a task reference (e.g. EL-0186) or title."}
                    else:
                        result = await self.mp_portal.update_task(
                            task_id=tid, hours_taken=p.hours_taken,
                            production_hours=p.production_hours, customer_due_date=p.customer_due_date,
                            chargeable=p.chargeable, title=p.title,
                            non_technical_description=p.description,
                        )
                case CommandType.MP_SEARCH_TASKS:
                    p = MPSearchTasksPayload(**cmd.payload)
                    result = await self.mp_portal.search_tasks(query=p.query)
                case CommandType.MP_LIST_CUSTOMERS:
                    p = MPListCustomersPayload(**cmd.payload)
                    result = await self.mp_portal.list_customers(q=p.q)
                case CommandType.MP_GET_CUSTOMER:
                    p = MPGetCustomerPayload(**cmd.payload)
                    result = await self.mp_portal.get_customer(customer_id=p.customer_id)
                case CommandType.MP_CREATE_CUSTOMER:
                    p = MPCreateCustomerPayload(**cmd.payload)
                    result = await self.mp_portal.create_customer(**p.model_dump())
                case CommandType.MP_IN_PROGRESS_TASKS:
                    result = await self.mp_portal.get_in_progress_tasks()
                case CommandType.MP_MY_TASKS:
                    result = await self.mp_portal.get_my_tasks()
                case CommandType.MP_OVERDUE_TASKS:
                    result = await self.mp_portal.get_overdue_tasks()
                case CommandType.MP_RECENT_TASKS:
                    result = await self.mp_portal.get_recent_tasks()
                case CommandType.MP_OUTSTANDING_SUMMARY:
                    result = await self.mp_portal.get_outstanding_summary()
                case CommandType.MP_OUTSTANDING_BY_PROJECT:
                    result = await self.mp_portal.get_outstanding_by_project()
                case CommandType.MP_BILLABLE_SUMMARY:
                    result = await self.mp_portal.get_billable_summary()
                case CommandType.MP_ACTIVITY_RECENT:
                    result = await self.mp_portal.get_recent_activity()
                # --- Daily Brief ---
                case CommandType.DAILY_BRIEF:
                    p = DailyBriefPayload(**cmd.payload)
                    result = await self.daily_brief.generate(date_str=p.date)
                # --- Documents ---
                case CommandType.CONVERT_MD_TO_PDF:
                    p = ConvertDocumentPayload(**cmd.payload)
                    result = await asyncio.to_thread(self.documents.convert_md_to_pdf, md_path=p.md_path, output_path=p.output_path)
                case CommandType.CONVERT_MD_TO_DOCX:
                    p = ConvertDocumentPayload(**cmd.payload)
                    result = await asyncio.to_thread(self.documents.convert_md_to_docx, md_path=p.md_path, output_path=p.output_path)
                # --- Voice Memos ---
                case CommandType.LIST_RECORDINGS:
                    p = ListRecordingsPayload(**cmd.payload)
                    result = await asyncio.to_thread(self.voice_memos.list_recordings, date=p.date, top=p.top)
                case CommandType.TRANSCRIBE_RECORDING:
                    p = TranscribeRecordingPayload(**cmd.payload)
                    result = await self.voice_memos.transcribe(filename=p.filename, date=p.date)
                # --- Apple Notes ---
                case CommandType.SEARCH_NOTES:
                    p = SearchNotesPayload(**cmd.payload)
                    result = await asyncio.to_thread(self.notes.search_notes, query=p.query, folder=p.folder, top=p.top)
                case CommandType.GET_NOTE:
                    p = GetNotePayload(**cmd.payload)
                    result = await asyncio.to_thread(self.notes.get_note, note_id=p.note_id)
                case CommandType.CREATE_NOTE:
                    p = CreateNotePayload(**cmd.payload)
                    result = await asyncio.to_thread(self.notes.create_note, title=p.title, body=p.body, folder=p.folder, body_is_html=p.body_is_html)
                case CommandType.LIST_NOTE_FOLDERS:
                    result = await asyncio.to_thread(self.notes.list_folders)
                case CommandType.UPDATE_AGENT:
                    result = await self._self_update()
                case CommandType.PING:
                    result = {"pong": True, "agent": self.agent_name}
                case _:
                    return Response(
                        command_id=cmd.id,
                        status=Status.ERROR,
                        error=f"Unknown command type: {cmd.type}",
                    )

            if isinstance(result, dict) and "error" in result:
                return Response(
                    command_id=cmd.id,
                    status=Status.ERROR,
                    error=result["error"],
                )

            return Response(
                command_id=cmd.id,
                status=Status.SUCCESS,
                data=result if isinstance(result, dict) else {"result": result},
            )

        except Exception as e:
            logger.exception("Error handling command")
            cmd_id = "unknown"
            try:
                cmd_id = json.loads(raw).get("id", "unknown")
            except Exception:
                pass
            return Response(
                command_id=cmd_id,
                status=Status.ERROR,
                error=str(e),
            )

    async def _resolve_task_id(self, ref: str) -> int | None:
        """Resolve a task reference (e.g. EL-0186 or title) to a numeric ID."""
        try:
            data = await self.mp_portal.resolve_task(ref)
            return data.get("id")
        except Exception as e:
            logger.warning(f"Failed to resolve task ref '{ref}': {e}")
            return None

    async def _handle_mp_create_task(self, p) -> dict:
        """Create a task with fuzzy project matching, auto in-progress, and reminder."""
        project_id = p.project_id
        project_name = None

        # Resolve project by name if no ID given
        if not project_id and p.project_name:
            match_result = await self.mp_portal.find_project(p.project_name)
            if match_result.get("confidence") == "high":
                project_id = match_result["project_id"]
                project_name = match_result["project_name"]
            else:
                return match_result

        if not project_id:
            return {"error": "No project_id or project_name provided"}

        # Create the task
        task_result = await self.mp_portal.create_task(
            project_id=project_id, title=p.title,
            description=p.description, due_date=p.due_date,
            chargeable=p.chargeable, estimated_hours=p.estimated_hours,
        )

        # Auto-set to in-progress
        task_id = task_result.get("task_id") or task_result.get("task", {}).get("id") or task_result.get("id")
        task_ref = task_result.get("project_task_id") or task_result.get("task", {}).get("reference") or ""
        if task_id:
            try:
                await self.mp_portal.update_task_status(task_id=task_id, status="in_progress")
                task_result["status_set"] = "in_progress"
            except Exception as e:
                logger.warning(f"Failed to set task to in_progress: {e}")

        # Create reminder to upload files
        if task_id:
            try:
                reminder_title = f"Upload files for {task_ref or task_id}: {p.title}"
                self.reminders.create_reminder(title=reminder_title, list_name="Reminders")
                task_result["reminder_created"] = True
            except Exception as e:
                logger.warning(f"Failed to create upload reminder: {e}")

        if project_name:
            task_result["project_name"] = project_name
        return task_result

    async def _self_update(self) -> dict:
        """Pull latest code from git, install deps, then schedule a restart."""
        import subprocess as sp
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        try:
            pull = sp.run(["git", "pull"], cwd=project_root, capture_output=True, text=True, timeout=30)
            if pull.returncode != 0:
                return {"error": f"git pull failed: {pull.stderr.strip()}"}

            pip = sp.run(
                [sys.executable, "-m", "pip", "install", "-q", "-r", "agent/requirements.txt"],
                cwd=project_root, capture_output=True, text=True, timeout=60,
            )

            # Schedule restart after response is sent
            async def _delayed_exit():
                await asyncio.sleep(2)
                logger.info("Restarting after self-update...")
                os._exit(0)  # launchd KeepAlive restarts us

            asyncio.get_event_loop().create_task(_delayed_exit())

            return {
                "status": "updated",
                "agent": self.agent_name,
                "git": pull.stdout.strip(),
                "pip": "ok" if pip.returncode == 0 else pip.stderr.strip()[:200],
                "restarting": True,
            }
        except Exception as e:
            return {"error": f"Self-update failed: {e}"}

    def stop(self):
        self._running = False


async def run_web_ui(reminders: RemindersService, port: int = 8001):
    """Run the local web UI alongside the agent."""
    from agent.web import create_app, set_reminders_service
    set_reminders_service(reminders)
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    logger.info(f"Agent web UI running at http://127.0.0.1:{port}")
    return runner


async def run(web_port: int = 8001):
    agent = Agent()

    if not agent.reminders.authorize():
        logger.error("Cannot access Reminders — check System Settings > Privacy > Reminders")
        return

    if not agent.apple_calendar.authorize():
        logger.warning("Cannot access Calendar — check System Settings > Privacy > Calendars")

    # Google auth — try saved tokens first, prompt login if needed
    if agent.google_auth.client_id:
        if not await agent.google_auth.authorize():
            logger.warning("Google not authenticated — Gmail/GCal commands unavailable")
        else:
            await agent.google_auth.start_background_refresh()
    else:
        logger.info("GOOGLE_CLIENT_ID not set — Gmail/GCal integration disabled")

    # Outlook auth — try saved tokens first, prompt login if needed
    if agent.outlook_auth.client_id:
        if not await agent.outlook_auth.authorize():
            logger.warning("Outlook not authenticated — email/calendar commands unavailable")
        else:
            await agent.outlook_auth.start_background_refresh()
    else:
        logger.info("MS_CLIENT_ID not set — Outlook integration disabled")

    runner = await run_web_ui(agent.reminders, web_port)

    try:
        await agent.connect()
    finally:
        await runner.cleanup()


LOCK_FILE = os.path.join(tempfile.gettempdir(), "ross-mcp-agent.lock")


def acquire_lock():
    """Ensure only one agent runs at a time using a PID lock file."""
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                old_pid = int(f.read().strip())
            # Check if process is still running
            os.kill(old_pid, 0)
            logger.error(f"Agent already running (PID {old_pid}). Exiting.")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            # Process is dead, stale lock file
            pass

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(release_lock)


def release_lock():
    """Remove the lock file on exit."""
    try:
        os.remove(LOCK_FILE)
    except FileNotFoundError:
        pass


def main():
    acquire_lock()

    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    web_port = int(os.getenv("AGENT_WEB_PORT", "8001"))
    asyncio.run(run(web_port))


if __name__ == "__main__":
    main()
