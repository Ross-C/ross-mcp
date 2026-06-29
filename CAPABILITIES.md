# Ross MCP — Agent Capabilities

What the agents can do, and on which surface. Review this periodically and tick the **Verified** box once you've confirmed a skill works end to end. Keep it in sync whenever a skill is added (see the "Adding a new skill" checklist in `CLAUDE.md`).

**Surfaces**
- **Claude** = local Claude Code + the cloud MCP (`relay/mcp_endpoint.py`), used at your desk and headless.
- **Sophie** = the ElevenLabs voice agent + ChatGPT actions (`relay/openai_endpoints.py`), used away from the desk.

Both ultimately run through the local Mac agents. `✓` = available, `—` = not exposed on that surface.

| Skill | Claude | Sophie | Verified |
|---|:--:|:--:|:--:|
| **Reminders** | | | |
| create / list / complete reminder | ✓ | ✓ | ☐ |
| **Outlook Email** | | | |
| search / get / get-thread | ✓ | ✓ | ☐ |
| create draft / draft reply / update draft / send draft | ✓ | ✓ | ☐ |
| send email / schedule / cancel scheduled / archive / add attachment | ✓ | ✓ | ☐ |
| **Outlook Calendar** | | | |
| list / create / update / cancel event / find available slots | ✓ | ✓ | ☐ |
| **Gmail** | | | |
| search / get / get-thread / create draft / archive / list labels | ✓ | ✓ | ☐ |
| **Google Calendar** | | | |
| list events / create event | ✓ | ✓ | ☐ |
| **iCloud Calendar (personal)** | | | |
| list calendars / list events / create event | ✓ | ✓ | ☐ |
| **Apple Notes** | | | |
| search / get / create / list folders | ✓ | ✓ | ☐ |
| **Documents** | | | |
| convert MD → PDF / DOCX | ✓ | ✓ | ☐ |
| **Voice Memos** | | | |
| list recordings / transcribe | ✓ | ✓ | ☐ |
| **Contacts** | | | |
| lookup contact | ✓ | ✓ | ☐ |
| **Support tickets (CBS / RCSC)** | | | |
| list / get / close ticket (both desks) | ✓ | ✓ | ☐ |
| **MP Portal — Projects & Tasks** | | | |
| list projects / match project / list-save-delete alias | ✓ | ✓ | ☐ |
| create task / update status / update / get / search task | ✓ | ✓ | ☐ |
| in-progress / mine / overdue / recent tasks | ✓ | ✓ | ☐ |
| outstanding summary / by-project / billable summary / recent activity | ✓ | ✓ | ☐ |
| **MP Portal — Customers** | | | |
| list / get / **create** customer (confirm before create) | ✓ | ✓ | ☐ |
| **MP Portal — Activity audit log** | | | |
| log activity / list activities | ✓ | — | ☐ |
| **Composite / misc** | | | |
| daily brief | ✓ | ✓ | ☐ |
| local weather | — | ✓ | ☐ |
| submit feedback / update agent / agent status | ✓ | partial | ☐ |

**Surface differences to remember**
- **Activity logging** (`mp_log_activity` / `mp_list_activities`) is **Claude-only** on purpose — Sophie/11Labs doesn't log dev activity.
- **Local weather** is **Sophie-only**.
- Anything needing "general intelligence" away from the desk (e.g. looking up a customer's address) is the planned **OpenAI lookup on the relay** (Phase 2, not yet built).

_Counts as of last sync: Claude 73 tools · Sophie 71 tools._
