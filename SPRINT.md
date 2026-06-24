# Sprint Log

## Phase 1: Apple Reminders (Current)

### Goal
End-to-end pipeline: Claude -> Cloud Relay -> Local Agent -> Apple Reminders

### Features
- Create reminders (with optional due date, list, priority)
- List reminders (by list, filter by status)
- Complete reminders
- Schedule reminders (due dates/times)

### Tasks
1. [x] Project scaffolding and shared schemas
2. [ ] Local agent with Apple Reminders support + web UI
3. [ ] Cloud relay with WebSocket hub + HTTP API + web dashboard
4. [ ] Security layer (auth, encryption, API keys)
5. [ ] End-to-end local testing
6. [ ] Deploy relay to Fly.io
7. [ ] MCP server integration for Claude

---

## Phase 2: iCloud Calendar (Planned)
- Add/list/update calendar events via EventKit
- Conflict detection

## Phase 3: Office 365 Integration (Planned)
- Email: summarise, draft, send
- Calendar: add/list events
- Via Microsoft Graph API

## Phase 4: Gmail Integration (Planned)
- Email: summarise, draft, send
- Calendar: add/list events
- Via Google APIs
