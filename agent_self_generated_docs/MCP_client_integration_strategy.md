# Integration of Node.js MCP Client with GEMINI_LEGION_HQ Minions

## 1. Introduction

This document outlines the strategy for integrating the existing Node.js-based MCP (Model Context Protocol) client, found in the `mcp_super_tool/` directory, into the Python-based `GEMINI_LEGION_HQ` minion architecture. The goal is to enable minions to leverage tools provided by MCP servers through this existing client.

## 2. Understanding the Existing Node.js MCP Client (`mcp_super_tool/`)

The Node.js MCP client is designed to allow a Gemini LLM to interact with tools exposed by various MCP servers.

*   **Location:** `/Users/ttig/GEMINI_LEGION_HQ/mcp_super_tool/`
<--NOTE: Note from user: this MCP client was originally created as a standalone app that runs through CLI interface, if you want to reference the original codebase for that app, it's located at `/Users/ttig/GEMINI_LEGION_HQ/mcp_gemini_original_app_for_REFERENCE` just for your own reference. -->>
*   **Core Purpose:** Acts as a bridge between an LLM (originally its own Gemini instance) and one or more MCP servers. It handles the lifecycle of these servers, tool discovery, and tool execution.
*   **Key Components:**
    *   **[`mcp_super_tool/mcp-config.json`](mcp_super_tool/mcp-config.json:1):** Configuration file defining the MCP servers to be managed. Each server entry specifies the command and arguments needed to start it (e.g., `npx @modelcontextprotocol/server-filesystem`).
    *   **[`mcp_super_tool/src/mcp_client_manager.js`](mcp_super_tool/src/mcp_client_manager.js:1):** The heart of the client. It uses the `@modelcontextprotocol/sdk` (specifically `StdioClientTransport`) to:
        *   Launch and connect to MCP server processes based on `mcp-config.json`.
        *   Discover available tools from each server using an MCP `tools/list` request.
        *   Execute tools on the appropriate server using an MCP `tools/call` request, passing arguments and receiving results.
        *   It maintains these connections, presumably for the duration of the client's operation.
    *   **[`mcp_super_tool/src/gemini_interactor.js`](mcp_super_tool/src/gemini_interactor.js:85):** Handles direct interaction with the Google Gemini API (using `@google/generative-ai`). *This component will be largely unused in the minion integration, as minions have their own LLM interaction logic.*
    *   **[`mcp_super_tool/src/tool_parser.js`](mcp_super_tool/src/tool_parser.js:87):** Parses responses from the LLM to detect tool call requests formatted in an XML-like syntax (e.g., `<use_mcp_tool>...</use_mcp_tool>`).
    *   **[`mcp_super_tool/src/prompt_builder.js`](mcp_super_tool/src/prompt_builder.js:88):** Constructs the system prompt for the LLM, detailing available tools and how to call them. *This logic will need to be adapted for the minion's existing prompt generation.*
    *   **[`mcp_super_tool/src/main.js`](mcp_super_tool/src/main.js:1):** The main application entry point. It initializes the `mcpClientManager`, sets up a chat loop with `gemini_interactor`, and orchestrates the process. *This CLI interaction will be replaced by programmatic control from the minion.*
*   **Operation:**
    1.  Reads [`mcp_super_tool/mcp-config.json`](mcp_super_tool/mcp-config.json:1).
    2.  For each enabled server, `mcp_client_manager.js` spawns it as a subprocess and establishes an MCP connection via STDIO.
    3.  It fetches the list of tools from each connected server.
    4.  (Originally) It would then wait for LLM input, parse for tool calls, execute them, and feed results back to the LLM.

## 3. Proposed Integration Strategy

The core idea is to adapt the Node.js MCP client to run as a managed service or a set of functions that the Python-based minions can interact with. Direct modification of the Node.js client will be minimized; instead, we will focus on creating an interface layer.

**Option A: Node.js Client as a Long-Running Service with a Simple IPC/API**

This is the recommended approach. The Node.js client (`main.js` or a modified version) would run as a separate, persistent process. Minions would communicate with it via a simple IPC mechanism (e.g., ZeroMQ, a simple HTTP API on localhost, or even named pipes if kept very simple).

*   **Node.js Side:**
    *   Modify [`mcp_super_tool/src/main.js`](mcp_super_tool/src/main.js:1) (or create a new entry point) to:
        *   Initialize `mcpClientManager` as it does now.
        *   Instead of a chat loop, expose functions/endpoints for:
            *   `get_available_mcp_tools()`: Returns a structured list of all tools from all connected MCP servers (server name, tool name, description, input schema). This would leverage `mcpClientManager.getConnectedServersAndTools()`.
            *   `execute_mcp_tool(server_name, tool_name, arguments)`: Takes server name, tool name, and arguments, then calls `mcpClientManager.callTool()` and returns the result.
    *   This service would be responsible for managing the lifecycle of the MCP server subprocesses.
*   **Python (Minion) Side:**
    *   A new Python module (e.g., `mcp_node_bridge.py`) would handle communication with this Node.js service.
    *   This bridge would have methods mirroring the exposed Node.js functions (e.g., `get_mcp_tools()`, `call_mcp_tool()`).

**Option B: Python Directly Managing Node.js Script Execution (Less Ideal)**

Python could directly execute parts of the Node.js client as short-lived scripts for specific tasks (e.g., one script to list tools, another to call a tool). This is less efficient due to repeated startup/shutdown of Node.js and MCP servers.

### 3.1. Tool Discovery and Invocation

*   **Discovery:**
    *   On startup, or when requested, [`minion_core/tool_manager.py`](minion_core/tool_manager.py) would call the `get_available_mcp_tools()` function via the `mcp_node_bridge.py`.
    *   The returned tool definitions (including server name, tool name, description, and input schema) would be registered within the `ToolManager`, similar to how native Python tools are registered. The `server_name` becomes a crucial part of the tool's unique identifier or metadata.
*   **Invocation:**
    *   When a minion's LLM decides to use an MCP tool (e.g., by generating a `<use_mcp_tool>` tag or a similar structured request that the `ToolManager` understands), the `ToolManager` would:
        1.  Identify that it's an MCP tool.
        2.  Extract `server_name`, `tool_name`, and `arguments`.
        3.  Call `mcp_node_bridge.py`'s `call_mcp_tool(server_name, tool_name, arguments)`.
        4.  The bridge communicates with the Node.js service, which executes the tool via the appropriate MCP server.
        5.  The result is passed back to the `ToolManager` and then to the minion's LLM.

### 3.2. Configuration

*   **MCP Server Configuration:** The existing [`mcp_super_tool/mcp-config.json`](mcp_super_tool/mcp-config.json:1) will continue to be the source of truth for defining MCP servers. The Node.js service will read this directly.
*   **Minion Configuration:**
    *   Minions need to know how to communicate with the Node.js MCP service (e.g., port number if using HTTP, or socket path for ZeroMQ/pipes). This could be added to the minion's main configuration file (e.g., [`system_configs/config.toml`](system_configs/config.toml) or a new `mcp_integration_config.json`).
    *   A global flag to enable/disable this MCP integration.
*   **Authentication:** The current Node.js MCP client does not seem to implement authentication with the MCP servers themselves beyond what the MCP server's startup command might entail. If specific MCP servers require authentication tokens passed as arguments or environment variables, this would be configured in [`mcp_super_tool/mcp-config.json`](mcp_super_tool/mcp-config.json:1). Communication between the Python minion and the local Node.js service can be secured by ensuring the service only listens on localhost or uses a simple token if running in a less trusted environment.

## 4. Changes to Minion Codebase

### 4.1. `minion_core/main_minion.py`

*   **Initialization:**
    *   If MCP integration is enabled, `MainMinion` would be responsible for ensuring the Node.js MCP service is started (if not already running as a separate system service). This might involve spawning it as a subprocess.
    *   It would initialize the `McpNodeBridge` instance, providing it with connection details.
*   **Tool Registration:**
    *   Pass the `McpNodeBridge` instance to the `ToolManager` during its initialization, so `ToolManager` can use it to discover MCP tools.
*   **Shutdown:**
    *   Ensure graceful shutdown of the Node.js MCP service if the minion started it.

### 4.2. `minion_core/tool_manager.py`

*   **New Methods/Logic:**
    *   `discover_mcp_tools(mcp_bridge)`:
        *   Calls `mcp_bridge.get_mcp_tools()`.
        *   For each tool, create a wrapper or representation that fits the `ToolManager`'s internal structure. This representation must store `server_name`, `tool_name`, `description`, and `input_schema`.
        *   The "callable" part of this registered tool would be a function that uses the `mcp_bridge` to execute the tool.
    *   Modify `execute_tool` (or similar method):
        *   If the tool to be executed is identified as an MCP tool, delegate the call to the `mcp_bridge` using the stored `server_name`, `tool_name`, and provided arguments.
*   **Prompt Generation:**
    *   The `ToolManager` (or a component it uses for prompt generation) will need to include information about available MCP tools in the system prompt for the minion's LLM. The format should be consistent with how other tools are presented, ensuring the LLM knows how to request them (e.g., using the `<use_mcp_tool>` syntax with `server_name` and `tool_name` attributes/parameters).

### 4.3. New Components

*   **`minion_core/mcp_node_bridge.py` (New Python Module):**
    *   Handles all communication with the Node.js MCP service.
    *   Implements methods like:
        *   `__init__(self, service_address)`
        *   `get_mcp_tools()`: Fetches tool list.
        *   `call_mcp_tool(self, server_name, tool_name, arguments)`: Executes a tool.
        *   Handles serialization/deserialization of data (e.g., JSON for HTTP/ZeroMQ).
        *   Error handling for communication failures.
*   **Modified Node.js Client (within `mcp_super_tool/`):**
    *   A new entry point or modified [`mcp_super_tool/src/main.js`](mcp_super_tool/src/main.js:1) to run as a service exposing the necessary functions, rather than an interactive CLI.
    *   This service would use `mcpClientManager` internally.

## 5. Configuration Files

*   **Existing:** [`mcp_super_tool/mcp-config.json`](mcp_super_tool/mcp-config.json:1) (used by the Node.js service).
*   **Potentially Modified/New:**
    *   [`system_configs/config.toml`](system_configs/config.toml) (or a dedicated `mcp_integration.toml`):
        *   `enable_mcp_integration = true/false`
        *   `mcp_node_service_address = "tcp://localhost:5555"` (example for ZeroMQ) or `"http://localhost:3000/mcp"` (example for HTTP).
        *   `mcp_node_service_startup_command = "node /path/to/mcp_super_tool/src/service_main.js"` (if minions are to manage its lifecycle).

## 6. Workflow Diagram (High-Level)

```mermaid
sequenceDiagram
    participant Minion as MainMinion.py
    participant TM as ToolManager.py
    participant Bridge as McpNodeBridge.py
    participant NodeSvc as Node.js MCP Service
    participant McpServer as Actual MCP Server (e.g., filesystem)

    Minion->>TM: Initialize ToolManager
    TM->>Bridge: discover_mcp_tools()
    Bridge->>NodeSvc: Request: get_available_mcp_tools
    NodeSvc-->>Bridge: Response: List of tools (name, server, schema)
    Bridge-->>TM: Return tool list
    TM->>TM: Register MCP tools

    Note over Minion, McpServer: Later, during task execution...

    Minion->>TM: LLM requests to use MCP tool "X" on server "S"
    TM->>Bridge: call_mcp_tool(server="S", tool="X", args={...})
    Bridge->>NodeSvc: Request: execute_mcp_tool(server="S", tool="X", args={...})
    NodeSvc->>McpServer: MCP tools/call (via StdioClientTransport)
    McpServer-->>NodeSvc: MCP tool result
    NodeSvc-->>Bridge: Response: Tool result
    Bridge-->>TM: Return tool result
    TM-->>Minion: Return tool result to LLM

--- 

## 7. Open Questions & Considerations
**Error Handling:** Robust error handling is needed at each step of communication (Python <-> Node.js, Node.js <-> MCP Server).
**Performance:** The overhead of IPC should be considered, but for typical tool calls, it's likely acceptable.
**Security:** If the Node.js service binds to anything other than localhost, proper security measures (authentication, authorization) would be needed. For initial integration, localhost-only is recommended.
**Lifecycle Management of Node.js Service:** Should it be a system-level service managed independently, or spawned/managed by the MainMinion? Spawning by MainMinion simplifies deployment for single-machine setups but adds complexity to MainMinion.
**Alternative IPC:** While HTTP or ZeroMQ are robust, simpler STDIO-based communication between Python and a single-purpose Node.js script (per call) could be an alternative if the long-running service model proves too complex initially, but this would be less performant due to repeated Node.js startup.
**SDK Parity:** The @modelcontextprotocol/sdk is used in JavaScript. Python minions might eventually want a native Python MCP SDK for direct communication if performance or complexity of the bridge becomes an issue, but leveraging the existing JS client is a good first step.

This integration strategy aims to leverage the existing, functional Node.js MCP client with minimal modifications, providing a clear path to extending minion capabilities.