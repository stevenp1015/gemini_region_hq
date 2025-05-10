import subprocess
import os
import sys # Added for sys.path manipulation
import time
# import json # No longer directly used
import argparse

# Ensure the project root is in sys.path to find system_configs.config_manager
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

from system_configs.config_manager import config # Import the global config instance

# --- Paths and Configs from ConfigManager ---
PROJECT_ROOT = config.get_project_root()
LOGS_DIR = config.get_path("global.logs_dir", "logs") # Uses PROJECT_ROOT implicitly

# Paths for spawner operation - consider making these configurable in config.toml under [minion_spawner]
MINION_SCRIPT_PATH = config.get_path("minion_spawner.minion_script_path", os.path.join(PROJECT_ROOT, "minion_core/main_minion.py"))
VENV_PYTHON_PATH = config.get_path("minion_spawner.venv_python_path", os.path.join(PROJECT_ROOT, "venv_legion/bin/python"))
SPAWNER_LOG_FILE = os.path.join(LOGS_DIR, "minion_spawner.log")

# Ensure logs directory exists for spawner log
if not os.path.exists(LOGS_DIR):
    try:
        os.makedirs(LOGS_DIR)
    except OSError as e:
        print(f"CRITICAL: Could not create logs directory {LOGS_DIR}. Error: {e}", file=sys.stderr)
        sys.exit(1) # Exit if cannot create log dir

# Basic logger for the spawner itself
def spawner_log(message, level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    log_entry = f"{timestamp} - SPAWNER - {level} - {message}"
    print(log_entry) # Keep console output for spawner
    with open(SPAWNER_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

# Load Minion definitions from config.toml
MINION_DEFINITIONS_FROM_CONFIG = config.get_list("minion_spawner.minions", [])
if not MINION_DEFINITIONS_FROM_CONFIG:
    spawner_log("Warning: No minion definitions found in config.toml under [minion_spawner.minions]. Spawner will not launch any minions.", level="WARNING")
    # Optionally, provide a default fallback if desired, or exit. For now, it will spawn 0.

def spawn_minions(num_minions_to_spawn_arg, a2a_server_url_arg):
    if not os.path.exists(VENV_PYTHON_PATH):
        spawner_log(f"Python virtual environment not found at {VENV_PYTHON_PATH}. Check 'minion_spawner.venv_python_path' in config.toml or ensure deployment script ran.", level="ERROR")
        return [], []
    if not os.path.exists(MINION_SCRIPT_PATH):
        spawner_log(f"Minion script not found at {MINION_SCRIPT_PATH}. Check 'minion_spawner.minion_script_path' in config.toml or ensure deployment script ran correctly.", level="ERROR")
        return [], []

    processes = []
    spawned_minion_ids = []
    
    # Use minion definitions from config
    actual_minion_definitions = MINION_DEFINITIONS_FROM_CONFIG
    if not actual_minion_definitions:
        spawner_log("No minion definitions loaded from config. Cannot spawn minions.", level="ERROR")
        return [], []

    num_available_definitions = len(actual_minion_definitions)
    num_to_spawn_final = min(num_minions_to_spawn_arg, num_available_definitions)

    if num_minions_to_spawn_arg > num_available_definitions:
        spawner_log(f"Requested {num_minions_to_spawn_arg} minions, but only {num_available_definitions} are defined in config.toml. Spawning {num_available_definitions}.", level="WARNING")
    elif num_minions_to_spawn_arg == 0 and num_available_definitions > 0 : # If count is 0, but definitions exist, spawn all defined
        spawner_log(f"--count is 0, spawning all {num_available_definitions} defined minions.", level="INFO")
        num_to_spawn_final = num_available_definitions


    default_user_facing_name = config.get_str("minion_defaults.default_user_facing_name", "Minion") # Read from config

    for i in range(num_to_spawn_final):
        minion_def = actual_minion_definitions[i]
        minion_id = minion_def.get("id")
        personality = minion_def.get("personality")
        # For now, use the default name. Future enhancements could allow per-minion names from config.
        user_facing_name = default_user_facing_name
        # A simple naming scheme if spawning multiple and we want them to be unique for now, e.g. "Minion-Alpha"
        # This could be made more sophisticated based on minion_def if needed.
        # For this initial step, we'll pass the same default or a slightly modified one.
        # If there's more than one minion, append the ID to the default name.
        if num_to_spawn_final > 1:
            user_facing_name = f"{default_user_facing_name}-{minion_id}"
        else:
            user_facing_name = default_user_facing_name


        if not minion_id or not personality:
            spawner_log(f"Skipping minion definition at index {i} due to missing 'id' or 'personality': {minion_def}", level="WARNING")
            continue
        
        spawner_log(f"Spawning Minion {minion_id} (Name: {user_facing_name}) with personality: {personality}...")
        
        # Set BASE_PROJECT_DIR for the Minion process environment
        minion_env = os.environ.copy()
        minion_env["BASE_PROJECT_DIR"] = PROJECT_ROOT # Use PROJECT_ROOT from ConfigManager
        minion_env["PYTHONUNBUFFERED"] = "1" # For unbuffered output from subprocess

        # Add a2a_framework/samples/python to PYTHONPATH for the minion process
        # so it can find the 'common' module.
        a2a_python_path = os.path.join(PROJECT_ROOT, "a2a_framework", "samples", "python")
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
                [VENV_PYTHON_PATH, MINION_SCRIPT_PATH, "--id", minion_id, "--name", user_facing_name, "--personality", personality, "--a2a-server", a2a_server_url_arg],
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

    spawner_log(f"Attempted to spawn {num_to_spawn_final} minions. Check individual minion logs in {LOGS_DIR}.")
    return processes, spawned_minion_ids

if __name__ == "__main__":
    # Construct default A2A server URL from config for argparse help text and default
    default_a2a_host_for_arg = config.get_str("a2a_server.host", "127.0.0.1")
    default_a2a_port_for_arg = config.get_int("a2a_server.port", 8080)
    default_a2a_url_for_arg = f"http://{default_a2a_host_for_arg}:{default_a2a_port_for_arg}"

    parser = argparse.ArgumentParser(description="Spawn AI Minions for Steven's Army.")
    parser.add_argument(
        "--count",
        type=int,
        default=config.get_int("minion_spawner.default_spawn_count", len(MINION_DEFINITIONS_FROM_CONFIG) if MINION_DEFINITIONS_FROM_CONFIG else 0),
        help="Number of Minions to spawn from definitions in config.toml. Default is number of defined minions or 0 if none defined."
    )
    parser.add_argument(
        "--a2a-server",
        type=str,
        default=default_a2a_url_for_arg,
        help=f"URL of the A2A server. Overrides config.toml. Default from config: {default_a2a_url_for_arg}"
    )
    args = parser.parse_args()

    spawner_log("Minion Spawner Initializing...")
    spawner_log(f"Project Root: {PROJECT_ROOT}")
    spawner_log(f"Logs Directory: {LOGS_DIR}")
    spawner_log(f"Minion Script: {MINION_SCRIPT_PATH}")
    spawner_log(f"Venv Python: {VENV_PYTHON_PATH}")
    spawner_log(f"Minion definitions in config: {len(MINION_DEFINITIONS_FROM_CONFIG)}")


    # ConfigManager handles BASE_PROJECT_DIR internally. No need to set os.environ here.

    # Check A2A server URL format (from arg, which might override config)
    a2a_server_url_to_use = args.a2a_server
    if not (a2a_server_url_to_use.startswith("http://") or a2a_server_url_to_use.startswith("https://")):
        spawner_log(f"A2A Server URL '{a2a_server_url_to_use}' seems invalid. It should start with http:// or https://.", level="ERROR")
        sys.exit(1)
    
    spawner_log(f"Targeting A2A Server at: {a2a_server_url_to_use}")
    spawner_log(f"Attempting to spawn {args.count} minions (respecting defined limit).")

    active_processes, active_ids = spawn_minions(args.count, a2a_server_url_to_use)
    
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
