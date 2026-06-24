#!/usr/bin/env bash
# Automated Azure AD app registration for Ross MCP.
# Run once: ./setup_azure.sh
# Prerequisites: brew install azure-cli && az login

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"
APP_NAME="ross-mcp-outlook"
REDIRECT_PORT=9876
REDIRECT_URI="http://localhost:${REDIRECT_PORT}/callback"

# Microsoft Graph delegated permissions (IDs from Microsoft docs)
MAIL_READ_WRITE="024d486e-b451-40bb-833d-3e66d98c5c73"
MAIL_SEND="e383f46e-2787-4529-855e-0e479a3ffac0"
CALENDARS_READ_WRITE="1ec239c2-d7c9-4623-a91a-a9775856bb36"
OFFLINE_ACCESS="7427e0e9-2fba-42fe-b0c0-848c9e6a8182"
USER_READ="e1fe6dd8-ba31-4d61-89e7-88639da4683d"

echo "=== Ross MCP — Azure AD App Setup ==="
echo ""

# Check Azure CLI
if ! command -v az &>/dev/null; then
    echo "ERROR: Azure CLI not installed. Run: brew install azure-cli"
    exit 1
fi

# Check login
if ! az account show &>/dev/null 2>&1; then
    echo "Not logged in. Opening browser for Azure login..."
    az login
fi

ACCOUNT=$(az account show --query user.name -o tsv)
echo "Logged in as: $ACCOUNT"
echo ""

# Check if app already exists
EXISTING=$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv 2>/dev/null || true)
if [[ -n "$EXISTING" ]]; then
    echo "App '$APP_NAME' already exists (Client ID: $EXISTING)"
    read -rp "Delete and recreate? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        OBJECT_ID=$(az ad app list --display-name "$APP_NAME" --query "[0].id" -o tsv)
        az ad app delete --id "$OBJECT_ID"
        echo "Deleted existing app."
    else
        echo "Keeping existing app. Exiting."
        exit 0
    fi
fi

echo "Creating Azure AD app: $APP_NAME"

# Create the app with redirect URI
APP_ID=$(az ad app create \
    --display-name "$APP_NAME" \
    --sign-in-audience "AzureADandPersonalMicrosoftAccount" \
    --web-redirect-uris "$REDIRECT_URI" \
    --query appId -o tsv)

echo "App created — Client ID: $APP_ID"

# Add required Microsoft Graph delegated permissions
echo "Adding Microsoft Graph permissions..."
az ad app permission add \
    --id "$APP_ID" \
    --api 00000003-0000-0000-c000-000000000000 \
    --api-permissions \
        "${MAIL_READ_WRITE}=Scope" \
        "${MAIL_SEND}=Scope" \
        "${CALENDARS_READ_WRITE}=Scope" \
        "${OFFLINE_ACCESS}=Scope" \
        "${USER_READ}=Scope"

# Create a client secret (2-year expiry)
echo "Creating client secret..."
SECRET=$(az ad app credential reset \
    --id "$APP_ID" \
    --display-name "ross-mcp-agent" \
    --years 2 \
    --query password -o tsv)

# Get tenant ID
TENANT_ID=$(az account show --query tenantId -o tsv)

echo ""
echo "=== Setup Complete ==="
echo "Client ID:     $APP_ID"
echo "Tenant ID:     $TENANT_ID"
echo "Redirect URI:  $REDIRECT_URI"
echo "Secret:        (saved to .env)"
echo ""

# Append to .env
{
    echo ""
    echo "# Microsoft Graph (Office 365)"
    echo "MS_CLIENT_ID=$APP_ID"
    echo "MS_CLIENT_SECRET=$SECRET"
    echo "MS_TENANT_ID=$TENANT_ID"
    echo "MS_REDIRECT_PORT=$REDIRECT_PORT"
} >> "$ENV_FILE"

echo "Credentials appended to $ENV_FILE"
echo ""
echo "Next step: Run the agent — it will open a browser for OAuth consent on first start."
