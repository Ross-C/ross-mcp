#!/bin/bash
# Deploy ross-mcp — pushes code, deploys relay, updates agents.
# Run from any machine with the repo, fly CLI, and git remote.

set -e

cd "$(dirname "$0")"

RELAY_URL="${MCP_RELAY_URL:-https://ross-mcp-relay.fly.dev}"
API_KEY="${RELAY_API_KEY:-$(grep RELAY_API_KEY .env 2>/dev/null | cut -d= -f2)}"

echo "=== Ross MCP Deploy ==="

# 1. Push to git
echo ""
echo "--- Git Push ---"
if git diff --quiet && git diff --cached --quiet; then
    echo "No local changes, pushing any unpushed commits..."
else
    echo "You have uncommitted changes. Commit first, then run deploy."
    exit 1
fi
git push 2>&1 || echo "Push failed or nothing to push"

# 2. Deploy relay to Fly.io
echo ""
echo "--- Deploy Relay ---"
if command -v fly &>/dev/null; then
    fly deploy --app ross-mcp-relay
else
    echo "fly CLI not found — skipping relay deploy."
    echo "Install: curl -L https://fly.io/install.sh | sh"
fi

# 3. Update connected agents
echo ""
echo "--- Update Agents ---"
if [ -n "$API_KEY" ]; then
    RESPONSE=$(curl -s -X POST "$RELAY_URL/api/command" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" \
        -d '{"type": "update_agent", "payload": {}}')
    echo "Agent update response: $RESPONSE"
else
    echo "No API key found — skipping agent update."
fi

echo ""
echo "=== Deploy Complete ==="
echo "Agents will restart automatically after pulling updates."
