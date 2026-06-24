"""MCP server for Ross's life admin — connects Claude to the relay API."""

import json
import os
import sys

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

RELAY_URL = os.getenv("MCP_RELAY_URL", "https://ross-mcp-relay.fly.dev")
API_KEY = os.getenv("RELAY_API_KEY", "")

mcp = FastMCP(
    "Ross Life Admin",
    description="Manage Apple Reminders, Calendar, and Email via local Mac agents",
)


async def _send_command(command_type: str, payload: dict = {}) -> dict:
    """Send a command to the relay and return the response."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{RELAY_URL}/api/command",
            json={"type": command_type, "payload": payload},
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        resp.raise_for_status()
        return resp.json()


@mcp.tool()
async def create_reminder(
    title: str,
    notes: str | None = None,
    due_date: str | None = None,
    list_name: str | None = None,
    priority: int = 0,
) -> str:
    """Create an Apple Reminder.

    Args:
        title: The reminder title
        notes: Optional notes/description
        due_date: Optional due date in ISO format (e.g. 2026-06-25T09:00:00)
        list_name: Optional reminder list name (defaults to 'Reminders')
        priority: Priority level: 0=none, 1=low, 5=medium, 9=high
    """
    payload = {"title": title}
    if notes:
        payload["notes"] = notes
    if due_date:
        payload["due_date"] = due_date
    if list_name:
        payload["list_name"] = list_name
    if priority:
        payload["priority"] = priority

    result = await _send_command("create_reminder", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_reminders(
    list_name: str | None = None,
    include_completed: bool = False,
) -> str:
    """List Apple Reminders.

    Args:
        list_name: Optional filter by reminder list name
        include_completed: Whether to include completed reminders
    """
    payload = {}
    if list_name:
        payload["list_name"] = list_name
    if include_completed:
        payload["include_completed"] = True

    result = await _send_command("list_reminders", payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def complete_reminder(reminder_id: str) -> str:
    """Mark an Apple Reminder as completed.

    Args:
        reminder_id: The ID of the reminder to complete (from list_reminders)
    """
    result = await _send_command("complete_reminder", {"reminder_id": reminder_id})
    return json.dumps(result, indent=2)


if __name__ == "__main__":
    mcp.run()
