# Unified GUI Implementation Plan: Collaborative Tasks, Chat, and System Management

**Objective:** This document outlines the consolidated phases and sub-tasks required to refactor and enhance the Management GUI ([`management_gui/gui_app.py`](management_gui/gui_app.py)). The goal is to fully support the initiation, monitoring, and review of collaborative tasks, enable direct agent chat (individual and group), allow LLM and MCP tool configuration, and provide enhanced minion management and debugging capabilities, all leveraging the refactored `AsyncMinion` backend.

**Key Reference Documents:**
*   [`agent_self_generated_docs/ANALYSIS_management_GUI.md`](agent_self_generated_docs/ANALYSIS_management_GUI.md) (Original GUI state and limitations)
*   [`agent_self_generated_docs/collaborative_task_backend_flow_detailed.md`](agent_self_generated_docs/collaborative_task_backend_flow_detailed.md) (Detailed backend interactions for collaborative tasks)
*   [`minion_core/async_minion.py`](minion_core/async_minion.py) (For A2A message types and content structures)
*   [`minion_core/task_coordinator.py`](minion_core/task_coordinator.py) (For understanding task states)
*   [`system_configs/config.toml`](system_configs/config.toml) (For default configurations)
*   NiceGUI Documentation (For UI implementation details)

---
## Overall GUI Structure Considerations:
*   The GUI will likely need distinct sections/tabs for:
    *   **Dashboard/Minion Overview:** (Existing, to be enhanced)
    *   **Agent Chat:** (New) For direct communication.
    *   **Collaborative Tasks:** (New) For managing complex multi-minion tasks.
    *   **System Configuration:** (New) For LLM settings, MCP Tool Management.
    *   **System Status/Monitoring:** (Enhanced) More detailed than current.
*   `app_state` in `gui_app.py` will be significantly expanded to hold states for chat sessions, collaborative tasks, selected models, tool configurations, etc.
*   A robust A2A message handling loop (e.g., `fetch_commander_messages` or a WebSocket/SSE based approach) is critical for real-time updates.

---
## Phase GUI-1: Core Communication Infrastructure & GUI Foundation

**Overall Status:** 📝 Pending

**Goal:** Establish the foundational elements for direct agent chat and basic collaborative task acknowledgements. Update `app_state` and A2A message handlers.

### Subtask GUI-1.1: Extend `app_state` for Chat and Collaborative Tasks
*   **Status:** 📝 Pending
*   **Details:** In [`management_gui/gui_app.py`](management_gui/gui_app.py), update the `app_state` dictionary:
    ```python
    app_state.update({
        "chat_sessions": {},  # session_id -> {id, type: "individual"|"group", agents: [], created_at, messages: [], status}
        "active_chat_session_id": None,
        "collaborative_tasks": {}, # task_id -> {task_id, status, coordinator_id, description, message, subtasks: {}, created_at, last_updated, completed_at, results}
        "active_collaborative_task_id": None, # For detailed view
        # Potentially add keys for LLM config and tool list if fetched globally
        "llm_config": {"model": "gemini-2.5-pro", "temperature": 0.7, "max_tokens": 8192, "top_p": 0.95, "top_k": 40, "presence_penalty":0, "frequency_penalty":0 }, # Load from config
        "available_mcp_tools": [] # To be populated
    })
    ```

### Subtask GUI-1.2: Enhance A2A Message Handler for Chat & Basic Task Ack
*   **Status:** 📝 Pending
*   **Details:** Modify the `fetch_commander_messages` function (or equivalent real-time message handler) in [`management_gui/gui_app.py`](management_gui/gui_app.py).
    *   **Add handler for `chat_response`:**
        ```python
        elif msg_type == "chat_response":
            session_id = parsed_content.get("session_id")
            if session_id and session_id in app_state.get("chat_sessions", {}):
                session = app_state["chat_sessions"][session_id]
                message = {
                    "sender_id": msg_data.get("sender_id", "UnknownAgent"),
                    "content": parsed_content.get("message", ""),
                    "timestamp": msg_timestamp_float, # Ensure msg_timestamp_float is defined
                    "type": "agent_message",
                    "reasoning": parsed_content.get("reasoning")
                }
                session["messages"].append(message)
                if app_state.get("active_chat_session_id") == session_id and 'chat_container_ref' in app_state: # Assuming chat_container_ref is stored
                    app_state['chat_container_ref'].refresh() # Or a more specific update function
                elif not ui.current_path or not ui.current_path.startswith("/chat/"):
                    ui.notify(f"New message in chat {session_id} from {get_formatted_minion_display(message['sender_id'])}", type="info")
        ```
    *   **Add handler for `collaborative_task_acknowledgement`:**
        ```python
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
                 app_state['collaborative_tasks_container_ref'].refresh()
        ```
    *   **Add handler for `debug_state_response` (from Claude's revised plan):**
        ```python
        elif msg_type == "debug_state_response":
            minion_id = msg_data.get("sender_id")
            state_data = parsed_content.get("state_data", {})
            # This requires a way to target the specific UI container for debug output
            # For now, log or store in app_state, UI update will be part of debug UI task
            gui_log(f"Received debug state for {minion_id}: {str(state_data)[:200]}...")
            if "debug_info" not in app_state: app_state["debug_info"] = {}
            app_state["debug_info"][minion_id] = state_data
            # If a specific debug UI element is active and bound, it should update.
            # Example: if app_state.get('active_debug_minion_id') == minion_id and 'debug_state_container_ref' in app_state:
            # app_state['debug_state_container_ref'].clear()
            # with app_state['debug_state_container_ref']:
            # ui.json_editor({"content": {"json": state_data}})
        ```

### Subtask GUI-1.3: UI for Chat Session Creation
*   **Status:** 📝 Pending
*   **Details:** Implement `create_chat_session_ui()` and `start_chat_session()` (async) as detailed in `Claude_GUI_plan_revised.md` (Phase 1.1). This includes:
    *   Radio buttons for "Individual Chat" / "Group Chat".
    *   Dynamic agent selection UI (single select for individual, multi-select for group).
    *   "Start Chat Session" button.
    *   Logic in `start_chat_session` to create a unique session ID, update `app_state["chat_sessions"]`, optionally notify the agent for individual chats, and navigate to the chat page.
    *   Helper `get_formatted_minion_display(minion_id)` will be needed.

### Subtask GUI-1.4: Chat Interface Page
*   **Status:** 📝 Pending
*   **Details:** Implement the chat page `@ui.page('/chat/{session_id}') def chat_session_page(session_id: str):` and its helper `send_chat_message(session_id, message_text)` (async), and `update_chat_display(container, session_id, show_reasoning=False)` as detailed in `Claude_GUI_plan_revised.md` (Phase 1.2). This includes:
    *   Chat header displaying participants.
    *   Chat controls (Export, Show Agent Reasoning toggle, AI Settings popup with temperature slider).
    *   Chat message display area (scrollable).
    *   Message input area with a send button.
    *   `update_chat_display` should render messages from `app_state["chat_sessions"][session_id]["messages"]`, styling human vs. agent messages differently, and optionally showing reasoning.
    *   Store references to dynamic UI elements (like `chat_container`) in `app_state` if they need to be updated by the A2A message handler (e.g., `app_state['chat_container_ref'] = chat_container`).

---
## Phase GUI-2: Collaborative Task Management UI

**Overall Status:** 📝 Pending

**Goal:** Implement UI for initiating, monitoring, and reviewing collaborative tasks.

### Subtask GUI-2.1: New UI Section/Page for Collaborative Tasks
*   **Status:** 📝 Pending
*   **Details:** Within [`management_gui/gui_app.py`](management_gui/gui_app.py), create a new tab or navigation entry (e.g., in `create_header()`) leading to a "/collaborative-tasks" page. Define this page with `@ui.page('/collaborative-tasks')`.

### Subtask GUI-2.2: Collaborative Task Definition Form
*   **Status:** 📝 Pending
*   **Details:** On the "/collaborative-tasks" page, implement `create_collaborative_task_ui()` as detailed in `Claude_GUI_plan1.md` (Phase 2.1) and my previous plan (Subtask GUI-1.2). This includes:
    *   Inputs for Task Description.
    *   A selector for the Coordinator Minion (dynamically populated from `app_state["minions"]`, potentially filtering for minions with "task_coordination" skill if available in agent cards).
    *   "Submit Collaborative Task" button.
    *   The `handle_collaborative_task_submission(task_description, coordinator_id)` (async) function as per `Claude_GUI_plan1.md` (Phase 2.2), which constructs and sends the `collaborative_task_request` A2A message.
    *   Store a temporary reference to the submitted task description in `app_state` (e.g., `app_state["pending_collab_tasks"][generated_temp_id] = {"description": ...}`) so it can be populated when the acknowledgement comes back with the real task ID.

### Subtask GUI-2.3: Collaborative Task Dashboard Display
*   **Status:** 📝 Pending
*   **Details:** On the "/collaborative-tasks" page, below or alongside the creation form, implement the `update_collaborative_tasks_display()` function and its container, as detailed in `Claude_GUI_plan1.md` (Phase 2.3).
    *   This function will render a list/cards of collaborative tasks from `app_state["collaborative_tasks"]`.
    *   Display Task ID, Description (snippet), Coordinator, Status, Subtask progress.
    *   Include a "View Details" button for each task.
    *   Store a reference to the main container for this display (e.g., `collaborative_tasks_container`) in `app_state` (e.g. `app_state['collaborative_tasks_container_ref'] = collaborative_tasks_container`) so it can be refreshed by A2A handlers.

### Subtask GUI-2.4: A2A Message Handling for Collaborative Task Status Updates
*   **Status:** 📝 Pending
*   **Details:**
    *   **Backend Prerequisite:** Ensure `AsyncMinion`'s `TaskCoordinator` sends `collaborative_task_status_update` messages to `STEVEN_GUI_COMMANDER` when subtask statuses change or overall task status changes. This message should contain `collaborative_task_id`, `subtask_id` (optional), `new_status`, `details` (e.g., subtask description if new, error message), and `timestamp`.
    *   **GUI Frontend:** In `fetch_commander_messages` (or equivalent), add a handler for `collaborative_task_status_update` as detailed in `Claude_GUI_plan1.md` (Phase 1.1, but expanded here):
        ```python
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
                if 'collaborative_tasks_container_ref' in app_state:
                    app_state['collaborative_tasks_container_ref'].refresh()
                if app_state.get("active_collaborative_task_id") == task_id and 'collaborative_task_detail_container_ref' in app_state:
                     app_state['collaborative_task_detail_container_ref'].refresh() # Or a more specific update function
            else:
                gui_log(f"Received status update for unknown collaborative task: {task_id}", level="WARNING")
        ```

### Subtask GUI-2.5: Detailed Collaborative Task View Page
*   **Status:** 📝 Pending
*   **Details:** Implement `show_task_details(task_id)` and the page `@ui.page('/collaborative-task/{task_id}') def task_detail_page(task_id: str):` as detailed in `Claude_GUI_plan1.md` (Phase 2.4).
    *   This page displays full task description, coordinator, overall status, timestamps.
    *   It includes a table or list of subtasks with their ID, description, assigned minion, status, dependencies, and last update.
    *   This view must be reactive to updates from `collaborative_task_status_update` messages. Store a reference to its main container in `app_state` for targeted refresh.

### Subtask GUI-2.6: Handling and Displaying Final Task Completion
*   **Status:** 📝 Pending
*   **Details:**
    *   In `fetch_commander_messages` (or equivalent), implement the handler for `collaborative_task_completed` as detailed in `Claude_GUI_plan1.md` (Phase 1.1).
        ```python
        elif msg_type == "collaborative_task_completed":
            task_id = parsed_content.get("task_id")
            if task_id and task_id in app_state.get("collaborative_tasks", {}):
                task = app_state["collaborative_tasks"][task_id]
                task["status"] = "completed" # Or parsed_content.get("status", "completed")
                task["results"] = parsed_content.get("results", {}) # This should be the final aggregated result
                task["last_updated"] = time.time()
                task["completed_at"] = parsed_content.get("timestamp", time.time()) # Use timestamp from message if available
                task["elapsed_seconds"] = parsed_content.get("elapsed_seconds")

                ui.notify(f"Collaborative task {task_id} completed!", type="positive")
                # Refresh UI
                if 'collaborative_tasks_container_ref' in app_state:
                    app_state['collaborative_tasks_container_ref'].refresh()
                if app_state.get("active_collaborative_task_id") == task_id and 'collaborative_task_detail_container_ref' in app_state:
                     app_state['collaborative_task_detail_container_ref'].refresh()
        ```
    *   On the `task_detail_page`, if `task.get("status") == "completed"`, display the `task.get("results")` prominently (e.g., using `ui.markdown` if text, or structured display if it's a dict).

---
## Phase GUI-3: Enhanced Minion & System Configuration/Management

**Overall Status:** 📝 Pending

**Goal:** Provide UI for configuring LLM settings, managing MCP tools, customizing minion personalities, and accessing minion debug information.

### Subtask GUI-3.1: LLM Configuration Interface
*   **Status:** 📝 Pending
*   **Details:** Implement `create_model_config_ui()` and `save_llm_config(config_data)` (async) as detailed in `Claude_GUI_plan_revised.md` (Phase 2.1).
    *   This UI will allow selection of default LLM model, temperature, max tokens, and advanced parameters (top_p, top_k, penalties).
    *   "Save Configuration" should ideally update the central `system_configs/config.toml` (this is complex from GUI, might require a backend API endpoint on a service that *can* write files, or just update `app_state` and send A2A `update_llm_config` messages to all active minions). For now, focus on sending A2A to minions.
    *   **Backend Prerequisite:** `AsyncMinion` needs to handle an A2A message type `update_llm_config` to dynamically change its `LLMInterface` settings.

### Subtask GUI-3.2: MCP Tool Management Interface
*   **Status:** 📝 Pending
*   **Details:** Implement `create_tool_management_ui()`, `fetch_available_tools(container)` (async), and `open_add_tool_dialog()` as detailed in `Claude_GUI_plan_revised.md` (Phase 2.2).
    *   `fetch_available_tools` will query an endpoint on the `mcp_super_tool` service (e.g., `/list-tools` - this endpoint needs to exist on `mcp_super_tool` and return a list of tools with their server_name, status).
    *   The UI will display tools in a table with actions: Configure, Enable/Disable, Delete.
    *   `open_add_tool_dialog` provides a form to define new tools.
    *   **Backend Prerequisite:** `mcp_super_tool` needs API endpoints for:
        *   `/list-tools` (GET)
        *   `/add-tool` (POST, with tool definition)
        *   `/configure-tool/{tool_id_or_name}` (PUT/POST)
        *   `/toggle-tool-status/{tool_id_or_name}` (POST)
        *   `/delete-tool/{tool_id_or_name}` (DELETE)
    *   These backend endpoints on `mcp_super_tool` would modify its `mcp-config.json` and reload its tool clients.

### Subtask GUI-3.3: Minion Personality Customization Interface
*   **Status:** 📝 Pending
*   **Details:** Implement `open_personality_dialog(minion_id)` and `update_minion_personality(minion_id, personality_traits)` (async) as detailed in `Claude_GUI_plan_revised.md` (Phase 3.1).
    *   This UI will be accessible, perhaps from an enhanced minion card or detail view.
    *   It allows editing personality traits text area, with templates.
    *   "Apply Personality" sends an A2A `update_personality` message to the specific minion.
    *   **Backend Prerequisite:** `AsyncMinion` needs to handle an A2A message type `update_personality` to change its `self.personality_traits` and potentially re-initialize or update its system prompt.

### Subtask GUI-3.4: Minion Debugging Interface
*   **Status:** 📝 Pending
*   **Details:** Implement `create_debug_console_ui(minion_id)` and associated fetch functions (e.g., `fetch_minion_state`, `fetch_minion_conversation`, etc.) as detailed in `Claude_GUI_plan_revised.md` (Phase 3.2).
    *   This UI, likely on a minion detail page, will have tabs for: Internal State, Conversation History, Task Queue, Log Viewer, Performance Metrics.
    *   Each tab will have a button to request the specific debug information from the minion.
    *   **Backend Prerequisite:** `AsyncMinion` needs to handle new A2A message types for these debug requests (e.g., `debug_get_state`, `debug_get_conversation_history`, `debug_get_task_queue`, `debug_get_logs`, `debug_get_metrics`) and respond with the requested data in a corresponding `_response` message type (e.g., `debug_state_response`). The GUI's A2A handler will process these responses to populate the debug views.

### Subtask GUI-3.5: Enhanced Minion Cards & Detail View
*   **Status:** 📝 Pending
*   **Details:** Integrate elements from `Claude_GUI_plan1.md` (Phase 3.1, 3.2) into the existing minion display.
    *   Update `update_minion_display()`: Minion cards should show if a minion can be a "Task Coordinator" (based on skills in its agent card) and counts of active collaborative tasks it's coordinating or participating in.
    *   Implement `show_minion_details(minion_id)` and the `@ui.page('/minion/{minion_id}') def minion_detail_page(minion_id: str):`.
    *   This page should display: Basic info (ID, status, personality, description), Capabilities/Skills, list of collaborative tasks it's coordinating, list of subtasks it's assigned. Buttons to navigate to the full detail of those collaborative tasks. Access to the new Debugging Interface (Subtask GUI-3.4) and Personality Customization (Subtask GUI-3.3) for this minion.

---
## Phase GUI-4: System-Wide UI/UX Improvements & Finalization

**Overall Status:** 📝 Pending

**Goal:** Implement a system monitoring dashboard, refine error handling, add loading states, and perform final testing.

### Subtask GUI-4.1: System Monitoring Dashboard
*   **Status:** 📝 Pending
*   **Details:** Implement the `@ui.page('/system-dashboard') def system_dashboard_page():` as detailed in `Claude_GUI_plan1.md` (Phase 4.1).
    *   Display overall A2A Server status, active minion count, total collaborative tasks.
    *   Show a summary of minion statuses (e.g., X Idle, Y Running, Z Paused).
    *   **Data Source:** This data will come from `app_state` which is updated by various A2A messages and polling.

### Subtask GUI-4.2: Consistent Error Handling & User Feedback
*   **Status:** 📝 Pending
*   **Details:** Review all new UI interactions.
    *   Ensure `ui.notify` is used consistently for feedback on actions (success, failure, warnings).
    *   Display backend error messages clearly when A2A calls fail or tasks/subtasks report errors.
    *   Implement this as per my original `GUI_Implementation_Plan_Collaborative_Tasks.md` (Subtask GUI-5.1).

### Subtask GUI-4.3: Loading Indicators
*   **Status:** 📝 Pending
*   **Details:** Implement loading indicators (`ui.spinner`, messages) for asynchronous operations, such as:
    *   Submitting new collaborative tasks.
    *   Fetching tool lists.
    *   Loading minion/task detail pages.
    *   Requesting debug information.
    *   Implement this as per my original `GUI_Implementation_Plan_Collaborative_Tasks.md` (Subtask GUI-5.2).

### Subtask GUI-4.4: Comprehensive Testing & UI/UX Refinement
*   **Status:** 📝 Pending
*   **Details:**
    *   Thoroughly test all new GUI features with the live backend.
    *   Test different collaborative task scenarios.
    *   Test chat functionality with multiple minions.
    *   Test tool and model configuration changes.
    *   Gather user feedback (from yourself) on usability and make refinements to layout, navigation, and clarity.
    *   Ensure responsive design considerations.

---
This unified plan provides a comprehensive roadmap for the GUI development. Each sub-task should be implemented and tested iteratively. Communication between the GUI and the backend (AsyncMinions, A2A Server, MCP Super Tool) via A2A messages is paramount and forms the backbone of this plan.
