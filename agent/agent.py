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
    UpdateAgentPayload,
)
from agent.services.reminders import RemindersService
from agent.services.outlook_auth import OutlookAuth
from agent.services.outlook_mail import OutlookMailService
from agent.services.outlook_calendar import OutlookCalendarService
from agent.services.google_auth import GoogleAuth
from agent.services.gmail import GmailService
from agent.services.notes import NotesService
from agent.services.voice_memos import VoiceMemosService
from agent.services.documents import DocumentService

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
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
        self.notes = NotesService()
        self.voice_memos = VoiceMemosService()
        self.documents = DocumentService()
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
        """Connect to relay and process commands."""
        headers = {"Authorization": f"Bearer {self.api_key}"}

        while self._running:
            try:
                logger.info(f"Connecting to relay at {self.relay_url}")
                async with websockets.connect(self.relay_url, additional_headers=headers) as ws:
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
                        CommandType.UPDATE_AGENT,
                    CommandType.PING,
                    ]
                    if self.google_auth.is_authenticated:
                        capabilities.extend([
                            CommandType.GMAIL_SEARCH,
                            CommandType.GMAIL_GET_EMAIL,
                            CommandType.GMAIL_GET_THREAD,
                            CommandType.GMAIL_CREATE_DRAFT,
                            CommandType.GMAIL_ARCHIVE,
                            CommandType.GMAIL_LIST_LABELS,
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

                    async for message in ws:
                        response = await self._handle_message(message)
                        await ws.send(response.model_dump_json())

            except websockets.ConnectionClosed:
                logger.warning("Connection to relay lost, reconnecting in 5s...")
            except ConnectionRefusedError:
                logger.warning("Relay not available, retrying in 5s...")
            except Exception as e:
                logger.error(f"Unexpected error: {e}, retrying in 5s...")

            if self._running:
                await asyncio.sleep(5)

    async def _handle_message(self, raw: str) -> Response:
        """Parse and execute a command."""
        try:
            cmd = Command.model_validate_json(raw)
            logger.info(f"Received command: {cmd.type} (id={cmd.id})")

            match cmd.type:
                case CommandType.CREATE_REMINDER:
                    payload = CreateReminderPayload(**cmd.payload)
                    result = self.reminders.create_reminder(
                        title=payload.title,
                        notes=payload.notes,
                        due_date=payload.due_date,
                        list_name=payload.list_name,
                        priority=payload.priority,
                    )
                case CommandType.LIST_REMINDERS:
                    payload = ListRemindersPayload(**cmd.payload)
                    result = self.reminders.list_reminders(
                        list_name=payload.list_name,
                        include_completed=payload.include_completed,
                    )
                    result = {"reminders": result}
                case CommandType.COMPLETE_REMINDER:
                    payload = CompleteReminderPayload(**cmd.payload)
                    result = self.reminders.complete_reminder(
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
                # --- Documents ---
                case CommandType.CONVERT_MD_TO_PDF:
                    p = ConvertDocumentPayload(**cmd.payload)
                    result = self.documents.convert_md_to_pdf(md_path=p.md_path, output_path=p.output_path)
                case CommandType.CONVERT_MD_TO_DOCX:
                    p = ConvertDocumentPayload(**cmd.payload)
                    result = self.documents.convert_md_to_docx(md_path=p.md_path, output_path=p.output_path)
                # --- Voice Memos ---
                case CommandType.LIST_RECORDINGS:
                    p = ListRecordingsPayload(**cmd.payload)
                    result = self.voice_memos.list_recordings(date=p.date, top=p.top)
                case CommandType.TRANSCRIBE_RECORDING:
                    p = TranscribeRecordingPayload(**cmd.payload)
                    result = await self.voice_memos.transcribe(filename=p.filename, date=p.date)
                # --- Apple Notes ---
                case CommandType.SEARCH_NOTES:
                    p = SearchNotesPayload(**cmd.payload)
                    result = self.notes.search_notes(query=p.query, folder=p.folder, top=p.top)
                case CommandType.GET_NOTE:
                    p = GetNotePayload(**cmd.payload)
                    result = self.notes.get_note(note_id=p.note_id)
                case CommandType.CREATE_NOTE:
                    p = CreateNotePayload(**cmd.payload)
                    result = self.notes.create_note(title=p.title, body=p.body, folder=p.folder, body_is_html=p.body_is_html)
                case CommandType.LIST_NOTE_FOLDERS:
                    result = self.notes.list_folders()
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
