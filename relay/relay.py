"""Cloud relay — WebSocket hub for agents, HTTP API for commands."""

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.messages import AgentRegistration, Command, CommandType, Response

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("relay")

API_KEY = os.getenv("RELAY_API_KEY", "")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app):
    # Record relay startup
    from relay.dashboard import record_update
    ver = os.getenv("GIT_VERSION", "")
    msg = os.getenv("GIT_MESSAGE", "")
    record_update("relay", f"Relay deployed: {msg}" if msg else "Relay deployed and started", version=ver or None)

    # Start the MCP session manager (sub-app lifespans don't auto-run)
    from relay.mcp_endpoint import get_session_manager
    sm = get_session_manager()
    if sm:
        async with sm.run():
            yield
    else:
        yield


app = FastAPI(
    title="Ross MCP Relay",
    version="0.1.0",
    lifespan=lifespan,
    servers=[{"url": "https://ross-mcp-relay.fly.dev"}],
)
security = HTTPBearer()


# --- Error handlers (return clean errors for ElevenLabs/ChatGPT) ---

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    import json as _json
    errors = exc.errors()
    details = "; ".join(f"{e.get('loc', ['?'])[-1]}: {e.get('msg', 'invalid')}" for e in errors)
    error_msg = f"Invalid request: {details}"

    # Capture failed request for retry
    if request.url.path.startswith("/api/tools/"):
        try:
            body = exc.body if hasattr(exc, 'body') else {}
            from relay.dashboard import record_failed_request
            record_failed_request(
                endpoint=request.url.path,
                payload=_json.dumps(body) if body else "{}",
                error=error_msg,
                source=_detect_source(request),
            )
        except Exception:
            pass

    return JSONResponse(
        status_code=200,
        content={"error": error_msg},
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    # Only wrap errors as 200 for the ElevenLabs/ChatGPT tool endpoints
    if request.url.path.startswith("/api/tools/") and exc.status_code not in (401, 403):
        return JSONResponse(
            status_code=200,
            content={"error": f"Error ({exc.status_code}): {exc.detail}"},
        )
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


def _detect_source(request: Request) -> str:
    """Detect whether the request came from ElevenLabs, ChatGPT, or other."""
    ua = request.headers.get("user-agent", "")
    if "elevenlabs" in ua.lower() or "eleven" in ua.lower():
        return "elevenlabs"
    if "openai" in ua.lower() or "chatgpt" in ua.lower():
        return "chatgpt"
    return "api"


# --- Agent Registry ---

TASK_DESCRIPTIONS = {
    "search_emails": "Searching emails",
    "get_email": "Reading an email",
    "get_thread": "Reading email thread",
    "create_draft": "Drafting an email",
    "draft_reply": "Drafting a reply",
    "update_draft": "Updating a draft",
    "send_draft": "Sending a draft",
    "send_email": "Sending an email",
    "schedule_send": "Scheduling an email",
    "cancel_scheduled_send": "Cancelling scheduled email",
    "archive_email": "Archiving an email",
    "add_attachment": "Adding attachment",
    "list_events": "Checking calendar",
    "create_event": "Creating calendar event",
    "update_event": "Updating calendar event",
    "cancel_event": "Cancelling calendar event",
    "find_available_slots": "Finding free time slots",
    "create_reminder": "Creating a reminder",
    "list_reminders": "Listing reminders",
    "complete_reminder": "Completing a reminder",
    "search_notes": "Searching notes",
    "get_note": "Reading a note",
    "create_note": "Creating a note",
    "list_note_folders": "Listing note folders",
    "list_recordings": "Listing recordings",
    "transcribe_recording": "Transcribing a recording",
    "convert_md_to_pdf": "Converting to PDF",
    "convert_md_to_docx": "Converting to DOCX",
    "cbs_list_tickets": "Checking CBS tickets",
    "cbs_get_ticket": "Reading CBS ticket",
    "cbs_close_ticket": "Closing CBS ticket",
    "rcsc_list_tickets": "Checking RCSC tickets",
    "rcsc_get_ticket": "Reading RCSC ticket",
    "rcsc_close_ticket": "Closing RCSC ticket",
    "mp_list_projects": "Listing projects",
    "mp_match_project": "Matching project",
    "mp_list_aliases": "Listing project aliases",
    "mp_save_alias": "Saving project alias",
    "mp_delete_alias": "Deleting project alias",
    "mp_create_task": "Creating dev task",
    "mp_update_task_status": "Updating task status",
    "mp_search_tasks": "Searching tasks",
    "mp_in_progress_tasks": "Checking in-progress tasks",
    "mp_my_tasks": "Checking my tasks",
    "mp_overdue_tasks": "Checking overdue tasks",
    "mp_recent_tasks": "Checking recent tasks",
    "mp_get_task": "Getting task details",
    "mp_update_task": "Updating task",
    "update_agent": "Updating agent",
    "ping": "Ping",
}


class ConnectedAgent:
    def __init__(self, ws: WebSocket, registration: AgentRegistration):
        self.ws = ws
        self.registration = registration
        self.connected_at = datetime.now(timezone.utc)
        self.last_seen = self.connected_at
        self.pending_responses: dict[str, asyncio.Future] = {}
        self.current_task: dict | None = None  # {"command_type": str, "description": str, "started_at": str}


agents: dict[str, ConnectedAgent] = {}
command_log: list[dict] = []
MAX_LOG_SIZE = 100


# --- Auth ---

def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server API key not configured")
    if credentials.credentials != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return credentials.credentials


def verify_ws_api_key(token: str) -> bool:
    if not API_KEY:
        return False
    return token == API_KEY


# --- WebSocket endpoint for agents ---

@app.websocket("/ws/agent")
async def agent_websocket(ws: WebSocket):
    await ws.accept()

    # Check auth from header
    auth = ws.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not verify_ws_api_key(auth[7:]):
        await ws.close(code=4001, reason="Unauthorized")
        return

    # Wait for registration message
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
        registration = AgentRegistration.model_validate_json(raw)
    except Exception as e:
        logger.error(f"Agent failed to register: {e}")
        await ws.close(code=4002, reason="Invalid registration")
        return

    agent_id = registration.agent_name
    agents[agent_id] = ConnectedAgent(ws, registration)
    logger.info(f"Agent connected: {agent_id} ({registration.machine_name})")

    from relay.dashboard import record_update
    ver = getattr(registration, 'version', None) or 'unknown'
    record_update(agent_id, f"Agent connected ({registration.machine_name})", version=ver)

    try:
        async for message in ws.iter_text():
            # Agent sends responses to commands
            try:
                response = Response.model_validate_json(message)
                agent = agents.get(agent_id)
                if agent and response.command_id in agent.pending_responses:
                    agent.pending_responses[response.command_id].set_result(response)
                    agent.last_seen = datetime.now(timezone.utc)
            except Exception as e:
                logger.error(f"Invalid response from agent {agent_id}: {e}")
    except WebSocketDisconnect:
        pass
    finally:
        agents.pop(agent_id, None)
        logger.info(f"Agent disconnected: {agent_id}")


# --- HTTP API for sending commands ---

class CommandRequest(BaseModel):
    type: CommandType
    payload: dict = {}


async def _try_agent(agent_id: str, agent: ConnectedAgent, command_type: CommandType, payload: dict) -> dict:
    """Send a command to a specific agent and return the response dict.

    Raises asyncio.TimeoutError or Exception on failure.
    """
    cmd = Command(
        id=str(uuid.uuid4()),
        type=command_type,
        payload=payload,
    )

    loop = asyncio.get_event_loop()
    future: asyncio.Future[Response] = loop.create_future()
    agent.pending_responses[cmd.id] = future

    try:
        agent.current_task = {
            "command_type": command_type.value,
            "description": TASK_DESCRIPTIONS.get(command_type.value, command_type.value),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }
        await agent.ws.send_text(cmd.model_dump_json())
        slow_commands = {"search_notes", "get_note", "transcribe_recording"}
        timeout = 60 if command_type.value in slow_commands else 30
        response = await asyncio.wait_for(future, timeout=timeout)
        agent.current_task = {
            **agent.current_task,
            "status": "done",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": cmd.model_dump(),
            "response": response.model_dump(),
            "agent": agent_id,
        }
        command_log.append(log_entry)
        if len(command_log) > MAX_LOG_SIZE:
            command_log.pop(0)

        from relay.dashboard import record_command, record_update
        record_command(
            command_type=command_type.value,
            agent_name=agent_id,
            status=response.status.value,
            error=response.error,
        )

        if command_type == CommandType.UPDATE_AGENT and response.status.value == "success":
            git_msg = response.data.get("git", "")
            record_update(agent_id, f"Agent self-updated: {git_msg}")

        return response.model_dump()

    except asyncio.TimeoutError:
        agent.current_task = {
            **(agent.current_task or {}),
            "status": "done",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        from relay.dashboard import record_command
        record_command(
            command_type=command_type.value,
            agent_name=agent_id,
            status="error",
            error="Agent did not respond in time",
        )
        raise
    except Exception:
        if agent.current_task:
            agent.current_task = {
                **agent.current_task,
                "status": "done",
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        raise
    finally:
        agent.pending_responses.pop(cmd.id, None)


# Preferred agent order — mac-mini is always-on primary, macbook-pro as fallback
PREFERRED_AGENTS = ["mac-mini", "macbook-pro"]


async def execute_command(command_type: CommandType, payload: dict) -> dict:
    """Route a command to a capable agent and return the response dict.

    Selects agents that registered the requested capability, tries them
    in preferred order, and fails over to the next if one times out.
    Shared by the HTTP API and the MCP endpoint.
    Raises HTTPException on failure.
    """
    if not agents:
        raise HTTPException(status_code=503, detail="No agents connected")

    # Build ordered list of capable agents
    capable = []
    for name in PREFERRED_AGENTS:
        if name in agents and command_type in agents[name].registration.capabilities:
            capable.append(name)
    # Add any other connected agents not in the preferred list
    for name in agents:
        if name not in capable and command_type in agents[name].registration.capabilities:
            capable.append(name)

    # If no agent has the capability, fall back to all agents (system commands like ping)
    if not capable:
        for name in PREFERRED_AGENTS:
            if name in agents:
                capable.append(name)
        for name in agents:
            if name not in capable:
                capable.append(name)

    if not capable:
        raise HTTPException(status_code=503, detail="No agents connected")

    last_error = None
    for agent_id in capable:
        agent = agents.get(agent_id)
        if not agent:
            continue
        try:
            logger.info(f"Routing {command_type.value} to {agent_id}")
            return await _try_agent(agent_id, agent, command_type, payload)
        except asyncio.TimeoutError:
            last_error = f"Agent {agent_id} did not respond in time"
            logger.warning(f"{last_error}, trying next agent...")
            continue
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Agent {agent_id} failed: {last_error}, trying next agent...")
            continue

    raise HTTPException(status_code=504, detail=last_error or "All agents failed to respond")


@app.post("/api/command", include_in_schema=False)
async def send_command(
    request: CommandRequest,
    _: str = Depends(verify_api_key),
):
    return await execute_command(request.type, request.payload)


# --- Status & Dashboard ---

@app.get("/api/status", include_in_schema=False)
async def status(_: str = Depends(verify_api_key)):
    return {
        "agents": {
            name: {
                "machine": a.registration.machine_name,
                "capabilities": [c.value for c in a.registration.capabilities],
                "connected_at": a.connected_at.isoformat(),
                "last_seen": a.last_seen.isoformat(),
                "version": getattr(a.registration, 'version', None),
                "current_task": a.current_task,
            }
            for name, a in agents.items()
        },
        "recent_commands": len(command_log),
    }


# --- Mount dashboard and remote MCP endpoint ---

from relay.dashboard import router as dashboard_router, set_agents
set_agents(agents)
app.include_router(dashboard_router)

from relay.mcp_endpoint import create_mcp_app, set_execute_command, set_agents as set_mcp_agents
from relay.openai_endpoints import router as openai_router, init as openai_init

set_execute_command(execute_command)
set_mcp_agents(agents)
openai_init(execute_command, verify_api_key)
app.include_router(openai_router)
app.mount("/mcp", create_mcp_app())


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("RELAY_HOST", "0.0.0.0")
    port = int(os.getenv("RELAY_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
