# Project Rules

## Architecture

Client (Claude/ChatGPT/API) → Cloud Relay (Fly.io) → Local Mac Agent → Apple APIs / Microsoft Graph

All clients connect to the **same remote MCP endpoint**: `https://ross-mcp-relay.fly.dev/mcp/mcp`
No local MCP server needed. The relay routes commands to whichever agent is online.

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
5. `mcp_server.py` — add tool (legacy, optional)

## Email Drafting Style

When generating email drafts via Outlook:

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

## Venv Setup (Apple Silicon)

Always create venvs with `arch -arm64` on Apple Silicon Macs:
```bash
arch -arm64 python3 -m venv .venv
arch -arm64 pip install -r agent/requirements.txt
```
The terminal may run under Rosetta but launchd runs native arm64.
