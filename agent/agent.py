"""Local Mac agent — connects to relay via WebSocket, executes commands."""

import asyncio
import atexit
import json
import logging
import os
import platform
import signal
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
    UpdateDraftPayload,
    SendDraftPayload,
    SendEmailPayload,
    ScheduleSendPayload,
    CancelScheduledSendPayload,
    ArchiveEmailPayload,
    ListEventsPayload,
    CreateEventPayload,
    UpdateEventPayload,
    CancelEventPayload,
    FindAvailableSlotsPayload,
)
from agent.services.reminders import RemindersService
from agent.services.outlook_auth import OutlookAuth
from agent.services.outlook_mail import OutlookMailService
from agent.services.outlook_calendar import OutlookCalendarService

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
        self._running = True

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
                        CommandType.PING,
                    ]
                    if self.outlook_auth.is_authenticated:
                        capabilities.extend([
                            CommandType.SEARCH_EMAILS,
                            CommandType.GET_EMAIL,
                            CommandType.GET_THREAD,
                            CommandType.CREATE_DRAFT,
                            CommandType.UPDATE_DRAFT,
                            CommandType.SEND_DRAFT,
                            CommandType.SEND_EMAIL,
                            CommandType.SCHEDULE_SEND,
                            CommandType.CANCEL_SCHEDULED_SEND,
                            CommandType.ARCHIVE_EMAIL,
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
                    )
                    await ws.send(reg.model_dump_json())
                    logger.info(f"Registered as '{self.agent_name}'")

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
