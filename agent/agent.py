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
)
from agent.services.reminders import RemindersService

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("agent")


class Agent:
    def __init__(self):
        self.relay_url = os.getenv("RELAY_URL", "ws://localhost:8000/ws/agent")
        self.api_key = os.getenv("AGENT_API_KEY", "")
        self.agent_name = os.getenv("AGENT_NAME", platform.node())
        self.reminders = RemindersService()
        self._running = True

    async def connect(self):
        """Connect to relay and process commands."""
        headers = {"Authorization": f"Bearer {self.api_key}"}

        while self._running:
            try:
                logger.info(f"Connecting to relay at {self.relay_url}")
                async with websockets.connect(self.relay_url, additional_headers=headers) as ws:
                    # Register with relay
                    reg = AgentRegistration(
                        agent_name=self.agent_name,
                        machine_name=platform.node(),
                        capabilities=[
                            CommandType.CREATE_REMINDER,
                            CommandType.LIST_REMINDERS,
                            CommandType.COMPLETE_REMINDER,
                            CommandType.PING,
                        ],
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
