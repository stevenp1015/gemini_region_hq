# minion_core/a2a_message_defs.py
# This file formally defines the structure of new A2A messages
# required for pausing, resuming, and messaging paused minions,
# as well as general minion state updates.

# Message Type: "control_pause_request"
# Sender: GUI
# Recipient: Target Minion
# Payload: {
#   "target_minion_id": "string (minion_id)"
# }
# Purpose: Instructs the Minion to pause.
# Reference: Minion_Process_Control_design_document.md (Section 5)

# Message Type: "control_pause_ack"
# Sender: Target Minion
# Recipient: GUI (via A2A server, possibly to STEVEN_GUI_COMMANDER)
# Payload: {
#   "minion_id": "string (minion_id of sender)",
#   "status": "string (e.g., 'paused')",
#   "timestamp": "string (ISO_timestamp)"
# }
# Purpose: Acknowledges pause command and confirms new state.
# Reference: Minion_Process_Control_design_document.md (Section 5)

# Message Type: "control_resume_request"
# Sender: GUI
# Recipient: Target Minion
# Payload: {
#   "target_minion_id": "string (minion_id)"
# }
# Purpose: Instructs a paused Minion to resume.
# Reference: Minion_Process_Control_design_document.md (Section 5)

# Message Type: "control_resume_ack"
# Sender: Target Minion
# Recipient: GUI
# Payload: {
#   "minion_id": "string (minion_id of sender)",
#   "status": "string (e.g., 'running', 'idle')",
#   "timestamp": "string (ISO_timestamp)"
# }
# Purpose: Acknowledges resume command and confirms new state.
# Reference: Minion_Process_Control_design_document.md (Section 5)

# Message Type: "message_to_paused_minion_request"
# Sender: GUI
# Recipient: Target Paused Minion
# Payload: {
#   "minion_id": "string (target_minion_id)", # As per design doc, though routing might make it implicit
#   "message_content": "string (User's message text)",
#   "timestamp": "string (ISO_timestamp of request)"
# }
# Purpose: Delivers a message from the user to a paused Minion.
# Reference: Minion_Process_Control_design_document.md (Section 5)

# Message Type: "message_to_paused_minion_ack"
# Sender: Target Minion
# Recipient: GUI
# Payload: {
#   "minion_id": "string (minion_id of sender)",
#   "status": "string (e.g., 'message_received')",
#   "original_message_timestamp": "string (ISO_timestamp from the request, for correlation)",
#   "timestamp": "string (ISO_timestamp of ack)"
# }
# Purpose: Acknowledges receipt of the message while paused.
# Reference: Minion_Process_Control_design_document.md (Section 5)

# Message Type: "minion_state_update"
# Sender: Minion
# Recipient: GUI / Commander Agent (e.g., STEVEN_GUI_COMMANDER)
# Payload: {
#   "minion_id": "string (minion_id of sender)",
#   "new_status": "string (e.g., 'paused', 'running', 'idle', 'error', 'task_started', 'task_completed')",
#   "task_id": "string (optional, ID of current/relevant task)",
#   "details": "string (optional, further details about the state or transition)",
#   "timestamp": "string (ISO_timestamp)"
# }
# Purpose: General purpose message for Minions to report significant state changes.
# Reference: Minion_Process_Control_design_document.md (Section 5)