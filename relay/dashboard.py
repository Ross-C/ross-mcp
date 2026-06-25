"""Secure dashboard — login, agent status, persistent command stats, setup instructions."""

import os
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(include_in_schema=False)

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
        conn.execute("""CREATE TABLE IF NOT EXISTS failed_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            payload TEXT NOT NULL,
            error TEXT NOT NULL,
            source TEXT,
            status TEXT NOT NULL DEFAULT 'failed',
            reprocessed_at TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_failed_ts ON failed_requests(timestamp)")
        conn.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('small_talk', 'high')")
        conn.execute("""CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            source TEXT,
            feedback TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'new',
            processed_at TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_ts ON feedback(timestamp)")
        conn.execute("""CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            company TEXT,
            allowed_recipient INTEGER NOT NULL DEFAULT 0
        )""")
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


def get_setting(key: str, default: str = "") -> str:
    try:
        with _get_db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default
    except Exception:
        return default


def set_setting(key: str, value: str):
    try:
        with _get_db() as conn:
            conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    except Exception:
        pass


def record_feedback(feedback: str, source: str | None = None):
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _get_db() as conn:
            conn.execute(
                "INSERT INTO feedback (timestamp, source, feedback) VALUES (?, ?, ?)",
                (ts, source, feedback),
            )
    except Exception:
        pass


def get_feedback() -> list[dict]:
    try:
        with _get_db() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT id, timestamp, source, feedback, status, processed_at FROM feedback ORDER BY id DESC LIMIT 100"
            )]
    except Exception:
        return []


def get_contacts() -> list[dict]:
    try:
        with _get_db() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM contacts ORDER BY name")]
    except Exception:
        return []


def lookup_contact(name: str) -> list[dict]:
    try:
        with _get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM contacts WHERE name LIKE ? COLLATE NOCASE",
                (f"%{name}%",),
            )
            return [dict(r) for r in rows]
    except Exception:
        return []


def is_allowed_recipient(email: str) -> bool:
    try:
        with _get_db() as conn:
            row = conn.execute(
                "SELECT allowed_recipient FROM contacts WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
            return bool(row and row["allowed_recipient"])
    except Exception:
        return False


def record_failed_request(endpoint: str, payload: str, error: str, source: str | None = None):
    """Record a failed API request with its full payload for later retry."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _get_db() as conn:
            conn.execute(
                "INSERT INTO failed_requests (timestamp, endpoint, payload, error, source) VALUES (?, ?, ?, ?, ?)",
                (ts, endpoint, payload, error, source),
            )
            conn.execute("DELETE FROM failed_requests WHERE timestamp < datetime('now', '-30 days')")
    except Exception:
        pass


def mark_reprocessed(request_id: int):
    """Mark a failed request as reprocessed."""
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _get_db() as conn:
            conn.execute(
                "UPDATE failed_requests SET status = 'reprocessed', reprocessed_at = ? WHERE id = ?",
                (ts, request_id),
            )
    except Exception:
        pass


def get_failed_request(request_id: int) -> dict | None:
    """Get a single failed request by ID."""
    try:
        with _get_db() as conn:
            row = conn.execute("SELECT * FROM failed_requests WHERE id = ?", (request_id,)).fetchone()
            return dict(row) if row else None
    except Exception:
        return None


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

            failed = []
            for row in conn.execute(
                "SELECT id, timestamp, endpoint, payload, error, source, status, reprocessed_at "
                "FROM failed_requests ORDER BY id DESC LIMIT 100"
            ):
                failed.append(dict(row))

            return {
                "total": total,
                "by_type": by_type,
                "by_date": by_date,
                "by_agent": by_agent,
                "recent": recent,
                "recent_errors": recent_errors,
                "updates": updates,
                "failed_requests": failed,
                "feedback": get_feedback(),
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


@router.get("/api/dashboard/feedback")
async def list_feedback(request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    return {"feedback": get_feedback()}


@router.post("/api/dashboard/feedback/{feedback_id}/process")
async def mark_feedback_processed(feedback_id: int, request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with _get_db() as conn:
            conn.execute(
                "UPDATE feedback SET status = 'processed', processed_at = ? WHERE id = ?",
                (ts, feedback_id),
            )
        return {"status": "processed"}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/api/dashboard/feedback/{feedback_id}")
async def delete_feedback(feedback_id: int, request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    try:
        with _get_db() as conn:
            conn.execute("DELETE FROM feedback WHERE id = ?", (feedback_id,))
        return {"status": "deleted"}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/dashboard/settings")
async def get_settings(request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    return {"small_talk": get_setting("small_talk", "medium")}


@router.post("/api/dashboard/settings")
async def update_settings(request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    data = await request.json()
    for key, value in data.items():
        set_setting(key, str(value).lower())
    return {"status": "updated"}


@router.get("/api/dashboard/contacts")
async def list_contacts(request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    return {"contacts": get_contacts()}


@router.post("/api/dashboard/contacts")
async def add_contact(request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    data = await request.json()
    try:
        with _get_db() as conn:
            conn.execute(
                "INSERT INTO contacts (name, email, company, allowed_recipient) VALUES (?, ?, ?, ?)",
                (data["name"], data["email"], data.get("company", ""), int(data.get("allowed_recipient", False))),
            )
        return {"status": "created"}
    except Exception as e:
        return {"error": str(e)}


@router.put("/api/dashboard/contacts/{contact_id}")
async def update_contact(contact_id: int, request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    data = await request.json()
    try:
        with _get_db() as conn:
            conn.execute(
                "UPDATE contacts SET name=?, email=?, company=?, allowed_recipient=? WHERE id=?",
                (data["name"], data["email"], data.get("company", ""), int(data.get("allowed_recipient", False)), contact_id),
            )
        return {"status": "updated"}
    except Exception as e:
        return {"error": str(e)}


@router.delete("/api/dashboard/contacts/{contact_id}")
async def delete_contact(contact_id: int, request: Request):
    if not _verify_session(request):
        return Response(status_code=401)
    try:
        with _get_db() as conn:
            conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
        return {"status": "deleted"}
    except Exception as e:
        return {"error": str(e)}


@router.post("/api/dashboard/retry/{request_id}")
async def retry_failed_request(request_id: int, request: Request):
    """Retry a failed request by replaying its original payload."""
    if not _verify_session(request):
        return Response(status_code=401)

    failed = get_failed_request(request_id)
    if not failed:
        return {"error": "Request not found"}

    import json
    import httpx

    endpoint = failed["endpoint"]
    payload = json.loads(failed["payload"])
    api_key = os.getenv("RELAY_API_KEY", "")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"http://localhost:{os.getenv('RELAY_PORT', '8000')}{endpoint}",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            result = resp.json()

        mark_reprocessed(request_id)
        return {"status": "reprocessed", "result": result}
    except Exception as e:
        return {"error": f"Retry failed: {e}"}


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
                    <button onclick="showTab('feedback')" data-tab="feedback" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Feedback</button>
                    <button onclick="showTab('updates')" data-tab="updates" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Updates</button>
                    <button onclick="showTab('contacts')" data-tab="contacts" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Contacts</button>
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
            <div class="space-y-3" id="failed-requests-list"></div>
            <div id="no-errors" class="hidden bg-white border border-gray-200 rounded-xl px-4 py-8 text-center text-gray-400 text-sm">No failed requests</div>
        </div>

        <!-- Feedback Tab -->
        <div id="tab-feedback" class="hidden">
            <div class="space-y-3" id="feedback-list"></div>
            <div id="no-feedback" class="hidden bg-white border border-gray-200 rounded-xl px-4 py-8 text-center text-gray-400 text-sm">No feedback yet</div>
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

        <!-- Contacts Tab -->
        <div id="tab-contacts" class="hidden">
            <div class="bg-white border border-gray-200 rounded-xl p-5 mb-4">
                <h3 class="text-sm font-semibold text-gray-700 mb-3">Sophie Settings</h3>
                <div class="flex items-center gap-3">
                    <label class="text-sm text-gray-600">Small talk</label>
                    <select id="small-talk-level" onchange="updateSmallTalk()" class="bg-gray-50 border border-gray-200 text-gray-700 text-sm rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <option value="off">Off</option>
                        <option value="medium">Medium (occasional)</option>
                        <option value="high">High (demo mode)</option>
                    </select>
                    <span class="text-xs text-gray-400" id="small-talk-desc"></span>
                </div>
            </div>
            <div class="bg-white border border-gray-200 rounded-xl p-5 mb-4">
                <h3 class="text-sm font-semibold text-gray-700 mb-4">Add Contact</h3>
                <form onsubmit="addContact(event)" class="flex flex-wrap gap-3 items-end">
                    <div>
                        <label class="text-xs text-gray-400 block mb-1">Name</label>
                        <input type="text" id="c-name" required class="bg-gray-50 border border-gray-200 text-gray-700 rounded-lg px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div>
                        <label class="text-xs text-gray-400 block mb-1">Email</label>
                        <input type="email" id="c-email" required class="bg-gray-50 border border-gray-200 text-gray-700 rounded-lg px-3 py-1.5 text-sm w-56 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div>
                        <label class="text-xs text-gray-400 block mb-1">Company</label>
                        <input type="text" id="c-company" class="bg-gray-50 border border-gray-200 text-gray-700 rounded-lg px-3 py-1.5 text-sm w-40 focus:outline-none focus:ring-2 focus:ring-blue-500" />
                    </div>
                    <div class="flex items-center gap-2">
                        <input type="checkbox" id="c-allowed" class="rounded" />
                        <label for="c-allowed" class="text-xs text-gray-600">Direct send allowed</label>
                    </div>
                    <button type="submit" class="px-4 py-1.5 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors">Add</button>
                </form>
            </div>
            <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <div class="px-4 py-3 border-b border-gray-100">
                    <span class="text-sm font-semibold text-gray-700">Contact Directory</span>
                    <span class="text-gray-400 text-xs ml-2" id="contacts-count"></span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-gray-400 text-xs uppercase tracking-wide border-b border-gray-100 bg-gray-50">
                                <th class="text-left px-4 py-2.5 font-medium">Name</th>
                                <th class="text-left px-4 py-2.5 font-medium">Email</th>
                                <th class="text-left px-4 py-2.5 font-medium">Company</th>
                                <th class="text-left px-4 py-2.5 font-medium">Direct Send</th>
                                <th class="text-left px-4 py-2.5 font-medium"></th>
                            </tr>
                        </thead>
                        <tbody id="contacts-body" class="divide-y divide-gray-50"></tbody>
                    </table>
                </div>
                <div id="no-contacts" class="hidden px-4 py-8 text-center text-gray-400 text-sm">No contacts yet</div>
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

    // Preserve open/closed state of all <details> across DOM rebuilds
    function saveOpenDetails(container) {
        const open = new Set();
        (container || document).querySelectorAll('details[open]').forEach(d => {
            const key = d.dataset.agent || d.dataset.id || d.querySelector('summary')?.textContent?.trim();
            if (key) open.add(key);
        });
        return open;
    }
    function restoreOpenDetails(container, openSet) {
        (container || document).querySelectorAll('details').forEach(d => {
            const key = d.dataset.agent || d.dataset.id || d.querySelector('summary')?.textContent?.trim();
            if (key && openSet.has(key)) d.open = true;
        });
    }

    const TOOL_CATEGORIES = {
        'Email': ['search_emails', 'get_email', 'get_thread', 'create_draft', 'draft_reply', 'update_draft', 'send_draft', 'send_email', 'schedule_send', 'cancel_scheduled_send', 'archive_email', 'add_attachment'],
        'Gmail': ['gmail_search', 'gmail_get_email', 'gmail_get_thread', 'gmail_create_draft', 'gmail_archive', 'gmail_list_labels'],
        'Calendar': ['list_events', 'create_event', 'update_event', 'cancel_event', 'find_available_slots'],
        'Reminders': ['create_reminder', 'list_reminders', 'complete_reminder'],
        'Notes': ['search_notes', 'get_note', 'create_note', 'list_note_folders'],
        'Voice': ['list_recordings', 'transcribe_recording'],
        'Documents': ['convert_md_to_pdf', 'convert_md_to_docx'],
        'CBS Support': ['cbs_list_tickets', 'cbs_get_ticket'],
        'RCSC Support': ['rcsc_list_tickets', 'rcsc_get_ticket'],
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
        'CBS Support': '#fb923c',
        'RCSC Support': '#a78bfa',
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
        'cbs_list_tickets': 'List CBS tickets',
        'cbs_get_ticket': 'Read CBS ticket',
        'rcsc_list_tickets': 'List RCSC tickets',
        'rcsc_get_ticket': 'Read RCSC ticket',
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
            renderFeedback();
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
        const failedReqs = (s.failed_requests || []).filter(r => r.status === 'failed');
        const errorCount = failedReqs.length;

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
        const openDetails = saveOpenDetails(el);
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
                <details class="mt-3" data-agent="${name}" ${openDetails.has(name) ? 'open' : ''}>
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
        restoreOpenDetails(el, openDetails);
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
        const failed = dashData.stats.failed_requests || [];
        const noErrors = document.getElementById('no-errors');
        const list = document.getElementById('failed-requests-list');
        if (failed.length === 0) {
            noErrors.classList.remove('hidden');
            list.innerHTML = '';
            return;
        }
        noErrors.classList.add('hidden');
        const openDetails = saveOpenDetails(list);
        list.innerHTML = failed.map(r => {
            const time = new Date(r.timestamp).toLocaleString();
            const isReprocessed = r.status === 'reprocessed';
            const statusBadge = isReprocessed
                ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-600">Reprocessed</span>'
                : '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-50 text-red-600">Failed</span>';
            const retryBtn = isReprocessed ? '' :
                `<button onclick="retryRequest(${r.id})" class="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors">Retry</button>`;
            let payloadStr = r.payload || '{}';
            try { payloadStr = JSON.stringify(JSON.parse(payloadStr), null, 2); } catch(e) {}
            const source = r.source ? `<span class="text-gray-400 text-xs ml-2">${r.source}</span>` : '';
            return `<div class="bg-white border border-gray-200 rounded-xl p-4">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                        ${statusBadge}
                        <span class="text-gray-700 font-mono text-sm">${r.endpoint}</span>
                        ${source}
                    </div>
                    <div class="flex items-center gap-3">
                        <span class="text-xs text-gray-400">${time}</span>
                        ${retryBtn}
                    </div>
                </div>
                <div class="text-red-600 text-sm mb-2">${r.error}</div>
                <details data-id="failed-${r.id}">
                    <summary class="text-xs text-gray-400 cursor-pointer hover:text-gray-600">Show payload</summary>
                    <pre class="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs font-mono text-gray-700 overflow-x-auto max-h-48 overflow-y-auto">${payloadStr.replace(/</g,'&lt;')}</pre>
                </details>
                ${isReprocessed ? '<div class="text-xs text-emerald-500 mt-2">Reprocessed at ' + new Date(r.reprocessed_at).toLocaleString() + '</div>' : ''}
            </div>`;
        }).join('');
        restoreOpenDetails(list, openDetails);
    }

    async function retryRequest(id) {
        const btn = event.target;
        btn.disabled = true;
        btn.textContent = 'Retrying...';
        try {
            const resp = await fetch('/api/dashboard/retry/' + id, { method: 'POST' });
            const data = await resp.json();
            if (data.error) {
                alert('Retry failed: ' + data.error);
                btn.textContent = 'Retry';
                btn.disabled = false;
            } else {
                btn.textContent = 'Done';
                btn.classList.replace('bg-blue-600', 'bg-emerald-600');
                btn.classList.replace('hover:bg-blue-700', 'hover:bg-emerald-700');
                fetchData();
            }
        } catch (e) {
            alert('Retry failed: ' + e.message);
            btn.textContent = 'Retry';
            btn.disabled = false;
        }
    }

    // --- Contacts ---
    let contactsData = [];

    async function fetchContacts() {
        try {
            const resp = await fetch('/api/dashboard/contacts');
            if (resp.status === 401) return;
            const data = await resp.json();
            contactsData = data.contacts || [];
            renderContacts();
        } catch(e) {}
    }

    function renderContacts() {
        const tbody = document.getElementById('contacts-body');
        const noContacts = document.getElementById('no-contacts');
        document.getElementById('contacts-count').textContent = contactsData.length + ' contacts';
        if (contactsData.length === 0) {
            noContacts.classList.remove('hidden');
            tbody.innerHTML = '';
            return;
        }
        noContacts.classList.add('hidden');
        tbody.innerHTML = contactsData.map(c => {
            const allowed = c.allowed_recipient
                ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-600">Yes</span>'
                : '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-400">No</span>';
            return `<tr class="hover:bg-gray-50">
                <td class="px-4 py-2.5 text-gray-700 font-medium">${c.name}</td>
                <td class="px-4 py-2.5 text-gray-500 font-mono text-xs">${c.email}</td>
                <td class="px-4 py-2.5 text-gray-400">${c.company || ''}</td>
                <td class="px-4 py-2.5">${allowed}</td>
                <td class="px-4 py-2.5">
                    <div class="flex gap-2">
                        <button onclick="toggleAllowed(${c.id}, ${!c.allowed_recipient})" class="text-xs ${c.allowed_recipient ? 'text-amber-500 hover:text-amber-700' : 'text-blue-500 hover:text-blue-700'}">${c.allowed_recipient ? 'Revoke' : 'Allow'}</button>
                        <button onclick="deleteContact(${c.id})" class="text-xs text-red-400 hover:text-red-600">Delete</button>
                    </div>
                </td>
            </tr>`;
        }).join('');
    }

    async function addContact(e) {
        e.preventDefault();
        const data = {
            name: document.getElementById('c-name').value,
            email: document.getElementById('c-email').value,
            company: document.getElementById('c-company').value,
            allowed_recipient: document.getElementById('c-allowed').checked,
        };
        await fetch('/api/dashboard/contacts', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data) });
        document.getElementById('c-name').value = '';
        document.getElementById('c-email').value = '';
        document.getElementById('c-company').value = '';
        document.getElementById('c-allowed').checked = false;
        fetchContacts();
    }

    async function toggleAllowed(id, allowed) {
        const c = contactsData.find(x => x.id === id);
        if (!c) return;
        await fetch('/api/dashboard/contacts/' + id, {
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({...c, allowed_recipient: allowed}),
        });
        fetchContacts();
    }

    async function deleteContact(id) {
        if (!confirm('Delete this contact?')) return;
        await fetch('/api/dashboard/contacts/' + id, { method: 'DELETE' });
        fetchContacts();
    }

    fetchContacts();

    // --- Feedback ---
    function renderFeedback() {
        if (!dashData) return;
        const items = dashData.stats.feedback || [];
        const list = document.getElementById('feedback-list');
        const noFeedback = document.getElementById('no-feedback');
        if (items.length === 0) {
            noFeedback.classList.remove('hidden');
            list.innerHTML = '';
            return;
        }
        noFeedback.classList.add('hidden');
        list.innerHTML = items.map(f => {
            const time = new Date(f.timestamp).toLocaleString();
            const isProcessed = f.status === 'processed';
            const badge = isProcessed
                ? '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-600">Processed</span>'
                : '<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-50 text-amber-600">New</span>';
            const source = f.source ? `<span class="text-gray-400 text-xs ml-2">${f.source}</span>` : '';
            const actions = isProcessed
                ? `<button onclick="deleteFeedback(${f.id})" class="text-xs text-red-400 hover:text-red-600">Delete</button>`
                : `<button onclick="processFeedback(${f.id})" class="px-3 py-1.5 text-xs font-medium text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg transition-colors">Mark processed</button>
                   <button onclick="deleteFeedback(${f.id})" class="text-xs text-red-400 hover:text-red-600 ml-2">Delete</button>`;
            return `<div class="bg-white border border-gray-200 rounded-xl p-4">
                <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                        ${badge}
                        ${source}
                    </div>
                    <div class="flex items-center gap-3">
                        <span class="text-xs text-gray-400">${time}</span>
                        ${actions}
                    </div>
                </div>
                <p class="text-gray-700 text-sm">${f.feedback}</p>
                ${isProcessed ? '<div class="text-xs text-emerald-500 mt-2">Processed at ' + new Date(f.processed_at).toLocaleString() + '</div>' : ''}
            </div>`;
        }).join('');
    }

    async function processFeedback(id) {
        await fetch('/api/dashboard/feedback/' + id + '/process', { method: 'POST' });
        fetchData();
    }

    async function deleteFeedback(id) {
        if (!confirm('Delete this feedback?')) return;
        await fetch('/api/dashboard/feedback/' + id, { method: 'DELETE' });
        fetchData();
    }

    // --- Settings ---
    const SMALL_TALK_DESCS = {
        off: 'No weather or casual comments',
        medium: 'Occasional touches, roughly one in three calls',
        high: 'Every call — weather, time of day, day of week',
    };

    async function fetchSettings() {
        try {
            const resp = await fetch('/api/dashboard/settings');
            if (resp.status === 401) return;
            const data = await resp.json();
            const level = data.small_talk === true ? 'medium' : (data.small_talk || 'medium');
            document.getElementById('small-talk-level').value = level;
            document.getElementById('small-talk-desc').textContent = SMALL_TALK_DESCS[level] || '';
        } catch(e) {}
    }

    async function updateSmallTalk() {
        const level = document.getElementById('small-talk-level').value;
        document.getElementById('small-talk-desc').textContent = SMALL_TALK_DESCS[level] || '';
        await fetch('/api/dashboard/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({small_talk: level}),
        });
    }

    fetchSettings();

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
