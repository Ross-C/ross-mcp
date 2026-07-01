# Ross MCP — Agent Capabilities

What the agents can do, and on which surface. Review this periodically and tick the **Verified** box once you've confirmed a skill works end to end. Keep it in sync whenever a skill is added (see the "Adding a new skill" checklist in `CLAUDE.md`).

**Surfaces**
- **Claude** = local Claude Code + the cloud MCP (`relay/mcp_endpoint.py`), used at your desk and headless.
- **Sophie** = the ElevenLabs voice agent + ChatGPT actions (`relay/openai_endpoints.py`), used away from the desk.

Both ultimately run through the local Mac agents. `✓` = available, `—` = not exposed on that surface.

## Architecture — the two-agents + cloud workflow

- **Two local Mac agents** (`mac-mini`, `macbook-pro`) in `agent/` do the real work (Apple / Outlook / Google / portal APIs) and each connects OUT to the relay.
- **Cloud relay** on Fly.io (`ross-mcp-relay`, `relay/`) — the always-on hub. Exposes the **cloud MCP** (`relay/mcp_endpoint.py`) for Claude, and **ChatGPT/11Labs REST tools** (`relay/openai_endpoints.py`) for Sophie; routes each command to a connected agent.
- **Clients:** local Claude Code + Claude Desktop/Web (cloud MCP), ChatGPT actions, and **Sophie** (ElevenLabs voice). All share the same agents via the relay.
- **MP Portal** (`mp.portal-app.uk`, **production**) — the data the portal tools read/write: projects, tasks, customers, and the activity audit log. Token id 10 (all abilities) authenticates the agents to it.
- **Activity logging:** run **`/link-customer`** in any repo to record which customer/project it maps to (writes a block into that repo's `CLAUDE.md`); Claude then logs dev work via `mp_log_activity`. See `~/CLAUDE.md`.

> Keep this document current — updating it is part of the **"Adding New Tools"** checklist in `CLAUDE.md` (every new feature is added across all surfaces, both agents restarted, fully tested, no data loss).

## Skill matrix

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
| **create project** (confirm before create) | ✓ | ✓ | ☐ |
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

## MyPurchases (external MCP — Claude only)

A separate private app (https://mypurchases.fly.dev) connected **directly to Claude Code** (`claude mcp add`, both agents), **not** via this relay — so Claude only, not Sophie. Endpoint `https://mypurchases.fly.dev/api/mcp` (bearer API key). Tracks bank transactions and whether each purchase's receipt/invoice is stored.

| Skill | Claude | Sophie | Verified |
|---|:--:|:--:|:--:|
| `missing_invoices` — what's missing by date range | ✓ | — | ☐ |
| `push_invoice` — attach a receipt/invoice to a transaction | ✓ | — | ☐ |
| `list_suppliers` | ✓ | — | ☐ |
| `list_categories` — find a category id (e.g. Payroll) | ✓ | — | ☐ |
| `classify_transaction` (single) | ✓ | — | ☐ |
| `bulk_classify` (e.g. all Holly Calvert → Payroll) | ✓ | — | ☐ |
| `backup_database` (on-demand DB snapshot) | ✓ | — | ☐ |

Workflow to add invoices: `missing_invoices` → match each file to a transaction by supplier+amount+date → `push_invoice` (one per file). **Bulk actions:** always `dry_run` first, confirm the count, offer a `backup_database` snapshot, then apply. See the MyPurchases section in `CLAUDE.md`.

**Surface differences to remember**
- **Activity logging** (`mp_log_activity` / `mp_list_activities`) is **Claude-only** on purpose — Sophie/11Labs doesn't log dev activity.
- **Local weather** is **Sophie-only**.
- Anything needing "general intelligence" away from the desk (e.g. looking up a customer's address) is the planned **OpenAI lookup on the relay** (Phase 2, not yet built).

_Counts as of last sync: Claude 73 tools · Sophie 71 tools._
