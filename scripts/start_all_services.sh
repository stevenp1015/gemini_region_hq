#!/bin/bash
# Master script to start all core services for the AI Minion Army.
# Run this from the BASE_PROJECT_DIR (/Users/ttig/GEMINI_LEGION_HQ)

BASE_PROJECT_DIR_LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="${BASE_PROJECT_DIR_LOCAL}/venv_legion/bin/python"
LOGS_DIR_MAIN="${BASE_PROJECT_DIR_LOCAL}/logs"

A2A_SERVER_RUNNER="${BASE_PROJECT_DIR_LOCAL}/a2a_server_runner/run_a2a_server.py"
A2A_SERVER_LOG="${LOGS_DIR_MAIN}/a2a_server_main.log"

GUI_APP_RUNNER="${BASE_PROJECT_DIR_LOCAL}/management_gui/gui_app.py"
GUI_APP_LOG="${LOGS_DIR_MAIN}/management_gui_main.log"

# Function to start a process in the background and save its PID
start_background_process() {
    local cmd_name="$1"
    local log_file="$2"
    shift 2
    local cmd_array=("$@")

    echo "Starting $cmd_name..." | tee -a "$log_file"
    # Start process in background, redirect stdout/stderr to its log file
    nohup "${cmd_array[@]}" >> "$log_file" 2>&1 &
    local pid=$!
    echo "$pid" > "${LOGS_DIR_MAIN}/${cmd_name}.pid"
    echo "$cmd_name started with PID $pid. Logs: $log_file"
    sleep 2 # Give it a moment to start or fail
    if ! ps -p $pid > /dev/null; then
        echo "ERROR: $cmd_name (PID $pid) failed to stay running. Check $log_file."
        return 1
    fi
    return 0
}

# Ensure logs directory exists
mkdir -p "$LOGS_DIR_MAIN"

# Set BASE_PROJECT_DIR for child scripts
export BASE_PROJECT_DIR="${BASE_PROJECT_DIR_LOCAL}"
export A2A_FRAMEWORK_DIR="${BASE_PROJECT_DIR_LOCAL}/a2a_framework" # For A2A server runner
export LOGS_DIR="${LOGS_DIR_MAIN}" # For A2A server runner

# Activate Python Virtual Environment for Python scripts
# shellcheck disable=SC1091
source "${BASE_PROJECT_DIR_LOCAL}/venv_legion/bin/activate" || { echo "CRITICAL: Failed to activate Python venv. Aborting."; exit 1; }
echo "Python virtual environment activated."

# Start A2A Server
start_background_process "A2A_Server" "$A2A_SERVER_LOG" "$VENV_PYTHON" "$A2A_SERVER_RUNNER"
if [ $? -ne 0 ]; then echo "Failed to start A2A Server. Aborting further launches."; exit 1; fi

# Start Management GUI
# Set GUI_HOST and GUI_PORT if needed, defaults are in gui_app.py
export GUI_HOST="127.0.0.1"
export GUI_PORT="8081"
start_background_process "Management_GUI" "$GUI_APP_LOG" "$VENV_PYTHON" "$GUI_APP_RUNNER"
if [ $? -ne 0 ]; then echo "Failed to start Management GUI. Check logs."; fi # Don't abort if only GUI fails

# Codex Omega Note: MCP Servers (like computer-use) are typically started on-demand by the
# MCP Super-Tool (Node.js Client Omega) via stdio, as defined in mcp_config.json.
# Therefore, we usually don't need to start them persistently here unless that design changes.
# If you *do* want to run one persistently (e.g., for debugging):
# COMPUTER_USE_MCP_RUNNER="${BASE_PROJECT_DIR_LOCAL}/mcp_server_runners/run_computer_use_mcp.sh"
# start_background_process "ComputerUseMCP" "${LOGS_DIR_MAIN}/computer_use_mcp_persistent.log" "bash" "$COMPUTER_USE_MCP_RUNNER"

echo ""
echo "All requested services have been launched."
echo "AI Minion Army Command Center GUI should be accessible at: http://127.0.0.1:8081"
echo "A2A Server should be running on: http://127.0.0.1:8080"
echo "Check PID files in ${LOGS_DIR_MAIN} and individual log files for status."
echo "To stop services, use the 'stop_all_services.sh' script or manually kill PIDs."

deactivate # Deactivate venv
echo "Python virtual environment deactivated."
