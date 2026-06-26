#!/bin/bash
# Health check script for ross-mcp agent
# Checks if the local agent is connected to the relay and restarts if not.
# Run via launchd every 5 minutes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="$HOME/Library/Logs/mcp-agent/healthcheck.log"
AGENT_NAME="${AGENT_NAME:-$(hostname -s | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g')}"
LAUNCHD_LABEL="com.ross.mcp-agent"

# Load env for API key
if [ -f "$SCRIPT_DIR/.env" ]; then
    export $(grep -v '^#' "$SCRIPT_DIR/.env" | grep RELAY_API_KEY | xargs)
fi

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "$LOG_FILE"
}

# Check if agent process is running at all
if ! launchctl list "$LAUNCHD_LABEL" &>/dev/null; then
    log "WARN: Agent launchd service not loaded. Loading..."
    launchctl load "$HOME/Library/LaunchAgents/$LAUNCHD_LABEL.plist" 2>/dev/null || true
    exit 0
fi

# Check if agent is connected to relay
if [ -z "${RELAY_API_KEY:-}" ]; then
    log "ERROR: RELAY_API_KEY not set, cannot check relay status"
    exit 1
fi

STATUS=$(curl -s -m 10 -H "Authorization: Bearer $RELAY_API_KEY" \
    "https://ross-mcp-relay.fly.dev/api/status" 2>/dev/null || echo '{"agents":{}}')

# Check if our agent name appears in the connected agents
if echo "$STATUS" | python3 -c "import sys,json; agents=json.load(sys.stdin).get('agents',{}); sys.exit(0 if any(k for k in agents) else 1)" 2>/dev/null; then
    # At least one agent is connected, check if ours is
    if echo "$STATUS" | python3 -c "import sys,json; agents=json.load(sys.stdin).get('agents',{}); sys.exit(0 if '$AGENT_NAME' in agents or any(1 for k in agents if '$AGENT_NAME' in k.lower()) else 1)" 2>/dev/null; then
        exit 0  # Our agent is connected, all good
    fi
fi

# Agent not connected to relay, restart it
log "WARN: Agent not found in relay. Restarting $LAUNCHD_LABEL..."
launchctl kickstart -k "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null || {
    launchctl stop "$LAUNCHD_LABEL" 2>/dev/null
    sleep 2
    launchctl start "$LAUNCHD_LABEL" 2>/dev/null
}
log "INFO: Agent restart triggered"
