# management_gui/main_app.py
import os
import sys
import asyncio
import time
from datetime import datetime, timezone
from nicegui import ui, app

# Ensure project root is in path for config loading within app_state if needed early
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

# Import from new modules
try:
    from .app_state import (
        app_state, gui_log, config, A2A_SERVER_URL, LOGS_DIR, # Added LOGS_DIR
        GUI_COMMANDER_MESSAGE_POLLING_INTERVAL_SECONDS,
        GUI_SERVER_STATUS_POLLING_INTERVAL_SECONDS,
        GUI_MINION_LIST_POLLING_INTERVAL_SECONDS
    )
    # Import necessary constants/functions if needed directly by main_app setup
except ImportError as e:
    print(f"CRITICAL ERROR: Failed to import from .app_state: {e}. Check structure.", file=sys.stderr)
    sys.exit(1) # Cannot run without app_state

# Import from UI helpers if needed for core setup (e.g., global style)
# from .ui_helpers import configure_global_style # Example if needed

# --- Temporary Imports from Monolith ---
# These functions will need to be defined in gui_app.py to encapsulate
# the UI page definitions and background task setups that haven't been moved yet.
try:
    # Assuming gui_app.py will be refactored to provide these entry points
    # Renamed setup_background_tasks to setup_periodic_tasks for clarity
    # Added setup_a2a_polling based on original timer setup
    from .gui_app import setup_ui_pages, setup_a2a_polling
    gui_log("Successfully imported temporary setup functions from gui_app.")
except ImportError as e:
    gui_log(f"WARNING: Could not import setup functions from .gui_app: {e}. UI pages and background tasks might not load.", level="WARNING")
    # Define dummy functions to prevent crash if gui_app isn't ready
    def setup_ui_pages(): gui_log("Dummy setup_ui_pages called.", level="WARNING")
    def setup_a2a_polling(): gui_log("Dummy setup_a2a_polling called.", level="WARNING")


# --- Application Setup ---

# @app.on_startup - Handled by calling setup functions before ui.run
# @app.on_shutdown - No explicit shutdown tasks identified to move yet

# --- Main GUI Execution ---

def run_gui(host: str, port: int):
    """
    Initializes and runs the NiceGUI application server.
    Sets up global configurations and starts background tasks.
    """
    gui_log(f"Starting Management GUI - Main App Entry Point on http://{host}:{port}")

    # Configure global appearance (e.g., dark mode)
    ui.dark_mode().enable()
    gui_log("Dark mode enabled.")

    # Ensure logs directory exists (moved from original run_gui)
    try:
        if not os.path.exists(LOGS_DIR):
            os.makedirs(LOGS_DIR)
            gui_log(f"Created logs directory: {LOGS_DIR}")
    except OSError as e:
         gui_log(f"ERROR: Could not create logs directory '{LOGS_DIR}': {e}", level="ERROR")
         # Decide if this is fatal? For now, continue.

    # Generate storage secret (moved from original run_gui)
    generated_storage_secret = os.urandom(16).hex()
    gui_log(f"Generated NiceGUI storage_secret: {'*' * len(generated_storage_secret)}")

    # --- Setup UI Pages and Background Tasks ---
    # These calls rely on the temporary imports from gui_app.py
    # They register UI routes and initialize timers/handlers.
    try:
        # Setup UI Pages (@ui.page definitions)
        setup_ui_pages()
        gui_log("UI pages setup initiated from gui_app.")

        # Setup A2A Polling Tasks (Timers for fetch_... functions)
        # This replaces the direct ui.timer calls from the original run_gui
        setup_a2a_polling()
        gui_log("A2A polling tasks setup initiated from gui_app.")

    except Exception as e:
        gui_log(f"ERROR during setup calls from gui_app: {e}", level="CRITICAL", exc_info=True)
        # Decide whether to proceed or exit
        # For now, log and continue, but the app might be broken.

    # --- Start NiceGUI Server ---
    ui.run(
        host=host,
        port=port,
        title="Minion Army Command Center (Modular)",
        dark=True, # Set directly here
        reload=False, # Set to True for development if needed
        storage_secret=generated_storage_secret,
        # uvicorn_logging_level='warning' # Optional: Reduce uvicorn verbosity
    )

# --- Script Entry Point ---

if __name__ == "__main__":
    # Get GUI host/port from ConfigManager for direct run
    gui_host_run = config.get_str("gui.host", "127.0.0.1")
    gui_port_run = config.get_int("gui.port", 8081)

    # Ensure app_state['llm_config'] is initialized (already done in app_state.py)
    # gui_log(f"LLM config in app_state before run: {app_state.get('llm_config')}", level="DEBUG")

    gui_log(f"Attempting to run GUI directly via main_app.py on {gui_host_run}:{gui_port_run}")
    run_gui(host=gui_host_run, port=gui_port_run)