# management_gui/app_state.py
import os
import sys
import time
import json
import logging # Using standard logging might be better long-term, but sticking to gui_log for now
from typing import Dict, Any

# Ensure the project root is in sys.path to find system_configs.config_manager
# This might be needed if app_state is run directly or imported early
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

try:
    from system_configs.config_manager import config # Import the global config instance
except ImportError as e:
    print(f"CRITICAL ERROR: Failed to import config_manager: {e}. Check PYTHONPATH.", file=sys.stderr)
    # Fallback or raise? For now, provide dummy config accessors to avoid immediate crash
    class DummyConfig:
        def get_project_root(self): return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        def get_path(self, key, default): return os.path.join(self.get_project_root(), default)
        def get_str(self, key, default=""): return default
        def get_int(self, key, default=0): return default
        def get_float(self, key, default=0.0): return default
    config = DummyConfig()
    print("WARNING: Using dummy config due to import error.", file=sys.stderr)


# --- Paths and URLs from ConfigManager ---
PROJECT_ROOT = config.get_project_root()
LOGS_DIR = config.get_path("global.logs_dir", "logs") # Uses PROJECT_ROOT implicitly

# A2A Server URL
# Priority: gui.a2a_server_url in config.toml > construct from a2a_server section > hardcoded default
explicit_a2a_url = config.get_str("gui.a2a_server_url")
if explicit_a2a_url:
    A2A_SERVER_URL = explicit_a2a_url
else:
    a2a_host = config.get_str("a2a_server.host", "127.0.0.1")
    a2a_port = config.get_int("a2a_server.port", 8080)
    A2A_SERVER_URL = f"http://{a2a_host}:{a2a_port}"

GUI_LOG_FILE = os.path.join(LOGS_DIR, "management_gui.log")

# --- Configuration for Polling Intervals from ConfigManager ---
DEFAULT_CMD_POLL_INTERVAL = 10.0
DEFAULT_STATUS_POLL_INTERVAL = 30.0
DEFAULT_MINION_LIST_POLL_INTERVAL = 60.0

GUI_COMMANDER_MESSAGE_POLLING_INTERVAL_SECONDS = config.get_float(
    "gui.commander_message_polling_interval", DEFAULT_CMD_POLL_INTERVAL
)
GUI_SERVER_STATUS_POLLING_INTERVAL_SECONDS = config.get_float(
    "gui.server_status_polling_interval", DEFAULT_STATUS_POLL_INTERVAL
)
GUI_MINION_LIST_POLLING_INTERVAL_SECONDS = config.get_float(
    "gui.minion_list_polling_interval", DEFAULT_MINION_LIST_POLL_INTERVAL
)

# Validate positive polling intervals
if GUI_COMMANDER_MESSAGE_POLLING_INTERVAL_SECONDS <= 0:
    print(f"WARNING: Invalid gui.commander_message_polling_interval. Using default: {DEFAULT_CMD_POLL_INTERVAL}s.", file=sys.stderr)
    GUI_COMMANDER_MESSAGE_POLLING_INTERVAL_SECONDS = DEFAULT_CMD_POLL_INTERVAL
if GUI_SERVER_STATUS_POLLING_INTERVAL_SECONDS <= 0:
    print(f"WARNING: Invalid gui.server_status_polling_interval. Using default: {DEFAULT_STATUS_POLL_INTERVAL}s.", file=sys.stderr)
    GUI_SERVER_STATUS_POLLING_INTERVAL_SECONDS = DEFAULT_STATUS_POLL_INTERVAL
if GUI_MINION_LIST_POLLING_INTERVAL_SECONDS <= 0:
    print(f"WARNING: Invalid gui.minion_list_polling_interval. Using default: {DEFAULT_MINION_LIST_POLL_INTERVAL}s.", file=sys.stderr)
    GUI_MINION_LIST_POLLING_INTERVAL_SECONDS = DEFAULT_MINION_LIST_POLL_INTERVAL

# --- Constants ---
GUI_COMMANDER_ID = "STEVEN_GUI_COMMANDER"

# --- Logging ---
# Ensure logs directory exists before trying to write
try:
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
except OSError as e:
    print(f"ERROR: Could not create logs directory '{LOGS_DIR}': {e}", file=sys.stderr)

def gui_log(message, level="INFO"):
    """Basic logger for the GUI application state and related logic."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    log_entry = f"{timestamp} - GUI_STATE - {level} - {message}"
    print(log_entry) # Also print to console
    try:
        with open(GUI_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    except Exception as e:
        print(f"ERROR: Failed to write to GUI log file '{GUI_LOG_FILE}': {e}", file=sys.stderr)

gui_log(f"GUI State using A2A Server URL: {A2A_SERVER_URL}")
gui_log(f"GUI State using commander message polling interval: {GUI_COMMANDER_MESSAGE_POLLING_INTERVAL_SECONDS} seconds.")
gui_log(f"GUI State using server status polling interval: {GUI_SERVER_STATUS_POLLING_INTERVAL_SECONDS} seconds.")
gui_log(f"GUI State using minion list polling interval: {GUI_MINION_LIST_POLLING_INTERVAL_SECONDS} seconds.")

# --- App State Dictionary ---
# Centralized application state. Other modules will import this dictionary.
app_state: Dict[str, Any] = {
    "minions": {}, # { "minion_id": {"status": "Idle", "last_seen": ..., "personality": ...} }
    "a2a_server_status": "Unknown",
    "system_logs": [], # For displaying recent log entries (Consider moving if becomes complex)
    "last_broadcast_command": "",
    "chat_messages": [], # To store chat message dictionaries (Consider moving to chat module later)
    "last_commander_reply_timestamp": 0.0, # Tracks the timestamp of the last fetched reply for GUI_COMMANDER_ID
    "chat_sessions": {},  # session_id -> {id, type: "individual"|"group", agents: [], created_at, messages: [], status} (Consider moving to chat module later)
    "active_chat_session_id": None, # (Consider moving to chat module later)
    "collaborative_tasks": {}, # task_id -> {task_id, status, coordinator_id, description, message, subtasks: {}, created_at, last_updated, completed_at, results} (Consider moving to task module later)
    "pending_collab_tasks": {}, # temp_task_id -> {"description": ..., "coordinator_id": ..., "submitted_at": ...} (Consider moving to task module later)
    "collaborative_tasks_container_ref": None, # UI Reference (Should not be here long-term)
    "active_collaborative_task_id": None, # UI State (Should not be here long-term)
    "llm_config": {}, # Populated from main config on startup
    "available_mcp_tools": [], # To be populated from MCP service
    "minion_detail_container_ref": {}, # UI Reference (Should not be here long-term)
    "debug_info": {}, # {minion_id: {state_data: ..., conversation_history: ...}} (Consider moving to debug module)
    "ui_elements": {}, # References to specific UI elements for updates (e.g., status label) (Should not be here long-term)
    "chat_container_ref": None, # UI Reference (Should not be here long-term)
    "collaborative_task_detail_container_ref": None, # UI Reference (Should not be here long-term)
}

# Initialize LLM config from main config if not already set (e.g., by main_app)
# This provides defaults if app_state is imported before main_app runs fully.
if not app_state.get("llm_config"):
    app_state["llm_config"] = {
        "model": config.get_str("llm.model", config.get_str("llm.default_model", "gemini-2.5-pro")),
        "temperature": config.get_float("llm.temperature", 0.7),
        "max_tokens": config.get_int("llm.max_tokens", 8192),
        "top_p": config.get_float("llm.top_p", 0.95),
        "top_k": config.get_int("llm.top_k", 40),
        "presence_penalty": config.get_float("llm.presence_penalty", 0.0),
        "frequency_penalty": config.get_float("llm.frequency_penalty", 0.0)
    }
    gui_log(f"Initialized app_state['llm_config'] from global config: {app_state['llm_config']}", level="DEBUG")

gui_log("Application state module initialized.")