#!/bin/bash
# Master script to stop all core services for the AI Minion Army.

BASE_PROJECT_DIR_LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOGS_DIR_MAIN="${BASE_PROJECT_DIR_LOCAL}/logs"
PID_FILES_PATTERN="${LOGS_DIR_MAIN}/*.pid"

echo "Attempting to stop AI Minion Army services..."

if ! ls $PID_FILES_PATTERN 1> /dev/null 2>&1; then
    echo "No .pid files found in ${LOGS_DIR_MAIN}. Are services running or were PIDs recorded?"
    # Fallback: try to find by common process names if pgrep is available
    if command -v pgrep >/dev/null 2>&1; then
        echo "Attempting to find processes by name (python run_a2a_server.py, python gui_app.py)..."
        pgrep -f "run_a2a_server.py" | xargs -r kill -15 # SIGTERM
        pgrep -f "gui_app.py" | xargs -r kill -15 # SIGTERM
        # Add other pgrep patterns if needed for other services
        sleep 2
        pgrep -f "run_a2a_server.py" | xargs -r kill -9 # SIGKILL if still running
        pgrep -f "gui_app.py" | xargs -r kill -9 # SIGKILL if still running
        echo "Sent termination signals based on process names. Check manually if they stopped."
    else
        echo "pgrep not found. Cannot attempt to stop by process name. Please stop manually."
    fi
    exit 0
fi

for pid_file in $PID_FILES_PATTERN; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file")
        service_name=$(basename "$pid_file" .pid)
        if ps -p $pid > /dev/null; then
            echo "Stopping $service_name (PID: $pid)..."
            kill -15 $pid # Send SIGTERM for graceful shutdown
            # Wait a bit
            sleep 3
            if ps -p $pid > /dev/null; then
                echo "Service $service_name (PID: $pid) did not stop gracefully. Sending SIGKILL..."
                kill -9 $pid
                sleep 1
                if ps -p $pid > /dev/null; then
                     echo "ERROR: Failed to kill $service_name (PID: $pid) even with SIGKILL."
                else
                    echo "Service $service_name (PID: $pid) killed."
                fi
            else
                echo "Service $service_name (PID: $pid) stopped gracefully."
            fi
        else
            echo "Service $service_name (PID: $pid from $pid_file) is not running."
        fi
        rm -f "$pid_file" # Clean up pid file
    fi
done

# Also attempt to kill Minion spawner and Minion processes if any are running detached
# This is a more aggressive cleanup.
if command -v pgrep >/dev/null 2>&1; then
    echo "Attempting to clean up any remaining Minion Spawner or Minion Core processes..."
    pgrep -f "spawn_legion.py" | xargs -r kill -9
    pgrep -f "main_minion.py" | xargs -r kill -9
    echo "Cleanup attempt complete."
fi

echo "All service stop attempts complete."
