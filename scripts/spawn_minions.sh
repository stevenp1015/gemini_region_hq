#!/bin/bash
# Wrapper script to spawn AI Minions.

BASE_PROJECT_DIR_LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${BASE_PROJECT_DIR_LOCAL}/venv_legion/bin/python"
MINION_SPAWNER_PY="${BASE_PROJECT_DIR_LOCAL}/minion_spawner/spawn_legion.py"

DEFAULT_MINION_COUNT=3
DEFAULT_A2A_SERVER_URL="http://127.0.0.1:8080"

COUNT=${1:-$DEFAULT_MINION_COUNT}
A2A_URL=${2:-$DEFAULT_A2A_SERVER_URL}

echo "Attempting to spawn $COUNT minions connected to A2A server: $A2A_URL"

if [ ! -f "$VENV_PYTHON" ]; then echo "ERROR: Python venv not found at $VENV_PYTHON"; exit 1; fi
if [ ! -f "$MINION_SPAWNER_PY" ]; then echo "ERROR: Minion spawner script not found at $MINION_SPAWNER_PY"; exit 1; fi

# Set BASE_PROJECT_DIR for the spawner process
export BASE_PROJECT_DIR="${BASE_PROJECT_DIR_LOCAL}"

# Activate venv
# shellcheck disable=SC1091
source "${BASE_PROJECT_DIR_LOCAL}/venv_legion/bin/activate" || { echo "CRITICAL: Failed to activate Python venv. Aborting."; exit 1; }

"$VENV_PYTHON" "$MINION_SPAWNER_PY" --count "$COUNT" --a2a-server "$A2A_URL"

# Deactivate venv (spawner script might run for a long time, so this might not be hit immediately if spawner is blocking)
# The spawner itself doesn't need venv after launching child processes if they use the venv python directly.
deactivate
echo "Minion Spawner launched. It will manage Minion processes. Press Ctrl+C in its terminal to stop it."
