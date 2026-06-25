# Ross MCP — Virtual PA System

A virtual PA to help Ross manage admin bottlenecks. Accessible from Claude Code, Claude Desktop, ChatGPT, and voice (ElevenLabs agent via phone).

## Architecture

```
Claude Code / Claude Desktop / Claude Web
    → MCP (streamable-http) → Fly.io Relay → WebSocket → Local Mac Agent → Apple APIs / Microsoft Graph

ChatGPT Custom GPT
    → REST API (/api/tools/*) → Fly.io Relay → WebSocket → Local Mac Agent

Phone (ElevenLabs Voice Agent)
    → Telnyx SIP → ElevenLabs → Webhook tools (/api/tools/*) → Fly.io Relay → WebSocket → Local Mac Agent
```

All clients connect to the **same relay**: `https://ross-mcp-relay.fly.dev`
- MCP endpoint: `/mcp/mcp`
- REST/OpenAI endpoint: `/api/tools/*`
- Dashboard: `/` (password protected)

## Deploying Changes

After making changes, deploy with:
1. `git commit` + `git push`
2. `./deploy.sh` — pushes code, deploys relay to Fly.io, tells agents to self-update

Or manually: `fly deploy` for relay, then use `update_agent` tool for agents.

**Important:** If you change `shared/messages.py` (e.g. add new CommandType), the relay MUST be redeployed before agents will reconnect, otherwise Pydantic validation will reject the registration.

## Adding New Tools

When adding a new tool, update ALL of these:
1. `shared/messages.py` — add CommandType enum value and payload model
2. `agent/agent.py` — add capability to registration list + handler in `_handle_message`
3. `relay/mcp_endpoint.py` — add `@mcp.tool()` function
4. `relay/openai_endpoints.py` — add request model + endpoint
5. ElevenLabs — create webhook tool via API pointing to `/api/tools/<slug>` and add to agent's `tool_ids`

## Clients

### Claude Code / Claude Desktop / Claude Web
- MCP server: `https://ross-mcp-relay.fly.dev/mcp/mcp` (streamable-http, Bearer token auth)
- Email style rules embedded in MCP `instructions` and tool docstrings

### ChatGPT Custom GPT
- Actions imported from: `https://ross-mcp-relay.fly.dev/openapi.json`
- Auth: API Key, Bearer token (RELAY_API_KEY)
- New endpoints auto-discovered from OpenAPI spec on deploy
- Max 30 operations (internal routes excluded via `include_in_schema=False`)

### ElevenLabs Voice Agent
- Agent ID: `agent_1601kvz6xrrje8avnvdcchnsnwcf`
- Voice: Kerry — Northern UK female (`Q7iNt6VsGSsBbtyUto9N`)
- Model: `eleven_turbo_v2_5` (low latency)
- 14 webhook tools pointing to `/api/tools/*`, authed via workspace secret `G8E20IiwKsZx00jnMr1I`
- Phone: +441615203725 (Telnyx) → SIP → ElevenLabs → agent

### Voice Agent Security
- **SIP-level**: Only `+447500221211` allowed (enforced by ElevenLabs `allowed_numbers`)
- **Agent-level**: Security code `205492` — agent asks for 2 random digits before any tool use
- Both layers must pass before any actions are taken

### Phone Routing (Telnyx → ElevenLabs)
- Telnyx FQDN connection `2990033598767171037` → `sip.rtc.elevenlabs.io:5060` (TCP)
- ElevenLabs phone number ID: `phnum_2601kvz79axqe8ka813gm8ptfp53`
- No SIP auth (relies on IP allowlist + caller number restriction)
- `trunk1` connection (`2834172269066978794`) is a SEPARATE system — do not modify

## Email Drafting Style

When generating ANY email draft via Outlook (create_draft, draft_reply, or "email someone"):

- **Always enrich and polish** what Ross asks for. Never parrot his words back verbatim. Take the intent and key points, then write a well-worded, natural email that sounds like Ross wrote it carefully. Add appropriate context, smooth transitions, and proper phrasing.
- Greeting: "Hi [Name]" for one person, "Hi [Name]/[Name]" for two, "Hi all" for 3+
- Tone: conversational and direct, not corporate or formal
- Never use em dashes (—) or hyphens to join clauses. Use commas or full stops. Dashes look AI-generated.
- One thought per paragraph, keep paragraphs short
- UK date format (DD/MM/YYYY)
- Sign off: "Kind regards" then "Ross" on the next line
- Wrap body in Aptos font: `<div style="font-family:Aptos,Arial,Helvetica,sans-serif;font-size:12pt;color:rgb(0,0,0)">...</div>`
- NEVER send emails. Only create drafts.

## Document Generation

- DOCX: always use `agent/services/reference.docx` template (Calibri 11pt)
- PDF: must include `<meta charset="UTF-8">` and `--encoding UTF-8` flag for wkhtmltopdf
- Never attach .md files to emails (Outlook blocks them). Convert to PDF or DOCX first.

## Timezone

All dates and times use Europe/London. Never use UTC unless explicitly asked.

## Default Services

- "email" / "calendar" = Outlook (Office 365) — this is the ONLY calendar. Never use Apple Calendar or Google Calendar.
- "Gmail" = Google (explicitly named, email only)

## Meeting Transcription

When transcribing meetings:
1. Ask when the meeting was (if not clear)
2. Find the recording by date in iCloud Drive/Meetings
3. Transcribe via Deepgram with speaker diarisation
4. Enrich: summary, who said what (label speakers), action points
5. Create Apple Note: "[Meeting Topic] — [DD/MM/YYYY HH:MM]"

## Apple Notes

- Format with HTML: h2 for sections, p tags, ol/ul for lists
- Space between sections with `<br>`
- Never create raw unformatted notes

## Reminders

- Always use Apple Reminders MCP tools
- If a time is given without a date and hasn't passed today, use today
- Only use tomorrow if the time has already passed

## Agents

- `macbook-pro` — Ross's M3 Pro MacBook (user: ross, home: /Users/ross)
- `mac-mini` — Mac Mini (user: neo@192.168.5.120, home: /Users/neo, Python: /opt/homebrew/bin/python3.13)
- Both run via launchd (`com.ross.mcp-agent`) with KeepAlive
- WebSocket ping keepalives (20s interval, 10s timeout)
- Rotating logs at `~/Library/Logs/mcp-agent/agent.log` (2MB, 3 backups)

## Dashboard

- URL: `https://ross-mcp-relay.fly.dev/`
- Sessions persist in SQLite across deploys
- Live task tracking: running (blue pulse) → done (green tick, 5s) → idle
- Activity/Updates paginated at 25 per page
- 30-day auto-cleanup on all data
- 3-second refresh interval

## Venv Setup (Apple Silicon)

Always create venvs with `arch -arm64` on Apple Silicon Macs:
```bash
arch -arm64 python3 -m venv .venv
arch -arm64 pip install -r agent/requirements.txt
```
The terminal may run under Rosetta but launchd runs native arm64.
