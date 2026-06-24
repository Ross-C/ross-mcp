# Ross MCP

Personal life admin system — manage Apple Reminders, Outlook email/calendar, and Apple Notes from Claude, ChatGPT, or any MCP/API client.

**Architecture:** Client (Claude/ChatGPT/API) → Cloud Relay (Fly.io) → Local Mac Agent → Apple APIs / Microsoft Graph

## Features

| Category | Tools |
|----------|-------|
| **Apple Reminders** | Create, list, complete reminders |
| **Outlook Email** | Search, read, draft, send, schedule, archive emails |
| **Outlook Calendar** | List events, create/update/cancel events, find free slots |
| **Apple Notes** | Search, read, create notes, list folders |

**22 tools** accessible from:
- **Claude** (web/desktop/CLI) via MCP protocol
- **ChatGPT** via Custom GPT Actions (OpenAPI)
- **Any HTTP client** via REST API

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
# Edit .env — set RELAY_API_KEY (must match the Fly.io secret)
```

### 3. Set up Outlook (one-time)

```bash
# Install Azure CLI
brew install azure-cli

# Log in to Azure
az login

# Register the app and save credentials to .env
./agent/setup_azure.sh

# Run the OAuth login (opens browser)
python3 -c "
import asyncio
from dotenv import load_dotenv
load_dotenv()
from agent.services.outlook_auth import OutlookAuth
auth = OutlookAuth()
asyncio.run(auth.authorize())
print('Success!' if auth.is_authenticated else 'Failed')
"
```

You only need to do this once per Mac. The refresh token auto-renews every 3 days.

### 4. Run the agent

```bash
source .venv/bin/activate
python -m agent.agent
```

The agent will:
- Connect to the cloud relay via WebSocket
- Start a local web UI at http://127.0.0.1:8001
- Listen for commands from any client

### 5. Install as auto-start service

```bash
./agent/install.sh
```

Creates a launchd service that starts on boot and keeps running.

## Connecting Clients

### Claude Web / Desktop (MCP)

Connect to the remote MCP endpoint:

| Setting | Value |
|---------|-------|
| URL | `https://ross-mcp-relay.fly.dev/mcp/mcp` |
| Transport | Streamable HTTP |
| Auth | Bearer token (your `RELAY_API_KEY`) |

### Claude Code (CLI)

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "ross-life-admin": {
      "command": "/path/to/ross-mcp/.venv/bin/python",
      "args": ["/path/to/ross-mcp/mcp_server.py"],
      "env": {
        "RELAY_API_KEY": "your-api-key",
        "MCP_RELAY_URL": "https://ross-mcp-relay.fly.dev"
      }
    }
  }
}
```

### ChatGPT (Custom GPT)

1. Create a Custom GPT at chat.openai.com
2. Add an **Action** → Import from URL: `https://ross-mcp-relay.fly.dev/openapi.json`
3. Set auth to **Bearer** with your `RELAY_API_KEY`

This imports all 22 tool endpoints. See the Swagger UI at `https://ross-mcp-relay.fly.dev/docs`.

### Direct REST API

```bash
curl -X POST https://ross-mcp-relay.fly.dev/api/command \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "create_reminder", "payload": {"title": "Buy milk"}}'
```

## Deployment

### Cloud Relay (Fly.io)

The relay runs on Fly.io in the `lhr` region. To deploy changes:

```bash
fly deploy
```

**Manage secrets:**

```bash
fly secrets list --app ross-mcp-relay
fly secrets set RELAY_API_KEY=your-key --app ross-mcp-relay
```

**View logs:**

```bash
fly logs --app ross-mcp-relay
```

### Local Agent

**Manual start:**

```bash
source .venv/bin/activate
python -m agent.agent
```

**Launchd service commands:**

| Action | Command |
|--------|---------|
| Install | `./agent/install.sh` |
| Stop | `launchctl unload ~/Library/LaunchAgents/com.ross.mcp-agent.plist` |
| Start | `launchctl load ~/Library/LaunchAgents/com.ross.mcp-agent.plist` |
| Restart | Unload then load |
| Logs | `tail -f ~/Library/Logs/mcp-agent/mcp-agent.log` |
| Errors | `tail -f ~/Library/Logs/mcp-agent/mcp-agent.err` |

### Setting up a second Mac

1. Clone the repo
2. Set up venv and install dependencies
3. Copy `.env` and change `AGENT_NAME` to identify the machine
4. Run `./agent/setup_azure.sh` then the OAuth login (one-time)
5. Run `./agent/install.sh`

Both agents connect to the same relay — commands route to whichever is online.

## Remote Endpoints

| Endpoint | URL | Auth |
|----------|-----|------|
| Dashboard | `https://ross-mcp-relay.fly.dev/` | API key in UI |
| MCP (Claude) | `POST https://ross-mcp-relay.fly.dev/mcp/mcp` | Bearer token |
| REST API | `POST https://ross-mcp-relay.fly.dev/api/command` | Bearer token |
| Tool endpoints (ChatGPT) | `POST https://ross-mcp-relay.fly.dev/api/tools/*` | Bearer token |
| Swagger UI | `https://ross-mcp-relay.fly.dev/docs` | None (read-only) |
| Status | `GET https://ross-mcp-relay.fly.dev/api/status` | Bearer token |
| Agent WebSocket | `wss://ross-mcp-relay.fly.dev/ws/agent` | Bearer token |

## Secrets

| Secret | Location | Notes |
|--------|----------|-------|
| `RELAY_API_KEY` | `.env` (local) | Shared by agent, MCP server, and clients |
| `RELAY_API_KEY` | Fly.io secrets | Set via `fly secrets set` |
| `MS_CLIENT_ID` / `MS_CLIENT_SECRET` | `.env` (local) | Azure AD app credentials |
| `.outlook_tokens.json` | Project root (gitignored) | OAuth tokens, auto-refreshed |
| `DEEPGRAM_API_KEY` | `.env` (local) | For voice memo transcription (future) |

**Regenerate API key:**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Update: .env, fly secrets set, and any client configs
```

## Project Structure

```
ross-mcp/
├── agent/                         # Local Mac agent
│   ├── agent.py                   # Main agent (WebSocket client + command dispatch)
│   ├── web.py                     # Local web UI (port 8001)
│   ├── setup_azure.sh             # Azure AD app registration script
│   ├── install.sh                 # Launchd auto-start installer
│   └── services/
│       ├── reminders.py           # Apple Reminders via EventKit
│       ├── notes.py               # Apple Notes via AppleScript
│       ├── outlook_auth.py        # OAuth2 for Microsoft Graph
│       ├── outlook_mail.py        # Outlook email operations
│       └── outlook_calendar.py    # Outlook calendar operations
├── relay/                         # Cloud relay (Fly.io)
│   ├── relay.py                   # FastAPI hub (WebSocket + HTTP + dashboard)
│   ├── mcp_endpoint.py            # Remote MCP server (streamable-http)
│   ├── openai_endpoints.py        # REST endpoints for ChatGPT Actions
│   ├── Dockerfile
│   └── requirements.txt
├── shared/
│   └── messages.py                # Command/Response schemas (23 command types)
├── mcp_server.py                  # Local MCP server (stdio, for Claude Code)
├── fly.toml                       # Fly.io config
├── .env.example                   # Environment template
├── ROADMAP.md                     # Planned features
└── SPRINT.md                      # Sprint log
```

## Links

- [Roadmap](ROADMAP.md) — Planned features
- [Sprint Log](SPRINT.md) — Development history
- [Fly.io Dashboard](https://fly.io/apps/ross-mcp-relay) — Deployment management
- [Swagger UI](https://ross-mcp-relay.fly.dev/docs) — API documentation
