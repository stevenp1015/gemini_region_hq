import os
import time
import sys
import json
import asyncio # For async operations with NiceGUI if needed
from nicegui import ui, app, Client
import requests # For sending commands to A2A server or Minions directly (if designed)
from datetime import datetime

# Assumes this script is run from BASE_PROJECT_DIR or BASE_PROJECT_DIR is in env
BASE_DIR = os.getenv("BASE_PROJECT_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
A2A_SERVER_URL = f"http://{os.getenv('A2A_SERVER_HOST', '127.0.0.1')}:{os.getenv('A2A_SERVER_PORT', '8080')}"
GUI_LOG_FILE = os.path.join(LOGS_DIR, "management_gui.log")

# Basic logger for the GUI
# NiceGUI has its own logging, this is for app-specific logic
def gui_log(message, level="INFO"):
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    log_entry = f"{timestamp} - GUI_APP - {level} - {message}"
    print(log_entry) # Also print to console where NiceGUI runs
    with open(GUI_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry + "\n")

# --- App State (simplified for V1) ---
# In a real app, this might come from a more robust state management solution
# or by querying the A2A server / Minions directly.
# For V1, we'll simulate some state and provide ways to interact.
app_state = {
    "minions": {}, # { "minion_id": {"status": "Idle", "last_seen": ..., "personality": ...} }
    "a2a_server_status": "Unknown",
    "system_logs": [], # For displaying recent log entries
    "last_broadcast_command": ""
}

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
            for agent in agents_data:
                minion_id = agent.get("name", "UnknownID") # Use "name" as the key, as per AgentCard model
                app_state["minions"][minion_id] = {
                    "status": agent.get("status", "Unknown"), # A2A server might provide status
                    "name": agent.get("name", minion_id),
                    "description": agent.get("description", "N/A"),
                    "capabilities": agent.get("capabilities", []),
                    "last_seen": datetime.utcnow().isoformat() # Update when fetched
                }
            gui_log(f"Fetched {len(app_state['minions'])} minions.")
            update_minion_display()
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
                    ui.label(f"Sent to {minion_id}: OK").style('color: green;')
                success_count += 1
            else:
                gui_log(f"Failed to send message to {minion_id}. Status: {response.status_code}, Resp: {response.text[:100]}", level="ERROR")
                with broadcast_status_area:
                    ui.label(f"Sent to {minion_id}: FAIL ({response.status_code})").style('color: red;')
                fail_count += 1
        except requests.exceptions.RequestException as e:
            gui_log(f"Exception sending message to {minion_id}: {e}", level="ERROR")
            with broadcast_status_area:
                 ui.label(f"Sent to {minion_id}: EXCEPTION").style('color: red;')
            fail_count +=1
        await asyncio.sleep(0.1) # Small delay between sends

    final_status_msg = f"Broadcast attempt complete. Success: {success_count}, Failed: {fail_count}."
    gui_log(final_status_msg)
    with broadcast_status_area:
        ui.label(final_status_msg).style('font-weight: bold;')
    last_broadcast_label.set_text(f"Last Broadcast: {app_state['last_broadcast_command'][:60]}...")


# --- UI Display Updaters ---
minion_cards_container = None # Will be defined in create_ui

def update_minion_display():
    if not minion_cards_container:
        return
    
    minion_cards_container.clear()
    with minion_cards_container:
        if not app_state["minions"]:
            ui.label("No minions registered or found.").classes('text-italic')
            return

        # BIAS_ACTION: Displaying detailed info helps user validate Minion state.
        # Using cards for better visual separation.
        ui.label(f"Minion Army ({len(app_state['minions'])} active):").classes('text-h6')
        with ui.grid(columns=3).classes('gap-4'): # Adjust columns as needed
            for minion_id, data in sorted(app_state["minions"].items()):
                with ui.card().tight():
                    with ui.card_section():
                        ui.label(data.get("name", minion_id)).classes('text-subtitle1 font-bold')
                        ui.label(f"ID: {minion_id}")
                        ui.label(f"Status: {data.get('status', 'N/A')}")
                        ui.label(f"Description: {data.get('description', 'N/A')[:100]}...")
                        # ui.label(f"Last Seen: {data.get('last_seen', 'N/A')}")
                        # ui.button("Details", on_click=lambda mid=minion_id: show_minion_details(mid))
    gui_log("Minion display updated.")


# --- UI Layout ---
@ui.page('/')
async def main_page(client: Client):
    global status_label, minion_cards_container, command_input, broadcast_status_area, last_broadcast_label
    
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
        
        # Section: Minion Army Status
        with ui.card().classes('w-full q-mb-md'):
            with ui.card_section().classes('row justify-between items-center'):
                ui.label("Minion Army Status").classes('text-h6')
                ui.button(icon='refresh', on_click=fetch_registered_minions).props('flat').tooltip("Refresh Minion List")
            minion_cards_container = ui.card_section() # Minion cards will be rendered here
            # Initial call to populate
            await fetch_registered_minions()


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
    ui.timer(30.0, fetch_a2a_server_status, active=True) # Refresh server status every 30s
    ui.timer(60.0, fetch_registered_minions, active=True) # Refresh minion list every 60s
    
    # Initial fetch on page load
    await fetch_a2a_server_status()
    # fetch_registered_minions is already called after container creation

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
    # This allows running the GUI directly for testing, but it's intended to be launched by the main bash script.
    # Ensure BASE_PROJECT_DIR is set if running directly.
    if not os.getenv("BASE_PROJECT_DIR"):
        os.environ["BASE_PROJECT_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        gui_log(f"GUI_APP standalone: BASE_PROJECT_DIR set to: {os.environ['BASE_PROJECT_DIR']}")

    # Default host/port if not specified by launcher
    GUI_HOST_RUN = os.getenv("GUI_HOST", "127.0.0.1")
    GUI_PORT_RUN = int(os.getenv("GUI_PORT", "8081"))
    
    gui_log("Attempting to run GUI directly (if not imported).")
    run_gui(host=GUI_HOST_RUN, port=GUI_PORT_RUN)
