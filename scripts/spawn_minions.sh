#!/bin/bash

# Get the directory of this script to robustly find the project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." &> /dev/null && pwd)"

# Path to the virtual environment's Python interpreter
VENV_PYTHON="$PROJECT_ROOT/venv_legion/bin/python"

# Check if the venv Python exists
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Error: Virtual environment Python interpreter not found at $VENV_PYTHON"
    echo "Please ensure the virtual environment 'venv_legion' exists in the project root ($PROJECT_ROOT/venv_legion)."
    exit 1
fi

echo "Using Python interpreter: $VENV_PYTHON"

ARGS_TO_PASS=()

# Check if the first argument is a number (potential count)
if [[ "$1" =~ ^[0-9]+$ ]]; then
    ARGS_TO_PASS+=("--count" "$1")
    shift # Remove the count from the list of arguments to process
fi

# Add any remaining arguments (e.g., --a2a-server)
ARGS_TO_PASS+=("$@")

# Execute the spawner script using the venv's Python
echo "Executing: $VENV_PYTHON $PROJECT_ROOT/minion_spawner/spawn_legion.py ${ARGS_TO_PASS[@]}"
"$VENV_PYTHON" "$PROJECT_ROOT/minion_spawner/spawn_legion.py" "${ARGS_TO_PASS[@]}"
