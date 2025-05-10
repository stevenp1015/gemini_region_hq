# Minion-to-Minion (M2M) Message Definitions
# Version: 1.1

# This file defines the structure of M2M messages exchanged between minions.
# These definitions are based on the M2M Communication Plan Self-Critique document,
# specifically section 3.4: Refined and New Message Types.

# --- m2m_task_delegation (Modified) ---
# Purpose: To delegate a task from one minion to another.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the sending minion
#   "recipient_id": "string",     # ID of the target minion
#   "task_id": "string",          # Unique ID for this specific task instance
#   "parent_task_id": "string",   # Optional: ID of the parent task, if this is a sub-task
#   "trace_id": "string",         # ID for tracing a request across multiple services/minions
#   "task_description": "string", # Detailed description of the task to be performed
#   "required_capabilities": ["string"], # Optional: List of capabilities the recipient must possess
#   "required_mcp_tools": [       # Optional: List of specific MCP tools required for the task
#     {
#       "tool_name": "string",    # Name of the MCP tool
#       "server_name": "string"   # Name of the MCP server providing the tool
#     }
#   ],
#   "deadline": "timestamp",      # Optional: Suggested completion deadline
#   "priority": "enum",           # Priority of the task (e.g., "low", "normal", "high")
#   "timeout_seconds": "int",     # How long the sender will wait for an acknowledgement/completion
#   "version": "string"           # Version of this message schema (e.g., "1.1")
# }

# --- m2m_task_status_update (Modified) ---
# Purpose: For a minion to report the status of a delegated task back to the delegator.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the minion providing the status update
#   "recipient_id": "string",     # ID of the minion that originally delegated the task
#   "task_id": "string",          # ID of the task whose status is being updated
#   "trace_id": "string",         # Trace ID from the original delegation request
#   "status": "enum",             # Current status of the task (e.g., "accepted", "in_progress", "completed", "failed", "rejected", "deferred")
#   "details": "string",          # Optional: Additional details about the status
#   "progress_percentage": "float", # Optional: Estimated progress (0.0 to 100.0)
#   "version": "string"           # Version of this message schema
# }

# --- m2m_data_request (Modified) ---
# Purpose: For a minion to request specific data from another minion.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the requesting minion
#   "recipient_id": "string",     # ID of the minion expected to provide the data
#   "request_id": "string",       # Unique ID for this data request
#   "trace_id": "string",         # Trace ID for the request chain
#   "data_query": "string",       # Description or query for the data being requested
#   "parameters": {},             # Optional: Dictionary of parameters for the data query
#   "priority": "enum",           # Priority of the data request
#   "timeout_seconds": "int",     # How long the sender will wait for the data response
#   "version": "string"           # Version of this message schema
# }

# --- m2m_data_response (Modified) ---
# Purpose: For a minion to send requested data back to the requester.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the minion sending the data
#   "recipient_id": "string",     # ID of the minion that made the data request
#   "request_id": "string",       # ID of the original data_request message
#   "trace_id": "string",         # Trace ID from the original request
#   "status": "enum",             # Status of the data retrieval (e.g., "success", "error", "not_found", "pending_async")
#   "data": "any",                # The requested data (payload varies based on request)
#   "error_message": "string",    # Optional: Error message if status is "error"
#   "version": "string"           # Version of this message schema
# }

# --- m2m_info_broadcast (Modified for V1.1) ---
# Purpose: For a minion to broadcast informational messages to multiple other minions.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the broadcasting minion
#   "recipient_ids": ["string"],  # List of recipient minion IDs (replaces recipient_group for V1.1)
#   "info_id": "string",          # Unique ID for this piece of information
#   "trace_id": "string",         # Trace ID for the broadcast chain
#   "info_payload": {},           # The actual information being broadcast (flexible dictionary)
#   "urgency": "enum",            # Urgency of the broadcast (e.g., "low", "medium", "high")
#   "version": "string"           # Version of this message schema
# }

# --- m2m_negative_acknowledgement (NACK) (NEW) ---
# Purpose: For a minion to explicitly reject or indicate failure in processing a received M2M message.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the minion sending the NACK
#   "recipient_id": "string",     # ID of the minion that sent the original message being NACKed
#   "original_message_id": "string", # ID of the message that is being NACKed (e.g., task_id, request_id)
#   "reason_code": "enum",        # Reason for the NACK (e.g., "overloaded", "incapable", "invalid_request", "security_concern", "internal_error", "timeout")
#   "details": "string",          # Optional: Further details about the NACK reason
#   "version": "string"           # Version of this message schema (e.g., "1.1")
# }

# --- m2m_capability_query (NEW) ---
# Purpose: For a minion to query the capabilities of another minion or a central registry.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the querying minion
#   "recipient_id": "string",     # ID of the target minion or registry (e.g., A2A server's registry address)
#   "query_id": "string",         # Unique ID for this capability query
#   "trace_id": "string",         # Trace ID for the request chain
#   "capability_filter": {        # Optional: Filter to narrow down the query
#     "type": "string",           # e.g., "mcp_tool", "general_skill"
#     "tool_name": "string"       # e.g., "code-reasoning" (if type is "mcp_tool")
#     # ... other filter criteria
#   },
#   "version": "string"           # Version of this message schema
# }

# --- m2m_capability_response (NEW) ---
# Purpose: For a minion or registry to respond to a capability query.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the minion/registry sending the response
#   "recipient_id": "string",     # ID of the minion that made the capability query
#   "query_id": "string",         # ID of the original m2m_capability_query
#   "trace_id": "string",         # Trace ID from the original query
#   "capabilities": [             # List of capabilities possessed by the sender (or matching the query)
#     {
#       "type": "string",         # e.g., "mcp_tool", "general_skill"
#       "name": "string",         # Name of the capability or tool
#       "server_name": "string",  # Optional: MCP server name if type is "mcp_tool"
#       "version": "string",      # Optional: Version of the tool/capability
#       "status": "string",       # e.g., "available", "unavailable", "busy"
#       "current_load_estimate": "float" # Optional: Estimated current load (0.0 to 1.0)
#       # ... other capability-specific details
#     }
#   ],
#   "version": "string"           # Version of this message schema
# }

# --- m2m_tool_invocation_request (NEW - for MCP Integration) ---
# Purpose: For a minion to request another minion to invoke a specific MCP tool.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the requesting minion
#   "recipient_id": "string",     # ID of the minion that will execute the MCP tool
#   "invocation_id": "string",    # Unique ID for this tool invocation request
#   "parent_task_id": "string",   # Optional: ID of the parent task this invocation is part of
#   "trace_id": "string",         # Trace ID for the request chain
#   "mcp_server_name": "string",  # Name of the MCP server hosting the tool
#   "mcp_tool_name": "string",    # Name of the MCP tool to invoke
#   "mcp_arguments": {},          # Arguments to be passed to the MCP tool
#   "priority": "enum",           # Priority of the tool invocation
#   "timeout_seconds": "int",     # How long the sender will wait for the invocation response
#   "version": "string"           # Version of this message schema
# }

# --- m2m_tool_invocation_response (NEW) ---
# Purpose: For a minion to respond to an MCP tool invocation request.
# Expected JSON Payload:
# {
#   "sender_id": "string",        # ID of the minion that executed the tool (or attempted to)
#   "recipient_id": "string",     # ID of the minion that requested the tool invocation
#   "invocation_id": "string",    # ID of the original m2m_tool_invocation_request
#   "trace_id": "string",         # Trace ID from the original request
#   "status": "enum",             # Status of the tool invocation (e.g., "success", "error", "in_progress_async")
#   "result": "any",              # Optional: Result from the MCP tool if execution was successful and synchronous
#   "error_message": "string",    # Optional: Error message if status is "error"
#   "async_ticket_id": "string",  # Optional: Ticket ID if the tool execution is asynchronous (status "in_progress_async")
#   "version": "string"           # Version of this message schema
# }