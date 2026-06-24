# Ross MCP

Personal life admin MCP server — manage Apple Reminders (and later calendars, email) from any Claude session.

Architecture: **Claude** -> **Cloud Relay (Fly.io)** -> **Local Mac Agent** -> **Apple APIs**

## Current Features

- **Apple Reminders**: Create, list, and complete reminders
- **Multi-agent**: Multiple Macs can connect to the relay simultaneously
- **Web dashboards**: Relay dashboard (cloud) and agent UI (local)
- **MCP server**: Any Claude Code or Claude Chat session can use reminder tools
- **Auto-start**: Agent runs as a launchd service, survives reboots

## Quick Start

### 1. Clone and set up Python

```bash
cd ross-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r agent/requirements.txt
pip install mcp httpx
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API key and relay URL
```

### 3. Run the agent manually (for testing)

```bash
source .venv/bin/activate
python -m agent.agent
```

The agent will:
- Connect to the cloud relay via WebSocket
- Start a local web UI at http://127.0.0.1:8001
- Listen for commands from any Claude session

### 4. Install as auto-start service

```bash
./agent/install.sh
```

This installs a launchd service that starts the agent on boot and keeps it running. See [Agent Installation](#agent-installation) for details.

### 5. Configure Claude Code MCP

Add to your `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "ross-life-admin": {
      "command": "VENV_PYTHON_PATH",
      "args": ["/path/to/ross-mcp/mcp_server.py"],
      "env": {
        "RELAY_API_KEY": "your-api-key-here",
        "MCP_RELAY_URL": "https://ross-mcp-relay.fly.dev"
      }
    }
  }
}
```

Replace `VENV_PYTHON_PATH` with the full path to `.venv/bin/python` and update the project path.

## Agent Installation

### Manual run

```bash
source .venv/bin/activate
python -m agent.agent
```

### Auto-start on boot (launchd)

Run the install script:

```bash
./agent/install.sh
```

This creates a launchd service at `~/Library/LaunchAgents/com.ross.mcp-agent.plist`.

**Service commands:**

| Action | Command |
|--------|---------|
| Stop | `launchctl unload ~/Library/LaunchAgents/com.ross.mcp-agent.plist` |
| Start | `launchctl load ~/Library/LaunchAgents/com.ross.mcp-agent.plist` |
| Restart | Unload then load |
| View logs | `tail -f ~/Library/Logs/mcp-agent/mcp-agent.log` |
| View errors | `tail -f ~/Library/Logs/mcp-agent/mcp-agent.err` |

### Installing on a second Mac

1. Clone the repo on the second Mac
2. Set up the venv and install dependencies
3. Copy your `.env` file (change `AGENT_NAME` to identify the machine)
4. Run `./agent/install.sh`

Both agents will connect to the same relay — commands route to whichever is available.

## Remote Endpoints

The cloud relay is deployed on Fly.io at:

| Endpoint | URL | Auth |
|----------|-----|------|
| Dashboard | `https://ross-mcp-relay.fly.dev/` | API key (entered in UI) |
| Send command | `POST https://ross-mcp-relay.fly.dev/api/command` | Bearer token |
| Status | `GET https://ross-mcp-relay.fly.dev/api/status` | Bearer token |
| Agent WebSocket | `wss://ross-mcp-relay.fly.dev/ws/agent` | Bearer token |

### Example: Create a reminder via curl

```bash
curl -X POST https://ross-mcp-relay.fly.dev/api/command \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "create_reminder", "payload": {"title": "Buy milk"}}'
```

## Where Secrets Are Stored

| Secret | Location | Notes |
|--------|----------|-------|
| `RELAY_API_KEY` | `.env` (local, gitignored) | Used by both agent and MCP server |
| `RELAY_API_KEY` | Fly.io secrets | Set via `fly secrets set`, not in any file |
| `AGENT_API_KEY` | `.env` (local, gitignored) | Same value as RELAY_API_KEY |
| MCP server env | `~/.claude/settings.json` | Claude Code reads this at startup |

**To view/update Fly.io secrets:**

```bash
fly secrets list --app ross-mcp-relay
fly secrets set RELAY_API_KEY=new-key-here --app ross-mcp-relay
```

**To regenerate all keys:**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Update: .env, fly secrets, and ~/.claude/settings.json
```

## Project Structure

```
ross-mcp/
├── agent/                    # Local Mac agent
│   ├── agent.py              # Main agent (WebSocket client + web UI)
│   ├── web.py                # Local web UI (port 8001)
│   ├── services/
│   │   └── reminders.py      # Apple Reminders via EventKit
│   ├── install.sh            # Launchd auto-start installer
│   └── com.ross.mcp-agent.plist  # Launchd template
├── relay/                    # Cloud relay (Fly.io)
│   ├── relay.py              # FastAPI app (WebSocket hub + HTTP API + dashboard)
│   ├── Dockerfile
│   └── requirements.txt
├── shared/                   # Shared schemas
│   └── messages.py           # Command/Response message types
├── mcp_server.py             # MCP server for Claude integration
├── fly.toml                  # Fly.io deployment config
├── .env.example              # Environment template
├── SPRINT.md                 # Current sprint tasks
├── ROADMAP.md                # Future planned features
└── README.md                 # This file
```

## Links

- [Roadmap](ROADMAP.md) — Future planned features
- [Sprint Log](SPRINT.md) — Current sprint tasks
- [Fly.io Dashboard](https://fly.io/apps/ross-mcp-relay) — Deployment management
