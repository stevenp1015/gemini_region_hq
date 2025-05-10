# GEMINI_LEGION_HQ - Implementation Progress Tracker

This document tracks the high-level progress of implementing new features based on the approved design documents.

## Phase 1: Core Infrastructure & MCP Integration

### Node.js MCP Service Wrapper/API
- [x] Adapt `mcp_super_tool/src/main.js` to run as a persistent service exposing tool discovery and execution endpoints.

### Python Bridge for MCP Communication
- [x] Create `minion_core/mcp_node_bridge.py` to interface with the Node.js MCP service for tool listing and invocation.

### Minion Core MCP Integration
- [x] Integrate `McpNodeBridge` into `minion_core/main_minion.py` for initialization and optional service management.
- [x] Enhance `minion_core/tool_manager.py` to discover, register, and execute MCP tools via the bridge.
- [x] Update minion prompt generation to include discovered MCP tools.

### Configuration for MCP
- [x] Add MCP integration settings (enable flag, service address, startup command) to `system_configs/config.toml`.

## Phase 2: Minion Management Features

### Initial Naming Mechanism
- [x] Implement initial minion naming via `config.toml` and pass to `main_minion.py` via `spawn_legion.py`.
- [x] Update `main_minion.py` to accept a `--name` argument and include `user_facing_name` in its `agent_card`.

### Renaming Minions
- [x] Implement A2A server endpoint (`/agents/{minion_id}/rename`) to update `user_facing_name` in agent registry and `agent_card`.
- [x] Add rename functionality (UI and API call) to `management_gui/gui_app.py`.

### Dynamic Minion Creation
- [x] Implement A2A server endpoint (`/spawn-minion`) to generate `minion_id` and launch new `main_minion.py` processes with specified parameters.
- [x] Add dynamic minion creation functionality (UI and API call) to `management_gui/gui_app.py`.

### GUI Display for Naming
- [x] Update `management_gui/gui_app.py` to consistently display `user_facing_name` alongside `minion_id`.

## Phase 3: Minion Process Control

### A2A Messaging for Process Control
- [x] Define and enable A2A server routing for new control messages: pause/resume requests/acks, message_to_paused requests/acks.

### Minion Core Logic for Pause/Resume/Message
- [x] Modify `main_minion.py` main loop and task processing to handle pause state, checking `is_paused` at safe points.
- [x] Implement state serialization/deserialization in `main_minion.py` for pause/resume (V1: in-memory, persist on graceful shutdown).
- [x] Add methods in `main_minion.py` to handle pause/resume commands and messages to paused minions.

### Management GUI for Process Control
- [x] Add UI elements in `management_gui/gui_app.py` for pause, resume, and sending messages to paused minions.
- [x] Implement GUI logic to send control A2A messages and update minion status based on acks/state updates.

### Safe Pause for LLM/Tools
- [x] Ensure `llm_interface.py` and `tool_manager.py` interactions in `main_minion.py` complete current short step before fully pausing.

## Phase 4: Minion-to-Minion (M2M) Communication Enhancements

### Refined M2M Message Types
- [x] Implement new/modified M2M message types in A2A framework/minion core (e.g., task delegation with MCP tools, capability query, NACK, tool invocation).

### Minion Core Logic for Enhanced M2M
- [x] Update `main_minion.py` (or M2M handler) to process all new/refined M2M messages.
- [x] Implement M2M timeout, retry, backpressure (NACK), and basic deadlock prevention logic in minions.

### A2A Server Enhancements for M2M
- [x] Enhance A2A server's agent registry to store and serve minion capabilities (including MCP tools).
- [x] Ensure A2A server routes all new/refined M2M message types and logs M2M traffic with trace_ids.

### Management GUI for M2M Observability
- [x] Update `management_gui/gui_app.py` to display minion capabilities and allow filtering/searching by them.
- [ ] (Optional) Add basic M2M interaction tracing/logging access in GUI. *(Skipped for V1.1, noted for future enhancement)*

```