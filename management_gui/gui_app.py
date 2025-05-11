import os
import time
import sys
import json
import uuid
import asyncio
import urllib.parse
from nicegui import ui, app, Client
import requests
from datetime import datetime, timezone

# Ensure the project root is in sys.path to find system_configs.config_manager
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

from system_configs.config_manager import config # Import the global config instance

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


# Basic logger for the GUI
# NiceGUI has its own logging, this is for app-specific logic
def gui_log(message, level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    log_entry = f"{timestamp} - GUI_APP - {level} - {message}"
    print(log_entry) # Also print to console where NiceGUI runs
    with open(GUI_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

gui_log(f"GUI using commander message polling interval: {GUI_COMMANDER_MESSAGE_POLLING_INTERVAL_SECONDS} seconds.")

# --- App State (simplified for V1) ---
# In a real app, this might come from a more robust state management solution
# or by querying the A2A server / Minions directly.
# For V1, we'll simulate some state and provide ways to interact.
app_state = {
    "minions": {}, # { "minion_id": {"status": "Idle", "last_seen": ..., "personality": ...} }
    "a2a_server_status": "Unknown",
    "system_logs": [], # For displaying recent log entries
    "last_broadcast_command": "",
    "chat_messages": [], # To store chat message dictionaries
    "last_commander_reply_timestamp": 0.0, # Tracks the timestamp of the last fetched reply for STEVEN_GUI_COMMANDER
    "chat_sessions": {},  # session_id -> {id, type: "individual"|"group", agents: [], created_at, messages: [], status}
    "active_chat_session_id": None,
    "collaborative_tasks": {}, # task_id -> {task_id, status, coordinator_id, description, message, subtasks: {}, created_at, last_updated, completed_at, results}
    "pending_collab_tasks": {}, # temp_task_id -> {"description": ..., "coordinator_id": ..., "submitted_at": ...}
    "collaborative_tasks_container_ref": None, # Reference to the UI container for collaborative tasks
    "active_collaborative_task_id": None, # For detailed view
    # Potentially add keys for LLM config and tool list if fetched globally
    "llm_config": {"model": "gemini-2.5-pro", "temperature": 0.7, "max_tokens": 8192, "top_p": 0.95, "top_k": 40, "presence_penalty":0, "frequency_penalty":0 }, # Load from config
    "available_mcp_tools": [], # To be populated
    "minion_detail_container_ref": {}, # For storing references to minion detail page containers
}

# --- UI Styling Helpers ---

# Basic mapping for Quasar color names (used in classes like bg-*) to HEX codes for SVG
# This can be expanded as needed.
QUASAR_COLOR_TO_HEX = {
    "blue-2": "#BBDEFB", "blue-5": "#2196F3",
    "red-2": "#FFCDD2", "red-5": "#F44336",
    "green-2": "#C8E6C9", "green-5": "#4CAF50",
    "purple-2": "#E1BEE7", "purple-5": "#9C27B0",
    "orange-2": "#FFE0B2", "orange-5": "#FF9800",
    "teal-2": "#B2DFDB", "teal-5": "#009688",
    "pink-2": "#F8BBD0", "pink-5": "#E91E63",
    "grey-3": "#e0e0e0", "grey-5": "#9e9e9e", # For default/unknown minions
    "black": "#000000",
    "white": "#FFFFFF",
}

MINION_STYLE_PALETTE = [
    {"bubble_class": "bg-red-2 text-black", "avatar_color_name": "red-5"},
    {"bubble_class": "bg-green-2 text-black", "avatar_color_name": "green-5"},
    {"bubble_class": "bg-purple-2 text-black", "avatar_color_name": "purple-5"},
    {"bubble_class": "bg-orange-2 text-black", "avatar_color_name": "orange-5"},
    {"bubble_class": "bg-teal-2 text-black", "avatar_color_name": "teal-5"},
    {"bubble_class": "bg-pink-2 text-black", "avatar_color_name": "pink-5"},
]
# Store assigned styles to keep them consistent for minions during a session
_minion_styles_cache = {}
_next_minion_style_index = 0

def get_sender_style(sender_id: str):
    global _next_minion_style_index
    if sender_id == "STEVEN_GUI_COMMANDER":
        return {
            "avatar_letter": "S",
            "bubble_class": "bg-blue-2 text-black",
            "avatar_color_name": "blue-5",
            "sender_display_name": "STEVEN"
        }

    # Check app_state for the minion's display name
    minion_info = app_state["minions"].get(sender_id)
    
    # Use the core friendly name (name_display) for avatar logic
    core_display_name = sender_id # Default to sender_id
    if minion_info and minion_info.get("name_display"):
        core_display_name = minion_info["name_display"]

    # Use the formatted name for display in chat bubbles
    formatted_sender_name = get_formatted_minion_display(sender_id)

    if sender_id not in _minion_styles_cache:
        style_to_assign = MINION_STYLE_PALETTE[_next_minion_style_index % len(MINION_STYLE_PALETTE)]
        _minion_styles_cache[sender_id] = style_to_assign
        _next_minion_style_index += 1
    
    assigned_style = _minion_styles_cache[sender_id]
    
    avatar_letter = core_display_name[0].upper()
    # More robust way to get first char if core_display_name could be empty
    if not core_display_name:
        avatar_letter = sender_id[0].upper() if sender_id else "?"

    return {
        "avatar_letter": avatar_letter,
        "bubble_class": assigned_style["bubble_class"],
        "avatar_color_name": assigned_style["avatar_color_name"],
        "sender_display_name": formatted_sender_name
    }

def generate_circular_avatar_svg(letter: str, avatar_bg_color_name: str, text_color_hex: str = "#FFFFFF", size: int = 32) -> str:
    actual_bg_hex_color = QUASAR_COLOR_TO_HEX.get(avatar_bg_color_name, QUASAR_COLOR_TO_HEX.get("grey-5", "#9e9e9e"))
    
    svg_content = f'''
<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <circle cx="{size/2}" cy="{size/2}" r="{size/2}" fill="{actual_bg_hex_color}"/>
  <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
        font-family="sans-serif" font-weight="bold" font-size="{size*0.55}px" fill="{text_color_hex}">
    {letter}
  </text>
</svg>
    '''.strip()
    return f"data:image/svg+xml;utf8,{urllib.parse.quote(svg_content)}"

# --- Helper function to get formatted minion display name ---
def get_formatted_minion_display(minion_id: str) -> str:
    minion_data = app_state["minions"].get(minion_id)
    if minion_data:
        # name_display is already the prioritized user_facing_name, agent_card.name, or minion_id
        name_display = minion_data.get("name_display", minion_id) # Fallback to minion_id if key missing
        
        # If name_display is not the same as minion_id (meaning it's a friendly name)
        if name_display and name_display != minion_id:
            return f"{name_display} ({minion_id})"
        return name_display # This will be minion_id if it was the only name, or if name_display was None/empty
    return minion_id # Fallback if minion_id not in app_state or minion_data is None

# --- Helper Functions to Interact with A2A Server/Minions ---
# These are placeholders and need actual implementation based on A2A server API
async def fetch_a2a_server_status():
    gui_log("Fetching A2A server status...")
    current_status_for_state = "Unknown" # Default before fetch
    try:
        # Assuming A2A server has a /status or /health endpoint
        response = await asyncio.to_thread(requests.get, f"{A2A_SERVER_URL}/status", timeout=5)
        if response.status_code == 200:
            current_status_for_state = "Online"
            gui_log("A2A Server is Online.")
        else:
            current_status_for_state = f"Error: {response.status_code}"
            gui_log(f"A2A Server status error: {response.status_code}", level="ERROR")
    except requests.exceptions.RequestException as e:
        current_status_for_state = "Offline/Error"
        gui_log(f"Failed to connect to A2A server: {e}", level="ERROR")
        if ui.context.client: # Check if client context is available for ui.notify
            ui.notify(f"A2A Connection Error: {e}", type='negative', position='top-right')
    
    app_state["a2a_server_status"] = current_status_for_state # Update app_state

    # Now update the UI using the reference from app_state
    status_label_ref = app_state.get('ui_elements', {}).get('a2a_status_label')
    if status_label_ref:
        try:
            status_label_ref.set_text(f"A2A Server: {app_state['a2a_server_status']}")
        except Exception as e_ui: # Catch errors specific to UI update
            gui_log(f"Error updating status_label UI element: {e_ui}", level="ERROR")
            # Attempt to set a fallback text if the label is partially broken but accessible
            try:
                # Ensure app_state reflects this UI update issue if it's critical
                # app_state['a2a_server_status'] = "UI Update Error" # This might overwrite actual server status
                status_label_ref.set_text(f"A2A Server: UI Error") # Simpler UI error text
            except Exception as e_ui_fallback:
                gui_log(f"Failed to set fallback error text on status_label: {e_ui_fallback}", level="ERROR")
    else:
        gui_log("a2a_status_label UI element not found in app_state for update.", level="WARNING")


async def fetch_registered_minions():
    gui_log("Fetching registered minions from A2A server...")
    try:
        # Assuming A2A server has an /agents endpoint
        response = await asyncio.to_thread(requests.get, f"{A2A_SERVER_URL}/agents", timeout=5)
        if response.status_code == 200:
            agents_data = response.json() # Expects a list of agent cards
            # BIAS_ACTION: Clear old state before repopulating to avoid stale entries.
            app_state["minions"].clear()
            for agent_card in agents_data:
                agent_id_key = agent_card.get("id")
                if not agent_id_key:
                    agent_id_key = agent_card.get("name")  # Use name as fallback
                    if agent_id_key:
                        # Add missing fields expected by GUI
                        agent_card["id"] = agent_id_key
                        gui_log(f"Adapted agent: using name '{agent_id_key}' as ID", level="INFO")
                    else:
                        gui_log(f"Skipping agent card due to missing 'id' and 'name': {str(agent_card)[:100]}", level="WARNING")
                        continue
                
                # Prioritize "user_facing_name", then "name", then "id"
                user_facing_name = agent_card.get("user_facing_name")
                composite_name = agent_card.get("name")
                
                name_to_display = agent_id_key # Default to id
                if user_facing_name:
                    name_to_display = user_facing_name
                elif composite_name: # Fallback to composite name if user_facing_name is missing
                    name_to_display = composite_name
                
                # Ensure all relevant fields from the design doc are considered for app_state["minions"]
                # The design doc mentions: "name_display": "StrategistPrime"
                # And "id": "minion_uuid_1"
                # And "personality": "Analytical, Calm, Decisive"
                # And "description": "..."
                # And "status": "Idle"

                app_state["minions"][agent_id_key] = {
                    "id": agent_id_key, # Store the ID explicitly as per design doc example
                    "name_display": name_to_display, # This is the primary display name
                    "status": agent_card.get("status", "Unknown"),
                    "description": agent_card.get("description", "N/A"),
                    "personality": agent_card.get("personality_traits", "N/A"), # From agent_card.personality_traits
                    "capabilities": agent_card.get("capabilities", {}), # This should be a dict as per M2M doc
                    "skills": agent_card.get("skills", []), # Fallback, ideally skills are under capabilities
                    "last_seen": datetime.now(timezone.utc).isoformat()
                }
            gui_log(f"Fetched {len(app_state['minions'])} minions. GUI state uses 'name_display'.")
            update_minion_display() # This will now use the filter text if minion_filter_input is initialized
        else:
            gui_log(f"Failed to fetch minions, A2A server status: {response.status_code}", level="ERROR")
    except requests.exceptions.RequestException as e:
        gui_log(f"Error fetching minions: {e}", level="ERROR")
        if ui.context.client: # Check if client context is available for ui.notify
            ui.notify(f"Fetch Minions Connection Error: {e}", type='negative', position='top-right')
    except json.JSONDecodeError as e:
        gui_log(f"Error decoding minions response from A2A server: {e}", level="ERROR")


async def broadcast_message_to_all_minions(client: Client, message_content_str: str):
    # This is a simplified broadcast. A real A2A server might have a broadcast endpoint.
    # Or, we iterate through known minions and send one by one.
    # For V1, we assume a conceptual broadcast or sending to a "group" if A2A server supports.
    # If not, this needs to send individual messages.
    
    # Codex Omega Decision: For V1 GUI, this will attempt to send a message to each *known* minion.
    # This is not a true broadcast via the A2A server itself unless the server supports it.
    # The "ice breaker" task will use this.
    
    gui_log(f"Attempting to broadcast message: '{message_content_str[:50]}...'")
    app_state["last_broadcast_command"] = message_content_str

    # Log this broadcast to the chat_messages state
    current_timestamp_float = time.time() # Use Unix timestamp (float)
    chat_message = {
        "timestamp": current_timestamp_float,
        "sender_id": "STEVEN_GUI_COMMANDER", # Consistent ID for internal state
        "type": "directive", # Consistent type field
        "content": message_content_str
    }
    app_state["chat_messages"].append(chat_message)
    if chat_log_area: # Ensure chat_log_area is initialized
        update_chat_log_display()
    else:
        gui_log("chat_log_area not ready for update during broadcast.", level="WARNING")

    broadcast_status_area.clear() # Clear previous status

    if not app_state["minions"]:
        with broadcast_status_area:
            ui.label("No minions currently registered to broadcast to.").style('color: orange;')
        gui_log("Broadcast failed: No minions registered.", level="WARNING")
        return

    # Construct a generic message payload. Minions will parse this.
    # This is a command from Steven (via GUI) to all Minions.
    message_payload = {
        "sender_id": "STEVEN_GUI_COMMANDER", # Special ID for GUI commands
        "content": message_content_str,
        "message_type": "user_broadcast_directive", # Minions should recognize this type
        "timestamp": time.time()
    }
    
    success_count = 0
    fail_count = 0

    # BIAS_ACTION: Iterating and sending individually is more robust than a non-existent broadcast endpoint.
    for minion_id in app_state["minions"].keys():
        endpoint = f"{A2A_SERVER_URL}/agents/{minion_id}/messages"
        try:
            # This internal call to send_a2a_message_to_minion was for a generic POST.
            # However, the actual broadcast logic here is custom.
            # The ui.notify calls that caused issues were in the shared send_a2a_message_to_minion.
            # This broadcast function builds its own UI updates in broadcast_status_area.
            # For now, I will assume this function's direct UI updates are safe as they are within its context.
            # If this also causes "slot stack empty", it will need similar client passing for its ui.label calls.
            # The critical error was from ui.notify in the *shared* helper.
            # This function does not call the shared send_a2a_message_to_minion helper.
            # It implements its own direct requests.post.
            # Therefore, no change is needed here regarding passing `client` to a helper it doesn't use.
            # The following is the original logic for sending, which does not use the shared helper.
            response = await asyncio.to_thread(
                requests.post, endpoint, json=message_payload, timeout=10
            )
            if response.status_code in [200, 201, 202, 204]:
                gui_log(f"Message sent to {minion_id} successfully.")
                with broadcast_status_area: # This UI update should be fine as it's in the context of the broadcast_status_area
                    ui.label(f"Sent to {get_formatted_minion_display(minion_id)}: OK").style('color: green;')
                success_count += 1
            else:
                gui_log(f"Failed to send message to {minion_id}. Status: {response.status_code}, Resp: {response.text[:100]}", level="ERROR")
                with broadcast_status_area:
                    ui.label(f"Sent to {get_formatted_minion_display(minion_id)}: FAIL ({response.status_code})").style('color: red;')
                fail_count += 1
        except requests.exceptions.RequestException as e:
            gui_log(f"Exception sending message to {minion_id}: {e}", level="ERROR")
            with broadcast_status_area:
                 ui.label(f"Sent to {get_formatted_minion_display(minion_id)}: EXCEPTION").style('color: red;')
            fail_count +=1
        await asyncio.sleep(0.1) # Small delay between sends

    final_status_msg = f"Broadcast attempt complete. Success: {success_count}, Failed: {fail_count}."
    gui_log(final_status_msg)
    with broadcast_status_area:
        ui.label(final_status_msg).style('font-weight: bold;')
    last_broadcast_label.set_text(f"Last Broadcast: {app_state['last_broadcast_command'][:60]}...")


async def fetch_commander_messages():
    processed_messages = [] # Initialize here
    gui_log("Fetching commander messages for STEVEN_GUI_COMMANDER...")
    agent_id = "STEVEN_GUI_COMMANDER"
    endpoint = f"{A2A_SERVER_URL}/agents/{agent_id}/messages"
    
    try:
        response = await asyncio.to_thread(requests.get, endpoint, timeout=10)
        if response.status_code == 200:
            messages_data = response.json()
            if not messages_data:
                # gui_log("No new messages for STEVEN_GUI_COMMANDER.") # Can be noisy
                return

            last_known_reply_ts = app_state.get("last_commander_reply_timestamp", 0.0)
            # processed_messages is now initialized at the function start
            latest_message_ts_in_batch = last_known_reply_ts

            for msg_data in messages_data:
                msg_timestamp_raw = msg_data.get('timestamp', time.time())
                msg_timestamp_float = 0.0

                if isinstance(msg_timestamp_raw, (int, float)):
                    msg_timestamp_float = float(msg_timestamp_raw)
                elif isinstance(msg_timestamp_raw, str):
                    try:
                        # Try parsing as a float string first (e.g., "1622548800.0")
                        msg_timestamp_float = float(msg_timestamp_raw)
                    except ValueError:
                        try:
                            # Then try parsing as ISO 8601 datetime string
                            ts_to_parse = msg_timestamp_raw
                            if ts_to_parse.endswith("Z"):
                                ts_to_parse = ts_to_parse[:-1] + "+00:00"
                            msg_timestamp_float = datetime.fromisoformat(ts_to_parse).timestamp()
                        except ValueError:
                            gui_log(f"Could not parse timestamp string: '{msg_timestamp_raw}'. Using current time.", level="WARNING")
                            msg_timestamp_float = time.time() # Fallback
                else:
                    gui_log(f"Unknown timestamp format: {msg_timestamp_raw}. Using current time.", level="WARNING")
                    msg_timestamp_float = time.time() # Fallback

                if msg_timestamp_float > last_known_reply_ts:
                    message_content = msg_data.get('content', '')
                    # Handle if content itself is a dict (e.g. from some agent responses)
                    if isinstance(message_content, dict):
                        # Attempt to extract a 'payload' or 'text' field, otherwise stringify
                        if 'payload' in message_content:
                            message_content = message_content['payload']
                        elif 'text' in message_content:
                            message_content = message_content['text']
                        else:
                            message_content = json.dumps(message_content) # Stringify the dict
                    
                    if not isinstance(message_content, str): # Ensure it's a string for display
                        message_content = str(message_content)

                    new_message = {
                        'sender_id': msg_data.get('sender_id', 'UnknownMinion'), # Standardized key
                        'content': message_content,
                        'timestamp': msg_timestamp_float,
                        'type': 'reply'
                    }
                    processed_messages.append(new_message)
                    if msg_timestamp_float > latest_message_ts_in_batch:
                        latest_message_ts_in_batch = msg_timestamp_float
            
            if processed_messages:
                processed_messages.sort(key=lambda m: m['timestamp']) # Sort batch by timestamp
                app_state['chat_messages'].extend(processed_messages)
                app_state["last_commander_reply_timestamp"] = latest_message_ts_in_batch
                gui_log(f"Fetched and processed {len(processed_messages)} new messages for {agent_id}.")
                if chat_log_area:
                    update_chat_log_display()
            # else:
                # gui_log(f"No messages newer than {last_known_reply_ts} for {agent_id}.") # Can be noisy
        elif response.status_code == 404:
            gui_log(f"No messages found for {agent_id} (404). This might be normal.", level="INFO")
        else:
            gui_log(f"Failed to fetch messages for {agent_id}, A2A server status: {response.status_code}, Response: {response.text[:100]}", level="ERROR")
    except requests.exceptions.RequestException as e:
        gui_log(f"Error fetching messages for {agent_id}: {e}", level="ERROR")
        if ui.context.client: # Check if client context is available for ui.notify
            ui.notify(f"Commander Messages Connection Error: {e}", type='negative', position='top-right')
    except json.JSONDecodeError as e:
        gui_log(f"Error decoding messages JSON for {agent_id}: {e}", level="ERROR")
    except Exception as e:
        gui_log(f"Unexpected error processing messages for {agent_id}: {e}", level="CRITICAL")

    # After processing all messages in the batch, refresh the minion display if any state changed
    if processed_messages: # Check if any messages led to state changes that require UI update
        # This is a good place to call update_minion_display if states were changed by messages
        # For now, minion status updates are handled by fetch_registered_minions polling or direct state changes.
        # If minion_state_update messages are processed here and change app_state["minions"][id]["status"],
        # then update_minion_display() should be called.
        
        # Let's add specific handling for control messages and state updates
        needs_minion_display_update = False
        for msg_data in messages_data: # Re-iterate or store parsed messages if needed
            parsed_content = {}
            if isinstance(msg_data.get('content'), str):
                try:
                    parsed_content = json.loads(msg_data.get('content', '{}'))
                except json.JSONDecodeError:
                    parsed_content = {'raw_content': msg_data.get('content')} # Keep raw if not JSON
            elif isinstance(msg_data.get('content'), dict):
                parsed_content = msg_data.get('content')

            msg_type = parsed_content.get('message_type', msg_data.get('type')) # Check content first, then outer
            if not msg_type and 'original_message_type' in parsed_content: # For some wrapped messages
                 msg_type = parsed_content.get('original_message_type')


            # Standardize minion_id extraction
            minion_id_from_msg = parsed_content.get('minion_id', msg_data.get('sender_id'))
            if not minion_id_from_msg and 'source_minion_id' in parsed_content:
                minion_id_from_msg = parsed_content.get('source_minion_id')


            if minion_id_from_msg and minion_id_from_msg in app_state["minions"]:
                if msg_type == 'minion_state_update':
                    new_status = parsed_content.get('new_status')
                    if new_status:
                        app_state["minions"][minion_id_from_msg]["status"] = new_status
                        gui_log(f"Minion {minion_id_from_msg} status updated to '{new_status}' via minion_state_update.")
                        needs_minion_display_update = True
                elif msg_type == 'control_pause_ack':
                    ack_status = parsed_content.get('status', 'Paused') # Default to Paused
                    app_state["minions"][minion_id_from_msg]["status"] = ack_status
                    ui.notify(f"Minion {get_formatted_minion_display(minion_id_from_msg)} confirmed: {ack_status}", type='info')
                    needs_minion_display_update = True
                elif msg_type == 'control_resume_ack':
                    ack_status = parsed_content.get('status', 'Running') # Default to Running
                    app_state["minions"][minion_id_from_msg]["status"] = ack_status
                    ui.notify(f"Minion {get_formatted_minion_display(minion_id_from_msg)} confirmed: {ack_status}", type='info')
                    needs_minion_display_update = True
                elif msg_type == 'message_to_paused_minion_ack':
                    ui.notify(f"Message acknowledged by paused minion: {get_formatted_minion_display(minion_id_from_msg)}", type='info')
                    # No status change typically, but could refresh if needed
                    needs_minion_display_update = True # Refresh to ensure consistency
                elif msg_type == "chat_response":
                    session_id = parsed_content.get("session_id")
                    if session_id and session_id in app_state.get("chat_sessions", {}):
                        session = app_state["chat_sessions"][session_id]
                        message = {
                            "sender_id": msg_data.get("sender_id", "UnknownAgent"),
                            "content": parsed_content.get("message", ""),
                            "timestamp": msg_timestamp_float, # Ensure msg_timestamp_float is defined based on existing code
                            "type": "agent_message",
                            "reasoning": parsed_content.get("reasoning")
                        }
                        session["messages"].append(message)
                        if app_state.get("active_chat_session_id") == session_id and 'chat_container_ref' in app_state: # Assuming chat_container_ref is stored
                            # This refresh logic will be fully implemented when chat_container_ref is defined.
                            # For now, ensure the structure is in place.
                            # Example: app_state['chat_container_ref'].refresh()
                            pass # Placeholder for actual refresh call
                        elif not ui.current_path or not ui.current_path.startswith("/chat/"):
                            # Ensure get_formatted_minion_display is available or define a placeholder if not yet implemented
                            minion_display_name = app_state.get("minions", {}).get(message['sender_id'], {}).get("name_display", message['sender_id'])
                            ui.notify(f"New message in chat {session_id} from {minion_display_name}", type="info")
                elif msg_type == "collaborative_task_acknowledgement":
                    task_id = parsed_content.get("task_id")
                    status = parsed_content.get("status")
                    coordinator_id = parsed_content.get("coordinator_id")
                    # Assuming 'original_request' might be part of ack or fetched separately if needed for display
                    description = parsed_content.get("original_request", app_state.get("pending_collab_tasks", {}).get(task_id, {}).get("description", "N/A"))

                    if "collaborative_tasks" not in app_state:
                        app_state["collaborative_tasks"] = {}
                    
                    app_state["collaborative_tasks"][task_id] = {
                        "task_id": task_id,
                        "status": status,
                        "coordinator_id": coordinator_id,
                        "description": description,
                        "subtasks": {},
                        "created_at": time.time(), # Or from message if available
                        "last_updated": time.time()
                    }
                    # Remove from any temporary pending state
                    if "pending_collab_tasks" in app_state and task_id in app_state["pending_collab_tasks"]:
                        del app_state["pending_collab_tasks"][task_id]

                    ui.notify(f"Task '{task_id}' acknowledged by {coordinator_id}, status: {status}", type="positive")
                    # Refresh relevant UI parts (e.g., collaborative task dashboard)
                    if 'collaborative_tasks_container_ref' in app_state:
                         # This refresh logic will be fully implemented when collaborative_tasks_container_ref is defined.
                         # For now, ensure the structure is in place.
                         # Example: app_state['collaborative_tasks_container_ref'].refresh()
                         pass # Placeholder for actual refresh call
                elif msg_type == "debug_state_response":
                    minion_id = msg_data.get("sender_id")
                    state_data = parsed_content.get("state_data", {})
                    # This requires a way to target the specific UI container for debug output
                    # For now, log or store in app_state, UI update will be part of debug UI task
                    gui_log(f"Received debug state for {minion_id}: {str(state_data)[:200]}...", level="DEBUG") # Changed to DEBUG
                    if "debug_info" not in app_state: app_state["debug_info"] = {}
                    app_state["debug_info"][minion_id] = state_data
                    # If a specific debug UI element is active and bound, it should update.
                    # Example: if app_state.get('active_debug_minion_id') == minion_id and 'debug_state_container_ref' in app_state:
                    # app_state['debug_state_container_ref'].clear()
                    # with app_state['debug_state_container_ref']:
                    # ui.json_editor({"content": {"json": state_data}})
                    # For now, ensure the structure is in place.
                    pass # Placeholder for actual refresh call
                elif msg_type == "collaborative_task_status_update":
                    task_id = parsed_content.get("collaborative_task_id")
                    subtask_id = parsed_content.get("subtask_id") # Might be null for overall task updates
                    new_status = parsed_content.get("new_status")
                    details = parsed_content.get("details", {}) # Could contain subtask_description, assigned_to, error, result snippet

                    if task_id and task_id in app_state.get("collaborative_tasks", {}):
                        task = app_state["collaborative_tasks"][task_id]
                        task["last_updated"] = time.time()

                        if subtask_id:
                            if subtask_id not in task["subtasks"]:
                                task["subtasks"][subtask_id] = {"id": subtask_id} # Initialize if new
                            task["subtasks"][subtask_id].update({
                                "status": new_status,
                                "description": details.get("description", task["subtasks"][subtask_id].get("description", "N/A")),
                                "assigned_to": details.get("assigned_to", task["subtasks"][subtask_id].get("assigned_to", "N/A")),
                                "dependencies": details.get("dependencies", task["subtasks"][subtask_id].get("dependencies", [])),
                                "success_criteria": details.get("success_criteria", task["subtasks"][subtask_id].get("success_criteria", "N/A")),
                                "result": details.get("result", task["subtasks"][subtask_id].get("result")), # Store result/error
                                "error": details.get("error", task["subtasks"][subtask_id].get("error")),
                                "last_updated": time.time()
                            })
                        else: # Overall task status update
                            task["status"] = new_status
                            if "message" in details: task["message"] = details["message"]
                        
                        # Refresh UI
                        if 'collaborative_tasks_container_ref' in app_state and app_state['collaborative_tasks_container_ref']:
                            app_state['collaborative_tasks_container_ref'].refresh()
                        if app_state.get("active_collaborative_task_id") == task_id and 'collaborative_task_detail_container_ref' in app_state and app_state['collaborative_task_detail_container_ref']:
                             app_state['collaborative_task_detail_container_ref'].refresh() # Or a more specific update function
                    else:
                        gui_log(f"Received status update for unknown collaborative task: {task_id}", level="WARNING")
                elif msg_type == "collaborative_task_completed":
                    task_id = parsed_content.get("task_id")
                    if task_id and task_id in app_state.get("collaborative_tasks", {}):
                        task = app_state["collaborative_tasks"][task_id]
                        task["status"] = parsed_content.get("final_status", "completed") # Use final_status or default to completed
                        task["results"] = parsed_content.get("results", {})
                        task["last_updated"] = parsed_content.get("completed_at_timestamp", time.time())
                        task["completed_at"] = parsed_content.get("completed_at_timestamp", time.time())
                        task["elapsed_seconds"] = parsed_content.get("elapsed_seconds")

                        ui.notify(f"Collaborative task {task_id} completed!", type="positive")
                        gui_log(f"Collaborative task {task_id} completed. Results: {str(task['results'])[:100]}...", level="INFO")

                        # Refresh relevant UI
                        if 'collaborative_tasks_container_ref' in app_state and app_state['collaborative_tasks_container_ref']:
                            app_state['collaborative_tasks_container_ref'].refresh()
                        
                        if app_state.get("active_collaborative_task_id") == task_id and \
                           'collaborative_task_detail_container_ref' in app_state and \
                           app_state['collaborative_task_detail_container_ref']:
                            app_state['collaborative_task_detail_container_ref'].refresh()
                    else:
                        gui_log(f"Received completion for unknown collaborative task: {task_id}", level="WARNING")


        if needs_minion_display_update and minion_cards_container:
            update_minion_display()


async def send_a2a_message_to_minion(client: Client, minion_id: str, message_type: str, a2a_payload: dict, notification_verb: str = "send message"):
    """
    Helper function to send a generic A2A message to a specific minion.
    `a2a_payload` should be the complete message structure expected by the minion.
    Requires the client context for notifications.
    """
    gui_log(f"Attempting to {notification_verb} to {minion_id} of type {message_type} with payload: {str(a2a_payload)[:200]}")
    endpoint = f"{A2A_SERVER_URL}/agents/{minion_id}/messages"
    
    if "sender_id" not in a2a_payload:
        a2a_payload["sender_id"] = "STEVEN_GUI_COMMANDER"
    if "timestamp" not in a2a_payload:
        a2a_payload["timestamp"] = time.time()
    if "message_type" not in a2a_payload:
        a2a_payload["message_type"] = message_type

    try:
        response = await asyncio.to_thread(
            requests.post, endpoint, json=a2a_payload, timeout=10
        )
        if response.status_code in [200, 201, 202, 204]:
            gui_log(f"Successfully initiated {notification_verb} to {minion_id} (type: {message_type}).")
            client.notify(f"Request to {notification_verb} to {get_formatted_minion_display(minion_id)} sent.", type='positive')
            return True
        else:
            error_detail = f"status code {response.status_code}"
            try: error_detail = response.json().get("details", error_detail)
            except json.JSONDecodeError: pass
            gui_log(f"Failed to {notification_verb} to {minion_id} (type: {message_type}). Status: {response.status_code}, Resp: {response.text[:100]}", level="ERROR")
            client.notify(f"Failed to {notification_verb} to {get_formatted_minion_display(minion_id)}: {error_detail}", type='negative', multi_line=True)
            return False
    except requests.exceptions.RequestException as e:
        gui_log(f"Exception during {notification_verb} to {minion_id} (type: {message_type}): {e}", level="ERROR")
        client.notify(f"Error connecting to server to {notification_verb} for {get_formatted_minion_display(minion_id)}: {e}", type='negative', multi_line=True)
        return False
    except Exception as e: # This will catch the "slot stack empty" error if it originates here
        gui_log(f"Unexpected error during {notification_verb} to {minion_id} (type: {message_type}): {e}", level="CRITICAL", exc_info=True)
        # Try to notify, but this might also fail if the context is truly lost
        try:
            client.notify(f"Unexpected error trying to {notification_verb} for {get_formatted_minion_display(minion_id)}: {str(e)[:100]}", type='negative', multi_line=True)
        except Exception as notify_e:
            gui_log(f"Failed to send notification even with client context: {notify_e}", level="CRITICAL")
        return False

async def copy_message_to_clipboard(text: str):
    # json.dumps is crucial for handling special characters in text for JavaScript
    js_command = f"navigator.clipboard.writeText({json.dumps(text)});"
    try:
        await ui.run_javascript(js_command) # Removed respond=False
        ui.notify("Copied to clipboard!", type='positive', position='top-right', timeout=2000)
    except Exception as e:
        gui_log(f"Failed to copy to clipboard: {e}", level="ERROR") # gui_log is globally available
        ui.notify("Failed to copy to clipboard.", type='negative', position='top-right', timeout=3000)

# --- Rename Minion Logic ---
async def handle_rename_minion(minion_id: str, new_name: str):
    gui_log(f"Attempting to rename minion {minion_id} to '{new_name}'")
    if not new_name or not new_name.strip():
        ui.notify("New name cannot be empty.", type='negative', position='top-right')
        gui_log("Rename failed: New name was empty.", level="WARNING")
        return

    endpoint = f"{A2A_SERVER_URL}/agents/{minion_id}/rename"
    payload = {"new_user_facing_name": new_name.strip()}

    try:
        response = await asyncio.to_thread(requests.post, endpoint, json=payload, timeout=10)
        if response.status_code == 200 or response.status_code == 204: # 204 No Content is also success
            app_state["minions"][minion_id]["name_display"] = new_name.strip()
            update_minion_display() # Refresh the minion cards
            update_chat_log_display() # Refresh chat if names are used there
            ui.notify(f"{get_formatted_minion_display(minion_id)} successfully updated.", type='positive', position='top-right')
            gui_log(f"Minion {minion_id} successfully renamed to '{new_name.strip()}'. Now displayed as {get_formatted_minion_display(minion_id)}")
        else:
            error_detail = f"status code {response.status_code}"
            try:
                error_json = response.json()
                error_detail = error_json.get("details", error_json.get("error", error_detail))
            except json.JSONDecodeError:
                pass # Keep original error_detail
            ui.notify(f"Failed to rename minion: {error_detail}", type='negative', position='top-right', multi_line=True)
            gui_log(f"Failed to rename minion {minion_id}. Server response: {response.status_code} - {response.text[:200]}", level="ERROR")
    except requests.exceptions.RequestException as e:
        ui.notify(f"Error connecting to server for rename: {e}", type='negative', position='top-right')
        gui_log(f"RequestException while renaming minion {minion_id}: {e}", level="ERROR")
    except Exception as e:
        ui.notify(f"An unexpected error occurred: {e}", type='negative', position='top-right')
        gui_log(f"Unexpected error while renaming minion {minion_id}: {e}", level="CRITICAL")


# --- Spawn Minion Logic ---
PREDEFINED_LLM_CONFIG_PROFILES = ["default", "creative_v1", "analytical_v2", "coding_assistant"]
PREDEFINED_CAPABILITIES = ["data_analysis", "reporting", "text_generation", "code_execution", "file_management", "web_browsing"]

async def handle_spawn_minion(details: dict):
    gui_log(f"BEGIN handle_spawn_minion with details: {details}") # ADDED EXTRA LOGGING
    
    user_facing_name = details.get("user_facing_name")
    minion_id_prefix = details.get("minion_id_prefix")
    llm_config_profile = details.get("llm_config_profile")
    capabilities = details.get("capabilities", [])
    config_overrides_str = details.get("config_overrides_str", "{}")

    if not user_facing_name or not user_facing_name.strip():
        ui.notify("User-Facing Name cannot be empty.", type='negative', position='top-right')
        gui_log("Spawn failed: User-Facing Name was empty.", level="WARNING")
        return

    if not llm_config_profile:
        ui.notify("LLM Config Profile must be selected.", type='negative', position='top-right')
        gui_log("Spawn failed: LLM Config Profile was not selected.", level="WARNING")
        return

    config_overrides = {}
    try:
        if config_overrides_str and config_overrides_str.strip():
            config_overrides = json.loads(config_overrides_str)
            if not isinstance(config_overrides, dict):
                ui.notify("Config Overrides must be a valid JSON object (dictionary).", type='negative', position='top-right', multi_line=True)
                gui_log("Spawn failed: Config Overrides was not a JSON object.", level="WARNING")
                return
    except json.JSONDecodeError as e:
        ui.notify(f"Invalid JSON in Config Overrides: {e}", type='negative', position='top-right', multi_line=True)
        gui_log(f"Spawn failed: Invalid JSON in Config Overrides - {e}", level="WARNING")
        return

    payload = {
        "user_facing_name": user_facing_name.strip(),
        "llm_config_profile": llm_config_profile,
        "capabilities": capabilities,
        "config_overrides": config_overrides
    }
    if minion_id_prefix and minion_id_prefix.strip():
        payload["minion_id_prefix"] = minion_id_prefix.strip()

    endpoint = f"{A2A_SERVER_URL}/spawn-minion"
    gui_log(f"Sending spawn request to {endpoint} with payload: {payload}")

    try:
        response = await asyncio.to_thread(requests.post, endpoint, json=payload, timeout=20) # Increased timeout for spawning
        if response.status_code == 200 or response.status_code == 201 or response.status_code == 202:
            # Success, response might contain new minion's ID/details
            try:
                response_data = response.json()
                new_minion_info = response_data.get("minion_id", "Unknown ID")
                ui.notify(f"Minion spawn initiated successfully! New minion: {new_minion_info}. It will appear in the list shortly.", type='positive', position='top-right', multi_line=True, timeout=5000)
                gui_log(f"Minion spawn initiated. Server response: {response_data}")
            except json.JSONDecodeError:
                ui.notify("Minion spawn initiated successfully! It will appear in the list shortly.", type='positive', position='top-right', timeout=5000)
                gui_log(f"Minion spawn initiated. Response status: {response.status_code}")
            await fetch_registered_minions() # Optionally refresh list immediately, or rely on poller
        else:
            error_detail = f"status code {response.status_code}"
            try:
                error_json = response.json()
                error_detail = error_json.get("details", error_json.get("error", error_detail))
            except json.JSONDecodeError:
                pass
            ui.notify(f"Failed to spawn minion: {error_detail}", type='negative', position='top-right', multi_line=True)
            gui_log(f"Failed to spawn minion. Server response: {response.status_code} - {response.text[:200]}", level="ERROR")
    except requests.exceptions.RequestException as e:
        ui.notify(f"Error connecting to server for spawning: {e}", type='negative', position='top-right', multi_line=True)
        gui_log(f"RequestException while spawning minion: {e}", level="ERROR")
    except Exception as e:
        ui.notify(f"An unexpected error occurred during spawn: {e}", type='negative', position='top-right', multi_line=True)
        gui_log(f"Unexpected error while spawning minion: {e}", level="CRITICAL")

def open_spawn_minion_dialog():
    with ui.dialog() as dialog, ui.card().classes('min-w-[600px]'): # Increased dialog width
        ui.label("Spawn New Minion").classes('text-h6 q-mb-md')
        
        form_data = {
            "user_facing_name": None,
            "minion_id_prefix": None,
            "llm_config_profile": None,
            "capabilities": [],
            "config_overrides_str": None
        }

        # Temporarily replace ui.form with ui.column for diagnostics
        with ui.column() as form_container: # Changed from ui.form()
            form_data["user_facing_name"] = ui.input(label="User-Facing Name*", placeholder="e.g., DataAnalystAlpha").props('outlined dense autofocus')
            form_data["minion_id_prefix"] = ui.input(label="Minion ID Prefix (Optional)", placeholder="e.g., DataAlpha").props('outlined dense')
            form_data["llm_config_profile"] = ui.select(PREDEFINED_LLM_CONFIG_PROFILES, label="LLM Config Profile*").props('outlined dense')
            
            ui.label("Capabilities (Optional)").classes('q-mt-sm text-caption')
            with ui.row().classes('q-gutter-sm'): # Checkboxes in a row for better layout
                for cap in PREDEFINED_CAPABILITIES:
                    ui.checkbox(cap, on_change=lambda checked, capability=cap: (
                        form_data["capabilities"].append(capability) if checked else form_data["capabilities"].remove(capability)
                    )).props('dense')
            
            form_data["config_overrides_str"] = ui.textarea(label="Config Overrides (JSON, Optional)",
                                                            placeholder='e.g., {"personality_traits": "Focused, Detail-oriented"}').props('outlined dense autogrow')
            
            with ui.row().classes('justify-end w-full q-mt-lg'):
                ui.button("Cancel", on_click=dialog.close, color='grey').props('flat')
                async def spawn_and_close_dialog():
                    await handle_spawn_minion({
                        "user_facing_name": form_data["user_facing_name"].value,
                        "minion_id_prefix": form_data["minion_id_prefix"].value,
                        "llm_config_profile": form_data["llm_config_profile"].value,
                        "capabilities": form_data["capabilities"], # This is already a list
                        "config_overrides_str": form_data["config_overrides_str"].value
                    })
                    dialog.close()
                ui.button("Create Minion", on_click=spawn_and_close_dialog).props('color=primary')

    dialog.open()

# --- LLM Configuration and MCP Tool Management UI (GUI-3.1, GUI-3.2) ---

# Placeholder functions for MCP Tool actions (as per spec for fetch_available_tools)
def open_configure_tool_dialog(tool_data: dict):
    ui.notify(f"Configure action for tool: {tool_data.get('tool_name', 'N/A')} (Not Implemented)")
    gui_log(f"Placeholder: Configure tool: {tool_data}")

async def toggle_tool_status(tool_data: dict, current_status: str):
    action = "Enable" if current_status != "Active" else "Disable"
    ui.notify(f"{action} action for tool: {tool_data.get('tool_name', 'N/A')} (Not Implemented)")
    gui_log(f"Placeholder: Toggle tool status for: {tool_data}, current: {current_status}")
    # In a real implementation, this would call an MCP endpoint and then refresh.

async def confirm_delete_tool(tool_data: dict):
    tool_name = tool_data.get('tool_name', 'N/A')
    with ui.dialog() as confirm_dialog, ui.card():
        ui.label(f"Are you sure you want to delete the tool '{tool_name}'?").classes('text-body1')
        with ui.row().classes('justify-end w-full q-mt-md'):
            ui.button("Cancel", on_click=confirm_dialog.close, color='grey').props('flat')
            async def do_delete():
                ui.notify(f"Delete action for tool: {tool_name} (Not Implemented)")
                gui_log(f"Placeholder: Delete tool: {tool_data}")
                confirm_dialog.close()
                # In a real implementation, this would call an MCP endpoint and then refresh.
            ui.button("Delete", on_click=do_delete, color='red')
    confirm_dialog.open()

# GUI-3.1: LLM Configuration Interface
def create_model_config_ui(client: Client): # Added client
    with ui.card().classes('w-full q-mb-md'):
        with ui.card_section():
            ui.label("LLM Configuration").classes('text-h6')
        
        with ui.card_section():
            available_models = [
                "gemini-2.5-pro", "gemini-2.5-flash",
                "gemini-1.5-pro", "gemini-1.5-flash",
                "claude-3-opus", "claude-3-sonnet", "gpt-4", "gpt-3.5-turbo"
            ]
            
            # Read initial values from the global config object
            # Fallback to app_state defaults if config keys are missing, or use hardcoded defaults from spec
            initial_llm_config = app_state.get("llm_config", {})

            model_select = ui.select(
                available_models,
                label="Default LLM Model",
                value=config.get_str("llm.model", initial_llm_config.get("model", "gemini-2.5-pro"))
            ).props('outlined dense')
            
            temperature = ui.number(
                "Temperature",
                value=config.get_float("llm.temperature", initial_llm_config.get("temperature", 0.7)),
                min=0, max=2, step=0.01 # Max 2 for some models
            ).props('outlined dense')
            
            max_tokens = ui.number(
                "Max Output Tokens",
                value=config.get_int("llm.max_tokens", initial_llm_config.get("max_tokens", 8192)),
                min=1, max=32768, format='%.0f'
            ).props('outlined dense')
            
            with ui.expansion("Advanced Parameters").classes('w-full q-mt-md'):
                top_p = ui.number("Top-p", value=config.get_float("llm.top_p", initial_llm_config.get("top_p", 0.95)), min=0, max=1, step=0.01).props('outlined dense')
                top_k = ui.number("Top-k", value=config.get_int("llm.top_k", initial_llm_config.get("top_k", 40)), min=0, max=100, format='%.0f').props('outlined dense') # Top-K can be 0 for some
                presence_penalty = ui.number("Presence Penalty", value=config.get_float("llm.presence_penalty", initial_llm_config.get("presence_penalty", 0.0)), min=-2, max=2, step=0.01).props('outlined dense')
                frequency_penalty = ui.number("Frequency Penalty", value=config.get_float("llm.frequency_penalty", initial_llm_config.get("frequency_penalty", 0.0)), min=-2, max=2, step=0.01).props('outlined dense')
            
            save_llm_button = ui.button("Save LLM Configuration", on_click=None).props('color=primary q-mt-md')
            save_llm_button.on('click', lambda: save_llm_config(
                client, # Pass client
                {
                    "model": model_select.value,
                    "temperature": temperature.value,
                "max_tokens": int(max_tokens.value) if max_tokens.value is not None else None,
                "top_p": top_p.value,
                "top_k": int(top_k.value) if top_k.value is not None else None,
                    "presence_penalty": presence_penalty.value,
                    "frequency_penalty": frequency_penalty.value
                },
                save_llm_button
            ))

async def save_llm_config(client: Client, config_data: dict, button_ref: ui.button): # Added client
    original_button_text = button_ref.text
    button_ref.props("loading=true icon=none")
    button_ref.text = "Saving..."
    gui_log(f"Saving LLM configuration: {config_data}", level="INFO")
    try:
        # Update app_state (local GUI view of config)
        current_app_state_llm_config = app_state.get("llm_config", {})
        current_app_state_llm_config.update(config_data)
        app_state["llm_config"] = current_app_state_llm_config
        gui_log(f"Updated app_state['llm_config']: {app_state['llm_config']}", level="DEBUG")

        # Attempt to update system config (in-memory global config object)
        for key, value in config_data.items():
            config_path = f"llm.{key}"
            try:
                if hasattr(config, 'set_value'):
                    config.set_value(config_path, value)
                    gui_log(f"Set in-memory config '{config_path}' to '{value}'", level="DEBUG")
                elif hasattr(config, '_config_data'):
                    keys = config_path.split('.')
                    cfg_ref = config._config_data
                    for k_idx, k_val in enumerate(keys[:-1]):
                        cfg_ref = cfg_ref.setdefault(k_val, {})
                    cfg_ref[keys[-1]] = value
                    gui_log(f"Set in-memory config (direct) '{config_path}' to '{value}'", level="DEBUG")
                else:
                    gui_log(f"Config object does not have 'set_value' or known way to update '{config_path}'. Skipping system config update for this key.", level="WARNING")
            except Exception as e_cfg_set:
                gui_log(f"Error trying to set system config for {config_path}: {e_cfg_set}", level="ERROR")
                # ui.notify(f"Error applying setting for '{config_path}': {e_cfg_set}", type="warning") # Optional: notify per-key error
        
        # Update active minions with new settings
        if app_state.get("minions"):
            gui_log(f"Sending LLM config update to {len(app_state['minions'])} minions.", level="INFO")
            tasks = [
                send_a2a_message_to_minion( # This call needs client
                    client=client,
                    minion_id=minion_id,
                    message_type="update_llm_config", # Corrected: message_type
                    a2a_payload={"new_config": config_data}, # Corrected: a2a_payload
                    notification_verb="update LLM configuration"
                )
                for minion_id in app_state["minions"]
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_sends = sum(1 for r in results if r is True)
            failed_sends = len(results) - success_sends
            if failed_sends > 0:
                gui_log(f"{failed_sends} errors while sending LLM config to minions.", level="WARNING")
                client.notify(f"LLM config saved. Errors sending to {failed_sends} minions. Check logs.", type="warning", multi_line=True)
            elif success_sends > 0 :
                 client.notify(f"LLM configuration updated and sent to {success_sends} minions.", type="positive")
            else:
                 client.notify("LLM configuration updated. No minions to send to or all sends failed.", type="info")
        else: # This else belongs to 'if app_state.get("minions")' and should be inside the try block
            gui_log("No active minions to send LLM config update to.", level="INFO")
            client.notify("LLM configuration updated. No active minions to notify.", type="positive")
            
    except Exception as e:
        gui_log(f"Critical error in save_llm_config: {e}", level="ERROR", exc_info=True) # Added exc_info
        client.notify(f"An unexpected error occurred while saving LLM configuration: {e}", type="negative", multi_line=True)
    finally:
        button_ref.props("loading=false")
        button_ref.text = original_button_text
        # Re-add icon if it was removed

# GUI-3.2: MCP Tool Management Interface
_tool_management_tools_container_ref = None # To hold the ui.element for refreshing

def create_tool_management_ui(client: Client): # Added client
    global _tool_management_tools_container_ref
    with ui.card().classes('w-full q-mb-md'):
        with ui.card_section():
            ui.label("MCP Tool Management").classes('text-h6')
        
        # Container for tools list - will be populated by fetch_available_tools
        _tool_management_tools_container_ref = ui.card_section().classes('q-pt-none') # No top padding
        
        with ui.card_actions().classes('justify-start q-gutter-sm'): # Actions at the bottom
            ui.button("Refresh Available Tools", icon="refresh", on_click=lambda: fetch_available_tools(client, _tool_management_tools_container_ref)).props('outline') # Pass client
            ui.button("Add New Tool", icon="add", on_click=lambda: open_add_tool_dialog(client), color="primary") # Pass client
    
    if _tool_management_tools_container_ref:
         fetch_available_tools(client, _tool_management_tools_container_ref) # Call initial fetch, pass client
    else:
        gui_log("Tool management container not ready for initial fetch.", level="WARNING")


async def fetch_available_tools(client: Client, container: ui.element): # Added client
    if not container:
        gui_log("fetch_available_tools called with no container.", level="ERROR")
        client.notify("UI error: Tool display container not found.", type="negative") # Use client.notify
        return
    
    container.clear()
    with container: # Show spinner
        ui.spinner(size='lg').classes('self-center q-my-md') # Centered spinner
    
    gui_log("Fetching available MCP tools...", level="INFO")
    mcp_base_url = config.get_str('mcp_integration.mcp_node_service_base_url', "http://localhost:7778")
    list_tools_url = f"{mcp_base_url}/list-tools"

    try:
        response = await asyncio.to_thread(requests.get, list_tools_url, timeout=10)
        
        container.clear() # Clear spinner
        with container: # Re-enter for content or error message
            if response.status_code == 200:
                try:
                    tools_data = response.json()
                    app_state['available_mcp_tools'] = tools_data # Update app_state
                    
                    if not tools_data:
                        ui.label("No MCP tools configured or available.").classes('text-italic q-pa-md text-center')
                        return

                    columns = [
                        {'name': 'tool_name', 'label': 'Tool Name', 'field': 'tool_name', 'required': True, 'align': 'left', 'sortable': True},
                        {'name': 'server_name', 'label': 'Server', 'field': 'server_name', 'align': 'left', 'sortable': True},
                        {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'center'},
                        {'name': 'actions', 'label': 'Actions', 'field': 'actions', 'align': 'right'},
                    ]
                    
                    rows = []
                    for tool in tools_data:
                        rows.append({
                            'tool_name': tool.get("tool_name", "Unnamed Tool"),
                            'server_name': tool.get("server_name", "Unknown Server"),
                            'status': tool.get("status", "Unknown"),
                            'id': tool.get("id", tool.get("tool_name")),
                            '_data': tool
                        })

                    tool_table = ui.table(columns=columns, rows=rows, row_key='id').classes('w-full')
                    tool_table.add_slot('body-cell-status', '''
                        <q-td :props="props">
                            <q-badge :color="props.row.status === 'Active' ? 'green' : (props.row.status === 'Error' ? 'red' : 'orange')">
                                {{ props.row.status }}
                            </q-badge>
                        </q-td>
                    ''')
                    tool_table.add_slot('body-cell-actions', '''
                        <q-td :props="props" class="q-gutter-xs">
                            <q-btn flat dense round icon="settings" @click="() => $parent.$emit('customAction', {action: 'configure', row: props.row})" />
                            <q-btn flat dense round :icon="props.row.status === 'Active' ? 'toggle_on' : 'toggle_off'"
                                   :color="props.row.status === 'Active' ? 'green' : 'grey'"
                                    @click="() => $parent.$emit('customAction', {action: 'toggle', row: props.row})" />
                            <q-btn flat dense round icon="delete" color="red" @click="() => $parent.$emit('customAction', {action: 'delete', row: props.row})" />
                        </q-td>
                    ''')

                    def handle_table_action(e):
                        action_details = e.args
                        tool_entry = action_details['row']['_data']
                        if action_details['action'] == 'configure':
                            open_configure_tool_dialog(tool_entry)
                        elif action_details['action'] == 'toggle':
                            toggle_tool_status(tool_entry, tool_entry.get("status", "Unknown"))
                        elif action_details['action'] == 'delete':
                            confirm_delete_tool(tool_entry)
                    
                    tool_table.on('customAction', handle_table_action)

                except json.JSONDecodeError as e:
                    error_message = f"Failed to parse tool data: {e}"
                    gui_log(f"Error in fetch_available_tools (JSONDecodeError): {error_message}", level="ERROR")
                    ui.label(error_message).classes("text-negative q-pa-md")
                    client.notify(f"Error parsing tool data from MCP service: {e}", type="negative", multi_line=True) # Use client.notify
            else:
                error_message = f"Error fetching tools: {response.status_code} - {response.reason}"
                gui_log(f"Failed to fetch MCP tools from {list_tools_url}. Status: {response.status_code}, Response: {response.text[:200]}", level="ERROR")
                ui.label(error_message).classes('text-red q-pa-md')
                client.notify(error_message, type="negative", multi_line=True) # Use client.notify

    except requests.exceptions.RequestException as e:
        container.clear()
        with container:
            error_message = f"Network error fetching tools: {e}"
            gui_log(f"Error in fetch_available_tools (RequestException): {error_message}", level="ERROR")
            ui.label(error_message).classes('text-red q-pa-md')
            client.notify(f"Could not connect to MCP service: {e}", type="negative", multi_line=True) # Use client.notify
            
    except Exception as e:
        container.clear()
        with container:
            error_message = f"An unexpected error occurred: {e}"
            gui_log(f"Error in fetch_available_tools (Exception): {error_message}", level="CRITICAL")
            ui.label(error_message).classes('text-red q-pa-md')
            client.notify(f"An unexpected error occurred while fetching tools: {e}", type="negative", multi_line=True) # Use client.notify

def open_add_tool_dialog(client: Client): # Added client
    with ui.dialog() as dialog, ui.card().classes('min-w-[700px] max-w-[90vw]'):
        ui.label("Add New MCP Tool").classes('text-h6 q-mb-md')
        
        form_data = {}

        with ui.column().classes('q-gutter-md'): # Changed from ui.form()
            form_data['tool_name'] = ui.input("Tool Name*", placeholder="e.g., WebSearchTool").props('outlined dense required')
            form_data['server_name'] = ui.input("Server Name*", placeholder="e.g., web_search_mcp_server").props('outlined dense required')
            form_data['server_url'] = ui.input("Server URL*", placeholder="e.g., http://localhost:3001/mcp").props('outlined dense required type=url')
            form_data['tool_description'] = ui.textarea("Description", placeholder="Briefly describe what this tool does and its purpose.").props('outlined dense autogrow')
            
            with ui.expansion("Authentication (Optional)").classes('w-full'):
                form_data['auth_required'] = ui.checkbox("Authentication Required")
                with ui.column().bind_visibility_from(form_data['auth_required'], 'value').classes('q-gutter-sm q-pt-sm'):
                    form_data['auth_type'] = ui.select(["Basic", "Bearer Token", "API Key"], label="Authentication Type").props('outlined dense')
                    form_data['auth_key'] = ui.input("Key / Username / Token Name").props('outlined dense')
                    form_data['auth_value'] = ui.input("Value / Password / API Key Value", password=True).props('outlined dense')
            
            with ui.expansion("Parameters Template (JSON, Optional)").classes('w-full'):
                form_data['params_template'] = ui.textarea(placeholder='Example: {"query": {"type": "string", "description": "Search query"},\n "num_results": {"type": "integer", "default": 5}}').props('outlined dense autogrow')
                ui.label("Define the JSON schema for tool parameters. This helps in validating inputs and generating forms.").classes('text-caption text-grey-7 q-mt-xs')

            with ui.row().classes('justify-end w-full q-mt-lg q-gutter-sm'):
                ui.button("Cancel", on_click=dialog.close, color='grey').props('flat')
                
                add_tool_button = ui.button("Add Tool").props('color=primary')

                async def submit_form_wrapper(): # Renamed from submit_form to avoid conflict if any
                    tool_payload = {
                        "tool_name": form_data['tool_name'].value,
                        "server_name": form_data['server_name'].value,
                        "server_url": form_data['server_url'].value,
                        "description": form_data['tool_description'].value,
                        "auth_config": None,
                        "parameters_schema": None
                    }
                    if form_data['auth_required'].value:
                        tool_payload["auth_config"] = {
                            "type": form_data['auth_type'].value,
                            "key_or_username": form_data['auth_key'].value,
                            "value_or_password": form_data['auth_value'].value
                        }
                    if form_data['params_template'].value:
                        try:
                            tool_payload["parameters_schema"] = json.loads(form_data['params_template'].value)
                        except json.JSONDecodeError as e:
                            gui_log(f"Error in open_add_tool_dialog (JSONDecodeError for params): {e}", level="ERROR")
                            client.notify(f"Invalid JSON in Parameters Template: {e}", type="negative", multi_line=True) # Use client.notify
                            return
                    
                    if not all([tool_payload["tool_name"], tool_payload["server_name"], tool_payload["server_url"]]):
                        client.notify("Tool Name, Server Name, and Server URL are required.", type="negative") # Use client.notify
                        return

                    await add_new_tool(client, tool_payload, add_tool_button) # Pass client & button_ref
                    dialog.close()
                
                add_tool_button.on('click', submit_form_wrapper)
    dialog.open()

async def add_new_tool(client: Client, tool_data: dict, button_ref: ui.button): # Added client
    original_button_text = button_ref.text
    button_ref.props("loading=true icon=none")
    button_ref.text = "Adding..."
    gui_log(f"Attempting to add new MCP tool: {tool_data.get('tool_name')}", level="INFO")
    
    mcp_base_url = config.get_str('mcp_integration.mcp_node_service_base_url', "http://localhost:7778")
    add_tool_url = f"{mcp_base_url}/add-tool"

    try:
        response = await asyncio.to_thread(requests.post, add_tool_url, json=tool_data, timeout=15)
        if response.status_code == 200 or response.status_code == 201:
            client.notify(f"Tool '{tool_data.get('tool_name')}' added successfully!", type="positive") # Use client.notify
            gui_log(f"Tool '{tool_data.get('tool_name')}' added. Response: {response.text[:200]}", level="INFO")
            if _tool_management_tools_container_ref:
                await fetch_available_tools(client, _tool_management_tools_container_ref) # Pass client
            else:
                gui_log("Tool management container ref not found for refresh after add.", level="WARNING")
        else:
            error_detail = f"status {response.status_code}"
            try:
                # Try to parse more detailed error from JSON response
                error_json = response.json()
                error_detail = error_json.get("detail", error_json.get("error", error_detail))
            except json.JSONDecodeError:
                # If response is not JSON, use the raw text or just status code
                error_detail = f"{error_detail} - {response.text[:100]}"
            
            user_friendly_message = f"Failed to add tool '{tool_data.get('tool_name')}': {error_detail}"
            client.notify(user_friendly_message, type="negative", multi_line=True) # Use client.notify
            gui_log(f"Error in add_new_tool: {user_friendly_message}. URL: {add_tool_url}, Status: {response.status_code}, Full Response: {response.text[:200]}", level="ERROR")
    
    except requests.exceptions.RequestException as e:
        error_message = f"Network error adding tool: {e}"
        gui_log(f"Error in add_new_tool (RequestException): {error_message}", level="ERROR")
        client.notify(f"Error connecting to MCP service to add tool: {e}", type="negative", multi_line=True) # Use client.notify
    except Exception as e:
        error_message = f"An unexpected error occurred: {e}"
        gui_log(f"Error in add_new_tool (Exception): {error_message}", level="CRITICAL")
        client.notify(f"An unexpected error occurred while adding tool: {e}", type="negative", multi_line=True) # Use client.notify
    finally:
        button_ref.props("loading=false")
        button_ref.text = original_button_text
        # Assuming the button originally had no icon or its icon should be restored if it had one.
        # For "Add Tool", it likely has no specific icon by default.

# --- End of LLM Configuration and MCP Tool Management UI ---


# --- UI Display Updaters ---
minion_cards_container = None # Will be defined in create_ui
chat_log_area = None # Will be defined in main_page for the chat log
minion_filter_input = None # Will be defined in main_page for filtering
status_label = None # Will be defined in main_page and used by timers

def update_minion_display(client: Optional[Client] = None): # Added client, optional for timer calls
    if not minion_cards_container:
        gui_log("update_minion_display called but minion_cards_container is not initialized.", level="WARNING")
        return
    
    filter_text = ""
    if minion_filter_input: # Check if the input element itself is initialized
        filter_text = minion_filter_input.value.lower() if minion_filter_input.value else ""
    else:
        gui_log("minion_filter_input not initialized when update_minion_display was called.", level="DEBUG")


    minion_cards_container.clear()
    
    # Filter minions
    filtered_minions = {}
    if filter_text:
        gui_log(f"Filtering minions with text: '{filter_text}'", level="DEBUG")
        for agent_id, data in app_state["minions"].items():
            # Check name, id, description, personality
            if filter_text in agent_id.lower() or \
               filter_text in data.get("name_display", "").lower() or \
               filter_text in data.get("description", "").lower() or \
               filter_text in data.get("personality", "").lower():
                filtered_minions[agent_id] = data
                continue # Already matched

            # Check capabilities
            capabilities_data = data.get('capabilities', {})
            if isinstance(capabilities_data, dict):
                # Check skills (also checking root 'skills' as a fallback)
                skills_list = capabilities_data.get('skills', data.get('skills', []))
                for skill in skills_list:
                    if isinstance(skill, dict):
                        if filter_text in skill.get('name', '').lower() or \
                           filter_text in skill.get('description', '').lower():
                            filtered_minions[agent_id] = data
                            break
                    elif isinstance(skill, str) and filter_text in skill.lower():
                         filtered_minions[agent_id] = data
                         break
                if agent_id in filtered_minions: continue

                # Check MCP tools
                mcp_tools_list = capabilities_data.get('mcp_tools', [])
                for tool in mcp_tools_list:
                    if isinstance(tool, dict):
                        if filter_text in tool.get('tool_name', '').lower() or \
                           filter_text in tool.get('server_name', '').lower() or \
                           filter_text in tool.get('description', '').lower():
                            filtered_minions[agent_id] = data
                            break
                    elif isinstance(tool, str) and filter_text in tool.lower():
                        filtered_minions[agent_id] = data
                        break
                if agent_id in filtered_minions: continue

                # Check Language models
                language_models_list = capabilities_data.get('language_models', [])
                for model in language_models_list:
                    if isinstance(model, dict):
                        if filter_text in model.get('model_name', '').lower() or \
                           filter_text in model.get('provider', '').lower():
                            filtered_minions[agent_id] = data
                            break
                    elif isinstance(model, str) and filter_text in model.lower():
                        filtered_minions[agent_id] = data
                        break
                if agent_id in filtered_minions: continue
                
                # Check other capability types
                other_capability_types = [k for k in capabilities_data.keys() if k not in ['skills', 'mcp_tools', 'language_models']]
                for cap_type in other_capability_types:
                    cap_list = capabilities_data.get(cap_type)
                    if isinstance(cap_list, list):
                        for item in cap_list:
                            if isinstance(item, str) and filter_text in item.lower():
                                filtered_minions[agent_id] = data
                                break
                            elif isinstance(item, dict): # If items are dicts, check their string values
                                for v in item.values():
                                    if isinstance(v, str) and filter_text in v.lower():
                                        filtered_minions[agent_id] = data
                                        break
                                if agent_id in filtered_minions: break
                    elif isinstance(cap_list, str) and filter_text in cap_list.lower(): # If capability value is a direct string
                        filtered_minions[agent_id] = data
                    if agent_id in filtered_minions: break
                if agent_id in filtered_minions: continue
    else:
        filtered_minions = app_state["minions"]

    with minion_cards_container:
        if not filtered_minions:
            ui.label("No minions match the current filter or none are registered.").classes('text-italic')
            return

        ui.label(f"Minion Army ({len(filtered_minions)} displayed / {len(app_state['minions'])} total):").classes('text-h6')
        with ui.grid(columns=3).classes('gap-4'): # Adjust columns as needed
            for agent_id_key, data in sorted(filtered_minions.items(), key=lambda item: item[1].get("name_display", item[0])):
                with ui.card().tight():
                    with ui.card_section():
                        with ui.row().classes('items-center justify-between w-full'):
                            ui.label(get_formatted_minion_display(agent_id_key)).classes('text-subtitle1 font-bold') # Use formatted display
                            ui.button(icon='edit', on_click=lambda bound_id=agent_id_key, current_name=data.get("name_display", agent_id_key): open_rename_dialog(bound_id, current_name), color='grey-7').props('flat dense round').tooltip('Rename Minion')
                        ui.label(f"ID: {agent_id_key}")
                        current_status = data.get('status', 'N/A')
                        ui.label(f"Status: {current_status}")
                        ui.label(f"Personality: {data.get('personality', 'N/A')}")
                        ui.label(f"Description: {data.get('description', 'N/A')[:60]}...") # Shorter desc

                        # Task Coordination and Collaborative Task Counts
                        skills_for_card = data.get('capabilities', {}).get('skills', [])
                        # Ensure skills_for_card is a list of strings or dicts for 'in' check
                        has_task_coordination_skill = False
                        if isinstance(skills_for_card, list):
                            for skill_item in skills_for_card:
                                if isinstance(skill_item, str) and skill_item == "task_coordination":
                                    has_task_coordination_skill = True
                                    break
                                elif isinstance(skill_item, dict) and skill_item.get('name') == "task_coordination":
                                    has_task_coordination_skill = True
                                    break
                        
                        coordinating_tasks_count = 0
                        participating_tasks_count = 0
                        active_task_statuses = ['pending', 'in_progress', 'awaiting_subtask_completion', 'decomposing', 'awaiting_coordination'] # Define active statuses

                        for task_iter_id, task_iter_data in app_state.get("collaborative_tasks", {}).items():
                            task_status_lower = task_iter_data.get('status', '').lower()
                            if task_iter_data.get('coordinator_id') == agent_id_key and task_status_lower in active_task_statuses:
                                coordinating_tasks_count += 1
                            
                            for subtask_iter_id, subtask_iter_data in task_iter_data.get('subtasks', {}).items():
                                subtask_status_lower = subtask_iter_data.get('status', '').lower()
                                if subtask_iter_data.get('assigned_to') == agent_id_key and subtask_status_lower in active_task_statuses:
                                    participating_tasks_count += 1
                                    break # Count minion once per parent task if participating in any subtask

                        ui.label(f"Coordinator Skill: {'Yes' if has_task_coordination_skill else 'No'}").classes('text-caption')
                        ui.label(f"Coordinating Tasks (Active): {coordinating_tasks_count}").classes('text-caption')
                        ui.label(f"Participating Tasks (Active): {participating_tasks_count}").classes('text-caption')

                        # Display Capabilities
                        capabilities = data.get('capabilities', {})
                        if capabilities:
                            with ui.expansion("Capabilities", icon="extension").classes('w-full q-mt-sm'):
                                if not isinstance(capabilities, dict):
                                    ui.label("Capabilities format is unexpected.")
                                else:
                                    # Skills (assuming skills might also be directly under capabilities or as a fallback)
                                    skills_list = capabilities.get('skills', data.get('skills', [])) # Check capabilities first, then root data
                                    if skills_list:
                                        with ui.card_section().classes('q-pt-none'):
                                            ui.label("Skills:").classes('text-caption font-medium text-grey-7')
                                            with ui.list().props('dense separator'):
                                                for skill in skills_list:
                                                    if isinstance(skill, dict):
                                                        skill_name = skill.get('name', 'N/A')
                                                        skill_version = skill.get('version', 'N/A')
                                                        skill_desc = skill.get('description', 'N/A')
                                                        with ui.item():
                                                            with ui.item_section():
                                                                ui.item_label(f"{skill_name} (v{skill_version})").classes('text-body2')
                                                                ui.item_label(skill_desc).props('caption').classes('text-grey-7')
                                                    else: # Handle if skill is just a string
                                                        ui.item_label(str(skill)).classes('text-body2')


                                    # MCP Tools
                                    mcp_tools_list = capabilities.get('mcp_tools', [])
                                    if mcp_tools_list:
                                        with ui.card_section().classes('q-pt-none'):
                                            ui.label("MCP Tools:").classes('text-caption font-medium text-grey-7')
                                            with ui.list().props('dense separator'):
                                                for tool in mcp_tools_list:
                                                    if isinstance(tool, dict):
                                                        tool_name = tool.get('tool_name', 'N/A')
                                                        server_name = tool.get('server_name', 'N/A')
                                                        tool_desc = tool.get('description', 'N/A')
                                                        with ui.item():
                                                            with ui.item_section():
                                                                ui.item_label(f"{tool_name} (Server: {server_name})").classes('text-body2')
                                                                ui.item_label(tool_desc).props('caption').classes('text-grey-7')
                                                    else:
                                                         ui.item_label(str(tool)).classes('text-body2')


                                    # Language Models
                                    language_models_list = capabilities.get('language_models', [])
                                    if language_models_list:
                                        with ui.card_section().classes('q-pt-none'):
                                            ui.label("Language Models:").classes('text-caption font-medium text-grey-7')
                                            with ui.list().props('dense separator'):
                                                for model in language_models_list:
                                                    if isinstance(model, dict):
                                                        model_name = model.get('model_name', 'N/A')
                                                        provider = model.get('provider', 'N/A')
                                                        with ui.item():
                                                            with ui.item_section():
                                                                ui.item_label(f"{model_name} (Provider: {provider})").classes('text-body2')
                                                    else:
                                                        ui.item_label(str(model)).classes('text-body2')
                                    
                                    # Fallback for any other capability types not explicitly handled
                                    other_capability_types = [k for k in capabilities.keys() if k not in ['skills', 'mcp_tools', 'language_models']]
                                    if any(capabilities.get(ct) for ct in other_capability_types):
                                        with ui.card_section().classes('q-pt-none'):
                                            ui.label("Other Capabilities:").classes('text-caption font-medium text-grey-7')
                                            with ui.list().props('dense separator'):
                                                for cap_type in other_capability_types:
                                                    cap_list = capabilities.get(cap_type)
                                                    if cap_list:
                                                        for cap_item in cap_list:
                                                            with ui.item():
                                                                with ui.item_section():
                                                                    ui.item_label(f"{cap_type.replace('_', ' ').title()}: {str(cap_item)}").classes('text-body2')
                        
                        # Add Process Control Buttons
                        with ui.row().classes('q-gutter-sm q-mt-xs'):
                            if current_status in ["Running", "Idle", "Unknown"]:
                                ui.button("Pause", on_click=lambda mid=agent_id_key, c=client: handle_pause_minion(c, mid) if c else gui_log("Pause: Client context not available for notification", "WARNING"), color='orange').props('dense')
                            elif current_status == "Paused":
                                ui.button("Resume", on_click=lambda mid=agent_id_key, c=client: handle_resume_minion(c, mid) if c else gui_log("Resume: Client context not available for notification", "WARNING"), color='green').props('dense')
                                ui.button("Send Msg", on_click=lambda mid=agent_id_key, c=client: open_send_message_to_paused_dialog(c, mid) if c else gui_log("SendMsgDialog: Client context not available", "WARNING"), color='blue').props('dense')
                            elif current_status in ["Pausing...", "Resuming..."]:
                                ui.spinner(size='sm').classes('q-ml-md')
                        
                        # Minion Actions Row (Details, Personality, Debug)
                        with ui.row().classes('q-gutter-sm q-mt-sm w-full justify-start'):
                            ui.button("Chat", icon="chat", on_click=lambda mid=agent_id_key: start_chat_session(session_type="individual", agent_ids_input=mid)).props('dense outline color=primary')
                            ui.button("View Details", on_click=lambda mid=agent_id_key: show_minion_details(mid)).props('dense outline')
                            ui.button("Personality", icon="face_retouching_natural", on_click=lambda mid=agent_id_key, c=client: open_personality_dialog(c, mid) if c else gui_log("PersonalityDialog: Client context missing", "WARNING")).props('dense outline')
                            ui.button("Debug", icon="bug_report", on_click=lambda mid=agent_id_key: show_minion_details(mid)).props('dense outline') # Debug also navigates to detail page

    gui_log("Minion display updated with process control, chat, and action buttons.")


# --- Process Control Action Handlers (Placeholder implementations) ---
async def handle_pause_minion(client: Optional[Client], minion_id: str):
    gui_log(f"GUI: Initiating PAUSE for minion: {minion_id}")
    payload = {
        "message_type": "control_pause_request",
        "target_minion_id": minion_id,
    }
    # Client might be None if called from a timer context indirectly
    success = await send_a2a_message_to_minion(client, minion_id, "control_pause_request", payload, notification_verb="pause minion") if client else \
              await send_a2a_message_to_minion(app.get_client(), minion_id, "control_pause_request", payload, notification_verb="pause minion") # Fallback for timer
    if success:
        if minion_id in app_state["minions"]:
            app_state["minions"][minion_id]["status"] = "Pausing..."
            update_minion_display(client) # Pass client if available

async def handle_resume_minion(client: Optional[Client], minion_id: str):
    gui_log(f"GUI: Initiating RESUME for minion: {minion_id}")
    payload = {
        "message_type": "control_resume_request",
        "target_minion_id": minion_id,
    }
    success = await send_a2a_message_to_minion(client, minion_id, "control_resume_request", payload, notification_verb="resume minion") if client else \
              await send_a2a_message_to_minion(app.get_client(), minion_id, "control_resume_request", payload, notification_verb="resume minion") # Fallback
    if success:
        if minion_id in app_state["minions"]:
            app_state["minions"][minion_id]["status"] = "Resuming..."
            update_minion_display(client) # Pass client if available

async def handle_send_message_to_paused_minion(client: Client, minion_id: str, message_text: str): # Client is required here
    gui_log(f"GUI: Sending message to PAUSED minion {minion_id}: {message_text[:50]}...")
    if not message_text.strip():
        client.notify("Message content cannot be empty.", type='warning')
        return

    payload = {
        "message_type": "message_to_paused_minion_request",
        "target_minion_id": minion_id,
        "message_content": message_text,
    }
    await send_a2a_message_to_minion(client, minion_id, "message_to_paused_minion_request", payload, notification_verb="send message to paused minion")

def open_send_message_to_paused_dialog(client: Optional[Client], minion_id: str): # Made client optional for safety, but dialog needs it
    minion_display_name = get_formatted_minion_display(minion_id)
    with ui.dialog() as dialog, ui.card().classes('min-w-[500px]'):
        ui.label(f"Send Message to Paused Minion: {minion_display_name}").classes('text-h6')
        message_input = ui.textarea(label="Your message:", placeholder="Enter instructions or information...").props('outlined dense autogrow autofocus')
        with ui.row().classes('justify-end w-full q-mt-md'):
            ui.button("Cancel", on_click=dialog.close, color='grey').props('flat')
            ui.button("Send", on_click=lambda: (
                handle_send_message_to_paused_minion(client, minion_id, message_input.value) if client else gui_log("SendPausedMsg: Client context missing", "ERROR"),
                dialog.close()
            )).props('color=primary')
    dialog.open()

def open_rename_dialog(minion_id: str, current_name: str):
    with ui.dialog() as dialog, ui.card():
        ui.label(f"Rename Minion: {current_name} (ID: {minion_id})").classes('text-h6')
        new_name_input = ui.input(label="New Minion Name", value=current_name).props('autofocus outlined')
        with ui.row().classes('justify-end w-full q-mt-md'):
            ui.button("Cancel", on_click=dialog.close, color='grey')
            ui.button("Save", on_click=lambda: (
                handle_rename_minion(minion_id, new_name_input.value),
                dialog.close()
            ))
    dialog.open()

# --- Minion Personality Customization UI (GUI-3.3) ---

async def update_minion_personality(client: Client, minion_id: str, personality_traits: str, button_ref: ui.button): # Added client
    """
    Updates the specified minion's personality traits via A2A message.
    Manages button loading state. Requires client context.
    """
    original_button_text = button_ref.text
    button_ref.props("loading=true icon=none")
    button_ref.text = "Applying..."
    gui_log(f"Attempting to update personality for minion {minion_id} to: '{personality_traits[:100]}...'")
    minion_display_name = get_formatted_minion_display(minion_id)

    payload = {
        "message_type": "update_personality",
        "new_personality_traits": personality_traits
    }

    try:
        success = await send_a2a_message_to_minion(
            client=client, # Pass client
            minion_id=minion_id,
            message_type="update_personality",
            a2a_payload=payload,
            notification_verb=f"update personality for {minion_display_name}"
        )

        if success:
            if minion_id in app_state.get("minions", {}):
                app_state["minions"][minion_id]["personality"] = personality_traits
                gui_log(f"Successfully updated personality in app_state for {minion_id}.")
                if minion_cards_container:
                    update_minion_display(client) # Pass client
                else:
                    gui_log("minion_cards_container not defined, skipping display update.", level="WARNING")
                client.notify(f"Personality for {minion_display_name} updated successfully.", type='positive')
            else:
                gui_log(f"Minion {minion_id} not found in app_state after successful A2A, cannot update local state.", level="WARNING")
                client.notify(f"Personality update sent for {minion_display_name}, but local display might be out of sync.", type='warning')
    except Exception as e:
        gui_log(f"Error in update_minion_personality for {minion_id}: {e}", level="ERROR")
        client.notify(f"An unexpected error occurred while updating personality for {minion_display_name}: {e}", type="negative", multi_line=True)
    finally:
        button_ref.props("loading=false")
        button_ref.text = original_button_text

def open_personality_dialog(client: Optional[Client], minion_id: str): # Added client, optional for safety
    """
    Opens a dialog to customize the personality of a given minion.
    """
    minion_data = app_state.get("minions", {}).get(minion_id)
    if not minion_data:
        if client:
            client.notify(f"Minion {minion_id} not found.", type='negative')
        else: # Should not happen if called from UI with client
            gui_log(f"open_personality_dialog: Minion {minion_id} not found (no client context for notify).", level="ERROR")
        gui_log(f"open_personality_dialog: Minion {minion_id} not found in app_state.", level="ERROR") # Log anyway
        return

    minion_name = get_formatted_minion_display(minion_id)
    current_personality = minion_data.get("personality", "")

    with ui.dialog() as dialog, ui.card().classes('min-w-[600px]'):
        ui.label(f"Customize {minion_name} Personality").classes('text-h6 q-mb-md')

        personality_textarea = ui.textarea(
            "Personality Traits",
            value=current_personality,
            placeholder="Describe the minion's personality traits, e.g., 'Analytical, cautious, detail-oriented'"
        ).props('outlined dense autogrow')

        ui.label("Personality Templates (Examples):").classes('text-caption q-mt-sm')
        with ui.row().classes('q-gutter-sm q-mb-md'):
            templates = {
                "Analytical": "Analytical, logical, data-driven, prefers facts over opinions.",
                "Creative": "Creative, imaginative, thinks outside the box, enjoys brainstorming.",
                "Supportive": "Supportive, empathetic, patient, good listener, team player.",
                "Direct": "Direct, concise, to-the-point, values efficiency."
            }
            for name, text in templates.items():
                ui.button(name, on_click=lambda t=text: personality_textarea.set_value(t)).props('outline dense')
        
        with ui.expansion("Advanced Personality Settings (Placeholders)").classes('w-full q-mt-md'):
            with ui.card_section():
                ui.slider(min=0, max=10, value=5, step=1).props('label label-always').bind_value(app_state, f"temp_verbosity_{minion_id}")
                ui.label("Verbosity").classes('q-ml-sm')
                ui.slider(min=0, max=10, value=7, step=1).props('label label-always').bind_value(app_state, f"temp_creativity_{minion_id}")
                ui.label("Creativity").classes('q-ml-sm')
                ui.slider(min=0, max=10, value=3, step=1).props('label label-always').bind_value(app_state, f"temp_formality_{minion_id}")
                ui.label("Formality").classes('q-ml-sm')
                ui.label("Note: Advanced settings are placeholders and not yet functional.").classes('text-caption text-orange')


        with ui.row().classes('justify-end w-full q-mt-lg'):
            ui.button("Cancel", on_click=dialog.close, color='grey').props('flat')
            apply_button = ui.button("Apply Personality").props('color=primary')
            def apply_action():
                if client:
                    update_minion_personality(client, minion_id, personality_textarea.value, apply_button)
                    dialog.close()
                else:
                    gui_log("ApplyPersonality: Client context missing.", "ERROR")
                    # Potentially notify via a global mechanism if possible, or just log
                    # This case should ideally not be hit if called from UI correctly
                    try:
                        ui.notify("Error: Cannot apply personality, client context lost.", type="negative")
                    except Exception as e_notify:
                        gui_log(f"Failed to show global notify in apply_action for personality: {e_notify}", "ERROR")


            apply_button.on('click', apply_action)

    dialog.open()

# --- Minion Debugging Interface UI (GUI-3.4) ---

async def fetch_minion_debug_data(client: Client, minion_id: str, data_type: str, container: ui.element):
    """
    Generic helper to request debug data from a minion and update a UI container.
    `data_type` corresponds to the A2A message (e.g., 'debug_get_state', 'debug_get_conversation_history').
    Manages loading state within the container. Requires client context.
    """
    minion_name = get_formatted_minion_display(minion_id)
    data_type_display = data_type.replace('debug_get_', '').replace('_', ' ')
    gui_log(f"Fetching '{data_type_display}' for minion {minion_name} ({minion_id}).")
    
    container.clear()
    with container:
        ui.spinner(size='md').classes('self-center')
        ui.label(f"Fetching {data_type_display}...").classes('text-italic')

    payload = {
        "message_type": data_type,
    }
    
    success = False # Initialize success flag
    try:
        success = await send_a2a_message_to_minion(
            client=client, # Pass client
            minion_id=minion_id,
            message_type=data_type,
            a2a_payload=payload,
            notification_verb=f"request {data_type_display} for {minion_name}"
        )
    except Exception as e:
        gui_log(f"Error during A2A call in fetch_minion_debug_data for {data_type} of {minion_id}: {e}", level="ERROR")
        client.notify(f"An error occurred while requesting {data_type_display} for {minion_name}: {e}", type="negative", multi_line=True)
        # Success remains False
    finally:
        container.clear() # Clear spinner and "Fetching..." message
        with container:
            if success:
                ui.label(f"Request for {data_type_display} sent. Waiting for response...").classes('text-green')
                # The actual data display will rely on app_state being updated by the A2A response handler
                # and the tab's content area being refreshed or observing app_state.
                # This part remains as a placeholder for when data arrives.
                debug_key_map = {
                    "debug_get_state": "state_data",
                    "debug_get_conversation_history": "conversation_history",
                    "debug_get_task_queue": "task_queue",
                    "debug_get_logs": "logs",
                    "debug_get_performance_metrics": "performance_metrics"
                }
                data_key = debug_key_map.get(data_type)

                # Check if data is already available (e.g., from a very fast response or previous fetch)
                if data_key and minion_id in app_state.get("debug_info", {}) and data_key in app_state["debug_info"][minion_id]:
                    retrieved_data = app_state["debug_info"][minion_id][data_key]
                    if isinstance(retrieved_data, (dict, list)):
                        ui.json_editor({"content": {"json": retrieved_data}}).props('readonly')
                    else:
                        ui.code(str(retrieved_data)) # Use ui.code for potentially long string data
                else:
                    ui.label(f"Data for '{data_key or data_type_display}' will appear here when received and processed.").classes('text-italic')
                    gui_log(f"No data yet in app_state for {minion_id} -> {data_key} after fetch attempt.", level="DEBUG")
            else:
                # If send_a2a_message_to_minion returned False, it would have shown a notification.
                # If an exception occurred in the try block, that also showed a notification.
                # So, this specific message might be redundant if send_a2a_message_to_minion is robust.
                # However, it's a good fallback if the request initiation itself failed silently before send_a2a.
                ui.label(f"Failed to send request for {data_type_display}. Check logs for details.").classes('text-red')
                # client.notify is handled by send_a2a_message_to_minion or the except block here.

# Specific fetch functions calling the generic helper
async def fetch_minion_state(client: Client, minion_id: str, container: ui.element):
    await fetch_minion_debug_data(client, minion_id, "debug_get_state", container)

async def fetch_minion_conversation(client: Client, minion_id: str, container: ui.element):
    await fetch_minion_debug_data(client, minion_id, "debug_get_conversation_history", container)

async def fetch_minion_task_queue(client: Client, minion_id: str, container: ui.element):
    await fetch_minion_debug_data(client, minion_id, "debug_get_task_queue", container)

async def fetch_minion_logs(client: Client, minion_id: str, container: ui.element):
    # For logs, we might want to specify parameters like 'lines' or 'since_timestamp' in payload
    await fetch_minion_debug_data(client, minion_id, "debug_get_logs", container)

async def fetch_minion_performance(client: Client, minion_id: str, container: ui.element):
    await fetch_minion_debug_data(client, minion_id, "debug_get_performance_metrics", container)


def create_debug_console_ui(client: Client, minion_id: str): # Added client
    """
    Creates the UI for the minion debug console.
    This function itself doesn't return a NiceGUI element directly to be embedded,
    but rather it would typically be called to populate a specific part of a page or dialog.
    For this task, we define it. Its integration into a minion detail page is GUI-3.5.
    Let's assume this function is called within a context where it can add UI elements.
    For example, it might be called inside a `with ui.card():` block on a minion detail page.
    """
    minion_data = app_state.get("minions", {}).get(minion_id)
    if not minion_data:
        ui.label(f"Minion {minion_id} not found for debug console.").classes('text-red')
        gui_log(f"create_debug_console_ui: Minion {minion_id} not found.", level="ERROR")
        return

    minion_name = get_formatted_minion_display(minion_id)
    
    # This function would be called to render into an existing container,
    # or it could return a ui.element to be added elsewhere.
    # For now, let's assume it adds to the current UI context.

    with ui.card().classes('w-full q-mt-md'):
        with ui.card_section():
            ui.label(f"Debug Console: {minion_name}").classes('text-h6')

        with ui.tabs().props('vertical').classes('w-full') as tabs:
            tab_internal_state = ui.tab("Internal State", icon="data_object")
            tab_conversation_history = ui.tab("Conversation History", icon="history")
            tab_task_queue = ui.tab("Task Queue", icon="queue")
            tab_log_viewer = ui.tab("Log Viewer", icon="article")
            tab_performance_metrics = ui.tab("Performance", icon="speed")

        with ui.tab_panels(tabs, value=tab_internal_state).props('vertical').classes('w-full'):
            with ui.tab_panel(tab_internal_state):
                ui.label("Minion Internal State").classes('text-subtitle1 q-mb-sm')
                state_container = ui.column().classes('w-full q-gutter-y-sm')
                ui.button("Fetch/Refresh State", icon="refresh", on_click=lambda: fetch_minion_state(client, minion_id, state_container)).props('outline dense')
                with state_container:
                     ui.label("Click 'Fetch/Refresh State' to load data.").classes('text-italic')
            
            with ui.tab_panel(tab_conversation_history):
                ui.label("Minion Conversation History").classes('text-subtitle1 q-mb-sm')
                conversation_container = ui.column().classes('w-full q-gutter-y-sm')
                ui.button("Fetch/Refresh History", icon="refresh", on_click=lambda: fetch_minion_conversation(client, minion_id, conversation_container)).props('outline dense')
                with conversation_container:
                    ui.label("Click 'Fetch/Refresh History' to load data.").classes('text-italic')

            with ui.tab_panel(tab_task_queue):
                ui.label("Minion Task Queue").classes('text-subtitle1 q-mb-sm')
                task_queue_container = ui.column().classes('w-full q-gutter-y-sm')
                ui.button("Fetch/Refresh Queue", icon="refresh", on_click=lambda: fetch_minion_task_queue(client, minion_id, task_queue_container)).props('outline dense')
                with task_queue_container:
                    ui.label("Click 'Fetch/Refresh Queue' to load data.").classes('text-italic')

            with ui.tab_panel(tab_log_viewer):
                ui.label("Minion Log Viewer").classes('text-subtitle1 q-mb-sm')
                logs_container = ui.column().classes('w-full q-gutter-y-sm')
                ui.button("Fetch/Refresh Logs", icon="refresh", on_click=lambda: fetch_minion_logs(client, minion_id, logs_container)).props('outline dense')
                with logs_container:
                    ui.label("Click 'Fetch/Refresh Logs' to load data.").classes('text-italic')

            with ui.tab_panel(tab_performance_metrics):
                ui.label("Minion Performance Metrics").classes('text-subtitle1 q-mb-sm')
                performance_container = ui.column().classes('w-full q-gutter-y-sm')
                ui.button("Fetch/Refresh Metrics", icon="refresh", on_click=lambda: fetch_minion_performance(client, minion_id, performance_container)).props('outline dense')
                with performance_container:
                    ui.label("Click 'Fetch/Refresh Metrics' to load data.").classes('text-italic')
    
    gui_log(f"Debug console UI structure defined for {minion_id}. To be integrated in GUI-3.5.")

# --- End of Minion Debugging Interface UI ---


# --- Chat Session Creation UI and Logic (Subtask GUI-1.3) ---

async def start_chat_session(session_type: str, agent_ids_input: any):
    """
    Handles the logic when "Start Chat Session" is clicked.
    Validates inputs, creates a session_id, updates app_state,
    optionally sends an A2A message, and navigates to the chat page.
    """
    gui_log(f"Attempting to start chat session. Type: {session_type}, Agent IDs input: {agent_ids_input}", level="INFO")

    agent_ids = []
    if session_type == "individual":
        if agent_ids_input and isinstance(agent_ids_input, str):
            agent_ids = [agent_ids_input]
        else:
            ui.notify("Please select an agent for individual chat.", type="negative")
            gui_log("Individual chat start failed: No agent selected.", level="WARNING")
            return
    elif session_type == "group":
        if agent_ids_input and isinstance(agent_ids_input, list) and len(agent_ids_input) > 0:
            agent_ids = agent_ids_input
        else:
            ui.notify("Please select at least one agent for group chat.", type="negative")
            gui_log("Group chat start failed: No agents selected.", level="WARNING")
            return
    else:
        ui.notify("Invalid session type selected.", type="negative")
        gui_log(f"Chat start failed: Invalid session type '{session_type}'.", level="ERROR")
        return

    if not agent_ids: # Should be caught by above checks, but as a safeguard
        ui.notify("No agents selected for the chat session.", type="negative")
        gui_log("Chat start failed: Agent ID list is empty after processing input.", level="ERROR")
        return

    session_id = uuid.uuid4().hex[:8]
    created_at_ts = time.time()

    new_session = {
        "id": session_id,
        "type": session_type,
        "agents": agent_ids, # Normalized list of agent IDs
        "created_at": created_at_ts,
        "messages": [],
        "status": "active"
    }

    if "chat_sessions" not in app_state:
        app_state["chat_sessions"] = {}
    app_state["chat_sessions"][session_id] = new_session
    app_state["active_chat_session_id"] = session_id

    gui_log(f"Chat session {session_id} created. Type: {session_type}, Agents: {agent_ids}. Stored in app_state.", level="INFO")

    # Optionally send a chat_session_start A2A message for individual chats
    if session_type == "individual" and agent_ids:
        primary_agent_id = agent_ids[0]
        payload = {
            "session_id": session_id,
            "initiator_id": "STEVEN_GUI_COMMANDER",
            "participants": agent_ids, # Full list of participants
            "session_type": "individual", # Explicitly state type
            "message_type": "chat_session_start" # Ensure this is part of the payload for minion processing
            # timestamp will be added by send_a2a_message_to_minion
        }
        gui_log(f"Sending chat_session_start A2A to {primary_agent_id} for session {session_id}.", level="DEBUG")
        # The message_type argument to send_a2a_message_to_minion is "chat_session_start"
        # The payload also contains "message_type": "chat_session_start" for clarity if minion inspects payload directly.
        await send_a2a_message_to_minion(
            minion_id=primary_agent_id,
            message_type="chat_session_start", # This is the A2A message type for routing/handling
            a2a_payload=payload,
            notification_verb="initiate chat session"
        )
    elif session_type == "group":
        # For group chats, a broadcast or individual messages to all participants might be considered.
        # For now, as per plan, only individual chat sends an initial A2A.
        # Future: Could send chat_session_start to all group members.
        gui_log(f"Group chat session {session_id} created. No initial A2A message sent by default for group type.", level="INFO")


    ui.notify(f"Chat session '{session_id}' with {', '.join(get_formatted_minion_display(aid) for aid in agent_ids)} started!", type="positive")
    ui.navigate.to(f"/chat/{session_id}")
    gui_log(f"Navigating to /chat/{session_id}", level="INFO")


def create_chat_session_ui():
    """
    Creates the UI elements for initiating a new chat session.
    Returns a ui.card component.
    """
    chat_params = {
        "type": "individual",  # Default selection
        "selected_agent_id": None,
        "selected_group_agents": []
    }
    
    # Container for the dynamic agent selection UI
    agent_selection_area = ui.column().classes('w-full q-mt-sm')

    def update_agent_selector_ui():
        agent_selection_area.clear()
        chat_params["selected_agent_id"] = None # Reset individual selection
        chat_params["selected_group_agents"] = [] # Reset group selection

        with agent_selection_area:
            minions = app_state.get("minions", {})
            if not minions:
                ui.label("No agents available for chat.").classes("text-italic text-negative")
                return

            if chat_params["type"] == "individual":
                options = {mid: get_formatted_minion_display(mid) for mid in minions.keys()}
                if not options:
                     ui.label("No agents available for individual chat.").classes("text-italic")
                else:
                    select_element = ui.select(
                        options=options,
                        label="Select Agent",
                        with_input=True,
                        on_change=lambda e: chat_params.update({"selected_agent_id": e.value})
                    ).props("outlined dense")
                    # Pre-select if there's a previous value and it's still valid
                    if chat_params["selected_agent_id"] in options:
                        select_element.set_value(chat_params["selected_agent_id"])
                    elif options: # Select the first available if no prior valid selection
                        first_agent_id = list(options.keys())[0]
                        # chat_params["selected_agent_id"] = first_agent_id # Auto-select first
                        # select_element.set_value(first_agent_id) # And update UI
                        # Decided against auto-selecting to force user choice.

            elif chat_params["type"] == "group":
                ui.label("Select Agents for Group Chat:").classes("text-caption")
                if not minions:
                    ui.label("No agents available for group chat.").classes("text-italic")
                else:
                    with ui.column().classes('q-gutter-xs'): # To space out checkboxes
                        for agent_id, agent_data in minions.items():
                            display_name = get_formatted_minion_display(agent_id)
                            checkbox = ui.checkbox(display_name)
                            # Use a more robust way to handle checkbox changes for list management
                            def on_checkbox_change(event, current_agent_id=agent_id):
                                if event.value: # Checked
                                    if current_agent_id not in chat_params["selected_group_agents"]:
                                        chat_params["selected_group_agents"].append(current_agent_id)
                                else: # Unchecked
                                    if current_agent_id in chat_params["selected_group_agents"]:
                                        chat_params["selected_group_agents"].remove(current_agent_id)
                                gui_log(f"Group chat selection: {chat_params['selected_group_agents']}", level="DEBUG")

                            checkbox.on('update:model-value', on_checkbox_change) # Use 'update:model-value' for NiceGUI checkboxes
                            # Pre-check if agent was previously selected
                            if agent_id in chat_params["selected_group_agents"]:
                                checkbox.set_value(True)
        gui_log(f"Agent selector UI updated for type: {chat_params['type']}", level="DEBUG")


    with ui.card().classes('w-full') as card_element:
        with ui.card_section():
            ui.label("Agent Communication").classes('text-h6')

        with ui.card_section():
            ui.label("Chat Type:").classes("q-mb-xs")
            chat_type_radio = ui.radio(
                options={"individual": "Individual Chat", "group": "Group Chat"},
                value=chat_params["type"],
                on_change=lambda e: (chat_params.update({"type": e.value}), update_agent_selector_ui())
            ).props("inline")

            # Initial call to populate the agent selector based on default chat_params["type"]
            update_agent_selector_ui()
        
        # The agent_selection_area is populated by update_agent_selector_ui
        # It needs to be added to the card layout here.
        # It's already a child of the card implicitly if defined within its context,
        # but explicit add ensures it's part of this section if needed.
        # However, since update_agent_selector_ui clears and rebuilds it,
        # it should be fine as long as agent_selection_area itself is part of the card.
        # Let's ensure agent_selection_area is directly under the card section where it's logical.
        # The current structure has it defined before the card, then populated.
        # It should be defined *inside* the card context where it will live.
        # Corrected: agent_selection_area is defined outside, then added to the card.
        # This is fine, NiceGUI attaches it.

        with ui.card_actions().classes('justify-end'):
            async def start_action():
                agent_ids_to_pass = None
                if chat_params["type"] == "individual":
                    if chat_params["selected_agent_id"]:
                        agent_ids_to_pass = chat_params["selected_agent_id"] # Single ID for individual
                    else:
                        ui.notify("Please select an agent for individual chat.", type="warning")
                        return
                elif chat_params["type"] == "group":
                    if chat_params["selected_group_agents"]:
                        agent_ids_to_pass = list(chat_params["selected_group_agents"]) # List of IDs for group
                    else:
                        ui.notify("Please select at least one agent for group chat.", type="warning")
                        return
                
                if agent_ids_to_pass is not None:
                    await start_chat_session(chat_params["type"], agent_ids_to_pass)
                else:
                    # This case should ideally be caught by the specific checks above
                    ui.notify("Agent selection is incomplete.", type="negative")
            
            ui.button("Start Chat Session", on_click=start_action).props('color=primary')
            
    return card_element

# --- End of Chat Session Creation UI and Logic ---
# --- Chat Interface Page (Subtask GUI-1.4) ---

def update_chat_display(container: ui.element, session_id: str, show_reasoning: bool = False):
    """
    Renders messages within the provided container for a given chat session.
    Clears the container and re-populates it with messages.
    Handles different styling for human vs. agent messages and optional reasoning display.
    """
    gui_log(f"Updating chat display for session {session_id}, show_reasoning: {show_reasoning}", level="DEBUG")
    try:
        session = app_state["chat_sessions"].get(session_id)
        if not session:
            gui_log(f"Session {session_id} not found in update_chat_display.", level="ERROR")
            with container:
                ui.label("Chat session not found.").classes("text-negative")
            return

        session_messages = session.get("messages", [])
        container.clear()

        with container:
            if not session_messages:
                ui.label("No messages in this chat yet. Send one to start!").classes("text-italic q-pa-md text-center w-full")
            else:
                # Ensure messages are sorted by timestamp if not already
                # Assuming timestamps are float/int Unix timestamps
                sorted_messages = sorted(session_messages, key=lambda m: m.get("timestamp", 0.0))

                for msg in sorted_messages:
                    sender_id = msg.get("sender_id", "Unknown")
                    is_human = sender_id == "STEVEN_GUI_COMMANDER"
                    
                    style_info = get_sender_style(sender_id) # Reuse existing style helper
                    avatar_svg = generate_circular_avatar_svg(
                        letter=style_info['avatar_letter'],
                        avatar_bg_color_name=style_info['avatar_color_name']
                    )
                    
                    timestamp_val = msg.get("timestamp")
                    timestamp_str = ""
                    if timestamp_val:
                        try:
                            timestamp_str = datetime.fromtimestamp(float(timestamp_val)).strftime('%H:%M:%S')
                        except (ValueError, TypeError) as e:
                            gui_log(f"Error formatting timestamp '{timestamp_val}': {e}", level="WARNING")
                            timestamp_str = "Invalid Time"
                    
                    # Use ui.row to control alignment
                    with ui.row().classes('w-full my-1').classes('justify-end' if is_human else 'justify-start'):
                        # Max width for chat message for better readability
                        with ui.chat_message(
                            name=style_info['sender_display_name'],
                            stamp=timestamp_str,
                            avatar=avatar_svg,
                            sent=is_human,
                            text=[msg.get("content", "")] # Main content as list item
                        ).classes(style_info['bubble_class']).classes('max-w-[70%]') as chat_bubble:
                            if show_reasoning and msg.get("reasoning"):
                                with ui.element('div').classes('q-mt-xs'): # Reasoning container
                                    ui.label("Reasoning:").classes('text-xs text-grey-7 font-bold')
                                    # Using ui.markdown for potentially complex reasoning strings
                                    ui.markdown(f"```text\n{msg['reasoning']}\n```").classes('text-xs bg-grey-2 q-pa-xs rounded-borders')
        
        # Auto-scroll to the bottom
        # Using a more reliable method if possible, or a slight delay if needed for elements to render
        async def delayed_scroll():
            await asyncio.sleep(0.1) # Small delay to ensure elements are rendered
            container.run_method('scrollIntoView', {'block': 'end', 'behavior': 'smooth'})
        
        asyncio.create_task(delayed_scroll())
        gui_log(f"Chat display for session {session_id} updated with {len(session_messages)} messages.", level="DEBUG")

    except Exception as e:
        gui_log(f"Error in update_chat_display for session {session_id}: {e}", level="CRITICAL")
        if container:
            container.clear()
            with container:
                ui.label(f"Error loading chat: {e}").classes("text-negative")

async def send_chat_message(client: Client, session_id: str, message_text_area: ui.textarea):
    """
    Handles sending a message from the GUI.
    Appends the message to the local session and sends it to relevant agents via A2A.
    Requires client context.
    """
    gui_log(f"send_chat_message called for session {session_id}. Input area: {message_text_area}") # LOG 1
    if not message_text_area:
        gui_log(f"send_chat_message: message_text_area is None for session {session_id}", level="ERROR")
        client.notify("Error: Chat input area is not available.", type="negative")
        return

    try:
        message_text = message_text_area.value
        gui_log(f"send_chat_message: message_text is '{message_text}' for session {session_id}") # LOG 2

        if not message_text or not message_text.strip():
            gui_log(f"send_chat_message: Message is empty or whitespace for session {session_id}.", level="WARNING")
            client.notify("Message cannot be empty.", type="warning")
            return # Important: return here so finally doesn't clear if only whitespace

        gui_log(f"Sending chat message for session {session_id}: '{message_text[:50]}...'", level="INFO") # LOG 3
        
        session = app_state["chat_sessions"].get(session_id)
        if not session:
            gui_log(f"send_chat_message: Session {session_id} not found.", level="ERROR")
            client.notify("Chat session not found. Cannot send message.", type="negative")
            return

        gui_log(f"send_chat_message: Session found. Appending human message. Session: {session_id}") # LOG 4
        current_timestamp = time.time()
        human_message = {
            "sender_id": "STEVEN_GUI_COMMANDER",
            "content": message_text.strip(),
            "timestamp": current_timestamp,
            "type": "human_message"
        }
        session["messages"].append(human_message)

        is_group_chat = session.get("type") == "group"
        participants = list(session.get("agents", []))
        a2a_payload_template = {
            "session_id": session_id,
            "message_text": message_text.strip(),
            "is_group_chat": is_group_chat,
            "participants": participants,
            "sender_id": "STEVEN_GUI_COMMANDER",
            "timestamp": current_timestamp,
            "message_type": "chat_message"
        }

        agents_to_message = session.get("agents", [])
        if not agents_to_message:
            gui_log(f"send_chat_message: No agents in session {session_id} to send to.", level="WARNING")
        
        gui_log(f"send_chat_message: About to loop through agents to send A2A. Agents: {agents_to_message}. Session: {session_id}") # LOG 5
        for agent_id in agents_to_message:
            gui_log(f"Sending A2A 'chat_message' to agent {agent_id} for session {session_id}.", level="DEBUG")
            await send_a2a_message_to_minion(
                client=client, # Pass client
                minion_id=agent_id,
                message_type="chat_message",
                a2a_payload=a2a_payload_template.copy(),
                notification_verb="send chat message"
            )
            await asyncio.sleep(0.05)

        gui_log(f"send_chat_message: A2A sending loop complete. Updating display. Session: {session_id}") # LOG 6
        if 'chat_container_ref' in app_state and app_state['chat_container_ref'] and app_state.get("active_chat_session_id") == session_id:
            show_reasoning_value = False
            if hasattr(app, 'current_page_context') and 'reasoning_toggle_ref' in app.current_page_context:
                show_reasoning_value = app.current_page_context['reasoning_toggle_ref'].value
            update_chat_display(app_state['chat_container_ref'], session_id, show_reasoning=show_reasoning_value)
            gui_log(f"send_chat_message: Chat display updated. Session: {session_id}") # LOG 7
        else:
            gui_log(f"send_chat_message: Chat container ref not available for update. Session: {session_id}", level="WARNING")

    except Exception as e:
        gui_log(f"Error in send_chat_message for session {session_id}: {e}", level="CRITICAL", exc_info=True)
        client.notify(f"Error sending message: {str(e)[:100]}", type="negative")
    finally:
        # Only clear if the message wasn't just whitespace (which would have returned early)
        if message_text_area and (not message_text_area.value or message_text_area.value.strip()): # Check if message_text_area is not None
             message_text_area.set_value("")
        gui_log(f"send_chat_message: finally block executed. Input cleared if appropriate. Session: {session_id}") # LOG 8


@ui.page('/chat/{session_id}')
async def chat_session_page(client: Client, session_id: str):
    """
    Displays the chat interface for a given session_id.
    """
    # Store page-specific context if needed, e.g., for send_chat_message to access toggle state
    app.current_page_context = {} # Initialize a simple context for this page load

    session = app_state["chat_sessions"].get(session_id)
    app_state["active_chat_session_id"] = session_id # Mark this session as active

    if not session:
        ui.notify(f"Chat session {session_id} not found.", type="negative")
        gui_log(f"Chat session page: Session {session_id} not found.", level="ERROR")
        ui.navigate.to('/')
        return

    # --- Page Header ---
    with ui.header(elevated=True).classes('bg-primary text-white items-center q-pa-sm'):
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/')).props('flat round dense')
        ui.label("AI Minion Army - Chat Interface").classes('text-h6')
        ui.space()
        # Placeholder for any header actions specific to chat page

    # --- Main Chat Page Layout ---
    with ui.column().classes('w-full h-screen p-0 m-0 flex flex-col'): # Full height, flex column
        
        # --- Chat Header Card ---
        with ui.card().classes('w-full q-mb-sm rounded-none'): # No rounded corners for top card
            with ui.card_section():
                participants = session.get("agents", [])
                participant_names = [get_formatted_minion_display(pid) for pid in participants]
                if session.get("type") == "group":
                    chat_title = f"Group Chat with {len(participants)} Agent(s)"
                    if participant_names:
                        chat_title += f": {', '.join(participant_names)}"
                else: # Individual
                    chat_title = f"Chat with {participant_names[0] if participant_names else 'Unknown Agent'}"
                ui.label(chat_title).classes('text-subtitle1 font-medium')

        # --- Chat Controls ---
        with ui.row().classes('w-full items-center q-pa-sm q-gutter-sm bg-grey-2'):
            ui.button("Export Chat", on_click=lambda: ui.notify("Export chat clicked (not implemented).")).props('dense outline')
            
            reasoning_toggle = ui.toggle({False: 'Hide Reasoning', True: 'Show Reasoning'}, value=False).props('dense')
            app.current_page_context['reasoning_toggle_ref'] = reasoning_toggle # Store ref for send_chat_message

            # AI Settings Dialog
            ai_settings_dialog = ui.dialog()
            with ai_settings_dialog, ui.card().classes('q-pa-md'):
                ui.label("AI Settings").classes('text-h6 q-mb-md')
                ui.label("AI Temperature").classes('text-caption')
                # Assuming llm_config is available in app_state
                temp_slider = ui.slider(min=0.0, max=1.0, step=0.1, value=app_state.get("llm_config", {}).get("temperature", 0.7)) \
                    .on('update:model-value', lambda e: app_state.setdefault("llm_config", {}).update({"temperature": e.value}))
                ui.label().bind_text_from(temp_slider, 'value', backward=lambda v: f"{v:.1f}")
                # Add more settings here if needed
                with ui.row().classes('justify-end w-full q-mt-md'):
                    ui.button("Close", on_click=ai_settings_dialog.close).props('flat')

            ui.button("AI Settings", icon='settings', on_click=ai_settings_dialog.open).props('dense outline')
        
        # --- Chat Messages Container ---
        # This container will be filled by update_chat_display
        # It needs to be scrollable and take up most of the space
        chat_container = ui.column().classes('w-full flex-grow overflow-y-auto q-pa-sm bg-grey-1')
        app_state['chat_container_ref'] = chat_container # Store reference for A2A handler and send_chat_message

        # --- Message Input Area ---
        with ui.row().classes('w-full items-center q-pa-sm q-gutter-xs bg-grey-3'):
            chat_input_area = ui.textarea(placeholder="Type your message here...") \
                .props('outlined dense autogrow rounded clearable hide-bottom-space') \
                .classes('flex-grow')
            
            send_button = ui.button(icon='send') \
                .props('round dense color=primary') \
                .on('click', lambda: asyncio.create_task(send_chat_message(client, session_id, chat_input_area))) # Pass client
            
            chat_input_area.on('keydown.enter', lambda: asyncio.create_task(send_chat_message(client, session_id, chat_input_area))) # Pass client
            
    # --- Event Handlers and Initial Load ---
    def handle_reasoning_toggle_change(e):
        gui_log(f"Reasoning toggle changed to: {e.value} for session {session_id}", level="DEBUG")
        if 'chat_container_ref' in app_state and app_state['chat_container_ref']:
            update_chat_display(app_state['chat_container_ref'], session_id, show_reasoning=e.value)
        else:
            gui_log("Chat container ref not found for reasoning toggle update.", level="WARNING")

    reasoning_toggle.on('update:model-value', handle_reasoning_toggle_change)

    # Initial call to load messages
    # Ensure client is fully connected and page is rendered before heavy JS like scrollIntoView
    await client.connected() 
    if 'chat_container_ref' in app_state and app_state['chat_container_ref']:
        update_chat_display(app_state['chat_container_ref'], session_id, show_reasoning=reasoning_toggle.value)
    else:
        gui_log("Chat container ref not found for initial display.", level="ERROR")
        with chat_container: # Fallback if ref somehow failed
             ui.label("Error: Chat display area not initialized correctly.").classes("text-negative")

    gui_log(f"Chat page for session {session_id} loaded.", level="INFO")

    # Cleanup when client disconnects or navigates away (optional)
    async def cleanup_chat_page():
        gui_log(f"Cleaning up chat page for session {session_id}", level="DEBUG")
        if app_state.get("active_chat_session_id") == session_id:
            app_state["active_chat_session_id"] = None
        if 'chat_container_ref' in app_state: # Clear ref to avoid issues if page is reloaded differently
            app_state['chat_container_ref'] = None
        if 'current_page_context' in app: # Clear page-specific context
            del app.current_page_context
    
    client.on_disconnect(cleanup_chat_page)
    # client.on_navigation(cleanup_chat_page) # Might be too aggressive, consider specific cleanup needs

# --- End of Chat Interface Page ---

# --- Collaborative Task Creation (GUI-2.2) ---

async def handle_collaborative_task_submission(client: Client, task_description_str: str, coordinator_id: str, submit_button_ref: ui.button):
    """
    Handles the form submission for creating a new collaborative task.
    Sends an A2A message to the selected coordinator.
    Includes error handling, user feedback, and loading indicators. Requires client context.
    """
    gui_log(f"Attempting to submit collaborative task. Description: '{task_description_str[:50]}...', Coordinator: {coordinator_id}", level="INFO")

    if not task_description_str or not task_description_str.strip():
        client.notify("Task Description cannot be empty.", type="negative")
        gui_log("Collaborative task submission failed: Task Description was empty.", level="WARNING")
        return

    if not coordinator_id:
        client.notify("Coordinator Minion must be selected.", type="negative")
        gui_log("Collaborative task submission failed: Coordinator Minion not selected.", level="WARNING")
        return

    original_button_text = submit_button_ref.text
    submit_button_ref.props("loading=true icon=none")
    submit_button_ref.text = "Submitting..."

    try:
        payload = {
            "task_description": task_description_str.strip(),
            "requester_id": "STEVEN_GUI_COMMANDER"
        }

        success = await send_a2a_message_to_minion(
            client=client, # Pass client
            minion_id=coordinator_id,
            message_type="collaborative_task_request",
            a2a_payload=payload,
            notification_verb="submit collaborative task request"
        )

        if success:
            client.notify("Collaborative task submitted successfully.", type="positive")
            gui_log(f"Collaborative task request successfully sent to coordinator {coordinator_id}.", level="INFO")
            # Optionally clear form fields here if needed
    except Exception as e:
        gui_log(f"Error in handle_collaborative_task_submission: {e}", level="ERROR")
        client.notify(f"Failed to submit task: {e}", type="negative")
    finally:
        submit_button_ref.props("loading=false")
        submit_button_ref.text = original_button_text


def create_collaborative_task_ui(client: Client): # Added client
    """
    Renders the UI elements for the collaborative task definition form.
    This function should be called within the collaborative_tasks_page.
    """
    with ui.card().classes('w-full q-mb-md'):
        with ui.card_section():
            ui.label("Define New Collaborative Task").classes('text-h6')

    with ui.column() as task_form: # Changed from ui.form()
        task_description_textarea = ui.textarea(
            "Task Description",
                placeholder="Enter a detailed description of the collaborative task..."
            ).props('outlined dense autogrow required')

        # Populate coordinator selector
        minions_with_coordination_skill = {}
        coordinator_select = None # Initialize to None

        # Temporarily mark all minions as having coordination skill
        for minion_id in app_state.get("minions", {}):
            if "capabilities" not in app_state["minions"][minion_id]:
                app_state["minions"][minion_id]["capabilities"] = {}
            if "skills" not in app_state["minions"][minion_id]["capabilities"]:
                app_state["minions"][minion_id]["capabilities"]["skills"] = []
            if "task_coordination" not in app_state["minions"][minion_id]["capabilities"]["skills"]: # Avoid duplicates
                app_state["minions"][minion_id]["capabilities"]["skills"].append("task_coordination")

        try:
            for minion_id, minion_data in app_state.get("minions", {}).items():
                capabilities = minion_data.get("capabilities", {})
                skills = capabilities.get("skills", [])
                has_skill = False
                for skill in skills:
                    if isinstance(skill, str) and skill == "task_coordination":
                        has_skill = True
                        break
                    elif isinstance(skill, dict) and skill.get("name") == "task_coordination":
                        has_skill = True
                        break
                if has_skill:
                    minions_with_coordination_skill[minion_id] = get_formatted_minion_display(minion_id)
        except Exception as e:
            gui_log(f"Error populating coordinator selector in create_collaborative_task_ui: {e}", level="ERROR")
            ui.notify("Error loading coordinator options. Please try refreshing or check logs.", type="warning", multi_line=True)
            # minions_with_coordination_skill will remain as it was before the error (likely empty)

        if not minions_with_coordination_skill:
             ui.label("No minions with 'task_coordination' skill found. Cannot assign coordinator.").classes("text-negative q-mb-sm")
             # coordinator_select remains None
        else:
            coordinator_select = ui.select(
                options=minions_with_coordination_skill,
                label="Select Coordinator Minion"
            ).props('outlined dense required')

            submit_button = ui.button("Submit Collaborative Task").props('color=primary q-mt-md')

            async def submit_action():
                if coordinator_select is not None and coordinator_select.value:
                    # Pass the button reference and client to the handler
                    await handle_collaborative_task_submission(
                        client, # Pass client
                        task_description_textarea.value,
                        coordinator_select.value,
                        submit_button
                    )
                elif coordinator_select is None and not minions_with_coordination_skill:
                     client.notify("Cannot submit: No coordinator minions available with the required skill.", type="negative")
                else:
                     client.notify("Please select a coordinator minion.", type="negative")
            
            submit_button.on('click', submit_action)


@ui.page('/collaborative-tasks')
async def collaborative_tasks_page(client: Client): # Client is already a parameter here
    """
    Page for managing and creating collaborative tasks.
    Currently, it only includes the UI for creating new tasks.
    """
    # Standard Page Header
    with ui.header(elevated=True).classes('bg-primary text-white items-center q-pa-sm'):
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/')).props('flat round dense color=white')
        ui.label("Collaborative Task Management").classes('text-h6')
        ui.space()
        # Add refresh or other actions if needed later

    # Main content area for the page
    with ui.column().classes('q-pa-md items-stretch w-full'):
        # Call the function to create the task definition UI, passing client
        create_collaborative_task_ui(client)

        # Placeholder for displaying existing collaborative tasks (GUI-2.3 / GUI-2.4)
        with ui.card().classes('w-full q-mt-lg'):
            with ui.card_section():
                ui.label("Existing Collaborative Tasks (Placeholder)").classes('text-subtitle1')
                # This area will be populated by GUI-2.3/2.4 logic
                ui.label("A list or table of ongoing and completed collaborative tasks will appear here.").classes('text-italic')
                # Reference to the container for existing tasks, if needed for dynamic updates
                app_state["collaborative_tasks_container_ref"] = ui.column() # Example placeholder

# --- End of Collaborative Task Creation ---

# --- Collaborative Task Detail Page (GUI-2.5) ---
def show_task_details(task_id: str):
    """Navigates to the detailed view of a specific collaborative task."""
    gui_log(f"Attempting to show details for collaborative task: {task_id}")
    if task_id in app_state.get("collaborative_tasks", {}):
        app_state["active_collaborative_task_id"] = task_id
        ui.navigate.to(f"/collaborative-task/{task_id}")
    else:
        ui.notify(f"Task ID {task_id} not found.", type="negative")
        gui_log(f"Task ID {task_id} not found in app_state['collaborative_tasks'] for detail view.", level="WARNING")

def show_minion_details(minion_id: str):
    """Navigates to the minion detail page."""
    gui_log(f"Navigating to details page for minion: {minion_id}")
    ui.navigate.to(f"/minion/{minion_id}")

@ui.page('/collaborative-task/{task_id}')
async def task_detail_page(client: Client, task_id: str):
    """Displays the detailed information for a specific collaborative task."""
    
    # --- Page Header ---
    with ui.header(elevated=True).classes('bg-primary text-white items-center q-pa-sm'):
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/#collaborative_tasks_dashboard_tab')).props('flat round dense') # Assuming tab navigation
        ui.label(f"Task Details: {task_id}").classes('text-h6')
        ui.space()
        # Placeholder for any header actions specific to this page

    task = app_state.get("collaborative_tasks", {}).get(task_id)
    if not task:
        ui.notify(f"Collaborative task {task_id} not found.", type="negative")
        gui_log(f"Collaborative task detail page: Task {task_id} not found in app_state.", level="ERROR")
        ui.navigate.to('/') # Navigate to home or a relevant dashboard page
        return

    # Store reference to the main container for A2A refresh
    with ui.column().classes('w-full q-pa-md items-stretch') as detail_container:
        app_state['collaborative_task_detail_container_ref'] = detail_container

        # --- General Task Information Card ---
        with ui.card().classes('w-full q-mb-md'):
            with ui.card_section():
                ui.label("General Task Information").classes('text-subtitle1 font-bold q-mb-sm')
                with ui.grid(columns=2).classes('gap-y-xs'): # Two columns for key-value pairs
                    ui.label("Task ID:").classes('font-medium')
                    ui.label(task.get("task_id", "N/A"))
                    
                    ui.label("Full Description:").classes('font-medium')
                    ui.label(task.get("description", "N/A")).classes('col-span-full' if len(task.get("description", "")) > 50 else '') # Span if long
                    
                    ui.label("Status:").classes('font-medium')
                    ui.label(task.get("status", "N/A")).classes(f"status-{task.get('status', 'unknown').lower()}") # For potential styling
                    
                    ui.label("Coordinator:").classes('font-medium')
                    ui.label(get_formatted_minion_display(task.get("coordinator_id", "N/A")))

                    ui.label("Creation Time:").classes('font-medium')
                    created_at_ts = task.get("created_at")
                    created_at_str = datetime.fromtimestamp(created_at_ts).strftime('%Y-%m-%d %H:%M:%S') if created_at_ts else "N/A"
                    ui.label(created_at_str)

                    ui.label("Completion Time:").classes('font-medium')
                    completed_at_ts = task.get("completed_at")
                    completed_at_str = datetime.fromtimestamp(completed_at_ts).strftime('%Y-%m-%d %H:%M:%S') if completed_at_ts else "N/A"
                    ui.label(completed_at_str)
                    
                    ui.label("Duration:").classes('font-medium')
                    duration_str = "N/A"
                    if created_at_ts and completed_at_ts:
                        duration_seconds = completed_at_ts - created_at_ts
                        # Format duration (e.g., Xh Ym Zs)
                        m, s = divmod(duration_seconds, 60)
                        h, m = divmod(m, 60)
                        duration_str = ""
                        if h > 0: duration_str += f"{int(h)}h "
                        if m > 0 or h > 0: duration_str += f"{int(m)}m " # Show minutes if hours are present or if minutes > 0
                        duration_str += f"{s:.2f}s"
                    elif task.get("elapsed_seconds") is not None:
                         # Format duration (e.g., Xh Ym Zs)
                        m, s = divmod(task["elapsed_seconds"], 60)
                        h, m = divmod(m, 60)
                        duration_str = ""
                        if h > 0: duration_str += f"{int(h)}h "
                        if m > 0 or h > 0: duration_str += f"{int(m)}m "
                        duration_str += f"{s:.2f}s"
                    ui.label(duration_str)

        # --- Subtasks Card ---
        with ui.card().classes('w-full q-mb-md'):
            with ui.card_section():
                ui.label("Subtasks").classes('text-subtitle1 font-bold q-mb-sm')
                subtasks = task.get("subtasks", {})
                if not subtasks:
                    ui.label("No subtasks defined for this task.").classes('text-italic')
                else:
                    subtask_table_columns = [
                        {'name': 'subtask_id', 'label': 'Subtask ID', 'field': 'subtask_id', 'sortable': True, 'align': 'left'},
                        {'name': 'description', 'label': 'Description', 'field': 'description', 'sortable': True, 'align': 'left', 'classes': 'max-w-xs overflow-hidden text-ellipsis whitespace-nowrap'},
                        {'name': 'assigned_minion', 'label': 'Assigned Minion', 'field': 'assigned_minion', 'sortable': True, 'align': 'left'},
                        {'name': 'status', 'label': 'Status', 'field': 'status', 'sortable': True, 'align': 'left'},
                        {'name': 'last_updated', 'label': 'Last Updated', 'field': 'last_updated_str', 'sortable': True, 'align': 'left'},
                    ]
                    subtask_table_rows = []
                    for st_id, st_data in subtasks.items():
                        last_updated_ts = st_data.get("last_updated")
                        subtask_table_rows.append({
                            "subtask_id": st_id,
                            "description": st_data.get("description", "N/A"),
                            "assigned_minion": get_formatted_minion_display(st_data.get("assigned_to", "N/A")),
                            "status": st_data.get("status", "N/A"),
                            "last_updated_ts": last_updated_ts, # For sorting
                            "last_updated_str": datetime.fromtimestamp(last_updated_ts).strftime('%Y-%m-%d %H:%M:%S') if last_updated_ts else "N/A"
                        })
                    
                    # Sort by last_updated by default, descending
                    subtask_table_rows.sort(key=lambda x: x.get("last_updated_ts", 0), reverse=True)

                    ui.table(columns=subtask_table_columns, rows=subtask_table_rows, row_key='subtask_id').classes('w-full')

        # --- Task Results Card (GUI-2.6) ---
        if task.get("status", "").lower() == "completed" and task.get("results"):
            with ui.card().classes('w-full q-mb-md'):
                with ui.card_section():
                    ui.label("Task Results").classes('text-subtitle1 font-bold q-mb-sm')
                    results_data = task.get("results", {})
                    if isinstance(results_data, dict) and results_data:
                        for key, value in results_data.items():
                            with ui.expansion(f"Result for: {key}", icon="description").classes('w-full q-mb-xs'):
                                if isinstance(value, str):
                                    ui.markdown(value)
                                else: # If result is complex (e.g. dict/list), display as JSON for now
                                    ui.json_editor({"content": {"json": value}}).props('readonly')
                    elif isinstance(results_data, str):
                        ui.markdown(results_data)
                    elif not results_data:
                         ui.label("No results available for this task.").classes('text-italic')
                    else: # Fallback for other types
                        ui.label("Results:").classes('font-medium')
                        ui.code(str(results_data))
        
        # Add a refresh button for debugging or manual refresh
        ui.button("Refresh Page Data", on_click=lambda: detail_container.refresh(), icon='refresh').props('outline dense color=grey-7 q-mt-md')


    # Ensure the page is refreshed if it's already the active task when loaded
    # This is mainly for cases where the user navigates directly via URL
    if app_state.get("active_collaborative_task_id") == task_id and 'collaborative_task_detail_container_ref' in app_state:
        app_state['collaborative_task_detail_container_ref'].refresh()

    await client.connected() # Ensure client is connected before trying to update UI from background tasks
    # Periodically refresh this page if it's the active one, to catch updates not pushed by A2A immediately
    # This is a fallback and might be removed if A2A updates are perfectly reliable.
    # async def _periodic_refresh():
    #     while client.id in app.clients and ui.context.client.id == client.id and app_state.get("active_collaborative_task_id") == task_id:
    #         await asyncio.sleep(15) # Refresh every 15 seconds
    #         if app_state.get("active_collaborative_task_id") == task_id and 'collaborative_task_detail_container_ref' in app_state:
    #             gui_log(f"Periodic refresh for task detail page {task_id}", level="DEBUG")
    #             app_state['collaborative_task_detail_container_ref'].refresh()
    # client.on_disconnect(lambda: gui_log(f"Client disconnected from task detail page {task_id}", level="DEBUG"))
    # asyncio.create_task(_periodic_refresh())

@ui.page('/minion/{minion_id}')
async def minion_detail_page(client: Client, minion_id: str):
    """Displays detailed information about a specific minion."""
    gui_log(f"Loading detail page for minion: {minion_id}")

    # Ensure app_state['minion_detail_container_ref'] exists
    if 'minion_detail_container_ref' not in app_state:
        app_state['minion_detail_container_ref'] = {}

    page_container = ui.column().classes('w-full items-stretch q-pa-md')
    app_state['minion_detail_container_ref'][minion_id] = page_container # Store ref

    def _render_minion_details():
        page_container.clear()
        minion_data = app_state.get("minions", {}).get(minion_id)

        with page_container:
            # Header with back button
            with ui.row().classes('items-center q-mb-md w-full'):
                ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/')).props('flat round dense')
                ui.label(f"Minion Details: {get_formatted_minion_display(minion_id) if minion_data else minion_id}").classes('text-h5 q-ml-md')

            if not minion_data:
                ui.label(f"Minion with ID '{minion_id}' not found.").classes('text-h6 text-negative q-ma-md')
                return

            # Main content area
            with ui.column().classes('w-full gap-4'):
                # Minion Info Card
                with ui.card().classes('w-full'):
                    with ui.card_section():
                        ui.label("Minion Information").classes('text-subtitle1 font-bold')
                    with ui.card_section().classes('q-gutter-xs'):
                        ui.label(f"ID: {minion_id}")
                        # Formatted name is already handled by get_formatted_minion_display in header
                        ui.label(f"Status: {minion_data.get('status', 'N/A')}")
                        ui.label(f"Personality: {minion_data.get('personality', 'N/A')}")
                        ui.label(f"Description: {minion_data.get('description', 'N/A')}")
                        ui.button("Customize Personality", icon="face_retouching_natural", on_click=lambda: open_personality_dialog(minion_id)).props('q-mt-sm outline dense')
                
                # Capabilities Card
                with ui.card().classes('w-full'):
                    with ui.card_section():
                        ui.label("Capabilities").classes('text-subtitle1 font-bold')
                    with ui.card_section():
                        capabilities = minion_data.get('capabilities', {})
                        if not capabilities or not isinstance(capabilities, dict):
                            ui.label("No capabilities data available or format is unexpected.")
                        else:
                            # Skills
                            skills_list = capabilities.get('skills', minion_data.get('skills', [])) # Check capabilities first, then root
                            if skills_list:
                                ui.label("Skills:").classes('text-caption font-medium text-grey-7 q-mt-xs')
                                with ui.list().props('dense separator dense-padding'):
                                    for skill in skills_list:
                                        with ui.item():
                                            with ui.item_section():
                                                if isinstance(skill, dict):
                                                    skill_name = skill.get('name', 'N/A')
                                                    skill_version = skill.get('version')
                                                    skill_desc = skill.get('description', 'N/A')
                                                    ui.item_label(f"{skill_name}{f' (v{skill_version})' if skill_version else ''}").classes('text-body2')
                                                    if skill_desc and skill_desc != 'N/A': ui.item_label(skill_desc).props('caption').classes('text-grey-7')
                                                else:
                                                    ui.item_label(str(skill)).classes('text-body2')
                            
                            # MCP Tools
                            mcp_tools_list = capabilities.get('mcp_tools', [])
                            if mcp_tools_list:
                                ui.label("MCP Tools:").classes('text-caption font-medium text-grey-7 q-mt-sm')
                                with ui.list().props('dense separator dense-padding'):
                                    for tool in mcp_tools_list:
                                        with ui.item():
                                            with ui.item_section():
                                                if isinstance(tool, dict):
                                                    tool_name = tool.get('tool_name', 'N/A')
                                                    server_name = tool.get('server_name', 'N/A')
                                                    tool_desc = tool.get('description', 'N/A')
                                                    ui.item_label(f"{tool_name} (Server: {server_name})").classes('text-body2')
                                                    if tool_desc and tool_desc != 'N/A': ui.item_label(tool_desc).props('caption').classes('text-grey-7')
                                                else:
                                                    ui.item_label(str(tool)).classes('text-body2')
                            
                            # Language Models
                            language_models_list = capabilities.get('language_models', [])
                            if language_models_list:
                                ui.label("Language Models:").classes('text-caption font-medium text-grey-7 q-mt-sm')
                                with ui.list().props('dense separator dense-padding'):
                                    for model in language_models_list:
                                        with ui.item():
                                            with ui.item_section():
                                                if isinstance(model, dict):
                                                    model_name = model.get('model_name', 'N/A')
                                                    provider = model.get('provider', 'N/A')
                                                    ui.item_label(f"{model_name} (Provider: {provider})").classes('text-body2')
                                                else:
                                                    ui.item_label(str(model)).classes('text-body2')
                            
                            # Other Capability Types (Generic Display)
                            other_cap_types = [k for k in capabilities.keys() if k not in ['skills', 'mcp_tools', 'language_models'] and capabilities[k]]
                            if other_cap_types:
                                ui.label("Other Defined Capabilities:").classes('text-caption font-medium text-grey-7 q-mt-sm')
                                with ui.list().props('dense separator dense-padding'):
                                    for cap_type_key in other_cap_types:
                                        cap_value = capabilities[cap_type_key]
                                        display_val = str(cap_value)
                                        if isinstance(cap_value, list) and len(cap_value) > 3:
                                            display_val = f"{len(cap_value)} items"
                                        elif isinstance(cap_value, dict) and len(cap_value) > 3:
                                            display_val = f"{len(cap_value)} keys"

                                        with ui.item():
                                            with ui.item_section():
                                                ui.item_label(f"{cap_type_key.replace('_', ' ').title()}: {display_val[:100]}{'...' if len(display_val) > 100 else ''}").classes('text-body2')


                # Collaborative Tasks Card
                with ui.card().classes('w-full'):
                    with ui.card_section():
                        ui.label("Collaborative Tasks Involvement").classes('text-subtitle1 font-bold')
                    with ui.card_section():
                        coordinated_tasks_list = []
                        participated_subtasks_list = []
                        all_collab_tasks = app_state.get("collaborative_tasks", {})
                        active_task_statuses = ['pending', 'in_progress', 'awaiting_subtask_completion', 'decomposing', 'awaiting_coordination']


                        for task_id_loop, task_data_loop in all_collab_tasks.items():
                            task_status_lower = task_data_loop.get('status', '').lower()
                            if task_data_loop.get('coordinator_id') == minion_id and task_status_lower in active_task_statuses:
                                coordinated_tasks_list.append(task_data_loop)
                            
                            for subtask_id_loop, subtask_data_loop in task_data_loop.get('subtasks', {}).items():
                                subtask_status_lower = subtask_data_loop.get('status', '').lower()
                                if subtask_data_loop.get('assigned_to') == minion_id and subtask_status_lower in active_task_statuses:
                                    participated_subtasks_list.append({
                                        "parent_task_id": task_id_loop,
                                        "parent_description": task_data_loop.get("description", "N/A"),
                                        "subtask_description": subtask_data_loop.get("description", "N/A"),
                                        "status": subtask_data_loop.get("status", "N/A"),
                                        "id": subtask_id_loop
                                    })
                        
                        if not coordinated_tasks_list and not participated_subtasks_list:
                            ui.label("Not actively involved in any collaborative tasks.").classes('text-italic')
                        
                        if coordinated_tasks_list:
                            ui.label("Tasks Coordinated by this Minion (Active):").classes('text-body1 q-mt-sm q-mb-xs font-medium')
                            with ui.list().props('bordered separator dense'):
                                for task in coordinated_tasks_list:
                                    with ui.item():
                                        with ui.item_section():
                                            ui.item_label(f"Task ID: {task.get('task_id')}")
                                            ui.item_label(f"Desc: {task.get('description', 'N/A')[:70]}{'...' if len(task.get('description', 'N/A')) > 70 else ''}").props('caption')
                                            ui.item_label(f"Status: {task.get('status', 'N/A')}")
                                            active_subtasks = [s for s_id, s in task.get('subtasks', {}).items() if s.get('status','').lower() in active_task_statuses]
                                            completed_subtasks = [s for s_id, s in task.get('subtasks', {}).items() if s.get('status','').lower() == 'completed']
                                            ui.item_label(f"Subtasks: {len(completed_subtasks)}/{len(task.get('subtasks', {}))} done ({len(active_subtasks)} active)").props('caption')
                                        with ui.item_section(side=True):
                                            ui.button("View Task", on_click=lambda t_id=task.get('task_id'): show_task_details(t_id)).props('flat dense size=sm')
                        
                        if participated_subtasks_list:
                            ui.label("Subtasks Assigned to this Minion (Active):").classes('text-body1 q-mt-md q-mb-xs font-medium')
                            with ui.list().props('bordered separator dense'):
                                for subtask in participated_subtasks_list:
                                    with ui.item():
                                        with ui.item_section():
                                            ui.item_label(f"Parent: {subtask['parent_task_id']} ({subtask['parent_description'][:30]}{'...' if len(subtask['parent_description']) > 30 else ''})")
                                            ui.item_label(f"Subtask: {subtask['subtask_description'][:70]}{'...' if len(subtask['subtask_description']) > 70 else ''}").props('caption')
                                            ui.item_label(f"Status: {subtask['status']}")
                                        with ui.item_section(side=True):
                                            ui.button("View Parent", on_click=lambda pt_id=subtask['parent_task_id']: show_task_details(pt_id)).props('flat dense size=sm')
                
                # Debug Console Integration
                with ui.card().classes('w-full'):
                    with ui.card_section():
                        ui.label("Debug Console").classes('text-subtitle1 font-bold')
                    with ui.card_section():
                        create_debug_console_ui(client, minion_id) # Pass client

    _render_minion_details() # Initial render

    # Optional: Set up a timer to refresh if minion data might change from other sources
    # For now, rely on navigation or manual refresh for simplicity, or A2A updates if they trigger this page's refresh.
    # If app_state['minions'][minion_id] is updated by an A2A message handler, that handler
    # could check if app_state['minion_detail_container_ref'][minion_id] exists and call its refresh/clear+re-render.

    async def on_disconnect():
        gui_log(f"Client disconnected from minion detail page for {minion_id}. Cleaning up container reference.")
        if minion_id in app_state.get('minion_detail_container_ref', {}):
            del app_state['minion_detail_container_ref'][minion_id]
            if not app_state['minion_detail_container_ref']: # if dict becomes empty
                del app_state['minion_detail_container_ref'] # remove the key itself
    client.on_disconnect(on_disconnect)

def update_chat_log_display():
    if not chat_log_area: # chat_log_area is now the ui.column
        gui_log("Chat display column (chat_log_area) not initialized.", level="WARNING")
        return

    # Normalize and sort all chat messages by timestamp (existing logic, good to keep)
    try:
        for i, msg_item in enumerate(app_state["chat_messages"]):
            ts = msg_item.get('timestamp')
            if isinstance(ts, str):
                try:
                    app_state["chat_messages"][i]['timestamp'] = float(ts)
                except ValueError:
                    try:
                        ts_to_parse = ts
                        if ts_to_parse.endswith("Z"): ts_to_parse = ts_to_parse[:-1] + "+00:00"
                        app_state["chat_messages"][i]['timestamp'] = datetime.fromisoformat(ts_to_parse).timestamp()
                    except ValueError:
                        gui_log(f"Chat log: Could not convert timestamp string '{ts}' to float. Using 0.0.", level="WARNING")
                        app_state["chat_messages"][i]['timestamp'] = 0.0
            elif not isinstance(ts, (float, int)):
                gui_log(f"Chat log: Invalid timestamp type '{type(ts)}'. Using 0.0.", level="WARNING")
                app_state["chat_messages"][i]['timestamp'] = 0.0
        
        app_state["chat_messages"].sort(key=lambda m: m.get('timestamp', 0.0))
    except Exception as e:
        gui_log(f"Error sorting/normalizing chat messages: {e}", level="ERROR")

    chat_log_area.clear() # Clear the column

    if not app_state["chat_messages"]:
        with chat_log_area:
            ui.label("No communications logged yet.").classes('text-italic q-pa-md text-center w-full')
        return

    with chat_log_area: # Add messages to the column
        for msg in app_state["chat_messages"]:
            sender_id = msg.get("sender_id", "Unknown")
            content_str = str(msg.get('content', '')) # Ensure content is string
            timestamp_val = msg.get('timestamp', 0.0)
            message_type = msg.get("type") # Get the message type
            
            timestamp_str = "No Time"
            if isinstance(timestamp_val, (float, int)) and timestamp_val > 0:
                try:
                    dt_object = datetime.fromtimestamp(timestamp_val)
                    timestamp_str = dt_object.strftime("%H:%M:%S")
                except (TypeError, ValueError) as e:
                    gui_log(f"Error formatting timestamp {timestamp_val}: {e}", level="WARNING")
                    timestamp_str = "Invalid Time"

            style_info = get_sender_style(sender_id)
            avatar_svg = generate_circular_avatar_svg(
                letter=style_info['avatar_letter'],
                avatar_bg_color_name=style_info['avatar_color_name']
            )
            
            is_sent_by_steven = sender_id == "STEVEN_GUI_COMMANDER"

            # Prepare content elements for ui.chat_message
            chat_content_elements = []
            if message_type == 'reply':
                # Render 'reply' type messages (from minions) as Markdown
                # The ui.markdown element handles its own styling for markdown content.
                chat_content_elements.append(ui.markdown(content_str))
            else:
                # For other types (e.g., 'directive' from STEVEN_GUI_COMMANDER), use a label with previous styling
                label_element = ui.label(content_str).classes('whitespace-pre-wrap text-sm text-black dark:text-white')
                chat_content_elements.append(label_element)

            cm = ui.chat_message(
                # text parameter removed, content will be added using 'with cm:'
                name=style_info['sender_display_name'],
                stamp=timestamp_str,
                avatar=avatar_svg,
                sent=is_sent_by_steven
            )
            cm.classes(style_info['bubble_class'])
            cm.classes('q-pa-sm') # Padding for the entire bubble

            with cm:
                with ui.row().classes('items-center justify-between w-full no-wrap'): # Ensure button stays on the same line
                    # Add the actual message content (markdown or label)
                    # chat_content_elements is a list with one element
                    if chat_content_elements:
                        with ui.column().classes('col'): # Allow content to take available space
                             chat_content_elements[0].classes('min-w-0') # Ensure content can shrink if needed
                    
                    ui.button(
                        icon='content_copy',
                        on_click=lambda bound_content=content_str: copy_message_to_clipboard(bound_content)
                    ).props('flat dense round color=grey-7').tooltip('Copy message text')
    
    # Scroll to the bottom of the chat area after updating
    # Note: Direct scroll manipulation in NiceGUI can be tricky.
    # This is a common pattern, but might need adjustment based on NiceGUI version/behavior.
    ui.run_javascript(f'getElement({chat_log_area.id}).scrollTop = getElement({chat_log_area.id}).scrollHeight')
    # gui_log(f"Chat log display refreshed with {len(app_state['chat_messages'])} messages.")


# --- UI Layout ---
@ui.page('/')
async def main_page(client: Client):
    global status_label, minion_cards_container, command_input, broadcast_status_area, \
           last_broadcast_label, chat_log_area, minion_filter_input
    
    # For dark mode preference (optional)
    # await client.connected() # Ensure client is connected before checking dark mode
    # if await client.javascript('window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches'):
    #     ui.dark_mode().enable()
    # else:
    #     ui.dark_mode().disable()
    ui.dark_mode().enable() # Codex Omega prefers dark mode for operational focus.

    with ui.header().classes('bg-primary text-white items-center'):
        ui.label("AI Minion Army - Command Center").classes('text-h5')
        ui.space()
        # status_label is a global variable, assigned here.
        # Initialize with a default text as per recommendation.
        status_label = ui.label("A2A Server: Initializing...")
        
        # Store the reference in app_state for reliable access by fetch_a2a_server_status
        if 'ui_elements' not in app_state:
            app_state['ui_elements'] = {}
        app_state['ui_elements']['a2a_status_label'] = status_label
        
        ui.button(icon='refresh', on_click=fetch_a2a_server_status, color='white').tooltip("Refresh A2A Server Status")

    with ui.left_drawer(value=True, bordered=True).classes('bg-grey-2 q-pa-md') as left_drawer:
        ui.label("Navigation").classes('text-bold q-mb-md text-grey-8')
        with ui.list():
            with ui.item().classes('cursor-pointer').on('click', lambda: ui.navigate.to('/')):
                with ui.item_section().props('avatar'):
                    ui.icon('home', color='grey-8')
                with ui.item_section():
                    ui.label("Dashboard").classes('text-grey-8')
            with ui.item().classes('cursor-pointer').on('click', lambda: ui.navigate.to('/collaborative-tasks')):
                with ui.item_section().props('avatar'):
                    ui.icon('groups', color='grey-8')
                with ui.item_section():
                    ui.label("Collaborative Tasks").classes('text-grey-8')
            with ui.item().classes('cursor-pointer').on('click', lambda: ui.navigate.to('/system-configuration')):
                with ui.item_section().props('avatar'):
                    ui.icon('settings_applications', color='grey-8')
                with ui.item_section():
                    ui.label("System Configuration").classes('text-grey-8')
            
            # Add more navigation items here if needed in future versions
            # e.g., Minion Detail Page, Task Management Page, System Settings Page

    # Main content area
    # ui.page_container() removed
    with ui.column().classes('q-pa-md items-stretch w-full'):
        
        # Section: Minion Control & Broadcast
        with ui.card().classes('w-full q-mb-md'):
            with ui.card_section():
                ui.label("Minion Command & Control").classes('text-h6')
            with ui.card_section():
                command_input = ui.textarea(label="Broadcast Directive to All Minions", placeholder="e.g., Initiate icebreaker protocols. Introduce yourselves to each other. Define initial roles.").props('outlined autogrow')
                ui.button("Broadcast Directive", on_click=lambda: broadcast_message_to_all_minions(client, command_input.value)).classes('q-mt-sm') # Pass client
                last_broadcast_label = ui.label("Last Broadcast: None").classes('text-caption q-mt-xs')
            broadcast_status_area = ui.card_section().classes('q-gutter-xs') # For individual send statuses

        # Section: Communications Log (NEW)
        with ui.card().classes('w-full q-mb-md'):
            with ui.card_section().classes('row items-center justify-between'):
                ui.label("Communications Log").classes('text-h6')
                ui.button(icon='refresh', on_click=fetch_commander_messages, color='primary').props('flat dense round').tooltip("Refresh Commander Messages")
            with ui.card_section().classes('q-pa-none'): # Remove padding for the log itself
                # chat_log_area will now be a ui.column for ui.chat_message elements
                # Styling: h-64 for fixed height, overflow-y-auto for scrolling, q-pa-sm for padding inside the container
                chat_log_area = ui.column().classes('w-full h-64 overflow-y-auto q-pa-sm rounded-borders bg-grey-1')
                # Initial population will be handled by update_chat_log_display called later
        
        # Section: Minion Army Status
        with ui.card().classes('w-full q-mb-md'):
            with ui.card_section().classes('column items-stretch'): # Use column for better layout of title and controls
                with ui.row().classes('justify-between items-center w-full'):
                    ui.label("Minion Army Status").classes('text-h6')
                    with ui.row().classes('items-center q-gutter-sm'): # Group refresh and spawn buttons
                        ui.button(icon='add_circle_outline', on_click=open_spawn_minion_dialog, color='positive').props('flat dense').tooltip("Spawn New Minion")
                        ui.button(icon='refresh', on_click=fetch_registered_minions).props('flat dense').tooltip("Refresh Minion List (clears filter if active)")
                
                minion_filter_input = ui.input(placeholder="Filter minions by name, ID, capability...", on_change=lambda e, c=client: update_minion_display(client=c)) \
                    .props('dense outlined clearable').classes('w-full q-mt-sm') \
                    .tooltip("Enter text to filter minions by name, ID, description, personality, or any capability detail.")

            minion_cards_container = ui.card_section() # Minion cards will be rendered here
            # Initial call to populate
            await fetch_registered_minions() # This will call update_minion_display which now uses the filter


        # Section: System Logs (placeholder for now)
        # BIAS_ACTION: A proper log viewer would be more complex, involving tailing files
        # or a dedicated logging service. For V1, this is a conceptual placeholder.
        with ui.card().classes('w-full'):
            with ui.card_section():
                ui.label("System Event Feed (Conceptual)").classes('text-h6')
            with ui.card_section():
                # This area would be dynamically updated with key system events
                # For now, it's static.
                ui.label("Recent critical system events would appear here...")
                # Example: ui.log().classes('h-48 w-full bg-black text-white') to show live logs

    with ui.footer().classes('bg-grey-3 text-black q-pa-sm text-center'):
        ui.label(f"AI Minion Army Command Center v1.0 - Codex Omega Genesis - User: Steven - Deployed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # Setup periodic refresh for server status and minion list
    # BIAS_CHECK: Frequent polling can be inefficient. Consider websockets or SSE for A2A server if it supports it.
    # For V1, polling is simpler to implement.
    # Use intervals from ConfigManager
    ui.timer(GUI_SERVER_STATUS_POLLING_INTERVAL_SECONDS, fetch_a2a_server_status, active=True)
    ui.timer(GUI_MINION_LIST_POLLING_INTERVAL_SECONDS, fetch_registered_minions, active=True)
    ui.timer(GUI_COMMANDER_MESSAGE_POLLING_INTERVAL_SECONDS, fetch_commander_messages, active=True)
    
    # Initial fetch on page load
    await fetch_a2a_server_status()
    # fetch_registered_minions is already called after container creation
    await fetch_commander_messages() # Initial fetch for commander messages
    update_chat_log_display() # Ensure chat log is populated on initial load / refresh after all fetches

@ui.page('/system-configuration')
async def system_configuration_page(client: Client):
    """
    Page for displaying system-level configurations like LLM settings and MCP Tool Management.
    """
    ui.dark_mode().enable() # Consistent dark mode
    # --- Header ---
    with ui.header(elevated=True).classes('bg-primary text-white items-center q-pa-sm'):
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to('/')).props('flat round dense color=white')
        ui.label("System Configuration").classes('text-h6')
        ui.space()

    # --- Main Content Area for System Configuration ---
    with ui.column().classes('q-pa-md items-stretch w-full'):
        ui.label("Manage system-wide settings for LLMs and MCP Tools.").classes('text-subtitle1 q-mb-md text-grey-8')
        
        create_model_config_ui(client) # Pass client
        create_tool_management_ui(client) # Pass client here too, as it calls fetch_available_tools which might use notify

        ui.element('div').classes('q-mt-xl') # Spacer

# --- System Monitoring Dashboard Page (GUI-4.1) ---
@ui.page('/system-dashboard')
async def system_dashboard_page(client: Client):
    """Displays system-wide monitoring information."""
    ui.dark_mode().enable() # Consistent dark mode

    # Header
    with ui.header(elevated=True).classes('bg-primary text-white items-center q-pa-sm'):
        ui.button(icon='arrow_back', on_click=lambda: ui.navigate.to("/")).props('flat round dense color=white')
        ui.label("System Monitoring Dashboard").classes('text-h6')
        ui.space()
        # Consider adding a refresh button that calls a data fetch and UI update function
        # ui.button(icon='refresh', on_click=system_dashboard_page.refresh).props('flat round dense color=white')

    with ui.column().classes('q-pa-md items-stretch w-full gap-4'): # Added gap-4 for spacing between cards
        # System Status Card
        with ui.card().classes('w-full'):
            with ui.card_section():
                ui.label("System Status").classes('text-h6')
            with ui.card_section().classes('q-gutter-md'): # q-gutter-md for spacing between elements if multiple rows
                with ui.row().classes('items-center w-full justify-around'):
                    with ui.card().classes('text-center q-pa-md min-w-[180px] shadow-2 rounded-borders'): # Added styling
                        ui.label("A2A Server Status").classes('text-subtitle2 text-grey-7')
                        a2a_status_val = app_state.get("a2a_server_status", "Unknown")
                        a2a_status_color = 'positive' if a2a_status_val == "Online" else ('negative' if "Error" in a2a_status_val or "Offline" in a2a_status_val else 'warning')
                        ui.badge(a2a_status_val, color=a2a_status_color).classes('text-body1 q-mt-xs q-pa-xs')
                    
                    with ui.card().classes('text-center q-pa-md min-w-[180px] shadow-2 rounded-borders'):
                        ui.label("Active Minions").classes('text-subtitle2 text-grey-7')
                        ui.label(str(len(app_state.get("minions", {})))).classes('text-h5 q-mt-xs font-weight-bold')

                    with ui.card().classes('text-center q-pa-md min-w-[180px] shadow-2 rounded-borders'):
                        ui.label("Collaborative Tasks").classes('text-subtitle2 text-grey-7')
                        # Display total number of collaborative tasks as per instruction
                        ui.label(str(len(app_state.get("collaborative_tasks", {})))).classes('text-h5 q-mt-xs font-weight-bold')
        
        # Minion Status Summary Card
        with ui.card().classes('w-full'):
            with ui.card_section():
                ui.label("Minion Status Summary").classes('text-h6')
            with ui.card_section():
                minion_statuses = {
                    "Idle": 0, "Running": 0, "Paused": 0, "Error": 0, "Unknown": 0,
                    "Pausing...": 0, "Resuming...": 0, "Initializing": 0, # Added Initializing
                }
                # Quasar standard colors: positive, negative, warning, info, dark, primary, secondary, accent
                status_colors_map = {
                    "Idle": "positive", "Running": "primary",
                    "Paused": "warning", "Error": "negative",
                    "Unknown": "grey-6", # More specific grey
                    "Pausing...": "orange-8", "Resuming...": "light-blue-7",
                    "Initializing": "info"
                }

                minions_list = app_state.get("minions", {}).values()
                if not minions_list:
                    ui.label("No minions registered to display status for.").classes('text-italic q-pa-sm')
                else:
                    for minion_data in minions_list:
                        status = minion_data.get("status", "Unknown")
                        if status in minion_statuses:
                            minion_statuses[status] += 1
                        else:
                            minion_statuses["Unknown"] += 1
                            gui_log(f"Dashboard: Encountered unexpected minion status '{status}'. Categorized as Unknown.", level="WARNING")
                    
                    with ui.row().classes('items-stretch w-full justify-around q-gutter-sm'): # items-stretch for equal height cards
                        displayed_statuses = 0
                        for status, count in sorted(minion_statuses.items()): # Sort for consistent order
                            if count > 0: # Only display statuses with minions
                                displayed_statuses +=1
                                with ui.card().classes('text-center q-pa-sm min-w-[130px] flex-grow shadow-1 rounded-borders'): # flex-grow for responsiveness
                                    ui.label(status).classes('text-caption text-grey-8')
                                    ui.badge(str(count), color=status_colors_map.get(status, "dark")).classes('text-h6 q-mt-xs q-pa-xs')
                        if displayed_statuses == 0 and minions_list: # All minions have unknown or unmapped statuses
                             ui.label("All registered minions have an unclassified status.").classes('text-italic q-pa-sm')


    # Setup a timer to refresh the data on this page periodically.
    # This is a simple way to keep the dashboard updated.
    # More sophisticated would be to use app.storage or client-specific updates.
    # For now, this will re-run the page function for the client.
    # Note: This creates a new timer each time the page is loaded.
    # A better approach for page-specific timers might involve client.on_connect and client.on_disconnect
    # or ensuring the timer is only created once.
    # However, for this task, a simple periodic refresh of the page content is acceptable.
    # async def refresh_dashboard_data():
    #     await fetch_a2a_server_status() # Ensure this updates app_state
    #     await fetch_registered_minions() # Ensure this updates app_state
    #     # Fetch collaborative tasks if needed for the count
    #     system_dashboard_page.refresh() # This re-runs the current page function

    # if client.has_socket_connection: # Only set timer if client is connected
    #    ui.timer(15, refresh_dashboard_data, active=True) # Refresh every 15s

# --- Entry point for running the GUI ---
def run_gui(host, port):
    gui_log(f"Starting Management GUI on http://{host}:{port}")
    # BIAS_CHECK: Ensure uvicorn is a dependency if not bundled with NiceGUI's default run method.
    # NiceGUI's ui.run handles server choice (uvicorn, hypercorn).
    # storage_secret is important for client sessions, especially if app.storage.user or app.storage.general are used.
    # Codex Omega Mandate: Generate a random secret for this deployment.
    # This is NOT cryptographically secure for production secrets but fine for NiceGUI's session management.
    generated_storage_secret = os.urandom(16).hex()
    gui_log(f"Generated NiceGUI storage_secret: {'*' * len(generated_storage_secret)}") # Don't log the actual secret

    # Ensure logs directory exists before starting timers that might log
    if not os.path.exists(LOGS_DIR):
        os.makedirs(LOGS_DIR)
        gui_log(f"Created logs directory: {LOGS_DIR}")

    # Global periodic tasks (should ideally be started once)
    # These are started when run_gui is called.
    # If run_gui can be called multiple times in some scenarios (e.g. testing), ensure timers are handled correctly.
    # For a typical single server start, this is fine.
    if not hasattr(app, 'startup_tasks_initialized'): # Simple flag to run once
        gui_log("Initializing global periodic tasks for GUI.")
        ui.timer(GUI_SERVER_STATUS_POLLING_INTERVAL_SECONDS, fetch_a2a_server_status, active=True)
        ui.timer(GUI_MINION_LIST_POLLING_INTERVAL_SECONDS, fetch_registered_minions, active=True)
        ui.timer(GUI_COMMANDER_MESSAGE_POLLING_INTERVAL_SECONDS, fetch_commander_messages, active=True)
        # ui.timer(COLLABORATIVE_TASK_POLLING_INTERVAL_SECONDS, fetch_collaborative_tasks, active=True) # If needed
        app.startup_tasks_initialized = True


    ui.run(
        host=host,
        port=port,
        title="Minion Army Command Center",
        dark=True, # Codex Omega's preference
        reload=False, # Set to True for development, False for "production" deployment of this script
        storage_secret=generated_storage_secret,
        # uvicorn_logging_level='warning' # Reduce uvicorn verbosity if needed
    )

if __name__ == "__main__":
    # This allows running the GUI directly for testing.
    # ConfigManager handles BASE_PROJECT_DIR internally.
    # No need to set os.environ["BASE_PROJECT_DIR"] here anymore.
    
    # Get GUI host/port from ConfigManager for direct run
    GUI_HOST_RUN = config.get_str("gui.host", "127.0.0.1")
    GUI_PORT_RUN = config.get_int("gui.port", 8081)

    # Ensure app_state['llm_config'] is initialized from the main config if not already set
    # This provides defaults for the LLM config UI if it's the first thing loaded.
    if "llm_config" not in app_state or not app_state["llm_config"]: # Check if it's missing or empty
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
    
    # gui_log is defined before this block, so it's safe to call.
    gui_log(f"Attempting to run GUI directly on {GUI_HOST_RUN}:{GUI_PORT_RUN} (if not imported).")
    run_gui(host=GUI_HOST_RUN, port=GUI_PORT_RUN)
