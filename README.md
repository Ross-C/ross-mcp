# Ross MCP

Personal life admin system — manage Apple Reminders, Outlook email/calendar, Apple Notes, voice memos, and documents from Claude, ChatGPT, or any MCP/API client.

**Architecture:** Client (Claude/ChatGPT/API) → Cloud Relay (Fly.io) → Local Mac Agent → Apple APIs / Microsoft Graph

## Features

| Category | Tools |
|----------|-------|
| **Apple Reminders** | Create, list, complete reminders |
| **Outlook Email** | Search, read threads, draft, send, schedule, archive, attachments |
| **Outlook Calendar** | List events, create/update/cancel events, find free slots |
| **Apple Notes** | Search, read, create notes, list folders |
| **Voice Memos** | List recordings, transcribe with speaker diarization (Deepgram) |
| **Documents** | Convert Markdown to PDF or DOCX |
| **Agent Management** | Check agent status, trigger remote self-update |

**29 tools** accessible from:
- **Claude Web/Desktop** via remote MCP (streamable-http)
- **Claude Code** via remote MCP (same endpoint)
- **ChatGPT** via Custom GPT Actions (OpenAPI)
- **Any HTTP client** via REST API

## Quick Start

### 1. Clone and set up Python

```bash
cd ross-mcp
arch -arm64 python3 -m venv .venv   # Use arch -arm64 on Apple Silicon
source .venv/bin/activate
pip install -r agent/requirements.txt
pip install mcp httpx python-dotenv
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set RELAY_API_KEY (must match the Fly.io secret)
```

### 3. Set up Outlook (one-time per Mac)

```bash
brew install azure-cli
az login
./agent/setup_azure.sh

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

The refresh token auto-renews every 3 days.

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

Creates a launchd service that starts on boot and stays running.

## Connecting Clients

All clients connect to the **same remote endpoint** on the relay. No local MCP server needed.

### Claude Web / Desktop (MCP)

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
      "type": "http",
      "url": "https://ross-mcp-relay.fly.dev/mcp/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}
```

### ChatGPT (Custom GPT)

1. Create a Custom GPT at chat.openai.com
2. Add an **Action** → Import from URL: `https://ross-mcp-relay.fly.dev/openapi.json`
3. Set auth to **Bearer** with your `RELAY_API_KEY`

### Direct REST API

```bash
curl -X POST https://ross-mcp-relay.fly.dev/api/command \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "create_reminder", "payload": {"title": "Buy milk"}}'
```

## Deployment & Updates

### Deploy workflow (from any machine)

The `deploy.sh` script handles the full deployment pipeline:

```bash
# 1. Commit your changes
git add . && git commit -m "your changes"

# 2. Deploy everything
./deploy.sh
```

This will:
1. Push code to git
2. Deploy the relay to Fly.io
3. Tell all connected agents to pull updates and restart

### Manual steps

**Deploy relay only:**
```bash
fly deploy --app ross-mcp-relay
```

**Update agents only (via any client):**
Tell Claude/ChatGPT: "update the agents" — this triggers a git pull + restart on all connected agents.

Or via API:
```bash
curl -X POST https://ross-mcp-relay.fly.dev/api/command \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"type": "update_agent", "payload": {}}'
```

**View relay logs:**
```bash
fly logs --app ross-mcp-relay
```

### Setting up a second Mac

1. Clone the repo
2. Set up venv: `arch -arm64 python3 -m venv .venv && pip install -r agent/requirements.txt`
3. Copy `.env` and change `AGENT_NAME` to identify the machine (e.g. `mac-mini`)
4. Run `./agent/setup_azure.sh` then the OAuth login (one-time)
5. Run `./agent/install.sh`

Both agents connect to the same relay. Commands route to whichever is online. Use `agent_status` to see connected agents.

### Launchd service commands

| Action | Command |
|--------|---------|
| Install | `./agent/install.sh` |
| Stop | `launchctl unload ~/Library/LaunchAgents/com.ross.mcp-agent.plist` |
| Start | `launchctl load ~/Library/LaunchAgents/com.ross.mcp-agent.plist` |
| Restart | Unload then load |
| Logs | `tail -f ~/Library/Logs/mcp-agent/mcp-agent.log` |
| Errors | `tail -f ~/Library/Logs/mcp-agent/mcp-agent.err` |

## Voice Memo Transcription

Record meetings on iPad using Voice Memos, share to iCloud Drive, then transcribe via Claude or ChatGPT.

### Setup

1. Create a "Meeting Recordings" folder in iCloud Drive (done automatically by the agent)
2. Create an iOS Shortcut called "Save Meeting Recording" on your iPad:
   - Action: **Save File** → iCloud Drive / Meeting Recordings (Ask Where to Save: off)
   - Enable **Show in Share Sheet**, set receives to **Audio**
3. Add your `DEEPGRAM_API_KEY` to `.env`

### After a meeting

1. Open Voice Memos on iPad → tap **...** → **Share** → **Save Meeting Recording**
2. Tell Claude: *"Transcribe my meeting with [name] from this morning"*
3. Claude finds the recording, transcribes with speaker diarization, enriches with summary and action points, and saves as an Apple Note

## Dashboard

The relay includes a secure web dashboard at `https://ross-mcp-relay.fly.dev/`.

**Features:**
- Password-protected login (session cookie, httponly + secure)
- Agent status with capabilities and uptime
- Command stats with counters (emails drafted, reminders created, etc.)
- Charts: commands by day (configurable range), breakdown by category
- Filterable activity log
- Client setup instructions (Claude Desktop, Claude Web, Claude Code, ChatGPT)

**Set the dashboard password:**

```bash
fly secrets set DASHBOARD_PASSWORD=your-password --app ross-mcp-relay
```

## Remote Endpoints

| Endpoint | URL | Auth |
|----------|-----|------|
| Dashboard | `https://ross-mcp-relay.fly.dev/` | Dashboard password |
| MCP (Claude) | `POST https://ross-mcp-relay.fly.dev/mcp/mcp` | Bearer token |
| REST API | `POST https://ross-mcp-relay.fly.dev/api/command` | Bearer token |
| Tool endpoints (ChatGPT) | `POST https://ross-mcp-relay.fly.dev/api/tools/*` | Bearer token |
| Swagger UI | `https://ross-mcp-relay.fly.dev/docs` | None (read-only) |
| Status | `GET https://ross-mcp-relay.fly.dev/api/status` | Bearer token |
| Agent WebSocket | `wss://ross-mcp-relay.fly.dev/ws/agent` | Bearer token |

## Secrets

| Secret | Location | Notes |
|--------|----------|-------|
| `RELAY_API_KEY` | `.env` (local) + Fly.io secrets | Shared by agent, relay, and clients |
| `DASHBOARD_PASSWORD` | Fly.io secrets | Web dashboard login |
| `MS_CLIENT_ID` / `MS_CLIENT_SECRET` | `.env` (local) | Azure AD app credentials |
| `.outlook_tokens.json` | Project root (gitignored) | OAuth tokens, auto-refreshed |
| `DEEPGRAM_API_KEY` | `.env` (local) | For voice memo transcription |

**Regenerate API key:**

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Update: .env, fly secrets set, Claude settings.json, and ChatGPT action auth
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
│       ├── outlook_calendar.py    # Outlook calendar operations
│       ├── voice_memos.py         # Voice memo transcription (Deepgram)
│       └── documents.py           # Markdown to PDF/DOCX conversion
├── relay/                         # Cloud relay (Fly.io)
│   ├── relay.py                   # FastAPI hub (WebSocket + HTTP + dashboard)
│   ├── mcp_endpoint.py            # Remote MCP server (streamable-http)
│   ├── openai_endpoints.py        # REST endpoints for ChatGPT Actions
│   ├── Dockerfile
│   └── requirements.txt
├── shared/
│   └── messages.py                # Command/Response schemas (all command types)
├── mcp_server.py                  # Local MCP server (stdio, legacy — use remote instead)
├── deploy.sh                      # Full deploy: git push + relay deploy + agent update
├── fly.toml                       # Fly.io config
└── .env.example                   # Environment template
```

## Links

- [Fly.io Dashboard](https://fly.io/apps/ross-mcp-relay) — Deployment management
- [Swagger UI](https://ross-mcp-relay.fly.dev/docs) — API documentation
