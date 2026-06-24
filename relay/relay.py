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
from fastapi.responses import HTMLResponse
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
    # Start the MCP session manager (sub-app lifespans don't auto-run)
    from relay.mcp_endpoint import get_session_manager
    sm = get_session_manager()
    if sm:
        async with sm.run():
            yield
    else:
        yield


app = FastAPI(title="Ross MCP Relay", version="0.1.0", lifespan=lifespan)
security = HTTPBearer()


# --- Agent Registry ---

class ConnectedAgent:
    def __init__(self, ws: WebSocket, registration: AgentRegistration):
        self.ws = ws
        self.registration = registration
        self.connected_at = datetime.now(timezone.utc)
        self.last_seen = self.connected_at
        self.pending_responses: dict[str, asyncio.Future] = {}


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


async def execute_command(command_type: CommandType, payload: dict) -> dict:
    """Route a command to an agent and return the response dict.

    Shared by the HTTP API and the MCP endpoint.
    Raises HTTPException on failure.
    """
    if not agents:
        raise HTTPException(status_code=503, detail="No agents connected")

    # Pick first available agent (later: smarter routing)
    agent_id = next(iter(agents))
    agent = agents[agent_id]

    cmd = Command(
        id=str(uuid.uuid4()),
        type=command_type,
        payload=payload,
    )

    loop = asyncio.get_event_loop()
    future: asyncio.Future[Response] = loop.create_future()
    agent.pending_responses[cmd.id] = future

    try:
        await agent.ws.send_text(cmd.model_dump_json())
        response = await asyncio.wait_for(future, timeout=30)

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "command": cmd.model_dump(),
            "response": response.model_dump(),
            "agent": agent_id,
        }
        command_log.append(log_entry)
        if len(command_log) > MAX_LOG_SIZE:
            command_log.pop(0)

        return response.model_dump()

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Agent did not respond in time")
    finally:
        agent.pending_responses.pop(cmd.id, None)


@app.post("/api/command")
async def send_command(
    request: CommandRequest,
    _: str = Depends(verify_api_key),
):
    return await execute_command(request.type, request.payload)


# --- Status & Dashboard ---

@app.get("/api/status")
async def status(_: str = Depends(verify_api_key)):
    return {
        "agents": {
            name: {
                "machine": a.registration.machine_name,
                "capabilities": [c.value for c in a.registration.capabilities],
                "connected_at": a.connected_at.isoformat(),
                "last_seen": a.last_seen.isoformat(),
            }
            for name, a in agents.items()
        },
        "recent_commands": len(command_log),
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Simple web dashboard — no auth required for the page, but API calls need keys."""
    return DASHBOARD_HTML


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ross MCP Relay</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0a0a0a; color: #e0e0e0; padding: 2rem; }
        h1 { color: #fff; margin-bottom: 0.5rem; }
        .subtitle { color: #888; margin-bottom: 2rem; }
        .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px;
                padding: 1.5rem; margin-bottom: 1rem; }
        .card h2 { color: #4fc3f7; margin-bottom: 1rem; font-size: 1.1rem; }
        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                      margin-right: 8px; }
        .online { background: #4caf50; }
        .offline { background: #f44336; }
        .agent-row { padding: 0.75rem 0; border-bottom: 1px solid #222; }
        .agent-row:last-child { border-bottom: none; }
        .agent-name { font-weight: 600; color: #fff; }
        .agent-meta { color: #888; font-size: 0.85rem; margin-top: 0.25rem; }
        .log-entry { padding: 0.5rem 0; border-bottom: 1px solid #222; font-size: 0.85rem; }
        .log-cmd { color: #81c784; }
        .log-status { color: #4fc3f7; }
        .log-error { color: #e57373; }
        .auth-form { margin-bottom: 2rem; display: flex; gap: 0.5rem; }
        input[type="password"] { background: #1a1a1a; border: 1px solid #333; color: #fff;
                                  padding: 0.5rem 1rem; border-radius: 4px; flex: 1; max-width: 400px; }
        button { background: #4fc3f7; color: #000; border: none; padding: 0.5rem 1.5rem;
                 border-radius: 4px; cursor: pointer; font-weight: 600; }
        button:hover { background: #29b6f6; }
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
        #error { color: #e57373; margin-top: 0.5rem; display: none; }
    </style>
</head>
<body>
    <h1>Ross MCP Relay</h1>
    <p class="subtitle">Personal life admin command relay</p>

    <div class="auth-form">
        <input type="password" id="apiKey" placeholder="Enter API key..." />
        <button onclick="connect()">Connect</button>
    </div>
    <p id="error"></p>

    <div class="grid">
        <div class="card">
            <h2>Connected Agents</h2>
            <div id="agents"><p style="color: #666;">Enter API key to view</p></div>
        </div>
        <div class="card">
            <h2>Recent Commands</h2>
            <div id="log"><p style="color: #666;">Enter API key to view</p></div>
        </div>
    </div>

    <script>
        let apiKey = '';
        let refreshInterval;

        async function connect() {
            apiKey = document.getElementById('apiKey').value;
            if (!apiKey) return;
            try {
                await refresh();
                document.getElementById('error').style.display = 'none';
                if (refreshInterval) clearInterval(refreshInterval);
                refreshInterval = setInterval(refresh, 5000);
            } catch (e) {
                document.getElementById('error').textContent = 'Invalid API key';
                document.getElementById('error').style.display = 'block';
            }
        }

        async function refresh() {
            const resp = await fetch('/api/status', {
                headers: { 'Authorization': `Bearer ${apiKey}` }
            });
            if (!resp.ok) throw new Error('Unauthorized');
            const data = await resp.json();

            const agentsEl = document.getElementById('agents');
            const entries = Object.entries(data.agents);
            if (entries.length === 0) {
                agentsEl.innerHTML = '<p style="color: #666;">No agents connected</p>';
            } else {
                agentsEl.innerHTML = entries.map(([name, info]) => `
                    <div class="agent-row">
                        <span class="status-dot online"></span>
                        <span class="agent-name">${name}</span>
                        <div class="agent-meta">${info.machine} &middot; Connected ${new Date(info.connected_at).toLocaleTimeString()}</div>
                        <div class="agent-meta">Capabilities: ${info.capabilities.join(', ')}</div>
                    </div>
                `).join('');
            }
        }

        document.getElementById('apiKey').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') connect();
        });
    </script>
</body>
</html>
"""


# --- Mount remote MCP endpoint ---

from relay.mcp_endpoint import create_mcp_app, set_execute_command

set_execute_command(execute_command)
app.mount("/mcp", create_mcp_app())


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("RELAY_HOST", "0.0.0.0")
    port = int(os.getenv("RELAY_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
