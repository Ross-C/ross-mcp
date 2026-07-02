# Ross MCP — Virtual PA System

## Portal activity mapping
Not customer-related — do not log portal activity (this is Ross's own admin tooling).

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

A new skill must be added **across the board** so Claude AND Sophie (11Labs) both get it. Update ALL of these:
1. `shared/messages.py` — add CommandType enum value and payload model
2. `agent/services/<service>.py` — the method that actually does the work (e.g. `mp_portal.py` for portal tools)
3. `agent/agent.py` — add the CommandType to the **capabilities registration list** AND a handler case (both — a missing capability means the relay can't route to the agent)
4. `relay/mcp_endpoint.py` — add `@mcp.tool()` function
5. `relay/openai_endpoints.py` — add request model + endpoint (unless the skill is deliberately Claude-only, like activity logging)
6. ElevenLabs — create webhook tool via API pointing to `/api/tools/<slug>` and add to agent's `tool_ids`
7. `CAPABILITIES.md` — add the skill row (which surfaces it's on)

**Then, every time (do not skip):**
- **Propagate everywhere:** `git push`, `fly deploy` the relay, and **restart BOTH local agents** (Mac Mini + MacBook) so they load the new code — `ssh macbook` is set up for this. An agent that didn't restart is running old code.
- **Fully test end to end** on each surface that exposes the skill — actually call it (e.g. via the MCP tool) and confirm the round trip. Don't assume; verify.
- **PRODUCTION SAFETY (always remember):** the portal is the **live production app**. NEVER run `migrate:fresh`/`migrate:refresh`/`db:wipe`. Never drop or destructively alter data without explicit permission. Migrations must be additive; back up the prod DB before any schema change; flag anything destructive and get a yes first.

## MyPurchases (connected MCP server)

**MyPurchases** is a separate private app (Ross-only) that tracks bank transactions (Starling) and whether each purchase has its receipt/invoice stored. It is connected to Claude Code as its **own MCP server** — added via `claude mcp add` on **both** agents (Mac Mini + MacBook), **not** routed through this relay. So at this stage it's available to **Claude Code only** (not Sophie/ChatGPT).

- **App / dashboard:** https://mypurchases.fly.dev
- **MCP endpoint:** `https://mypurchases.fly.dev/api/mcp` (streamable-http, JSON-RPC 2.0)
- **Auth:** `Authorization: Bearer <api-key>` (key generated in MyPurchases → Settings → Integrations)
- **Server name in Claude Code:** `mypurchases`

**Capabilities (tools — auto-discovered via `tools/list`):**
- `missing_invoices { from?, to?, supplier_id? }` — transactions still missing a receipt/invoice for a date range (defaults to last 30 days). Returns `transaction_id`, date, supplier, amount, reference.
- `push_invoice { transaction_id?, purchase_id?, filename, content_base64, modified_at? }` — attach ONE receipt/invoice file to a specific transaction OR a purchase (split line-item / installment) and mark it stored. **Individual** so THIS side decides placement.
- `push_invoice_to_supplier { supplier_id, filename, content_base64, on_duplicate?, modified_at? }` — fire an invoice at a supplier WITHOUT a transaction. It reads the invoice and PROPOSES a match for review on the Receipts page (exact-amount single, or a sum-to-payment group on a credit account) — **nothing is auto-attached** (Ross accepts/refuses). `on_duplicate` = skip (default) / replace / keep (dedupe by content hash+size).
- `ai_suggest_match { supplier_id?, document_id? }` — Claude reads the supplier's unmatched documents and **proposes** which transaction each belongs to + the VAT rate. **Proposals only — nothing is applied.** Show Ross, then apply with `push_invoice`/`classify_transaction`.
- `split_transaction { transaction_id, items:[{amount, description?, category_id?, vat_rate?, supplier_id?}] }` — ACCOUNT PAYMENT: split one transaction (e.g. an Amazon credit payment) into several purchases, each with its own invoice/VAT.
- `create_purchase { description?, supplier_id?, category_id?, amount?, vat_rate?, transaction_ids?[] }` + `link_purchase { purchase_id, transaction_id, amount? }` — INSTALLMENTS: one purchase paid across several transactions (e.g. a Klarna iPad).
- `list_suppliers` — id, name, bank match name.
- `list_categories` — id, name, is_purchase, default_type. **Call this to find the category_id** (e.g. for "Payroll") before classify/bulk. `default_type` = the type a category forces on its transactions (e.g. Payroll/Pension/Bank Charges → other, Drawings → drawing).
- `classify_transaction { transaction_id, type?, category_id?, vat_rate?, invoice_status?, supplier_id? }` — set a SINGLE transaction. `supplier_id` **overrides the supplier** (the bank counterparty may differ from the real supplier — e.g. a Klarna payment that's really KRCS; the bank name is kept).
- `bulk_classify { supplier_id?, search?, from?, to?, type?, category_id?, vat_rate?, invoice_status?, set_supplier_id?, make_default?, dry_run? }` — apply to EVERY matching transaction (e.g. all "Holly Calvert" → Payroll, or all "Klarna" → supplier KRCS via `set_supplier_id`). `make_default` stores it as the supplier's default for future imports.
- `create_supplier { name }` — create a supplier not in the bank feed (e.g. KRCS), returns its id so a transaction can be reassigned to it.
- `search_activity { q?, source?, subject?, limit? }` — search the **audit trail** (every change with before/after + source web/mcp/feed/rule/ai). Use to check what changed or trace something that went wrong automatically. `source` ∈ web|mcp|feed|rule|ai|system; `subject` ∈ Transaction|Supplier|Category|Purchase|Document.
- `process_dropbox_pickup {}` — pull loose receipts from the Dropbox `/Purchases/Pickup` folder into the Receipts queue (moves originals to `/Pickup/Processed`). Requires Dropbox connected + enabled in Settings.
- `backup_database {}` — on-demand DB backup to DigitalOcean Spaces.

**⚠️ Safety — ALWAYS (Ross's rule):**
- **Confirm before adding anything** (a document/invoice) or making any change. Never write on Ross's behalf without a clear yes.
- **Bulk actions require a two-step + backup offer:** for `bulk_classify`, FIRST call with `dry_run: true`, show Ross the count + sample, and **offer to take a database backup** (`backup_database`) first. Only call again with `dry_run: false` after he explicitly confirms. Same for anything that changes many rows.
- **Existing invoices are protected:** the server refuses any attempt by the MCP to replace or delete a stored receipt/invoice (e.g. `push_invoice_to_supplier` with `on_duplicate: replace`) — that's manual (web UI) only. Don't try to work around it.
- **Everything the MCP does is audited** (source `mcp`), so it's all traceable via `search_activity`.

**Workflow — adding invoices / "what am I missing?" (this is the logic to use):**
1. Call `missing_invoices` for the date range Ross means. Present the outstanding transactions (supplier · date · amount).
2. For each invoice file Ross has (email attachment, download, scan), work out which transaction it belongs to by **matching supplier + amount + date**. If ambiguous, ask Ross — never guess.
3. Read the file, base64-encode it, and call `push_invoice` with that `transaction_id`, the filename, and `content_base64`. **One call per invoice.**
4. Confirm each result (`status: "attached"`, `invoice_status: "stored"`).

MyPurchases is a peer MCP, not a relay tool, so it is NOT part of the "Adding New Tools" propagation checklist below. To add it to a new machine: `claude mcp add --transport http mypurchases https://mypurchases.fly.dev/api/mcp --header "Authorization: Bearer <key>" -s user`.

## Clients

### Claude Code / Claude Desktop / Claude Web
- MCP server: `https://ross-mcp-relay.fly.dev/mcp/mcp` (streamable-http, Bearer token auth)
- Email style rules embedded in MCP `instructions` and tool docstrings
- Also connected: **`mypurchases`** MCP (see the MyPurchases section above) — Claude-only, direct (not via relay).

### ChatGPT Custom GPT
- Actions imported from: `https://ross-mcp-relay.fly.dev/openapi.json`
- Auth: API Key, Bearer token (RELAY_API_KEY)
- New endpoints auto-discovered from OpenAPI spec on deploy
- Max 30 operations (internal routes excluded via `include_in_schema=False`)

### ElevenLabs Voice Agent
- Agent ID: `agent_1601kvz6xrrje8avnvdcchnsnwcf`
- Voice: Sophie — Northern UK female (`Q7iNt6VsGSsBbtyUto9N`)
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

- "email" / "calendar" = Outlook (Office 365)
- "Gmail" = Google email (explicitly named)
- "Google Calendar" = Google calendar (explicitly named)
- "personal calendar" / "iCloud calendar" / "birthdays" = Apple iCloud Calendar

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
