import subprocess
import os
import time
import json
import argparse

# Assumes this script is run from BASE_PROJECT_DIR or BASE_PROJECT_DIR is in env
BASE_DIR = os.getenv("BASE_PROJECT_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
MINION_SCRIPT_PATH = os.path.join(BASE_DIR, "minion_core/main_minion.py")
VENV_PYTHON_PATH = os.path.join(BASE_DIR, "venv_legion/bin/python")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

# Ensure logs directory exists for spawner log
if not os.path.exists(LOGS_DIR):
    os.makedirs(LOGS_DIR)

# Basic logger for the spawner itself
def spawner_log(message, level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    log_entry = f"{timestamp} - SPAWNER - {level} - {message}"
    print(log_entry)
    with open(os.path.join(LOGS_DIR, "minion_spawner.log"), "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

# Define some personalities - can be expanded or loaded from config
MINION_DEFINITIONS = [
    {"id": "Alpha", "personality": "Strategic, Analytical, CalmUnderPressure"},
    {"id": "Bravo", "personality": "Creative, Unconventional, Inquisitive"},
    {"id": "Charlie", "personality": "Meticulous, DetailOriented, Skeptical"},
    {"id": "Delta", "personality": "Resourceful, Pragmatic, FastLearner"},
    {"id": "Echo", "personality": "Empathetic, Communicative, Diplomatic"} # For A2A coordination
]

def spawn_minions(num_minions_to_spawn, a2a_server_url):
    if not os.path.exists(VENV_PYTHON_PATH):
        spawner_log(f"Python virtual environment not found at {VENV_PYTHON_PATH}. Please run deployment script.", level="ERROR")
        return []
    if not os.path.exists(MINION_SCRIPT_PATH):
        spawner_log(f"Minion script not found at {MINION_SCRIPT_PATH}. Please ensure deployment script ran correctly.", level="ERROR")
        return []

    processes = []
    spawned_minion_ids = []

    # Ensure we don't try to spawn more minions than defined personalities if using predefined list
    num_to_spawn = min(num_minions_to_spawn, len(MINION_DEFINITIONS))
    if num_minions_to_spawn > len(MINION_DEFINITIONS):
        spawner_log(f"Requested {num_minions_to_spawn} minions, but only {len(MINION_DEFINITIONS)} personalities defined. Spawning {len(MINION_DEFINITIONS)}.", level="WARNING")


    for i in range(num_to_spawn):
        minion_def = MINION_DEFINITIONS[i]
        minion_id = minion_def["id"]
        personality = minion_def["personality"]
        
        spawner_log(f"Spawning Minion {minion_id} with personality: {personality}...")
        
        # Set BASE_PROJECT_DIR for the Minion process environment
        minion_env = os.environ.copy()
        minion_env["BASE_PROJECT_DIR"] = BASE_DIR
        minion_env["PYTHONUNBUFFERED"] = "1" # For unbuffered output from subprocess

        # Add a2a_framework/samples/python to PYTHONPATH for the minion process
        # so it can find the 'common' module.
        a2a_python_path = os.path.join(BASE_DIR, "a2a_framework", "samples", "python")
        current_pythonpath = minion_env.get("PYTHONPATH", "")
        if current_pythonpath:
            minion_env["PYTHONPATH"] = f"{a2a_python_path}{os.pathsep}{current_pythonpath}"
        else:
            minion_env["PYTHONPATH"] = a2a_python_path
        spawner_log(f"Setting PYTHONPATH for Minion {minion_id} to: {minion_env['PYTHONPATH']}", level="DEBUG") # DEBUG level for verbosity

        # BIAS_ACTION: Launch each Minion in its own process.
        # Ensure logs for each Minion go to their specific files.
        # The main_minion.py script handles its own logging setup based on its ID.
        try:
            process = subprocess.Popen(
                [VENV_PYTHON_PATH, MINION_SCRIPT_PATH, "--id", minion_id, "--personality", personality, "--a2a-server", a2a_server_url],
                stdout=subprocess.PIPE, # Capture stdout
                stderr=subprocess.PIPE, # Capture stderr
                env=minion_env,
                text=True, # Decode stdout/stderr as text
                # cwd=BASE_DIR # Run from base project dir
            )
            processes.append(process)
            spawned_minion_ids.append(minion_id)
            spawner_log(f"Minion {minion_id} process started (PID: {process.pid}). Output will be piped to its log file and spawner log for errors.")
            
            # Non-blocking read of stdout/stderr can be complex.
            # For now, we're letting Minions log to their own files.
            # Spawner can periodically check process.poll() if needed.
            
        except Exception as e:
            spawner_log(f"Failed to spawn Minion {minion_id}. Error: {e}", level="ERROR")

        time.sleep(2) # Stagger spawning slightly

    spawner_log(f"Attempted to spawn {num_to_spawn} minions. Check individual minion logs in {LOGS_DIR}.")
    return processes, spawned_minion_ids

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Spawn AI Minions for Steven's Army.")
    parser.add_argument("--count", type=int, default=3, help="Number of Minions to spawn.")
    parser.add_argument("--a2a-server", type=str, default=f"http://127.0.0.1:8080", help="URL of the A2A server.")
    args = parser.parse_args()

    spawner_log("Minion Spawner Initializing...")
    # Set BASE_PROJECT_DIR for the spawner itself if it's not set (e.g. running directly)
    if not os.getenv("BASE_PROJECT_DIR"):
        os.environ["BASE_PROJECT_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        spawner_log(f"Spawner BASE_PROJECT_DIR set to: {os.environ['BASE_PROJECT_DIR']}")

    # Check A2A server URL format
    if not (args.a2a_server.startswith("http://") or args.a2a_server.startswith("https://")):
        spawner_log(f"A2A Server URL '{args.a2a_server}' seems invalid. It should start with http:// or https://.", level="ERROR")
        sys.exit(1)

    active_processes, active_ids = spawn_minions(args.count, args.a2a_server)
    
    if not active_processes:
        spawner_log("No Minion processes were started. Exiting.", level="ERROR")
        sys.exit(1)

    spawner_log(f"Minions spawned: {', '.join(active_ids)}. Monitoring their processes...")
    spawner_log("Press Ctrl+C to stop the spawner and terminate Minion processes.")

    try:
        while True:
            for i, proc in enumerate(active_processes):
                if proc.poll() is not None: # Process has terminated
                    spawner_log(f"Minion {active_ids[i]} (PID: {proc.pid}) has terminated with code {proc.returncode}.", level="WARNING")
                    # Capture any final output
                    stdout, stderr = proc.communicate()
                    if stdout: spawner_log(f"Minion {active_ids[i]} STDOUT: {stdout.strip()}", level="INFO")
                    if stderr: spawner_log(f"Minion {active_ids[i]} STDERR: {stderr.strip()}", level="ERROR")
                    # Remove from list of active processes
                    active_processes.pop(i)
                    active_ids.pop(i)
                    break # Restart loop since list was modified
            if not active_processes:
                spawner_log("All Minion processes have terminated.", level="INFO")
                break
            time.sleep(5)
    except KeyboardInterrupt:
        spawner_log("Spawner received KeyboardInterrupt. Terminating Minion processes...", level="INFO")
        for i, proc in enumerate(active_processes):
            spawner_log(f"Terminating Minion {active_ids[i]} (PID: {proc.pid})...")
            proc.terminate() # Send SIGTERM
            try:
                proc.wait(timeout=10) # Wait for graceful shutdown
                spawner_log(f"Minion {active_ids[i]} terminated.")
            except subprocess.TimeoutExpired:
                spawner_log(f"Minion {active_ids[i]} did not terminate gracefully. Sending SIGKILL...", level="WARNING")
                proc.kill() # Force kill
                spawner_log(f"Minion {active_ids[i]} killed.")
    finally:
        spawner_log("Minion Spawner shut down.")
