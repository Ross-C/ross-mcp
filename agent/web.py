"""Simple local web UI for the agent — status and manual testing."""

import asyncio
import json
import os
import sys

from aiohttp import web

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.services.reminders import RemindersService

reminders_service: RemindersService | None = None


def set_reminders_service(svc: RemindersService):
    global reminders_service
    reminders_service = svc


async def index(request):
    return web.Response(text=AGENT_HTML, content_type="text/html")


async def api_list_reminders(request):
    if not reminders_service:
        return web.json_response({"error": "Service not ready"}, status=503)
    list_name = request.query.get("list")
    include_completed = request.query.get("completed", "false").lower() == "true"
    result = reminders_service.list_reminders(list_name=list_name, include_completed=include_completed)
    return web.json_response(result)


async def api_create_reminder(request):
    if not reminders_service:
        return web.json_response({"error": "Service not ready"}, status=503)
    data = await request.json()
    result = reminders_service.create_reminder(
        title=data["title"],
        notes=data.get("notes"),
        due_date=None,
        list_name=data.get("list_name"),
        priority=data.get("priority", 0),
    )
    return web.json_response(result)


async def api_complete_reminder(request):
    if not reminders_service:
        return web.json_response({"error": "Service not ready"}, status=503)
    data = await request.json()
    result = reminders_service.complete_reminder(data["reminder_id"])
    return web.json_response(result)


async def api_lists(request):
    if not reminders_service:
        return web.json_response({"error": "Service not ready"}, status=503)
    return web.json_response(reminders_service.get_calendars())


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/reminders", api_list_reminders)
    app.router.add_post("/api/reminders", api_create_reminder)
    app.router.add_post("/api/reminders/complete", api_complete_reminder)
    app.router.add_get("/api/lists", api_lists)
    return app


AGENT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ross MCP Agent</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0a0a0a; color: #e0e0e0; padding: 2rem; max-width: 800px; margin: 0 auto; }
        h1 { color: #fff; margin-bottom: 0.5rem; }
        .subtitle { color: #888; margin-bottom: 2rem; }
        .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px;
                padding: 1.5rem; margin-bottom: 1rem; }
        .card h2 { color: #81c784; margin-bottom: 1rem; font-size: 1.1rem; }
        input, select { background: #1a1a1a; border: 1px solid #333; color: #fff;
                        padding: 0.5rem 1rem; border-radius: 4px; width: 100%; margin-bottom: 0.5rem; }
        button { background: #81c784; color: #000; border: none; padding: 0.5rem 1.5rem;
                 border-radius: 4px; cursor: pointer; font-weight: 600; margin-right: 0.5rem; margin-bottom: 0.5rem; }
        button:hover { background: #66bb6a; }
        button.secondary { background: #333; color: #e0e0e0; }
        button.secondary:hover { background: #444; }
        .reminder { padding: 0.75rem 0; border-bottom: 1px solid #222; display: flex;
                    justify-content: space-between; align-items: center; }
        .reminder:last-child { border-bottom: none; }
        .reminder-title { font-weight: 500; }
        .reminder-meta { color: #888; font-size: 0.85rem; }
        .complete-btn { background: #333; color: #4fc3f7; border: 1px solid #4fc3f7;
                        padding: 0.25rem 0.75rem; font-size: 0.8rem; }
        .msg { padding: 0.75rem; border-radius: 4px; margin-bottom: 1rem; display: none; }
        .msg.success { background: #1b5e20; color: #81c784; display: block; }
        .msg.error { background: #b71c1c33; color: #e57373; display: block; }
    </style>
</head>
<body>
    <h1>Ross MCP Agent</h1>
    <p class="subtitle">Local agent — Apple Reminders</p>

    <div id="message" class="msg"></div>

    <div class="card">
        <h2>Create Reminder</h2>
        <input type="text" id="title" placeholder="Reminder title..." />
        <input type="text" id="notes" placeholder="Notes (optional)" />
        <select id="list"></select>
        <button onclick="createReminder()">Create</button>
    </div>

    <div class="card">
        <h2>Reminders</h2>
        <button onclick="loadReminders()" class="secondary">Refresh</button>
        <div id="reminders" style="margin-top: 1rem;"></div>
    </div>

    <script>
        async function loadLists() {
            const resp = await fetch('/api/lists');
            const lists = await resp.json();
            const sel = document.getElementById('list');
            sel.innerHTML = lists.map(l => `<option value="${l.title}">${l.title}</option>`).join('');
        }

        async function loadReminders() {
            const resp = await fetch('/api/reminders');
            const reminders = await resp.json();
            const el = document.getElementById('reminders');
            if (reminders.length === 0) {
                el.innerHTML = '<p style="color: #666;">No reminders</p>';
                return;
            }
            el.innerHTML = reminders.map(r => `
                <div class="reminder">
                    <div>
                        <div class="reminder-title">${r.title}</div>
                        <div class="reminder-meta">${r.list || ''} ${r.due_date ? '&middot; Due: ' + r.due_date : ''}</div>
                    </div>
                    <button class="complete-btn" onclick="completeReminder('${r.id}')">Complete</button>
                </div>
            `).join('');
        }

        async function createReminder() {
            const title = document.getElementById('title').value;
            if (!title) return;
            const resp = await fetch('/api/reminders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title,
                    notes: document.getElementById('notes').value || null,
                    list_name: document.getElementById('list').value,
                }),
            });
            const result = await resp.json();
            const msg = document.getElementById('message');
            if (result.error) {
                msg.className = 'msg error';
                msg.textContent = result.error;
            } else {
                msg.className = 'msg success';
                msg.textContent = `Created: ${result.title}`;
                document.getElementById('title').value = '';
                document.getElementById('notes').value = '';
                loadReminders();
            }
        }

        async function completeReminder(id) {
            const resp = await fetch('/api/reminders/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reminder_id: id }),
            });
            const result = await resp.json();
            const msg = document.getElementById('message');
            if (result.error) {
                msg.className = 'msg error';
                msg.textContent = result.error;
            } else {
                msg.className = 'msg success';
                msg.textContent = `Completed: ${result.title}`;
                loadReminders();
            }
        }

        loadLists();
        loadReminders();
    </script>
</body>
</html>
"""
