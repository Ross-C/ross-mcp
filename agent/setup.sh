#!/usr/bin/env bash
# Ross MCP Agent — Interactive Setup
# Run: ./agent/setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

echo ""
echo "========================================="
echo "  Ross MCP Agent — Setup"
echo "========================================="
echo ""

# ----- Step 1: Python venv -----

echo "[1/6] Python environment"

if [ -d "$PROJECT_DIR/.venv" ]; then
    echo "  ✓ Virtual environment already exists"
else
    echo "  Creating virtual environment..."
    python3 -m venv "$PROJECT_DIR/.venv"
    echo "  ✓ Created .venv"
fi

echo "  Installing dependencies..."
"$PROJECT_DIR/.venv/bin/pip" install --quiet -r "$PROJECT_DIR/agent/requirements.txt"
echo "  ✓ Dependencies installed"
echo ""

# ----- Step 2: SSL certificates -----

echo "[2/6] SSL certificates"
"$PROJECT_DIR/.venv/bin/python" -c "import ssl; ssl.create_default_context()" 2>/dev/null && {
    echo "  ✓ SSL certificates OK"
} || {
    echo "  ⚠ SSL certificates may need installing."
    echo "  If you get SSL errors later, run:"
    echo "  /Applications/Python 3.*/Install Certificates.command"
}
echo ""

# ----- Step 3: Environment file -----

echo "[3/6] Environment configuration"

if [ -f "$ENV_FILE" ]; then
    echo "  .env file already exists."
    read -rp "  Overwrite it? [y/N] " overwrite
    if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
        echo "  ✓ Keeping existing .env"
        echo ""
        SKIP_ENV=true
    fi
fi

if [ "${SKIP_ENV:-false}" != "true" ]; then
    echo ""
    echo "  You need the RELAY_API_KEY from your existing setup."
    echo "  (This is the same key used on Fly.io and your other Mac.)"
    echo ""
    read -rp "  RELAY_API_KEY: " RELAY_API_KEY

    AGENT_NAME_DEFAULT=$(hostname -s | tr '[:upper:]' '[:lower:]')
    read -rp "  Agent name [$AGENT_NAME_DEFAULT]: " AGENT_NAME
    AGENT_NAME=${AGENT_NAME:-$AGENT_NAME_DEFAULT}

    cat > "$ENV_FILE" <<ENVEOF
# Relay
RELAY_API_KEY=$RELAY_API_KEY
RELAY_HOST=0.0.0.0
RELAY_PORT=8000

# Agent
AGENT_NAME=$AGENT_NAME
RELAY_URL=wss://ross-mcp-relay.fly.dev/ws/agent
AGENT_API_KEY=$RELAY_API_KEY
AGENT_WEB_PORT=8001

# Microsoft Graph (Office 365)
MS_CLIENT_ID=
MS_CLIENT_SECRET=
MS_TENANT_ID=
MS_REDIRECT_PORT=9876

# Deepgram (voice memo transcription)
DEEPGRAM_API_KEY=
ENVEOF

    echo "  ✓ .env created"
fi
echo ""

# ----- Step 4: Outlook setup -----

echo "[4/6] Outlook (Office 365) setup"

source "$ENV_FILE"

if [ -n "${MS_CLIENT_ID:-}" ] && [ -f "$PROJECT_DIR/.outlook_tokens.json" ]; then
    echo "  ✓ Outlook already configured (tokens found)"
    echo ""
elif [ -n "${MS_CLIENT_ID:-}" ]; then
    echo "  Azure app registered but no tokens found."
    echo "  Running OAuth login — a browser will open."
    read -rp "  Press Enter to continue..."
    "$PROJECT_DIR/.venv/bin/python" -c "
import asyncio
from dotenv import load_dotenv
load_dotenv('$ENV_FILE')
from agent.services.outlook_auth import OutlookAuth
auth = OutlookAuth()
result = asyncio.run(auth.authorize())
print('  ✓ Outlook login successful' if auth.is_authenticated else '  ✗ Outlook login failed')
"
    echo ""
else
    echo "  No Azure app credentials found."
    echo ""
    echo "  Option A: Register a new Azure app (requires Azure CLI)"
    echo "  Option B: Enter existing credentials from your other Mac"
    echo ""
    read -rp "  Choose [A/B]: " az_choice

    if [[ "$az_choice" =~ ^[Aa]$ ]]; then
        if ! command -v az &>/dev/null; then
            echo "  Azure CLI not installed. Installing via Homebrew..."
            brew install azure-cli
        fi
        if ! az account show &>/dev/null 2>&1; then
            echo "  Opening browser for Azure login..."
            az login
        fi
        "$SCRIPT_DIR/setup_azure.sh"
        source "$ENV_FILE"
    else
        echo ""
        echo "  Copy these from your other Mac's .env file:"
        echo ""
        read -rp "  MS_CLIENT_ID: " MS_CLIENT_ID
        read -rp "  MS_CLIENT_SECRET: " MS_CLIENT_SECRET
        read -rp "  MS_TENANT_ID: " MS_TENANT_ID

        # Update .env with Outlook credentials
        if grep -q "^MS_CLIENT_ID=" "$ENV_FILE"; then
            sed -i '' "s|^MS_CLIENT_ID=.*|MS_CLIENT_ID=$MS_CLIENT_ID|" "$ENV_FILE"
            sed -i '' "s|^MS_CLIENT_SECRET=.*|MS_CLIENT_SECRET=$MS_CLIENT_SECRET|" "$ENV_FILE"
            sed -i '' "s|^MS_TENANT_ID=.*|MS_TENANT_ID=$MS_TENANT_ID|" "$ENV_FILE"
        else
            echo "MS_CLIENT_ID=$MS_CLIENT_ID" >> "$ENV_FILE"
            echo "MS_CLIENT_SECRET=$MS_CLIENT_SECRET" >> "$ENV_FILE"
            echo "MS_TENANT_ID=$MS_TENANT_ID" >> "$ENV_FILE"
        fi
        echo "  ✓ Credentials saved"
    fi

    echo ""
    echo "  Running OAuth login — a browser will open."
    echo "  Sign in with r.calvert@rcsc.uk"
    read -rp "  Press Enter to continue..."

    source "$ENV_FILE"
    "$PROJECT_DIR/.venv/bin/python" -c "
import asyncio
from dotenv import load_dotenv
load_dotenv('$ENV_FILE')
from agent.services.outlook_auth import OutlookAuth
auth = OutlookAuth()
result = asyncio.run(auth.authorize())
print('  ✓ Outlook login successful' if auth.is_authenticated else '  ✗ Outlook login failed')
"
    echo ""
fi

# ----- Step 5: Test the agent -----

echo "[5/6] Testing agent connection"
echo "  Starting agent for 10 seconds to verify..."

"$PROJECT_DIR/.venv/bin/python" -c "
import asyncio, sys, os
sys.path.insert(0, '$PROJECT_DIR')
from dotenv import load_dotenv
load_dotenv('$ENV_FILE')
from agent.services.outlook_auth import OutlookAuth
from agent.services.reminders import RemindersService

r = RemindersService()
if r.authorize():
    print('  ✓ Apple Reminders access granted')
else:
    print('  ✗ Reminders access denied — check System Settings > Privacy > Reminders')

auth = OutlookAuth()
if auth.is_authenticated:
    async def check():
        try:
            await auth._refresh_access_token()
            print('  ✓ Outlook tokens valid')
        except:
            print('  ✗ Outlook tokens expired — re-run setup')
    asyncio.run(check())
else:
    print('  ⚠ Outlook not configured')
"
echo ""

# ----- Step 6: Auto-start -----

echo "[6/6] Auto-start service"
echo ""
read -rp "  Install launchd service to start agent on boot? [Y/n] " install_service
if [[ ! "$install_service" =~ ^[Nn]$ ]]; then
    "$SCRIPT_DIR/install.sh"
    echo "  ✓ Service installed"
else
    echo "  Skipped. Run manually with: .venv/bin/python -m agent.agent"
fi

echo ""
echo "========================================="
echo "  Setup complete!"
echo "========================================="
echo ""
echo "  Agent name:    ${AGENT_NAME:-$(hostname -s)}"
echo "  Web UI:        http://127.0.0.1:8001"
echo "  Relay:         ross-mcp-relay.fly.dev"
echo ""
echo "  To start manually:  source .venv/bin/activate && python -m agent.agent"
echo "  To view logs:       tail -f ~/Library/Logs/mcp-agent/mcp-agent.log"
echo ""
