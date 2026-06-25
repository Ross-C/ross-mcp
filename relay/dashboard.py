"""Secure dashboard — login, agent status, command stats, and setup instructions."""

import hashlib
import hmac
import os
import secrets
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
SESSION_SECRET = os.getenv("RELAY_API_KEY", secrets.token_hex(32))

# Active sessions (in-memory, cleared on restart)
active_sessions: set[str] = set()
MAX_SESSIONS = 20

# --- Command Stats (in-memory) ---

command_stats: dict = {
    "total": 0,
    "by_type": defaultdict(int),
    "by_date": defaultdict(lambda: defaultdict(int)),
    "recent": [],
}
MAX_RECENT = 500


def record_command(command_type: str, agent_name: str, status: str, timestamp: datetime | None = None):
    """Record a command execution for stats."""
    ts = timestamp or datetime.now(timezone.utc)
    date_key = ts.strftime("%Y-%m-%d")

    command_stats["total"] += 1
    command_stats["by_type"][command_type] += 1
    command_stats["by_date"][date_key][command_type] += 1

    command_stats["recent"].append({
        "timestamp": ts.isoformat(),
        "type": command_type,
        "agent": agent_name,
        "status": status,
    })
    if len(command_stats["recent"]) > MAX_RECENT:
        command_stats["recent"] = command_stats["recent"][-MAX_RECENT:]


def get_stats_summary() -> dict:
    """Return stats for the dashboard API."""
    return {
        "total": command_stats["total"],
        "by_type": dict(command_stats["by_type"]),
        "by_date": {k: dict(v) for k, v in command_stats["by_date"].items()},
    }


# --- Session Auth ---

def _sign_token(token: str) -> str:
    return hmac.new(SESSION_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()


def _create_session() -> str:
    token = secrets.token_urlsafe(32)
    active_sessions.add(token)
    if len(active_sessions) > MAX_SESSIONS:
        active_sessions.pop()
    return token


def _verify_session(request: Request) -> bool:
    token = request.cookies.get("session")
    return token is not None and token in active_sessions


# --- Routes ---

@router.get("/", response_class=HTMLResponse)
async def dashboard_root(request: Request):
    if not _verify_session(request):
        return HTMLResponse(LOGIN_HTML)
    from relay.relay import agents, command_log
    return HTMLResponse(DASHBOARD_HTML)


@router.post("/login")
async def login(request: Request):
    form = await request.form()
    password = form.get("password", "")

    if not DASHBOARD_PASSWORD:
        return HTMLResponse(LOGIN_HTML.replace("<!-- ERROR -->", '<p class="text-red-400 text-sm mt-2">Dashboard password not configured on server</p>'))

    if not secrets.compare_digest(str(password), DASHBOARD_PASSWORD):
        return HTMLResponse(LOGIN_HTML.replace("<!-- ERROR -->", '<p class="text-red-400 text-sm mt-2">Incorrect password</p>'))

    token = _create_session()
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400 * 7,
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
    from relay.relay import agents
    agent_data = {}
    for name, a in agents.items():
        agent_data[name] = {
            "machine": a.registration.machine_name,
            "capabilities": [c.value for c in a.registration.capabilities],
            "connected_at": a.connected_at.isoformat(),
            "last_seen": a.last_seen.isoformat(),
        }
    return {
        "agents": agent_data,
        "stats": get_stats_summary(),
        "recent": command_stats["recent"][-100:],
    }


# --- HTML Templates ---

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ross MCP</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 min-h-screen flex items-center justify-center">
    <div class="w-full max-w-sm">
        <div class="bg-slate-800 border border-slate-700 rounded-lg p-8">
            <h1 class="text-xl font-semibold text-white mb-1">Ross MCP</h1>
            <p class="text-slate-400 text-sm mb-6">Sign in to the dashboard</p>
            <form method="POST" action="/login">
                <input
                    type="password"
                    name="password"
                    placeholder="Password"
                    autofocus
                    class="w-full bg-slate-900 border border-slate-600 text-white rounded px-3 py-2 text-sm focus:outline-none focus:border-blue-500 placeholder-slate-500"
                />
                <button
                    type="submit"
                    class="w-full mt-3 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded px-3 py-2 transition-colors"
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
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
    <style>
        [x-cloak] { display: none !important; }
        .tab-active { border-bottom: 2px solid #3b82f6; color: #f8fafc; }
        .tab-inactive { border-bottom: 2px solid transparent; color: #94a3b8; }
        .tab-inactive:hover { color: #cbd5e1; }
    </style>
</head>
<body class="bg-slate-900 text-slate-200 min-h-screen">

    <!-- Nav -->
    <nav class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-10">
        <div class="max-w-6xl mx-auto px-4 sm:px-6 flex items-center justify-between h-14">
            <div class="flex items-center gap-6">
                <span class="text-white font-semibold">Ross MCP</span>
                <div class="flex gap-1" id="tabs">
                    <button onclick="showTab('overview')" data-tab="overview" class="tab-active px-3 py-4 text-sm font-medium transition-colors">Overview</button>
                    <button onclick="showTab('agents')" data-tab="agents" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Agents</button>
                    <button onclick="showTab('activity')" data-tab="activity" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Activity</button>
                    <button onclick="showTab('setup')" data-tab="setup" class="tab-inactive px-3 py-4 text-sm font-medium transition-colors">Setup</button>
                </div>
            </div>
            <a href="/logout" class="text-slate-400 hover:text-white text-sm transition-colors">Sign out</a>
        </div>
    </nav>

    <main class="max-w-6xl mx-auto px-4 sm:px-6 py-6">

        <!-- Overview Tab -->
        <div id="tab-overview">
            <!-- Stat Cards -->
            <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
                <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wide">Agents</div>
                    <div class="text-2xl font-semibold text-white mt-1" id="stat-agents">-</div>
                </div>
                <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wide">Total Commands</div>
                    <div class="text-2xl font-semibold text-white mt-1" id="stat-total">-</div>
                </div>
                <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wide">Emails Drafted</div>
                    <div class="text-2xl font-semibold text-white mt-1" id="stat-drafts">-</div>
                </div>
                <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wide">Reminders</div>
                    <div class="text-2xl font-semibold text-white mt-1" id="stat-reminders">-</div>
                </div>
                <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wide">Notes Created</div>
                    <div class="text-2xl font-semibold text-white mt-1" id="stat-notes">-</div>
                </div>
                <div class="bg-slate-800 border border-slate-700 rounded-lg p-4">
                    <div class="text-slate-400 text-xs font-medium uppercase tracking-wide">Transcriptions</div>
                    <div class="text-2xl font-semibold text-white mt-1" id="stat-transcriptions">-</div>
                </div>
            </div>

            <!-- Charts -->
            <div class="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
                <div class="lg:col-span-2 bg-slate-800 border border-slate-700 rounded-lg p-5">
                    <div class="flex items-center justify-between mb-4">
                        <h3 class="text-sm font-medium text-white">Commands by Day</h3>
                        <select id="chart-range" onchange="updateCharts()" class="bg-slate-900 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1">
                            <option value="7">Last 7 days</option>
                            <option value="14" selected>Last 14 days</option>
                            <option value="30">Last 30 days</option>
                        </select>
                    </div>
                    <canvas id="chart-daily" height="180"></canvas>
                </div>
                <div class="bg-slate-800 border border-slate-700 rounded-lg p-5">
                    <h3 class="text-sm font-medium text-white mb-4">By Category</h3>
                    <canvas id="chart-categories" height="220"></canvas>
                </div>
            </div>
        </div>

        <!-- Agents Tab -->
        <div id="tab-agents" class="hidden">
            <div id="agents-list" class="space-y-3">
                <p class="text-slate-500">Loading...</p>
            </div>
        </div>

        <!-- Activity Tab -->
        <div id="tab-activity" class="hidden">
            <div class="bg-slate-800 border border-slate-700 rounded-lg overflow-hidden">
                <div class="px-4 py-3 border-b border-slate-700 flex items-center gap-3">
                    <input
                        type="text"
                        id="activity-filter"
                        placeholder="Filter by command type..."
                        oninput="renderActivity()"
                        class="bg-slate-900 border border-slate-600 text-white rounded px-3 py-1.5 text-sm flex-1 max-w-xs focus:outline-none focus:border-blue-500 placeholder-slate-500"
                    />
                    <span class="text-slate-500 text-xs" id="activity-count"></span>
                </div>
                <div class="overflow-x-auto">
                    <table class="w-full text-sm">
                        <thead>
                            <tr class="text-slate-400 text-xs uppercase tracking-wide border-b border-slate-700">
                                <th class="text-left px-4 py-2 font-medium">Time</th>
                                <th class="text-left px-4 py-2 font-medium">Command</th>
                                <th class="text-left px-4 py-2 font-medium">Agent</th>
                                <th class="text-left px-4 py-2 font-medium">Status</th>
                            </tr>
                        </thead>
                        <tbody id="activity-body"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Setup Tab -->
        <div id="tab-setup" class="hidden">
            <div class="space-y-4 max-w-3xl">
                <div class="bg-slate-800 border border-slate-700 rounded-lg p-5">
                    <h3 class="text-white font-medium mb-3">Claude Desktop / Claude Web</h3>
                    <p class="text-slate-400 text-sm mb-3">Add as a remote MCP server in Claude's settings:</p>
                    <div class="bg-slate-900 rounded p-3 text-sm font-mono">
                        <div class="text-slate-400 mb-1"># Settings</div>
                        <div><span class="text-slate-500">URL:</span> <span class="text-blue-400">https://ross-mcp-relay.fly.dev/mcp/mcp</span></div>
                        <div><span class="text-slate-500">Transport:</span> <span class="text-slate-300">Streamable HTTP</span></div>
                        <div><span class="text-slate-500">Auth:</span> <span class="text-slate-300">Bearer token (your RELAY_API_KEY)</span></div>
                    </div>
                    <p class="text-slate-500 text-xs mt-3">In Claude Desktop: Settings > MCP Servers > Add Server. In Claude Web: same section in the sidebar settings.</p>
                </div>

                <div class="bg-slate-800 border border-slate-700 rounded-lg p-5">
                    <h3 class="text-white font-medium mb-3">Claude Code (CLI)</h3>
                    <p class="text-slate-400 text-sm mb-3">Add to <code class="text-blue-400 bg-slate-900 px-1 rounded">~/.claude/settings.json</code>:</p>
                    <pre class="bg-slate-900 rounded p-3 text-sm font-mono text-slate-300 overflow-x-auto">{
  "mcpServers": {
    "ross-life-admin": {
      "type": "http",
      "url": "https://ross-mcp-relay.fly.dev/mcp/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_API_KEY"
      }
    }
  }
}</pre>
                </div>

                <div class="bg-slate-800 border border-slate-700 rounded-lg p-5">
                    <h3 class="text-white font-medium mb-3">ChatGPT (Custom GPT)</h3>
                    <ol class="text-slate-400 text-sm space-y-2 list-decimal list-inside">
                        <li>Create a Custom GPT at <span class="text-blue-400">chat.openai.com</span></li>
                        <li>Go to <strong class="text-slate-300">Configure</strong> > <strong class="text-slate-300">Actions</strong> > <strong class="text-slate-300">Create new action</strong></li>
                        <li>Click <strong class="text-slate-300">Import from URL</strong> and enter: <code class="text-blue-400 bg-slate-900 px-1 rounded">https://ross-mcp-relay.fly.dev/openapi.json</code></li>
                        <li>Under <strong class="text-slate-300">Authentication</strong>, select <strong class="text-slate-300">API Key</strong>, type <strong class="text-slate-300">Bearer</strong>, and paste your RELAY_API_KEY</li>
                    </ol>
                </div>

                <div class="bg-slate-800 border border-slate-700 rounded-lg p-5">
                    <h3 class="text-white font-medium mb-3">REST API</h3>
                    <pre class="bg-slate-900 rounded p-3 text-sm font-mono text-slate-300 overflow-x-auto">curl -X POST https://ross-mcp-relay.fly.dev/api/command \\
  -H "Authorization: Bearer YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"type": "create_reminder", "payload": {"title": "Buy milk"}}'</pre>
                    <p class="text-slate-500 text-xs mt-3">
                        Swagger UI: <a href="/docs" class="text-blue-400 hover:underline">/docs</a>
                    </p>
                </div>
            </div>
        </div>

    </main>

    <script>
    let dashData = null;
    let dailyChart = null;
    let categoryChart = null;

    const TOOL_CATEGORIES = {
        'Email': ['search_emails', 'get_email', 'get_thread', 'create_draft', 'update_draft', 'send_draft', 'send_email', 'schedule_send', 'cancel_scheduled_send', 'archive_email', 'add_attachment'],
        'Calendar': ['list_events', 'create_event', 'update_event', 'cancel_event', 'find_available_slots'],
        'Reminders': ['create_reminder', 'list_reminders', 'complete_reminder'],
        'Notes': ['search_notes', 'get_note', 'create_note', 'list_note_folders'],
        'Voice': ['list_recordings', 'transcribe_recording'],
        'Documents': ['convert_md_to_pdf', 'convert_md_to_docx'],
        'System': ['update_agent', 'agent_status', 'ping'],
    };

    const CATEGORY_COLOURS = {
        'Email': '#3b82f6',
        'Calendar': '#22c55e',
        'Reminders': '#f59e0b',
        'Notes': '#8b5cf6',
        'Voice': '#ec4899',
        'Documents': '#06b6d4',
        'System': '#64748b',
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
            renderOverview();
            renderAgents();
            renderActivity();
            updateCharts();
        } catch (e) {
            console.error('Failed to fetch data:', e);
        }
    }

    function renderOverview() {
        if (!dashData) return;
        const s = dashData.stats;
        const bt = s.by_type || {};
        document.getElementById('stat-agents').textContent = Object.keys(dashData.agents).length;
        document.getElementById('stat-total').textContent = s.total.toLocaleString();
        document.getElementById('stat-drafts').textContent = (bt.create_draft || 0) + (bt.update_draft || 0);
        document.getElementById('stat-reminders').textContent = bt.create_reminder || 0;
        document.getElementById('stat-notes').textContent = bt.create_note || 0;
        document.getElementById('stat-transcriptions').textContent = bt.transcribe_recording || 0;
    }

    function renderAgents() {
        if (!dashData) return;
        const el = document.getElementById('agents-list');
        const entries = Object.entries(dashData.agents);
        if (entries.length === 0) {
            el.innerHTML = '<div class="bg-slate-800 border border-slate-700 rounded-lg p-5 text-slate-500">No agents connected</div>';
            return;
        }
        el.innerHTML = entries.map(([name, info]) => {
            const connectedAt = new Date(info.connected_at);
            const uptime = Math.round((Date.now() - connectedAt.getTime()) / 60000);
            const uptimeStr = uptime < 60 ? uptime + 'm' : Math.round(uptime / 60) + 'h ' + (uptime % 60) + 'm';
            return `
            <div class="bg-slate-800 border border-slate-700 rounded-lg p-5">
                <div class="flex items-center gap-2 mb-3">
                    <div class="w-2 h-2 rounded-full bg-green-500"></div>
                    <span class="text-white font-medium">${name}</span>
                    <span class="text-slate-500 text-sm">${info.machine}</span>
                </div>
                <div class="text-xs text-slate-400 mb-3">
                    Connected ${connectedAt.toLocaleString()} (uptime: ${uptimeStr})
                </div>
                <div class="flex flex-wrap gap-1.5">
                    ${info.capabilities.map(c =>
                        '<span class="bg-slate-700 text-slate-300 text-xs px-2 py-0.5 rounded">' + c + '</span>'
                    ).join('')}
                </div>
            </div>`;
        }).join('');
    }

    function renderActivity() {
        if (!dashData) return;
        const filter = (document.getElementById('activity-filter').value || '').toLowerCase();
        const items = [...dashData.recent].reverse().filter(r =>
            !filter || r.type.toLowerCase().includes(filter)
        );
        document.getElementById('activity-count').textContent = items.length + ' commands';
        document.getElementById('activity-body').innerHTML = items.map(r => {
            const time = new Date(r.timestamp).toLocaleString();
            const statusClass = r.status === 'success' ? 'text-green-400' : 'text-red-400';
            return `<tr class="border-b border-slate-700/50 hover:bg-slate-700/20">
                <td class="px-4 py-2 text-slate-400 whitespace-nowrap">${time}</td>
                <td class="px-4 py-2 text-slate-200 font-mono">${r.type}</td>
                <td class="px-4 py-2 text-slate-400">${r.agent}</td>
                <td class="px-4 py-2 ${statusClass}">${r.status}</td>
            </tr>`;
        }).join('');
    }

    function updateCharts() {
        if (!dashData) return;
        const days = parseInt(document.getElementById('chart-range').value) || 14;
        const byDate = dashData.stats.by_date || {};

        // Build date labels for the range
        const labels = [];
        const now = new Date();
        for (let i = days - 1; i >= 0; i--) {
            const d = new Date(now);
            d.setDate(d.getDate() - i);
            labels.push(d.toISOString().split('T')[0]);
        }

        // Daily totals
        const dailyTotals = labels.map(date => {
            const dayData = byDate[date] || {};
            return Object.values(dayData).reduce((a, b) => a + b, 0);
        });

        // Daily chart
        if (dailyChart) dailyChart.destroy();
        dailyChart = new Chart(document.getElementById('chart-daily'), {
            type: 'bar',
            data: {
                labels: labels.map(d => {
                    const parts = d.split('-');
                    return parts[2] + '/' + parts[1];
                }),
                datasets: [{
                    data: dailyTotals,
                    backgroundColor: '#3b82f6',
                    borderRadius: 3,
                    maxBarThickness: 32,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        grid: { display: false },
                        ticks: { color: '#64748b', font: { size: 11 } },
                        border: { color: '#334155' },
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: '#1e293b' },
                        ticks: {
                            color: '#64748b',
                            font: { size: 11 },
                            stepSize: 1,
                            callback: v => Number.isInteger(v) ? v : '',
                        },
                        border: { display: false },
                    }
                }
            }
        });

        // Category breakdown
        const catTotals = {};
        const bt = dashData.stats.by_type || {};
        for (const [cat, tools] of Object.entries(TOOL_CATEGORIES)) {
            const total = tools.reduce((sum, t) => sum + (bt[t] || 0), 0);
            if (total > 0) catTotals[cat] = total;
        }

        if (categoryChart) categoryChart.destroy();
        const catLabels = Object.keys(catTotals);
        categoryChart = new Chart(document.getElementById('chart-categories'), {
            type: 'doughnut',
            data: {
                labels: catLabels,
                datasets: [{
                    data: catLabels.map(c => catTotals[c]),
                    backgroundColor: catLabels.map(c => CATEGORY_COLOURS[c] || '#64748b'),
                    borderWidth: 0,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '65%',
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#94a3b8',
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

    // Initial load and auto-refresh
    fetchData();
    setInterval(fetchData, 10000);
    </script>
</body>
</html>"""
