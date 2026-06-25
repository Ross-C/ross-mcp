"""Secure dashboard — login, agent status, persistent command stats, setup instructions."""

import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
DB_PATH = os.getenv("DB_PATH", "/data/mcp_stats.db")

# Agents reference — set by relay.py to avoid circular import
_agents_ref = None


def set_agents(agents_dict):
    """Called by relay.py to pass the agents dict reference."""
    global _agents_ref
    _agents_ref = agents_dict

# Sessions are stored in SQLite so they persist across deploys
MAX_SESSIONS = 20

# --- SQLite ---

_db_lock = threading.Lock()


def _init_db():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            command_type TEXT NOT NULL,
            agent TEXT NOT NULL,
            status TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            command_type TEXT,
            agent TEXT,
            error TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_commands_ts ON commands(timestamp)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_commands_type ON commands(command_type)")
        conn.execute("""CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            source TEXT NOT NULL,
            version TEXT,
            summary TEXT NOT NULL
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_updates_ts ON updates(timestamp)")
        conn.commit()
        conn.close()


@contextmanager
def _get_db():
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def record_update(source: str, summary: str, version: str | None = None):
    """Record a system update (deploy, agent update, config change)."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _get_db() as conn:
            conn.execute(
                "INSERT INTO updates (timestamp, source, version, summary) VALUES (?, ?, ?, ?)",
                (ts, source, version, summary),
            )
    except Exception:
        pass


def record_command(command_type: str, agent_name: str, status: str, error: str | None = None):
    """Record a command execution to SQLite. Prunes data older than 30 days."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _get_db() as conn:
            conn.execute(
                "INSERT INTO commands (timestamp, command_type, agent, status) VALUES (?, ?, ?, ?)",
                (ts, command_type, agent_name, status),
            )
            if error:
                conn.execute(
                    "INSERT INTO errors (timestamp, command_type, agent, error) VALUES (?, ?, ?, ?)",
                    (ts, command_type, agent_name, error),
                )
            # Prune old data (30 days)
            conn.execute("DELETE FROM commands WHERE timestamp < datetime('now', '-30 days')")
            conn.execute("DELETE FROM errors WHERE timestamp < datetime('now', '-30 days')")
            conn.execute("DELETE FROM updates WHERE timestamp < datetime('now', '-30 days')")
    except Exception:
        pass  # Don't let stats recording break command execution


def get_stats() -> dict:
    """Query aggregated stats from SQLite."""
    try:
        with _get_db() as conn:
            total = conn.execute("SELECT COUNT(*) FROM commands").fetchone()[0]

            by_type = {}
            for row in conn.execute("SELECT command_type, COUNT(*) as cnt FROM commands GROUP BY command_type"):
                by_type[row["command_type"]] = row["cnt"]

            by_date = {}
            for row in conn.execute(
                "SELECT DATE(timestamp) as d, command_type, COUNT(*) as cnt "
                "FROM commands GROUP BY d, command_type ORDER BY d"
            ):
                by_date.setdefault(row["d"], {})[row["command_type"]] = row["cnt"]

            recent = []
            for row in conn.execute(
                "SELECT timestamp, command_type, agent, status FROM commands ORDER BY id DESC LIMIT 200"
            ):
                recent.append(dict(row))

            recent_errors = []
            for row in conn.execute(
                "SELECT timestamp, command_type, agent, error FROM errors ORDER BY id DESC LIMIT 50"
            ):
                recent_errors.append(dict(row))

            by_agent = {}
            for row in conn.execute(
                "SELECT agent, COUNT(*) as cnt FROM commands GROUP BY agent"
            ):
                by_agent[row["agent"]] = row["cnt"]

            updates = []
            for row in conn.execute(
                "SELECT timestamp, source, version, summary FROM updates ORDER BY id DESC LIMIT 100"
            ):
                updates.append(dict(row))

            return {
                "total": total,
                "by_type": by_type,
                "by_date": by_date,
                "by_agent": by_agent,
                "recent": recent,
                "recent_errors": recent_errors,
                "updates": updates,
            }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"total": 0, "by_type": {}, "by_date": {}, "by_agent": {}, "recent": [], "recent_errors": []}


# --- Session Auth ---

def _create_session() -> str:
    token = secrets.token_urlsafe(32)
    try:
        with _get_db() as conn:
            conn.execute("INSERT INTO sessions (token, created_at) VALUES (?, ?)",
                         (token, datetime.now(timezone.utc).isoformat()))
            # Prune old sessions (keep most recent MAX_SESSIONS)
            conn.execute(
                "DELETE FROM sessions WHERE token NOT IN "
                "(SELECT token FROM sessions ORDER BY created_at DESC LIMIT ?)",
                (MAX_SESSIONS,))
    except Exception:
        pass
    return token


def _verify_session(request: Request) -> bool:
    token = request.cookies.get("session")
    if not token:
        return False
    try:
        with _get_db() as conn:
            row = conn.execute("SELECT created_at FROM sessions WHERE token = ?", (token,)).fetchone()
            return row is not None
    except Exception:
        return False


# --- Routes ---

@router.get("/", response_class=HTMLResponse)
async def dashboard_root(request: Request):
    if not _verify_session(request):
        return HTMLResponse(LOGIN_HTML)
    return HTMLResponse(DASHBOARD_HTML, headers={"Cache-Control": "no-cache"})


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    password = form.get("password", "")

    if not DASHBOARD_PASSWORD:
        return HTMLResponse(LOGIN_HTML.replace("<!-- ERROR -->",
            '<p class="text-red-600 text-sm mt-3">Dashboard password not configured on server</p>'))

    if not secrets.compare_digest(str(password), DASHBOARD_PASSWORD):
        return HTMLResponse(LOGIN_HTML.replace("<!-- ERROR -->",
            '<p class="text-red-600 text-sm mt-3">Incorrect password</p>'))

    token = _create_session()
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="session", value=token,
        httponly=True, secure=True, samesite="lax", max_age=86400 * 7,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session")
    return response


@router.get("/api/dashboard/stats")
async def dashboard_stats(request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    agents = _agents_ref or {}
    now = datetime.now(timezone.utc)
    agent_data = {}
    for name, a in agents.items():
        task = a.current_task
        # Clear completed tasks after 5 seconds
        if task and task.get("status") == "done":
            completed = datetime.fromisoformat(task["completed_at"])
            if (now - completed).total_seconds() > 5:
                a.current_task = None
                task = None
        agent_data[name] = {
            "machine": a.registration.machine_name,
            "capabilities": [c.value for c in a.registration.capabilities],
            "connected_at": a.connected_at.isoformat(),
            "last_seen": a.last_seen.isoformat(),
            "version": getattr(a.registration, 'version', None),
            "current_task": task,
        }
    return {"agents": agent_data, "stats": get_stats()}


# Initialise DB on import
try:
    _init_db()
except Exception:
    pass


# --- HTML Templates ---

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ross MCP</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>tailwind.config = { theme: { extend: { colors: {
        brand: { 50: '#f0f7ff', 100: '#e0effe', 500: '#3b82f6', 600: '#2563eb' }
    }}}}</script>
</head>
<body class="bg-gray-200 min-h-screen flex items-center justify-center">
    <div class="w-full max-w-sm">
        <div class="bg-white border border-gray-200 rounded-xl shadow-sm p-8">
            <h1 class="text-lg font-semibold text-gray-900 mb-1">Ross MCP</h1>
            <p class="text-gray-500 text-sm mb-6">Sign in to your dashboard</p>
            <form method="POST" action="/login">
                <input
                    type="password"
                    name="password"
                    placeholder="Password"
                    autofocus
                    class="w-full bg-gray-50 border border-gray-300 text-gray-900 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 placeholder-gray-400"
                />
                <button
                    type="submit"
                    class="w-full mt-3 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg px-3 py-2.5 transition-colors"
                >
                    Sign in
                </button>
                <!-- ERROR -->
            </form>
        </div>
    </div>
</body>
</html>"""


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ross MCP</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <script>tailwind.config = { theme: { extend: { colors: {
        brand: { 50: '#f0f7ff', 100: '#e0effe', 500: '#3b82f6', 600: '#2563eb' }
    }}}}</script>
    <style>
        .tab-active { color: #1d4ed8; border-bottom: 2px solid #3b82f6; }
        .tab-inactive { color: #6b7280; border-bottom: 2px solid transparent; }
        .tab-inactive:hover { color: #374151; }
    </style>
</head>
<body class="bg-gray-200 text-gray-800 min-h-screen">

    <!-- Nav -->
    <nav class="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div class="max-w-6xl mx-auto px-4 sm:px-6 flex items-center justify-between h-14">
            <div class="flex items-center gap-6">
                <span class="text-gray-900 font-semibold text-sm">Ross MCP</span>
                <div class="flex" id="tabs">
                    <button onclick="showTab('overview')" data-tab="overview" class="tab-active px-3 py-4 text-sm font-medium transition-colors">Overview</button>
                    <button onclick="showTab('agents')" data-tab="agents" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Agents</button>
                    <button onclick="showTab('activity')" data-tab="activity" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Activity</button>
                    <button onclick="showTab('errors')" data-tab="errors" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Errors</button>
                    <button onclick="showTab('updates')" data-tab="updates" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Updates</button>
                    <button onclick="showTab('setup')" data-tab="setup" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Setup</button>
                </div>
            </div>
            <a href="/logout" class="text-gray-400 hover:text-gray-600 text-sm transition-colors">Sign out</a>
        </div>
    </nav>

    <main class="max-w-6xl mx-auto px-4 sm:px-6 py-6">

        <!-- Overview Tab -->
        <div id="tab-overview">
            <!-- Live agent status -->
            <div id="live-agents" class="mb-4"></div>
            <!-- Summary row -->
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
                <div class="bg-white border border-gray-200 rounded-xl p-4">
                    <div class="text-gray-400 text-xs font-medium uppercase tracking-wide">Agents Online</div>
                    <div class="text-2xl font-bold text-gray-900 mt-1" id="stat-agents">-</div>
                </div>
                <div class="bg-white border border-gray-200 rounded-xl p-4">
                    <div class="text-gray-400 text-xs font-medium uppercase tracking-wide">Total Commands</div>
                    <div class="text-2xl font-bold text-gray-900 mt-1" id="stat-total">-</div>
                </div>
                <div class="bg-white border border-gray-200 rounded-xl p-4">
                    <div class="text-gray-400 text-xs font-medium uppercase tracking-wide">Today</div>
                    <div class="text-2xl font-bold text-gray-900 mt-1" id="stat-today">-</div>
                </div>
                <div class="bg-white border border-gray-200 rounded-xl p-4">
                    <div class="text-gray-400 text-xs font-medium uppercase tracking-wide">Errors</div>
                    <div class="text-2xl font-bold text-gray-900 mt-1" id="stat-errors">-</div>
                </div>
            </div>

            <!-- Tool breakdown -->
            <div class="bg-white border border-gray-200 rounded-xl p-5 mb-6">
                <h3 class="text-sm font-semibold text-gray-700 mb-4">Tool Usage Breakdown</h3>
                <div id="tool-breakdown" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-8 gap-y-1 text-sm"></div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div class="lg:col-span-2 bg-white border border-gray-200 rounded-xl p-5">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-sm font-semibold text-gray-700">Commands by Day</h3>
                        <select id="chart-range" onchange="updateCharts()" class="bg-gray-50 border border-gray-200 text-gray-600 text-xs rounded-lg px-2.5 py-1.5 focus:outline-none">
                            <option value="7">7 days</option>
                            <option value="14" selected>14 days</option>
                            <option value="30">30 days</option>
                        </select>
                    </div>
                    <div class="relative" style="height:200px"><canvas id="chart-daily"></canvas></div>
                </div>
                <div class="bg-white border border-gray-200 rounded-xl p-5">
                    <h3 class="text-sm font-semibold text-gray-700 mb-4">Category Breakdown</h3>
                    <div id="chart-cat-wrap" class="relative" style="height:200px"><canvas id="chart-categories"></canvas></div>
                </div>
            </div>
        </div>

        <!-- Agents Tab -->
        <div id="tab-agents" class="hidden">
            <div id="agents-list" class="space-y-3">
                <p class="text-gray-400">Loading...</p>
            </div>
        </div>

        <!-- Activity Tab -->
        <div id="tab-activity" class="hidden">
            <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <div class="px-4 py-3 border-b border-gray-100 flex items-center gap-3">
                    <input
                        type="text"
                        id="activity-filter"
                        placeholder="Filter by command type..."
                        oninput="renderActivity()"
                        class="bg-gray-50 border border-gray-200 text-gray-700 rounded-lg px-3 py-1.5 text-sm flex-1 max-w-xs focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-400"
                    />
                    <span class="text-gray-400 text-xs" id="activity-count"></span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-gray-400 text-xs uppercase tracking-wide border-b border-gray-100 bg-gray-50">
                                <th class="text-left px-4 py-2.5 font-medium">Time</th>
                                <th class="text-left px-4 py-2.5 font-medium">Command</th>
                                <th class="text-left px-4 py-2.5 font-medium">Agent</th>
                                <th class="text-left px-4 py-2.5 font-medium">Status</th>
                            </tr>
                        </thead>
                        <tbody id="activity-body" class="divide-y divide-gray-50"></tbody>
                    </table>
                </div>
                <div id="activity-pagination" class="px-4 py-3 border-t border-gray-100 flex items-center justify-between"></div>
            </div>
        </div>

        <!-- Errors Tab -->
        <div id="tab-errors" class="hidden">
            <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-gray-400 text-xs uppercase tracking-wide border-b border-gray-100 bg-gray-50">
                                <th class="text-left px-4 py-2.5 font-medium">Time</th>
                                <th class="text-left px-4 py-2.5 font-medium">Command</th>
                                <th class="text-left px-4 py-2.5 font-medium">Agent</th>
                                <th class="text-left px-4 py-2.5 font-medium">Error</th>
                            </tr>
                        </thead>
                        <tbody id="errors-body" class="divide-y divide-gray-50"></tbody>
                    </table>
                </div>
                <div id="no-errors" class="hidden px-4 py-8 text-center text-gray-400 text-sm">No errors recorded</div>
            </div>
        </div>

        <!-- Updates Tab -->
        <div id="tab-updates" class="hidden">
            <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <div class="px-4 py-3 border-b border-gray-100">
                    <span class="text-sm font-semibold text-gray-700">System Updates</span>
                    <span class="text-gray-400 text-xs ml-2" id="updates-count"></span>
                </div>
                <div id="updates-list" class="divide-y divide-gray-50"></div>
                <div id="no-updates" class="hidden px-4 py-8 text-center text-gray-400 text-sm">No updates recorded yet</div>
                <div id="updates-pagination" class="px-4 py-3 border-t border-gray-100 flex items-center justify-between"></div>
            </div>
        </div>

        <!-- Setup Tab -->
        <div id="tab-setup" class="hidden">
            <div class="space-y-4 max-w-3xl">
                <div class="bg-white border border-gray-200 rounded-xl p-5">
                    <h3 class="text-gray-900 font-semibold mb-3">Claude Desktop / Claude Web</h3>
                    <p class="text-gray-500 text-sm mb-3">Add as a remote MCP server in Claude's settings:</p>
                    <div class="bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm font-mono">
                        <div class="text-gray-400 text-xs mb-2"># MCP Server Settings</div>
                        <div class="text-gray-700"><span class="text-gray-400">URL:</span> https://ross-mcp-relay.fly.dev/mcp/mcp</div>
                        <div class="text-gray-700"><span class="text-gray-400">Transport:</span> Streamable HTTP</div>
                        <div class="text-gray-700"><span class="text-gray-400">Auth:</span> Bearer token (your RELAY_API_KEY from .env)</div>
                    </div>
                    <p class="text-gray-400 text-xs mt-3">In Claude Desktop: Settings &gt; MCP Servers &gt; Add Server</p>
                </div>

                <div class="bg-white border border-gray-200 rounded-xl p-5">
                    <h3 class="text-gray-900 font-semibold mb-3">Claude Code (CLI)</h3>
                    <p class="text-gray-500 text-sm mb-3">Add to <code class="text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded text-xs">~/.claude/settings.json</code>:</p>
                    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm font-mono text-gray-700 overflow-x-auto">{
  "mcpServers": {
    "ross-life-admin": {
      "type": "http",
      "url": "https://ross-mcp-relay.fly.dev/mcp/mcp",
      "headers": {
        "Authorization": "Bearer your-relay-api-key"
      }
    }
  }
}</pre>
                </div>

                <div class="bg-white border border-gray-200 rounded-xl p-5">
                    <h3 class="text-gray-900 font-semibold mb-3">ChatGPT (Custom GPT)</h3>
                    <ol class="text-gray-500 text-sm space-y-2 list-decimal list-inside">
                        <li>Create a Custom GPT at <span class="text-blue-600">chat.openai.com</span></li>
                        <li>Go to <strong class="text-gray-700">Configure</strong> &gt; <strong class="text-gray-700">Actions</strong> &gt; <strong class="text-gray-700">Create new action</strong></li>
                        <li>Click <strong class="text-gray-700">Import from URL</strong>: <code class="text-blue-600 bg-blue-50 px-1.5 py-0.5 rounded text-xs">https://ross-mcp-relay.fly.dev/openapi.json</code></li>
                        <li>Under <strong class="text-gray-700">Authentication</strong>, select <strong class="text-gray-700">API Key</strong>, type <strong class="text-gray-700">Bearer</strong>, and paste the same RELAY_API_KEY</li>
                    </ol>
                </div>


                <div class="bg-white border border-gray-200 rounded-xl p-5">
                    <h3 class="text-gray-900 font-semibold mb-3">REST API</h3>
                    <pre class="bg-gray-50 border border-gray-200 rounded-lg p-3 text-sm font-mono text-gray-700 overflow-x-auto">curl -X POST https://ross-mcp-relay.fly.dev/api/command \\
  -H "Authorization: Bearer your-relay-api-key" \\
  -H "Content-Type: application/json" \\
  -d '{"type": "create_reminder", "payload": {"title": "Buy milk"}}'</pre>
                    <p class="text-gray-400 text-xs mt-3">
                        Interactive docs: <a href="/docs" class="text-blue-600 hover:underline">/docs</a>
                    </p>
                </div>
            </div>
        </div>

    </main>

    <script>
    let dashData = null;
    let dailyChart = null;
    let categoryChart = null;
    let activityPage = 0;
    let updatesPage = 0;
    const PAGE_SIZE = 25;

    function paginationHtml(totalItems, currentPage, onClickFn) {
        const totalPages = Math.ceil(totalItems / PAGE_SIZE);
        if (totalPages <= 1) return '';
        const start = currentPage * PAGE_SIZE + 1;
        const end = Math.min((currentPage + 1) * PAGE_SIZE, totalItems);
        return `<span class="text-xs text-gray-400">${start}–${end} of ${totalItems}</span>
            <div class="flex gap-1">
                <button onclick="${onClickFn}(-1)" ${currentPage === 0 ? 'disabled' : ''}
                    class="px-2.5 py-1 text-xs rounded border ${currentPage === 0 ? 'text-gray-300 border-gray-100 cursor-not-allowed' : 'text-gray-600 border-gray-200 hover:bg-gray-50'}">Prev</button>
                <button onclick="${onClickFn}(1)" ${currentPage >= totalPages - 1 ? 'disabled' : ''}
                    class="px-2.5 py-1 text-xs rounded border ${currentPage >= totalPages - 1 ? 'text-gray-300 border-gray-100 cursor-not-allowed' : 'text-gray-600 border-gray-200 hover:bg-gray-50'}">Next</button>
            </div>`;
    }

    function changeActivityPage(dir) { activityPage = Math.max(0, activityPage + dir); renderActivity(); }
    function changeUpdatesPage(dir) { updatesPage = Math.max(0, updatesPage + dir); renderUpdates(); }

    const TOOL_CATEGORIES = {
        'Email': ['search_emails', 'get_email', 'get_thread', 'create_draft', 'draft_reply', 'update_draft', 'send_draft', 'send_email', 'schedule_send', 'cancel_scheduled_send', 'archive_email', 'add_attachment'],
        'Gmail': ['gmail_search', 'gmail_get_email', 'gmail_get_thread', 'gmail_create_draft', 'gmail_archive', 'gmail_list_labels'],
        'Calendar': ['list_events', 'create_event', 'update_event', 'cancel_event', 'find_available_slots'],
        'Reminders': ['create_reminder', 'list_reminders', 'complete_reminder'],
        'Notes': ['search_notes', 'get_note', 'create_note', 'list_note_folders'],
        'Voice': ['list_recordings', 'transcribe_recording'],
        'Documents': ['convert_md_to_pdf', 'convert_md_to_docx'],
        'System': ['update_agent', 'agent_status', 'ping'],
    };

    const BLOCKED_TOOLS = new Set(['send_draft', 'send_email', 'schedule_send']);

    const CATEGORY_COLOURS = {
        'Email': '#60a5fa',
        'Gmail': '#f87171',
        'Calendar': '#6ee7b7',
        'Reminders': '#fbbf24',
        'Notes': '#c4b5fd',
        'Voice': '#f9a8d4',
        'Documents': '#67e8f9',
        'System': '#cbd5e1',
    };

    const TOOL_LABELS = {
        'search_emails': 'Search emails',
        'get_email': 'Read email',
        'get_thread': 'Read thread',
        'create_draft': 'Create draft',
        'draft_reply': 'Draft reply',
        'update_draft': 'Update draft',
        'send_draft': 'Send draft',
        'send_email': 'Send email',
        'schedule_send': 'Schedule email',
        'cancel_scheduled_send': 'Cancel scheduled',
        'archive_email': 'Archive email',
        'add_attachment': 'Add attachment',
        'list_events': 'List events',
        'create_event': 'Create event',
        'update_event': 'Update event',
        'cancel_event': 'Cancel event',
        'find_available_slots': 'Find free slots',
        'create_reminder': 'Create reminder',
        'list_reminders': 'List reminders',
        'complete_reminder': 'Complete reminder',
        'search_notes': 'Search notes',
        'get_note': 'Read note',
        'create_note': 'Create note',
        'list_note_folders': 'List folders',
        'list_recordings': 'List recordings',
        'transcribe_recording': 'Transcribe',
        'convert_md_to_pdf': 'MD to PDF',
        'convert_md_to_docx': 'MD to DOCX',
        'update_agent': 'Update agent',
        'agent_status': 'Agent status',
        'ping': 'Ping',
    };

    function showTab(name) {
        document.querySelectorAll('[id^="tab-"]').forEach(el => el.classList.add('hidden'));
        document.getElementById('tab-' + name).classList.remove('hidden');
        document.querySelectorAll('[data-tab]').forEach(btn => {
            btn.className = btn.dataset.tab === name
                ? 'tab-active px-3 py-4 text-sm font-medium transition-colors'
                : 'tab-inactive px-3 py-4 text-sm font-medium transition-colors';
        });
    }

    async function fetchData() {
        try {
            const resp = await fetch('/api/dashboard/stats');
            if (resp.status === 401) { window.location.href = '/'; return; }
            dashData = await resp.json();
            renderLiveAgents();
            renderOverview();
            renderAgents();
            renderActivity();
            renderErrors();
            renderUpdates();
            updateCharts();
        } catch (e) {
            console.error('Fetch failed:', e);
        }
    }

    function renderLiveAgents() {
        if (!dashData) return;
        const el = document.getElementById('live-agents');
        const entries = Object.entries(dashData.agents);
        if (entries.length === 0) {
            el.innerHTML = '<div class="bg-amber-50 border border-amber-200 rounded-xl p-4 text-amber-700 text-sm">No agents online</div>';
            return;
        }
        el.innerHTML = '<div class="grid grid-cols-1 sm:grid-cols-' + Math.min(entries.length, 3) + ' gap-3">' +
            entries.map(([name, info]) => {
                const task = info.current_task;
                if (task && task.status === 'running') {
                    return `<div class="bg-blue-50 border border-blue-200 rounded-xl p-4 flex items-center gap-3">
                        <div class="w-2 h-2 rounded-full bg-blue-500 animate-pulse flex-shrink-0"></div>
                        <div>
                            <span class="text-gray-900 font-semibold text-sm">${name}</span>
                            <span class="text-blue-700 text-sm ml-2">${task.description}</span>
                        </div>
                    </div>`;
                }
                if (task && task.status === 'done') {
                    return `<div class="bg-emerald-50 border border-emerald-200 rounded-xl p-4 flex items-center gap-3">
                        <svg class="w-4 h-4 text-emerald-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                        <div>
                            <span class="text-gray-900 font-semibold text-sm">${name}</span>
                            <span class="text-emerald-600 text-sm ml-2">${task.description}</span>
                        </div>
                    </div>`;
                }
                return `<div class="bg-white border border-gray-200 rounded-xl p-4 flex items-center gap-3">
                    <div class="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0"></div>
                    <div>
                        <span class="text-gray-900 font-semibold text-sm">${name}</span>
                        <span class="text-gray-400 text-sm ml-2">Idle</span>
                    </div>
                </div>`;
            }).join('') + '</div>';
    }

    function renderOverview() {
        if (!dashData) return;
        const s = dashData.stats;
        const bt = s.by_type || {};
        const byDate = s.by_date || {};
        const today = new Date().toISOString().split('T')[0];
        const todayData = byDate[today] || {};
        const todayTotal = Object.values(todayData).reduce((a, b) => a + b, 0);
        const errorCount = (s.recent_errors || []).length;

        document.getElementById('stat-agents').textContent = Object.keys(dashData.agents).length;
        document.getElementById('stat-total').textContent = (s.total || 0).toLocaleString();
        document.getElementById('stat-today').textContent = todayTotal;
        document.getElementById('stat-errors').textContent = errorCount;

        // Render granular tool breakdown grouped by category
        let html = '';
        for (const [cat, tools] of Object.entries(TOOL_CATEGORIES)) {
            const catTools = tools.filter(t => bt[t]);
            if (catTools.length === 0) continue;
            const colour = CATEGORY_COLOURS[cat];
            html += `<div class="mb-3">
                <div class="flex items-center gap-2 mb-1.5">
                    <div class="w-2 h-2 rounded-full" style="background:${colour}"></div>
                    <span class="text-xs font-semibold text-gray-500 uppercase tracking-wide">${cat}</span>
                </div>`;
            for (const t of catTools) {
                html += `<div class="flex justify-between py-0.5 pl-4">
                    <span class="text-gray-600">${TOOL_LABELS[t] || t}</span>
                    <span class="text-gray-900 font-medium tabular-nums">${bt[t]}</span>
                </div>`;
            }
            html += '</div>';
        }
        document.getElementById('tool-breakdown').innerHTML = html || '<p class="text-gray-400 col-span-3">No commands recorded yet</p>';
    }

    function renderAgents() {
        if (!dashData) return;
        const el = document.getElementById('agents-list');
        const entries = Object.entries(dashData.agents);
        const byAgent = dashData.stats.by_agent || {};
        if (entries.length === 0) {
            el.innerHTML = '<div class="bg-white border border-gray-200 rounded-xl p-6 text-center text-gray-400">No agents connected</div>';
            return;
        }
        el.innerHTML = entries.map(([name, info]) => {
            const connectedAt = new Date(info.connected_at);
            const mins = Math.round((Date.now() - connectedAt.getTime()) / 60000);
            const uptime = mins < 60 ? mins + 'm' : Math.floor(mins / 60) + 'h ' + (mins % 60) + 'm';
            const cmdCount = byAgent[name] || 0;
            const ver = info.version ? `<span class="text-gray-400 text-xs font-mono">${info.version}</span>` : '';
            const task = info.current_task;
            let taskHtml;
            if (task && task.status === 'running') {
                taskHtml = `<div class="flex items-center gap-2 mt-3 px-3 py-2 bg-blue-50 border border-blue-200 rounded-lg">
                    <div class="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse"></div>
                    <span class="text-blue-700 text-sm font-medium">${task.description}</span>
                   </div>`;
            } else if (task && task.status === 'done') {
                taskHtml = `<div class="flex items-center gap-2 mt-3 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-lg">
                    <svg class="w-3.5 h-3.5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
                    <span class="text-emerald-600 text-sm font-medium">${task.description}</span>
                   </div>`;
            } else {
                taskHtml = `<div class="flex items-center gap-2 mt-3 px-3 py-2 bg-gray-50 border border-gray-100 rounded-lg">
                    <div class="w-1.5 h-1.5 rounded-full bg-gray-300"></div>
                    <span class="text-gray-400 text-sm">Idle</span>
                   </div>`;
            }
            return `
            <div class="bg-white border border-gray-200 rounded-xl p-5">
                <div class="flex items-center justify-between mb-3">
                    <div class="flex items-center gap-2">
                        <div class="w-2 h-2 rounded-full bg-emerald-400"></div>
                        <span class="text-gray-900 font-semibold">${name}</span>
                        <span class="text-gray-400 text-sm font-normal">${info.machine}</span>
                        ${ver}
                    </div>
                    <span class="text-xs text-gray-400">${cmdCount} commands handled</span>
                </div>
                <div class="text-xs text-gray-400 mb-1">
                    Connected ${connectedAt.toLocaleString()} &middot; Uptime: ${uptime} &middot; ${info.capabilities.length} tools
                </div>
                ${taskHtml}
                <details class="mt-3">
                    <summary class="text-xs text-gray-400 cursor-pointer hover:text-gray-600">Show capabilities</summary>
                    <div class="flex flex-wrap gap-1.5 mt-2">
                        ${info.capabilities.map(c => {
                            if (BLOCKED_TOOLS.has(c)) {
                                return '<span class="bg-red-50 text-red-500 text-xs px-2 py-0.5 rounded-full border border-red-200" title="Blocked for safety">' + c + '</span>';
                            }
                            return '<span class="bg-gray-100 text-gray-500 text-xs px-2 py-0.5 rounded-full">' + c + '</span>';
                        }).join('')}
                    </div>
                </details>
            </div>`;
        }).join('');
    }

    function renderActivity() {
        if (!dashData) return;
        const filter = (document.getElementById('activity-filter').value || '').toLowerCase();
        if (filter) activityPage = 0;
        const allItems = (dashData.stats.recent || []).filter(r =>
            !filter || r.command_type.toLowerCase().includes(filter)
        );
        const paged = allItems.slice(activityPage * PAGE_SIZE, (activityPage + 1) * PAGE_SIZE);
        document.getElementById('activity-count').textContent = allItems.length + ' commands';
        document.getElementById('activity-body').innerHTML = paged.map(r => {
            const time = new Date(r.timestamp).toLocaleString();
            const ok = r.status === 'success';
            const desc = TOOL_LABELS[r.command_type] || r.command_type;
            return `<tr class="hover:bg-gray-50">
                <td class="px-4 py-2.5 text-gray-400 whitespace-nowrap">${time}</td>
                <td class="px-4 py-2.5"><span class="text-gray-700">${desc}</span> <span class="text-gray-300 font-mono text-xs">${r.command_type}</span></td>
                <td class="px-4 py-2.5 text-gray-400">${r.agent}</td>
                <td class="px-4 py-2.5">
                    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${ok ? 'bg-emerald-50 text-emerald-600' : 'bg-red-50 text-red-600'}">
                        ${r.status}
                    </span>
                </td>
            </tr>`;
        }).join('');
        document.getElementById('activity-pagination').innerHTML = paginationHtml(allItems.length, activityPage, 'changeActivityPage');
    }

    function renderErrors() {
        if (!dashData) return;
        const errors = dashData.stats.recent_errors || [];
        const noErrors = document.getElementById('no-errors');
        const tbody = document.getElementById('errors-body');
        if (errors.length === 0) {
            noErrors.classList.remove('hidden');
            tbody.innerHTML = '';
            return;
        }
        noErrors.classList.add('hidden');
        tbody.innerHTML = errors.map(r => {
            const time = new Date(r.timestamp).toLocaleString();
            return `<tr class="hover:bg-gray-50">
                <td class="px-4 py-2.5 text-gray-400 whitespace-nowrap">${time}</td>
                <td class="px-4 py-2.5 text-gray-700 font-mono text-xs">${r.command_type || '-'}</td>
                <td class="px-4 py-2.5 text-gray-400">${r.agent || '-'}</td>
                <td class="px-4 py-2.5 text-red-600 text-xs max-w-md truncate">${r.error}</td>
            </tr>`;
        }).join('');
    }

    function updateCharts() {
        if (!dashData) return;
        const days = parseInt(document.getElementById('chart-range').value) || 14;
        const byDate = dashData.stats.by_date || {};

        const labels = [];
        const now = new Date();
        for (let i = days - 1; i >= 0; i--) {
            const d = new Date(now);
            d.setDate(d.getDate() - i);
            labels.push(d.toISOString().split('T')[0]);
        }

        const dailyTotals = labels.map(date => {
            const dayData = byDate[date] || {};
            return Object.values(dayData).reduce((a, b) => a + b, 0);
        });

        if (dailyChart) dailyChart.destroy();
        dailyChart = new Chart(document.getElementById('chart-daily'), {
            type: 'bar',
            data: {
                labels: labels.map(d => { const p = d.split('-'); return p[2] + '/' + p[1]; }),
                datasets: [{
                    data: dailyTotals,
                    backgroundColor: '#93c5fd',
                    hoverBackgroundColor: '#60a5fa',
                    borderRadius: 4,
                    maxBarThickness: 28,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#9ca3af', font: { size: 11 } },
                        border: { color: '#e5e7eb' },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: '#f3f4f6' },
                        ticks: {
                            color: '#9ca3af',
                            font: { size: 11 },
                            stepSize: 1,
                            callback: v => Number.isInteger(v) ? v : '',
                        },
                        border: { display: false },
                    }
                }
            }
        });

        const catTotals = {};
        const bt = dashData.stats.by_type || {};
        for (const [cat, tools] of Object.entries(TOOL_CATEGORIES)) {
            const total = tools.reduce((sum, t) => sum + (bt[t] || 0), 0);
            if (total > 0) catTotals[cat] = total;
        }

        if (categoryChart) categoryChart.destroy();
        const catLabels = Object.keys(catTotals);

        if (catLabels.length === 0) {
            if (categoryChart) { categoryChart.destroy(); categoryChart = null; }
            const wrap = document.getElementById('chart-cat-wrap');
            if (!wrap.querySelector('.no-data')) {
                wrap.innerHTML = '<p class="no-data text-gray-400 text-sm text-center" style="padding-top:80px">No data yet</p>';
            }
            return;
        }
        // Restore canvas if it was replaced
        const wrap = document.getElementById('chart-cat-wrap');
        if (!wrap.querySelector('canvas')) {
            wrap.innerHTML = '<canvas id="chart-categories"></canvas>';
        }

        categoryChart = new Chart(document.getElementById('chart-categories'), {
            type: 'doughnut',
            data: {
                labels: catLabels,
                datasets: [{
                    data: catLabels.map(c => catTotals[c]),
                    backgroundColor: catLabels.map(c => CATEGORY_COLOURS[c] || '#cbd5e1'),
                    borderWidth: 0,
                    spacing: 2,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '60%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#6b7280',
                            font: { size: 11 },
                            padding: 12,
                            usePointStyle: true,
                            pointStyleWidth: 8,
                        }
                    }
                }
            }
        });
    }

    function renderUpdates() {
        if (!dashData) return;
        const allUpdates = dashData.stats.updates || [];
        const el = document.getElementById('updates-list');
        const noUpdates = document.getElementById('no-updates');
        document.getElementById('updates-count').textContent = allUpdates.length + ' entries';
        if (allUpdates.length === 0) {
            noUpdates.classList.remove('hidden');
            el.innerHTML = '';
            document.getElementById('updates-pagination').innerHTML = '';
            return;
        }
        noUpdates.classList.add('hidden');

        const paged = allUpdates.slice(updatesPage * PAGE_SIZE, (updatesPage + 1) * PAGE_SIZE);

        const SOURCE_ICONS = {
            'relay': '&#9881;',
            'macbook-pro': '&#9899;',
            'mac-mini': '&#9899;',
        };

        el.innerHTML = paged.map(u => {
            const time = new Date(u.timestamp).toLocaleString();
            const icon = SOURCE_ICONS[u.source] || '&#8226;';
            const ver = u.version ? `<span class="text-gray-400 font-mono text-xs ml-2">${u.version}</span>` : '';
            return `<div class="px-4 py-3 hover:bg-gray-50 flex items-start gap-3">
                <span class="text-gray-400 mt-0.5">${icon}</span>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2">
                        <span class="text-sm font-medium text-gray-700">${u.source}</span>
                        ${ver}
                        <span class="text-xs text-gray-400 ml-auto whitespace-nowrap">${time}</span>
                    </div>
                    <p class="text-sm text-gray-500 mt-0.5">${u.summary}</p>
                </div>
            </div>`;
        }).join('');
        document.getElementById('updates-pagination').innerHTML = paginationHtml(allUpdates.length, updatesPage, 'changeUpdatesPage');
    }

    fetchData();
    setInterval(fetchData, 3000);
    </script>
</body>
</html>"""
