# Roadmap

## Phase 1: Apple Reminders [COMPLETE]

- [x] Create reminders (with optional notes, list, priority)
- [x] List reminders (by list, filter by status)
- [x] Complete reminders
- [x] Cloud relay on Fly.io
- [x] Agent auto-start on boot (launchd)
- [x] MCP server for Claude integration
- [x] Web dashboards (relay + agent)
- [ ] Schedule reminders with due dates/times via MCP

## Phase 2: Office 365 Integration

- [ ] OAuth2 authentication with Microsoft Graph API
- [ ] Email: list/search emails
- [ ] Email: summarise threads
- [ ] Email: create and send drafts
- [ ] Calendar: list events
- [ ] Calendar: create/update events
- [ ] Calendar: find available slots

## Phase 3: iCloud Calendar

- [ ] List calendars
- [ ] Create calendar events (title, date/time, duration, location)
- [ ] List upcoming events
- [ ] Update/cancel events
- [ ] Conflict detection (warn if overlapping events)
- [ ] EventKit integration on local agent

## Phase 4: Gmail Integration

- [ ] OAuth2 authentication with Google APIs
- [ ] Email: list/search emails
- [ ] Email: summarise threads
- [ ] Email: create and send drafts
- [ ] Calendar: list events
- [ ] Calendar: create/update events

## Phase 5: Multi-Agent & Reliability

- [ ] Agent health monitoring and alerting
- [ ] Command queuing when no agents are online
- [ ] Agent capability-based routing (route calendar commands only to agents with calendar access)
- [ ] Command retry logic
- [ ] Audit log / command history persistence

## Phase 6: Advanced Features

- [ ] Natural language date parsing ("next Tuesday at 3pm")
- [ ] Recurring reminder creation
- [ ] Email templates
- [ ] Daily digest / summary (scheduled agent that emails a daily summary)
- [ ] Contacts integration
- [ ] Notes integration (Apple Notes)

## Ideas / Backlog

- Mobile notifications when agent goes offline
- Slack integration
- WhatsApp message sending
- Smart home integration (HomeKit)
- File management (iCloud Drive)
- Expense tracking from email receipts
