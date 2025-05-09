#!/bin/bash
# Runner script for the Computer-Use MCP Server (for manual testing/daemonizing)
# Normally, the MCP Super-Tool (Node.js Client Omega) starts this on-demand via stdio.

BASE_PROJECT_DIR_LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" # More robust way to get base dir
COMPUTER_USE_MCP_DIR="${BASE_PROJECT_DIR_LOCAL}/mcp_servers/computer_use_mcp"
MCP_SERVER_LOG_FILE="${BASE_PROJECT_DIR_LOCAL}/logs/computer_use_mcp_server.log"

echo "Attempting to start Computer-Use MCP Server..." | tee -a "$MCP_SERVER_LOG_FILE"
echo "Server Directory: $COMPUTER_USE_MCP_DIR" | tee -a "$MCP_SERVER_LOG_FILE"
echo "Logs will also be appended to: $MCP_SERVER_LOG_FILE"

if [ ! -d "$COMPUTER_USE_MCP_DIR" ]; then
    echo "ERROR: Computer-Use MCP Server directory not found at $COMPUTER_USE_MCP_DIR" | tee -a "$MCP_SERVER_LOG_FILE"
    exit 1
fi

if [ ! -f "${COMPUTER_USE_MCP_DIR}/dist/index.js" ]; then
    echo "ERROR: Computer-Use MCP Server entry point (dist/index.js) not found." | tee -a "$MCP_SERVER_LOG_FILE"
    echo "Ensure you have built the server if it requires a build step (e.g., TypeScript compilation)." | tee -a "$MCP_SERVER_LOG_FILE"
    # Codex Omega Note: The digest provided for computer-use-mcp already had a dist/index.js,
    # implying it's pre-built or the build step is part of its npm install.
    # If it needs , that should be added to dependency installation for it.
    exit 1
fi

# Check for Node
if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: Node.js is not installed or not in PATH." | tee -a "$MCP_SERVER_LOG_FILE"
    exit 1
fi

cd "$COMPUTER_USE_MCP_DIR" || exit 1

# The server is designed for stdio communication with an MCP client.
# Running it directly like this is mainly for testing its basic startup.
# It will listen on stdin and respond on stdout.
echo "Starting Computer-Use MCP Server via Node.js (listening on stdio)..." | tee -a "$MCP_SERVER_LOG_FILE"
# Redirect script's own stdout/stderr to its log file to capture Node.js output
exec >> "$MCP_SERVER_LOG_FILE" 2>&1

node dist/index.js
# If it exits, it will be logged. If it runs indefinitely, Ctrl+C to stop.
