#!/bin/bash
# Install the MCP agent as a launchd service (auto-start on boot)

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
PLIST_SRC="$PROJECT_DIR/agent/com.ross.mcp-agent.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.ross.mcp-agent.plist"
LOG_DIR="$HOME/Library/Logs/mcp-agent"

echo "Installing MCP Agent service..."
echo "  Project: $PROJECT_DIR"
echo "  Python:  $VENV_PYTHON"

# Check venv exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Python venv not found at $VENV_PYTHON"
    echo "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r agent/requirements.txt"
    exit 1
fi

# Check .env exists
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "Error: .env file not found. Copy .env.example to .env and configure it."
    exit 1
fi

# Create log directory
mkdir -p "$LOG_DIR"

# Unload existing service if present
if [ -f "$PLIST_DST" ]; then
    echo "  Unloading existing service..."
    launchctl unload "$PLIST_DST" 2>/dev/null || true
fi

# Generate plist with actual paths
sed -e "s|VENV_PYTHON_PATH|$VENV_PYTHON|g" \
    -e "s|PROJECT_PATH|$PROJECT_DIR|g" \
    -e "s|LOG_PATH|$LOG_DIR|g" \
    "$PLIST_SRC" > "$PLIST_DST"

# Load the service
launchctl load "$PLIST_DST"

echo ""
echo "Agent service installed and started."
echo "  Logs: $LOG_DIR/mcp-agent.log"
echo "  Errors: $LOG_DIR/mcp-agent.err"
echo ""
echo "Commands:"
echo "  Stop:    launchctl unload ~/Library/LaunchAgents/com.ross.mcp-agent.plist"
echo "  Start:   launchctl load ~/Library/LaunchAgents/com.ross.mcp-agent.plist"
echo "  Restart: launchctl unload ~/Library/LaunchAgents/com.ross.mcp-agent.plist && launchctl load ~/Library/LaunchAgents/com.ross.mcp-agent.plist"
echo "  Logs:    tail -f $LOG_DIR/mcp-agent.log"
