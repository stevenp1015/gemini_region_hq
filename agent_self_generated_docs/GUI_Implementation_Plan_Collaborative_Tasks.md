# GUI Implementation Plan: Collaborative Task Management

**Objective:** This document outlines the phases and sub-tasks required to enhance the Management GUI ([`management_gui/gui_app.py`](management_gui/gui_app.py)) to fully support the initiation, monitoring, and review of collaborative tasks executed by the `AsyncMinion` backend.

**Key Reference Documents:**
*   [`agent_self_generated_docs/ANALYSIS_management_GUI.md`](agent_self_generated_docs/ANALYSIS_management_GUI.md) (Current GUI state and limitations)
*   [`agent_self_generated_docs/collaborative_task_backend_flow_detailed.md`](agent_self_generated_docs/collaborative_task_backend_flow_detailed.md) (Detailed backend interactions for collaborative tasks)
*   [`minion_core/async_minion.py`](minion_core/async_minion.py) (For A2A message types and content structures)
*   [`minion_core/task_coordinator.py`](minion_core/task_coordinator.py) (For understanding task states)
*   NiceGUI Documentation (For UI implementation details)

---
## Phase GUI-1: Collaborative Task Initiation Interface

**Overall Status:** 📝 Pending

**Goal:** Allow users to define and launch new collaborative tasks, assigning a specific minion as the coordinator.

### Subtask GUI-1.1: New UI Section/Page for Collaborative Tasks
*   **Status:** 📝 Pending
*   **Details:**
    *   Within [`management_gui/gui_app.py`](management_gui/gui_app.py), create a new tab or navigation entry leading to a "Collaborative Tasks" page.
    *   Structure this page using NiceGUI elements (e.g., `ui.page`, `ui.header`, appropriate layout containers).

### Subtask GUI-1.2: Task Definition Form
*   **Status:** 📝 Pending
*   **Details:**
    *   On the "Collaborative Tasks" page, implement a form with the following NiceGUI input elements:
        *   `ui.input` for "Task Title" (optional, for GUI display purposes).
        *   `ui.textarea` for "Detailed Task Description".
        *   `ui.select` for "Select Coordinator Minion".
            *   This dropdown should be populated dynamically. **Action Item:** Determine how the GUI will fetch the list of currently available/registered and suitable (e.g., those running `AsyncMinion` with `TaskCoordinator` capabilities) minions. This might involve:
                *   The GUI's A2A client sending a request to the A2A server for a list of agents with specific capabilities.
                *   Or, if the GUI already maintains an `app_state.minions` list, filtering that list.
    *   A `ui.button` labeled "Launch Collaborative Task".

### Subtask GUI-1.3: "Launch Task" Button Logic
*   **Status:** 📝 Pending
*   **Details:**
    *   Implement the `on_click` handler for the "Launch Collaborative Task" button.
    *   This handler will:
        1.  Retrieve values from the form fields.
        2.  Perform basic validation (e.g., task description is not empty, a coordinator is selected).
        3.  Construct the A2A message payload for a `collaborative_task_request`.
            *   **Recipient:** Selected Coordinator Minion ID.
            *   **Sender ID:** `STEVEN_GUI_COMMANDER` (or a configurable GUI agent ID).
            *   **Message Type:** `collaborative_task_request`
            *   **Content:** `{"task_description": "...", "requester_id": "STEVEN_GUI_COMMANDER"}`
        4.  Use the GUI's A2A client instance (e.g., `app_state.a2a_client.send_message(...)`) to send the message.
        5.  Provide immediate feedback to the user (e.g., a `ui.notify` message like "Task submission initiated...").

### Subtask GUI-1.4: Handling Task Acknowledgement
*   **Status:** 📝 Pending
*   **Details:**
    *   The GUI's A2A message handling logic (likely in `poll_a2a_server_messages` or a new dedicated WebSocket/SSE handler) needs to be extended.
    *   Implement a handler for A2A messages of type `collaborative_task_acknowledgement`.
    *   When received, this handler should:
        1.  Extract `task_id`, `status`, and `coordinator_id` from the message content.
        2.  Update the GUI state to reflect that the task has been accepted by the coordinator. This might involve adding the task to a new list in `app_state` (e.g., `app_state.collaborative_tasks`) and displaying a `ui.notify` message (e.g., "Task '{task_id}' accepted by {coordinator_id}, status: {status}").

---
## Phase GUI-2: Collaborative Task Dashboard & Real-time Status Updates

**Overall Status:** 📝 Pending

**Goal:** Provide users with an overview of active and recent collaborative tasks and their current statuses, updated in real-time.

### Subtask GUI-2.1: Task Dashboard Display
*   **Status:** 📝 Pending
*   **Details:**
    *   On the "Collaborative Tasks" page (or a sub-section), implement a display area for listing collaborative tasks.
    *   This could be a `ui.table` or a series of `ui.card` elements, dynamically generated from `app_state.collaborative_tasks`.
    *   For each task, display at least:
        *   Task ID (or Title, if provided).
        *   Coordinator Minion ID.
        *   Overall Task Status (e.g., Decomposing, Assigning Subtasks, In Progress, Awaiting Subtask Completion, Aggregating Results, Completed, Failed).
        *   Timestamp of initiation or last update.
    *   The table/list should be reactive to changes in `app_state.collaborative_tasks`.

### Subtask GUI-2.2: A2A Message Handling for Status Updates
*   **Status:** 📝 Pending
*   **Details:**
    *   **Backend Consideration:** The `AsyncMinion` (specifically its `TaskCoordinator`) needs to be enhanced to send A2A messages to the GUI (`STEVEN_GUI_COMMANDER`) when significant status changes occur for a collaborative task or its subtasks. A new message type like `collaborative_task_status_update` might be needed. This message should include:
        *   `collaborative_task_id`
        *   `subtask_id` (if applicable, or `null` for overall task status)
        *   `new_status` (e.g., "Subtask Decomposed", "Subtask Assigned: Bravo", "Subtask Bravo: In Progress", "Subtask Bravo: Completed", "Overall Task: Aggregating")
        *   `details` (optional, e.g., error message if a subtask failed)
        *   `timestamp`
    *   **GUI Frontend:** Enhance the GUI's A2A message handling logic to process these `collaborative_task_status_update` messages.
    *   Upon receiving such a message, the handler should:
        1.  Find the corresponding task in `app_state.collaborative_tasks`.
        2.  Update its overall status or the status of a specific subtask (the `app_state.collaborative_tasks` structure will need to accommodate subtask details).
        3.  Trigger a UI update for the dashboard and any detailed views.

---
## Phase GUI-3: Detailed Collaborative Task View

**Overall Status:** 📝 Pending

**Goal:** Allow users to drill down into a specific collaborative task to see its full details, including subtask breakdown and individual statuses.

### Subtask GUI-3.1: Navigation to Detailed View
*   **Status:** 📝 Pending
*   **Details:**
    *   Make each task entry in the dashboard (from Subtask GUI-2.1) clickable.
    *   Clicking a task should navigate the user to a new page or a dynamic section displaying detailed information for that selected collaborative task. This could use query parameters in the URL or update a shared state variable that controls the detailed view's content.

### Subtask GUI-3.2: Detailed Task View Layout
*   **Status:** 📝 Pending
*   **Details:**
    *   Design and implement the layout for the detailed task view using NiceGUI elements.
    *   Display:
        *   The full original complex task description.
        *   The overall task status and the designated coordinator minion.
        *   A clear list or table of all subtasks associated with this collaborative task. This data will come from `app_state.collaborative_tasks[selected_task_id].subtasks` (this structure needs to be defined and populated by status updates).
        *   For each subtask, display:
            *   Subtask ID (or a more user-friendly identifier).
            *   Subtask Description.
            *   Assigned Minion ID.
            *   Current Status (e.g., Pending, Assigned, In Progress, Completed, Failed).
            *   Dependencies (IDs of other subtasks it depends on).
            *   Result (if completed, e.g., a snippet or link).
            *   Error message (if failed).
            *   Timestamps (start, end if applicable).

### Subtask GUI-3.3: Dynamic Updates for Detailed View
*   **Status:** 📝 Pending
*   **Details:**
    *   Ensure that the detailed task view is also reactive to the A2A `collaborative_task_status_update` messages.
    *   If the user is currently viewing a task that receives a status update, the displayed information (overall status, subtask statuses, results, errors) should refresh automatically without requiring a page reload.

---
## Phase GUI-4: Viewing Final Results & Task Completion Interface

**Overall Status:** 📝 Pending

**Goal:** Clearly present the final outcome of a completed collaborative task to the user.

### Subtask GUI-4.1: Displaying Final Aggregated Result
*   **Status:** 📝 Pending
*   **Details:**
    *   When the GUI receives an A2A message of type `collaborative_task_completed` (sent by the coordinator minion at the very end):
        *   The message content will include the overall task summary and, crucially, the final `results` (e.g., the aggregated report).
        *   In the detailed task view for this completed task, prominently display this final result. This might be in a `ui.markdown` element if it's text-based, or provide a download link if it's a file.
        *   Update the overall task status on the dashboard and detailed view to "✅ Completed".

### Subtask GUI-4.2: Task Archiving/Dismissal (Optional Enhancement)
*   **Status:** 📝 Pending
*   **Details:**
    *   Consider adding functionality to allow users to "archive" or "dismiss" completed (or failed) tasks from the main dashboard view to keep it focused on active tasks.
    *   This would likely involve filtering the `app_state.collaborative_tasks` list based on an "archived" flag.

---
## Phase GUI-5: Error Handling and User Feedback

**Overall Status:** 📝 Pending

**Goal:** Ensure robust error handling and clear feedback to the user throughout the collaborative task lifecycle.

### Subtask GUI-5.1: Displaying Backend Errors
*   **Status:** 📝 Pending
*   **Details:**
    *   If any A2A communication related to collaborative tasks fails (e.g., sending `collaborative_task_request`, receiving updates), display a clear error message to the user via `ui.notify`.
    *   If a `collaborative_task_status_update` indicates a subtask or the overall task has failed, ensure this is clearly reflected in the dashboard and detailed views, including any error messages provided by the backend.

### Subtask GUI-5.2: Loading Indicators
*   **Status:** 📝 Pending
*   **Details:**
    *   Implement loading indicators (e.g., `ui.spinner` or progress messages) when the GUI is waiting for responses from the backend, such as:
        *   After submitting a new collaborative task, while waiting for acknowledgement.
        *   When fetching the initial list of tasks for the dashboard.
        *   When loading the detailed view for a task.

---

This plan provides a structured approach to developing the GUI features. Each sub-task should be implemented and tested iteratively.