#!/usr/bin/env python3
"""Smoke test suite for Ross MCP — tests all capabilities across agents and relay.

Run after deploy or on a schedule:
    python3 tests/smoke_test.py
    ./deploy.sh && python3 tests/smoke_test.py
"""

import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

RELAY_URL = "https://ross-mcp-relay.fly.dev"
RELAY_KEY = os.getenv("RELAY_API_KEY", "")
MP_PORTAL_URL = os.getenv("MP_PORTAL_API_URL", "")
MP_PORTAL_TOKEN = os.getenv("MP_PORTAL_API_TOKEN", "")
ELEVENLABS_KEY = os.getenv("ELEVENLABS_API_KEY", "")
AGENT_ID = "agent_1601kvz6xrrje8avnvdcchnsnwcf"

# Test results
passed = []
failed = []
skipped = []


def relay_headers():
    return {"Authorization": f"Bearer {RELAY_KEY}", "Content-Type": "application/json"}


def test(name, fn):
    """Run a test and record pass/fail."""
    try:
        result = fn()
        if result:
            passed.append(name)
            print(f"  \033[32mPASS\033[0m  {name}")
        else:
            failed.append(name)
            print(f"  \033[31mFAIL\033[0m  {name}")
    except Exception as e:
        failed.append(name)
        print(f"  \033[31mFAIL\033[0m  {name}: {e}")


def call_tool(tool: str, payload: dict = {}, timeout: int = 60) -> dict:
    """Call a relay tool endpoint and return the parsed response."""
    resp = httpx.post(
        f"{RELAY_URL}/api/tools/{tool}",
        headers=relay_headers(),
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


# ==========================================
# 1. AGENT CONNECTIVITY
# ==========================================

def test_agents():
    print("\n--- Agent Connectivity ---")

    def agents_connected():
        resp = httpx.get(f"{RELAY_URL}/api/status", headers=relay_headers(), timeout=10)
        resp.raise_for_status()
        data = resp.json()
        agents = data.get("agents", {})
        return len(agents) >= 1

    def mac_mini_connected():
        resp = httpx.get(f"{RELAY_URL}/api/status", headers=relay_headers(), timeout=10)
        data = resp.json()
        return "mac-mini" in data.get("agents", {})

    def macbook_connected():
        resp = httpx.get(f"{RELAY_URL}/api/status", headers=relay_headers(), timeout=10)
        data = resp.json()
        return "macbook-pro" in data.get("agents", {})

    def agents_same_version():
        resp = httpx.get(f"{RELAY_URL}/api/status", headers=relay_headers(), timeout=10)
        data = resp.json()
        agents = data.get("agents", {})
        if len(agents) < 2:
            return True  # Can't compare if only one
        versions = [a.get("version") for a in agents.values()]
        return len(set(versions)) == 1

    def mac_mini_has_mp_portal():
        resp = httpx.get(f"{RELAY_URL}/api/status", headers=relay_headers(), timeout=10)
        data = resp.json()
        agent = data.get("agents", {}).get("mac-mini", {})
        caps = agent.get("capabilities", [])
        return "mp_create_task" in caps

    def ping_works():
        result = call_tool("mp-list-projects")  # Any tool will do — proves routing works
        return "error" not in result or result.get("error") is None

    test("At least one agent connected", agents_connected)
    test("Mac Mini connected", mac_mini_connected)
    test("MacBook Pro connected", macbook_connected)
    test("Agents on same version", agents_same_version)
    test("Mac Mini has MP Portal capabilities", mac_mini_has_mp_portal)
    test("Relay routes commands successfully", ping_works)


# ==========================================
# 2. OUTLOOK EMAIL & CALENDAR
# ==========================================

def test_outlook():
    print("\n--- Outlook Email & Calendar ---")

    def search_emails():
        result = call_tool("search-emails", {"query": "", "folder": "inbox", "top": 1})
        return "error" not in result or result.get("status") == "success"

    def list_events():
        result = call_tool("list-events", {"top": 1})
        return "error" not in result or result.get("status") == "success"

    def find_slots():
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        tomorrow = time.strftime("%Y-%m-%dT23:59:59")
        result = call_tool("find-available-slots", {"start": now, "end": tomorrow, "duration_minutes": 30})
        return "error" not in result or result.get("status") == "success"

    test("Search emails", search_emails)
    test("List calendar events", list_events)
    test("Find available slots", find_slots)


# ==========================================
# 3. APPLE REMINDERS
# ==========================================

def test_reminders():
    print("\n--- Apple Reminders ---")

    def list_reminders():
        result = call_tool("list-reminders", {})
        return "error" not in result or result.get("status") == "success"

    test("List reminders", list_reminders)


# ==========================================
# 4. APPLE NOTES
# ==========================================

def test_notes():
    print("\n--- Apple Notes ---")

    def list_folders():
        result = call_tool("list-note-folders", {})
        return "error" not in result or result.get("status") == "success"

    def search_notes():
        result = call_tool("search-notes", {"query": "test", "top": 1})
        return "error" not in result or result.get("status") == "success"

    test("List note folders", list_folders)
    test("Search notes", search_notes)


# ==========================================
# 5. ENCHANT SUPPORT TICKETS
# ==========================================

def test_enchant():
    print("\n--- Enchant Support Tickets ---")

    def cbs_list():
        result = call_tool("cbs-list-tickets", {"state": "open", "per_page": 1})
        return "error" not in result or result.get("status") == "success"

    def rcsc_list():
        result = call_tool("rcsc-list-tickets", {"state": "open", "per_page": 1})
        return "error" not in result or result.get("status") == "success"

    test("CBS list tickets", cbs_list)
    test("RCSC list tickets", rcsc_list)


# ==========================================
# 6. MP PORTAL
# ==========================================

def test_mp_portal():
    print("\n--- MP Portal ---")

    def portal_api_direct():
        """Test the portal API directly (not through relay)."""
        if not MP_PORTAL_TOKEN:
            return False
        resp = httpx.get(
            f"{MP_PORTAL_URL}/api/portal/v1/projects",
            headers={"Authorization": f"Bearer {MP_PORTAL_TOKEN}", "Accept": "application/json"},
            timeout=15,
        )
        return resp.status_code == 200

    def list_projects():
        result = call_tool("mp-list-projects", {})
        projects = result.get("projects", result.get("data", []))
        return isinstance(projects, list) and len(projects) > 0

    def match_project():
        result = call_tool("mp-match-project", {"alias": "ACHL"})
        return result.get("confidence") == "high" and result.get("project_name") == "ACHL Portal"

    def match_vss():
        result = call_tool("mp-match-project", {"alias": "VSS"})
        return result.get("confidence") == "high" and "VSS" in result.get("project_name", "")

    def in_progress_tasks():
        result = call_tool("mp-in-progress-tasks", {})
        return "error" not in result

    def my_tasks():
        result = call_tool("mp-my-tasks", {})
        return "error" not in result

    def overdue_tasks():
        result = call_tool("mp-overdue-tasks", {})
        return "error" not in result

    def recent_tasks():
        result = call_tool("mp-recent-tasks", {})
        return "error" not in result

    def search_tasks():
        result = call_tool("mp-search-tasks", {"query": "test"})
        return "error" not in result

    test("Portal API responds directly", portal_api_direct)
    test("List projects via relay", list_projects)
    test("Fuzzy match 'ACHL' → ACHL Portal", match_project)
    test("Fuzzy match 'VSS' → VSS Portal", match_vss)
    test("In-progress tasks", in_progress_tasks)
    test("My tasks", my_tasks)
    test("Overdue tasks", overdue_tasks)
    test("Recent tasks", recent_tasks)
    test("Search tasks", search_tasks)


# ==========================================
# 7. ELEVENLABS VOICE AGENT
# ==========================================

def test_elevenlabs():
    print("\n--- ElevenLabs Voice Agent ---")

    if not ELEVENLABS_KEY:
        print("  SKIP  No ELEVENLABS_API_KEY set")
        skipped.append("ElevenLabs tools check")
        return

    def tools_registered():
        resp = httpx.get(
            f"https://api.elevenlabs.io/v1/convai/agents/{AGENT_ID}",
            headers={"xi-api-key": ELEVENLABS_KEY},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        tool_ids = data["conversation_config"]["agent"]["prompt"]["tool_ids"]
        return len(tool_ids) >= 30  # We have 35 expected

    def mp_tools_present():
        resp = httpx.get(
            f"https://api.elevenlabs.io/v1/convai/agents/{AGENT_ID}",
            headers={"xi-api-key": ELEVENLABS_KEY},
            timeout=15,
        )
        data = resp.json()
        tool_ids = data["conversation_config"]["agent"]["prompt"]["tool_ids"]
        # Check each MP tool exists by fetching its config
        mp_count = 0
        for tid in tool_ids:
            try:
                tresp = httpx.get(
                    f"https://api.elevenlabs.io/v1/convai/tools/{tid}",
                    headers={"xi-api-key": ELEVENLABS_KEY},
                    timeout=10,
                )
                tdata = tresp.json()
                name = tdata.get("tool_config", {}).get("name", "")
                if name.startswith("mp-"):
                    mp_count += 1
            except Exception:
                pass
        return mp_count >= 10  # We have 12 MP tools

    test("ElevenLabs agent has 30+ tools", tools_registered)
    test("MP Portal tools registered on voice agent", mp_tools_present)


# ==========================================
# MAIN
# ==========================================

def main():
    print("=" * 50)
    print("Ross MCP Smoke Test Suite")
    print("=" * 50)

    if not RELAY_KEY:
        print("\nERROR: RELAY_API_KEY not set. Cannot run tests.")
        sys.exit(1)

    start = time.time()

    test_agents()
    test_outlook()
    test_reminders()
    test_notes()
    test_enchant()
    test_mp_portal()
    test_elevenlabs()

    elapsed = time.time() - start

    print("\n" + "=" * 50)
    print(f"Results: {len(passed)} passed, {len(failed)} failed, {len(skipped)} skipped ({elapsed:.1f}s)")
    print("=" * 50)

    if failed:
        print(f"\nFailed tests:")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("\nAll tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
