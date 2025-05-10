import os
import time
import sys
import json
import asyncio
import urllib.parse
from nicegui import ui, app, Client
import requests
from datetime import datetime

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
    "last_commander_reply_timestamp": 0.0 # Tracks the timestamp of the last fetched reply for STEVEN_GUI_COMMANDER
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
    try:
        # Assuming A2A server has a /status or /health endpoint
        response = await asyncio.to_thread(requests.get, f"{A2A_SERVER_URL}/status", timeout=5)
        if response.status_code == 200:
            app_state["a2a_server_status"] = "Online"
            gui_log("A2A Server is Online.")
        else:
            app_state["a2a_server_status"] = f"Error: {response.status_code}"
            gui_log(f"A2A Server status error: {response.status_code}", level="ERROR")
    except requests.exceptions.RequestException as e:
        app_state["a2a_server_status"] = "Offline/Error"
        gui_log(f"Failed to connect to A2A server: {e}", level="ERROR")
    status_label.set_text(f"A2A Server: {app_state['a2a_server_status']}")


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
                    gui_log(f"Skipping agent card due to missing 'id': {str(agent_card)[:100]}", level="WARNING")
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
                    "last_seen": datetime.utcnow().isoformat()
                }
            gui_log(f"Fetched {len(app_state['minions'])} minions. GUI state uses 'name_display'.")
            update_minion_display() # This will now use the filter text if minion_filter_input is initialized
        else:
            gui_log(f"Failed to fetch minions, A2A server status: {response.status_code}", level="ERROR")
    except requests.exceptions.RequestException as e:
        gui_log(f"Error fetching minions: {e}", level="ERROR")
    except json.JSONDecodeError as e:
        gui_log(f"Error decoding minions response from A2A server: {e}", level="ERROR")


async def broadcast_message_to_all_minions(message_content_str):
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
            # Run synchronous requests in a separate thread to avoid blocking NiceGUI's async loop
            response = await asyncio.to_thread(
                requests.post, endpoint, json=message_payload, timeout=10
            )
            if response.status_code in [200, 201, 202, 204]:
                gui_log(f"Message sent to {minion_id} successfully.")
                with broadcast_status_area:
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
            
            processed_messages = []
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

        if needs_minion_display_update and minion_cards_container:
            update_minion_display()


async def send_a2a_message_to_minion(minion_id: str, message_type: str, a2a_payload: dict, notification_verb: str = "send message"):
    """
    Helper function to send a generic A2A message to a specific minion.
    `a2a_payload` should be the complete message structure expected by the minion.
    """
    gui_log(f"Attempting to {notification_verb} to {minion_id} of type {message_type} with payload: {str(a2a_payload)[:200]}")
    endpoint = f"{A2A_SERVER_URL}/agents/{minion_id}/messages"
    
    # Ensure the payload includes sender_id and timestamp if not already present
    # These are often added by the A2A client library or server, but good practice for direct calls.
    if "sender_id" not in a2a_payload:
        a2a_payload["sender_id"] = "STEVEN_GUI_COMMANDER"
    if "timestamp" not in a2a_payload:
        a2a_payload["timestamp"] = time.time()
    if "message_type" not in a2a_payload: # Ensure message_type is in the payload itself if required by minion
        a2a_payload["message_type"] = message_type

    try:
        response = await asyncio.to_thread(
            requests.post, endpoint, json=a2a_payload, timeout=10
        )
        if response.status_code in [200, 201, 202, 204]: # Common success codes
            gui_log(f"Successfully initiated {notification_verb} to {minion_id} (type: {message_type}).")
            ui.notify(f"Request to {notification_verb} to {get_formatted_minion_display(minion_id)} sent.", type='positive')
            return True
        else:
            error_detail = f"status code {response.status_code}"
            try: error_detail = response.json().get("details", error_detail)
            except json.JSONDecodeError: pass
            gui_log(f"Failed to {notification_verb} to {minion_id} (type: {message_type}). Status: {response.status_code}, Resp: {response.text[:100]}", level="ERROR")
            ui.notify(f"Failed to {notification_verb} to {get_formatted_minion_display(minion_id)}: {error_detail}", type='negative', multi_line=True)
            return False
    except requests.exceptions.RequestException as e:
        gui_log(f"Exception during {notification_verb} to {minion_id} (type: {message_type}): {e}", level="ERROR")
        ui.notify(f"Error connecting to server to {notification_verb} for {get_formatted_minion_display(minion_id)}: {e}", type='negative', multi_line=True)
        return False
    except Exception as e:
        gui_log(f"Unexpected error during {notification_verb} to {minion_id} (type: {message_type}): {e}", level="CRITICAL")
        ui.notify(f"Unexpected error trying to {notification_verb} for {get_formatted_minion_display(minion_id)}: {e}", type='negative', multi_line=True)
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
                ui.button("Create Minion", on_click=lambda: (
                    handle_spawn_minion({
                        "user_facing_name": form_data["user_facing_name"].value,
                        "minion_id_prefix": form_data["minion_id_prefix"].value,
                        "llm_config_profile": form_data["llm_config_profile"].value,
                        "capabilities": form_data["capabilities"], # This is already a list
                        "config_overrides_str": form_data["config_overrides_str"].value
                    }),
                    dialog.close()
                )).props('color=primary')

    dialog.open()

# --- UI Display Updaters ---
minion_cards_container = None # Will be defined in create_ui
chat_log_area = None # Will be defined in main_page for the chat log
minion_filter_input = None # Will be defined in main_page for filtering

def update_minion_display():
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
                            if current_status in ["Running", "Idle", "Unknown"]: # Assuming "Unknown" might be pausable
                                ui.button("Pause", on_click=lambda mid=agent_id_key: handle_pause_minion(mid), color='orange').props('dense')
                            elif current_status == "Paused":
                                ui.button("Resume", on_click=lambda mid=agent_id_key: handle_resume_minion(mid), color='green').props('dense')
                                ui.button("Send Msg", on_click=lambda mid=agent_id_key: open_send_message_to_paused_dialog(mid), color='blue').props('dense')
                            elif current_status in ["Pausing...", "Resuming..."]:
                                ui.spinner(size='sm').classes('q-ml-md') # Show a spinner if transitioning

    gui_log("Minion display updated with process control buttons.")


# --- Process Control Action Handlers (Placeholder implementations) ---
async def handle_pause_minion(minion_id: str):
    gui_log(f"GUI: Initiating PAUSE for minion: {minion_id}")
    payload = {
        "message_type": "control_pause_request", # This is the A2A message type
        "target_minion_id": minion_id, # Explicitly target
        # Minimal payload as per design doc, actual content might be just routing info for A2A server
    }
    success = await send_a2a_message_to_minion(minion_id, "control_pause_request", payload, notification_verb="pause minion")
    if success:
        # Optimistically update status, will be confirmed by ack or state_update
        if minion_id in app_state["minions"]:
            app_state["minions"][minion_id]["status"] = "Pausing..."
            update_minion_display()

async def handle_resume_minion(minion_id: str):
    gui_log(f"GUI: Initiating RESUME for minion: {minion_id}")
    payload = {
        "message_type": "control_resume_request",
        "target_minion_id": minion_id,
    }
    success = await send_a2a_message_to_minion(minion_id, "control_resume_request", payload, notification_verb="resume minion")
    if success:
        if minion_id in app_state["minions"]:
            app_state["minions"][minion_id]["status"] = "Resuming..."
            update_minion_display()

async def handle_send_message_to_paused_minion(minion_id: str, message_text: str):
    gui_log(f"GUI: Sending message to PAUSED minion {minion_id}: {message_text[:50]}...")
    if not message_text.strip():
        ui.notify("Message content cannot be empty.", type='warning')
        return

    payload = {
        "message_type": "message_to_paused_minion_request",
        "target_minion_id": minion_id, # Ensure target_minion_id is part of the payload if needed by A2A server/minion logic
        "message_content": message_text,
        # "timestamp" will be added by send_a2a_message_to_minion helper
    }
    await send_a2a_message_to_minion(minion_id, "message_to_paused_minion_request", payload, notification_verb="send message to paused minion")
    # Confirmation is handled by send_a2a_message_to_minion or ack

def open_send_message_to_paused_dialog(minion_id: str):
    minion_display_name = get_formatted_minion_display(minion_id)
    with ui.dialog() as dialog, ui.card().classes('min-w-[500px]'):
        ui.label(f"Send Message to Paused Minion: {minion_display_name}").classes('text-h6')
        message_input = ui.textarea(label="Your message:", placeholder="Enter instructions or information...").props('outlined dense autogrow autofocus')
        with ui.row().classes('justify-end w-full q-mt-md'):
            ui.button("Cancel", on_click=dialog.close, color='grey').props('flat')
            ui.button("Send", on_click=lambda: (
                handle_send_message_to_paused_minion(minion_id, message_input.value),
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
                label_element = ui.label(content_str).classes('whitespace-pre-wrap text-sm')
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
        status_label = ui.label("A2A Server: Unknown")
        ui.button(icon='refresh', on_click=fetch_a2a_server_status, color='white').tooltip("Refresh A2A Server Status")

    with ui.left_drawer(value=True, bordered=True).classes('bg-grey-2 q-pa-md') as left_drawer:
        ui.label("Navigation").classes('text-bold q-mb-md text-grey-8')
        with ui.list():
            with ui.item().on('click', lambda: ui.navigate.to(main_page)): # Refresh or go home
                with ui.item_section().props('avatar'):
                    ui.icon('home').classes('text-grey-8')
                with ui.item_section():
                    ui.label("Dashboard").classes('text-grey-8')
            
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
                ui.button("Broadcast Directive", on_click=lambda: broadcast_message_to_all_minions(command_input.value)).classes('q-mt-sm')
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
                
                minion_filter_input = ui.input(placeholder="Filter minions by name, ID, capability...", on_change=update_minion_display) \
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
        ui.label(f"AI Minion Army Command Center v1.0 - Codex Omega Genesis - User: Steven - Deployed: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

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

    ui.run(
        host=host,
        port=port,
        title="Minion Army Command Center",
        dark=True, # Codex Omega's preference
        reload=False, # Set to True for development, False for "production" deployment of this script
        storage_secret=generated_storage_secret
    )

if __name__ == "__main__":
    # This allows running the GUI directly for testing.
    # ConfigManager handles BASE_PROJECT_DIR internally.
    # No need to set os.environ["BASE_PROJECT_DIR"] here anymore.
    
    # Get GUI host/port from ConfigManager for direct run
    GUI_HOST_RUN = config.get_str("gui.host", "127.0.0.1")
    GUI_PORT_RUN = config.get_int("gui.port", 8081)
    
    # gui_log is defined before this block, so it's safe to call.
    gui_log(f"Attempting to run GUI directly on {GUI_HOST_RUN}:{GUI_PORT_RUN} (if not imported).")
    run_gui(host=GUI_HOST_RUN, port=GUI_PORT_RUN)
