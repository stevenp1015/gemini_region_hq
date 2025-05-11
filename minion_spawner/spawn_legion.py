import subprocess
import os
import sys # Added for sys.path manipulation
import time
# import json # No longer directly used
import argparse
import asyncio # Added for asyncio

# Ensure the project root is in sys.path to find system_configs.config_manager
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

from system_configs.config_manager import config # Import the global config instance
from minion_core.async_minion import AsyncMinion # Import AsyncMinion
from minion_core.utils.resource_monitor import ResourceMonitor

# --- Paths and Configs from ConfigManager ---
PROJECT_ROOT = config.get_project_root()
LOGS_DIR = config.get_path("global.logs_dir", "logs") # Uses PROJECT_ROOT implicitly

# Paths for spawner operation - consider making these configurable in config.toml under [minion_spawner]
MINION_SCRIPT_PATH = config.get_path("minion_spawner.minion_script_path", os.path.join(PROJECT_ROOT, "minion_core/main_minion.py")) # This might be less relevant now
VENV_PYTHON_PATH = config.get_path("minion_spawner.venv_python_path", os.path.join(PROJECT_ROOT, "venv_legion/bin/python")) # This might be less relevant now
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

def spawn_minions(num_minions_to_spawn_arg, a2a_server_url_arg):
    # Existing validation code... (partially kept, some not needed for async in-process)
    # if not os.path.exists(VENV_PYTHON_PATH): # Not needed for in-process
    #     spawner_log(f"Python virtual environment not found at {VENV_PYTHON_PATH}. Check 'minion_spawner.venv_python_path' in config.toml or ensure deployment script ran.", level="ERROR")
    #     return [], []
    # if not os.path.exists(MINION_SCRIPT_PATH): # Not needed for in-process
    #     spawner_log(f"Minion script not found at {MINION_SCRIPT_PATH}. Check 'minion_spawner.minion_script_path' in config.toml or ensure deployment script ran correctly.", level="ERROR")
    #     return [], []

    # processes = [] # Not used in this version
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
    
    # Create a list to hold minion objects for the async version
    minions = []
    default_user_facing_name = config.get_str("minion_defaults.default_user_facing_name", "Minion")
    
    for i in range(num_to_spawn_final):
        minion_def = actual_minion_definitions[i]
        minion_id = minion_def.get("id")
        personality = minion_def.get("personality")
        
        # Resolve user_facing_name as in the original...
        if num_to_spawn_final > 1:
            user_facing_name = f"{default_user_facing_name}-{minion_id}"
        else:
            user_facing_name = default_user_facing_name
        
        if not minion_id or not personality:
            spawner_log(f"Skipping minion definition due to missing 'id' or 'personality': {minion_def}", level="WARNING")
            continue
        
        spawner_log(f"Creating Minion {minion_id} (Name: {user_facing_name}) with personality: {personality}...")
        
        # Set environment variables - less critical for in-process, but good for consistency if some parts still rely on them
        minion_env = os.environ.copy()
        minion_env["BASE_PROJECT_DIR"] = PROJECT_ROOT
        minion_env["PYTHONUNBUFFERED"] = "1"
        
        # Update PYTHONPATH - less critical for in-process if imports are direct
        a2a_python_path = os.path.join(PROJECT_ROOT, "a2a_framework", "samples", "python")
        current_pythonpath = minion_env.get("PYTHONPATH", "")
        if current_pythonpath:
            minion_env["PYTHONPATH"] = f"{a2a_python_path}{os.pathsep}{current_pythonpath}"
        else:
            minion_env["PYTHONPATH"] = a2a_python_path
        # spawner_log(f"Effective PYTHONPATH for Minion {minion_id} context: {minion_env['PYTHONPATH']}", level="DEBUG")

        # For the asyncio version, we'll create and store minion objects
        # that we'll run in the main process using asyncio
        try:
            minion = AsyncMinion(
                minion_id=minion_id,
                user_facing_name=user_facing_name,
                personality_traits_str=personality,
                a2a_server_url_override=a2a_server_url_arg
            )
            minions.append(minion)
            spawned_minion_ids.append(minion_id)
            spawner_log(f"Created Minion {minion_id} object successfully")
        except Exception as e:
            spawner_log(f"Failed to create Minion {minion_id} object: {e}", level="ERROR")
    
    return minions, spawned_minion_ids

async def run_minions(minions):
    """Run multiple minions concurrently using asyncio."""
    spawner_log(f"Starting {len(minions)} minions using asyncio...")
    
    # Create tasks for each minion
    tasks = [minion.run() for minion in minions]
    
    # Wait for all minions to complete (or until interrupted)
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        spawner_log("Minion tasks cancelled", level="WARNING")
    except Exception as e:
        spawner_log(f"Error running minions: {e}", level="ERROR")
    
    spawner_log("All minions have stopped")

def init_resource_monitor():
    """Initialize the resource monitor."""
    monitor = ResourceMonitor(check_interval=10.0) # Using spawner_log for consistency
    
    def alert_handler(resources, is_overloaded):
        if is_overloaded:
            spawner_log(f"ALERT: System resources critical: "
                        f"CPU {resources.get('cpu_percent')}%, "
                        f"Memory {resources.get('memory_percent')}%, "
                        f"Disk {resources.get('disk_percent')}%",
                        level="WARNING")
    
    monitor.add_alert_callback(alert_handler)
    monitor.start()
    return monitor

if __name__ == "__main__":
    # Construct default A2A server URL from config for argparse help text and default
    default_a2a_host_for_arg = config.get_str("a2a_server.host", "127.0.0.1")
    default_a2a_port_for_arg = config.get_int("a2a_server.port", 8080)
    default_a2a_url_for_arg = f"http://{default_a2a_host_for_arg}:{default_a2a_port_for_arg}"

    parser = argparse.ArgumentParser(description="Spawn AI Minions for Steven's Army (Async Version).")
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

    spawner_log("Minion Spawner Initializing (Async Mode)...")
    spawner_log(f"Project Root: {PROJECT_ROOT}")
    spawner_log(f"Logs Directory: {LOGS_DIR}")
    # spawner_log(f"Minion Script: {MINION_SCRIPT_PATH}") # Less relevant
    # spawner_log(f"Venv Python: {VENV_PYTHON_PATH}") # Less relevant
    spawner_log(f"Minion definitions in config: {len(MINION_DEFINITIONS_FROM_CONFIG)}")

    # Check A2A server URL format (from arg, which might override config)
    a2a_server_url_to_use = args.a2a_server
    if not (a2a_server_url_to_use.startswith("http://") or a2a_server_url_to_use.startswith("https://")):
        spawner_log(f"A2A Server URL '{a2a_server_url_to_use}' seems invalid. It should start with http:// or https://.", level="ERROR")
        sys.exit(1)
    
    spawner_log(f"Targeting A2A Server at: {a2a_server_url_to_use}")
    spawner_log(f"Attempting to create {args.count} minion objects (respecting defined limit).")

    minions, active_ids = spawn_minions(args.count, a2a_server_url_to_use)
    
    if not minions:
        spawner_log("No Minion objects were created. Exiting.", level="ERROR")
        sys.exit(1)
    
    spawner_log(f"Created minions: {', '.join(active_ids)}. Starting async execution...")
    spawner_log("Press Ctrl+C to stop the spawner and initiate minion shutdown.")
    
    # Initialize resource monitor
    resource_monitor = init_resource_monitor()
    globals()['global_resource_monitor'] = resource_monitor
    
    try:
        # Run the asyncio event loop
        asyncio.run(run_minions(minions))
    except KeyboardInterrupt:
        spawner_log("Spawner received KeyboardInterrupt. Initiating shutdown of minions...", level="INFO")
        # asyncio.run will handle the cancellation of tasks within run_minions
        # and the individual minion shutdown methods should be called.
    finally:
        # Stop resource monitor
        if 'resource_monitor' in locals() and resource_monitor:
            resource_monitor.stop()
        spawner_log("Minion Spawner shut down.")
