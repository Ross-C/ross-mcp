# Roadmap

## Phase 1: Apple Reminders [COMPLETE]

- [x] Create reminders (with optional notes, list, priority)
- [x] List reminders (by list, filter by status)
- [x] Complete reminders
- [x] Cloud relay on Fly.io
- [x] Agent auto-start on boot (launchd)
- [x] MCP server for Claude integration
- [x] Web dashboards (relay + agent)

## Phase 2: Office 365 Integration [COMPLETE]

- [x] OAuth2 authentication with Microsoft Graph API
- [x] Email: search emails
- [x] Email: read full messages and threads
- [x] Email: create, update, and send drafts
- [x] Email: schedule and cancel scheduled sends
- [x] Email: archive messages
- [x] Email: file attachments
- [x] Calendar: list events
- [x] Calendar: create/update/cancel events
- [x] Calendar: find available slots

## Phase 2b: Voice Memo Transcription [COMPLETE]

- [x] Find voice memos by date/time
- [x] Transcribe audio via Deepgram API with speaker diarization
- [x] Create Apple Note with enriched transcript

## Phase 2c: Apple Notes [COMPLETE]

- [x] Search notes by title/body
- [x] Read full note content
- [x] Create notes with HTML formatting
- [x] List folders

## Phase 2d: Document Conversion [COMPLETE]

- [x] Markdown to PDF (wkhtmltopdf, Calibri styling)
- [x] Markdown to DOCX (pandoc, reference template)

## Phase 3: Multi-Agent & Deployment [COMPLETE]

- [x] Remote MCP endpoint (streamable-http) for all clients
- [x] ChatGPT Custom GPT Actions (OpenAPI)
- [x] Agent self-update command (git pull + restart via relay)
- [x] Deploy script (git push + relay deploy + agent update)
- [x] Multi-machine support (Mac Mini + MacBook)

## Phase 4: Reliability & Monitoring

- [ ] Secure web dashboard with login (agent status, command history, stats)
- [ ] Agent version tracking (git commit hash reported at registration)
- [ ] Command queuing when no agents are online
- [ ] Agent capability-based routing
- [ ] Command retry logic
- [ ] Health check alerts (notify if agents go offline)

## Phase 5: Gmail Integration

- [ ] OAuth2 authentication with Google APIs
- [ ] Email: list/search emails
- [ ] Email: create and send drafts
- [ ] Calendar: list/create events

## Phase 6: Advanced Features

- [ ] Reply to / forward existing emails
- [ ] Natural language date parsing ("next Tuesday at 3pm")
- [ ] Recurring reminder creation
- [ ] Email templates
- [ ] Daily digest / summary
- [ ] Contacts integration

## Ideas / Backlog

- Mobile notifications when agent goes offline
- Slack integration
- WhatsApp message sending
- Smart home integration (HomeKit)
- File management (iCloud Drive)
- Expense tracking from email receipts
