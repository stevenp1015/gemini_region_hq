## Analysis Report: `computer_use_mcp`

**Date of Analysis:** 2025-05-10
**Analyst:** Roo (Architect Mode)

**Objective:** Analyze the `computer_use_mcp` component, focusing on its entry point, provided tools, Model Context Protocol (MCP) implementation, error handling, security, and potential issues.

### 1. Overview of `computer_use_mcp`

The `computer_use_mcp` is a Node.js application written in TypeScript, designed to function as an MCP server. Its primary purpose is to provide tools that allow an AI agent (presumably controlled via `mcp_super_tool`) to interact with the host computer's graphical user interface. This includes controlling the mouse and keyboard, and capturing screenshots.

**Architecture:**
*   It utilizes the `fastmcp` library to handle the MCP server functionalities, enabling communication with a parent MCP client (like `mcp_super_tool`).
*   For direct computer interaction (mouse, keyboard, screen), it employs the `@nut-tree-fork/nut-js` library.
*   Input validation and schema definition for tool parameters are managed using `zod`.
*   Image compression for screenshots is handled by `imagemin` and `imagemin-pngquant`.

**Communication:**
The server is configured to communicate over `stdio` ([`mcp_servers/computer_use_mcp/src/index.ts:223`](mcp_servers/computer_use_mcp/src/index.ts:223)), which is typical for child processes managed by a parent controller.

### 2. Project Structure and Dependencies

The project structure and dependencies are defined in [`mcp_servers/computer_use_mcp/package.json`](mcp_servers/computer_use_mcp/package.json:1).

*   **Name:** `computer-use-mcp` ([`mcp_servers/computer_use_mcp/package.json:2`](mcp_servers/computer_use_mcp/package.json:2))
*   **Version:** `1.0.0` ([`mcp_servers/computer_use_mcp/package.json:3`](mcp_servers/computer_use_mcp/package.json:3))
*   **Main Entry Point (compiled):** `dist/index.js` ([`mcp_servers/computer_use_mcp/package.json:12`](mcp_servers/computer_use_mcp/package.json:12))
*   **Source Entry Point:** [`mcp_servers/computer_use_mcp/src/index.ts`](mcp_servers/computer_use_mcp/src/index.ts:1)
*   **Key Scripts:**
    *   `start`: `npm run build && node dist/index.js` (builds the TypeScript code then runs the compiled JavaScript) ([`mcp_servers/computer_use_mcp/package.json:18`](mcp_servers/computer_use_mcp/package.json:18))
    *   `build`: `tsc --project tsconfig.build.json` (compiles TypeScript using a specific tsconfig for building) ([`mcp_servers/computer_use_mcp/package.json:23`](mcp_servers/computer_use_mcp/package.json:23))
*   **Core Dependencies ([`mcp_servers/computer_use_mcp/package.json:35-42`](mcp_servers/computer_use_mcp/package.json:35-42)):**
    *   `@nut-tree-fork/nut-js": "^4.2.4"`: For desktop automation (mouse, keyboard, screen).
    *   `fastmcp": "^1.16.1"`: MCP server implementation library.
    *   `zod": "^3.24.1"`: Schema declaration and validation.
    *   `imagemin": "^9.0.0"` & `imagemin-pngquant": "^10.0.0"`: For PNG image compression.
    *   `@types/node": "^22.10.5"`: TypeScript definitions for Node.js.
*   **Dev Dependencies ([`mcp_servers/computer_use_mcp/package.json:26-34`](mcp_servers/computer_use_mcp/package.json:26-34)):** Include `typescript`, `eslint`, `vitest` for testing, and TypeScript configurations.

### 3. Entry Point Analysis ([`mcp_servers/computer_use_mcp/src/index.ts`](mcp_servers/computer_use_mcp/src/index.ts:1))

The main logic resides in [`mcp_servers/computer_use_mcp/src/index.ts`](mcp_servers/computer_use_mcp/src/index.ts:1).

*   **MCP Server Initialization:**
    *   An instance of `FastMCP` is created with server metadata (name, version) ([`mcp_servers/computer_use_mcp/src/index.ts:21-24`](mcp_servers/computer_use_mcp/src/index.ts:21-24)).
    *   The server is started to listen for MCP messages using `stdio` as the transport type: `await server.start({ transportType: 'stdio' });` ([`mcp_servers/computer_use_mcp/src/index.ts:222-224`](mcp_servers/computer_use_mcp/src/index.ts:222-224)).
*   **Tool Registration:**
    *   A single tool named `"computer"` is defined and added to the MCP server using `server.addTool({...})` ([`mcp_servers/computer_use_mcp/src/index.ts:61`](mcp_servers/computer_use_mcp/src/index.ts:61)). This method registers the tool's schema and its execution handler.
*   **Configuration:**
    *   `nut-js` mouse and keyboard delays and speed are configured globally:
        *   `mouse.config.autoDelayMs = 100;` ([`mcp_servers/computer_use_mcp/src/index.ts:17`](mcp_servers/computer_use_mcp/src/index.ts:17))
        *   `mouse.config.mouseSpeed = 1000;` ([`mcp_servers/computer_use_mcp/src/index.ts:18`](mcp_servers/computer_use_mcp/src/index.ts:18))
        *   `keyboard.config.autoDelayMs = 10;` ([`mcp_servers/computer_use_mcp/src/index.ts:19`](mcp_servers/computer_use_mcp/src/index.ts:19))

### 4. Provided Tool: `computer`

The server exposes one primary tool for computer interaction.

*   **Name:** `computer` ([`mcp_servers/computer_use_mcp/src/index.ts:62`](mcp_servers/computer_use_mcp/src/index.ts:62))
*   **Description:** "Use a mouse and keyboard to interact with a computer, and take screenshots." ([`mcp_servers/computer_use_mcp/src/index.ts:63`](mcp_servers/computer_use_mcp/src/index.ts:63)). The description provides several important guidelines for the AI agent, such as preferring keyboard shortcuts, using screenshots to determine coordinates, and handling application load times. ([`mcp_servers/computer_use_mcp/src/index.ts:63-70`](mcp_servers/computer_use_mcp/src/index.ts:63-70))
*   **Input Parameters Schema (`computerToolParams` defined with `zod` ([`mcp_servers/computer_use_mcp/src/index.ts:41-59`](mcp_servers/computer_use_mcp/src/index.ts:41-59))):**
    *   `action`: An enum (`ActionEnum` ([`mcp_servers/computer_use_mcp/src/index.ts:27-38`](mcp_servers/computer_use_mcp/src/index.ts:27-38))) specifying the operation to perform.
    *   `coordinate`: An optional tuple `[x: number, y: number]` for actions requiring screen coordinates.
    *   `text`: An optional string for actions like typing or specifying key presses.

*   **Actions defined by `ActionEnum` and their Implementation ([`mcp_servers/computer_use_mcp/src/index.ts:83-212`](mcp_servers/computer_use_mcp/src/index.ts:83-212)):**
    1.  **`key`**:
        *   Description: Press a key or key-combination (supports xdotool `key` syntax).
        *   Requires: `text` (e.g., "a", "Return", "alt+Tab").
        *   Implementation: Uses `toKeys()` from [`./xdotoolStringToKeys.js`](mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:215) to parse the `text` into `nut-js` `Key` objects, then `keyboard.pressKey(...keys)` and `keyboard.releaseKey(...keys)`.
        *   Output: `{ content: [{type: 'text', text: 'Pressed key: ${args.text}'}] }`
    2.  **`type`**:
        *   Description: Type a string of text.
        *   Requires: `text`.
        *   Implementation: `keyboard.type(args.text)`.
        *   Output: `{ content: [{type: 'text', text: 'Typed text: ${args.text}'}] }`
    3.  **`mouse_move`**:
        *   Description: Move the cursor to specified (x, y) coordinates.
        *   Requires: `coordinate`.
        *   Implementation: `mouse.setPosition(new Point(args.coordinate[0], args.coordinate[1]))`.
        *   Output: `{ content: [{type: 'text', text: 'Moved cursor to: (${args.coordinate[0]}, ${args.coordinate[1]})'}] }`
    4.  **`left_click`**:
        *   Description: Click the left mouse button at the current cursor position.
        *   Implementation: `mouse.leftClick()`.
        *   Output: `{ content: [{type: 'text', text: 'Left clicked'}] }`
    5.  **`left_click_drag`**:
        *   Description: Click and drag the cursor to specified (x, y) coordinates.
        *   Requires: `coordinate`.
        *   Implementation: `mouse.pressButton(Button.LEFT)`, `mouse.setPosition(...)`, `mouse.releaseButton(Button.LEFT)`.
        *   Output: `{ content: [{type: 'text', text: 'Dragged to: (${args.coordinate[0]}, ${args.coordinate[1]})'}] }`
    6.  **`right_click`**:
        *   Description: Click the right mouse button at the current cursor position.
        *   Implementation: `mouse.rightClick()`.
        *   Output: `{ content: [{type: 'text', text: 'Right clicked'}] }`
    7.  **`middle_click`**:
        *   Description: Click the middle mouse button at the current cursor position.
        *   Implementation: `mouse.click(Button.MIDDLE)`.
        *   Output: `{ content: [{type: 'text', text: 'Middle clicked'}] }`
    8.  **`double_click`**:
        *   Description: Double-click the left mouse button at the current cursor position.
        *   Implementation: `mouse.doubleClick(Button.LEFT)`.
        *   Output: `{ content: [{type: 'text', text: 'Double clicked'}] }`
    9.  **`get_screenshot`**:
        *   Description: Take a screenshot of the entire screen.
        *   Implementation:
            *   Waits for 1 second (`setTimeout(1000)`) ([`mcp_servers/computer_use_mcp/src/index.ts:166`](mcp_servers/computer_use_mcp/src/index.ts:166)) to allow UI to settle.
            *   Captures screen with `screen.grab()` and converts to Jimp object with `imageToJimp()`.
            *   Resizes image if total pixels exceed 1366x768 to manage size ([`mcp_servers/computer_use_mcp/src/index.ts:173-179`](mcp_servers/computer_use_mcp/src/index.ts:173-179)).
            *   Compresses PNG buffer using `imageminPngquant()`.
            *   Converts optimized buffer to base64.
        *   Output: `{ content: [ {type: 'text', text: JSON.stringify({display_width_px, display_height_px})}, {type: 'image', data: base64Data, mimeType: 'image/png'} ] }` ([`mcp_servers/computer_use_mcp/src/index.ts:191-204`](mcp_servers/computer_use_mcp/src/index.ts:191-204))
    10. **`get_cursor_position`**:
        *   Description: Get the current (x, y) pixel coordinate of the cursor.
        *   Implementation: `mouse.getPosition()`.
        *   Output: `{ content: [{type: 'text', text: JSON.stringify({x: pos.x, y: pos.y})}] }`

*   **`xdotoolStringToKeys.ts` ([`mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:1`](mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:1)) Helper:**
    *   This module provides the `toKeys` function ([`mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:215`](mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:215)) used by the `key` action.
    *   It contains an extensive `keyMap` ([`mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:3-206`](mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:3-206)) that translates xdotool-style key names (e.g., "alt", "ctrl", "Return", "KP_0", "Up") and common aliases into the `Key` enum values required by `@nut-tree-fork/nut-js`.
    *   The `toKeys` function splits combined keys (e.g., "alt+Tab") by `+`, trims and lowercases each part, and maps them using `keyMap`.
    *   It throws an `InvalidKeyError` ([`mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:208`](mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:208)) if a key string is empty or not found in the map.

### 5. MCP Protocol Adherence

The `computer_use_mcp` server adheres to the Model Context Protocol primarily through the `fastmcp` library.
*   **Tool Discovery:** By using `server.addTool()`, the "computer" tool's schema (name, description, parameters) is made available for discovery by MCP clients. `fastmcp` likely handles the `toolDiscovery` request from the client and responds with the registered tool information.
*   **Tool Execution:** The `execute` async function provided in the `server.addTool()` call ([`mcp_servers/computer_use_mcp/src/index.ts:72-213`](mcp_servers/computer_use_mcp/src/index.ts:72-213)) serves as the handler for `toolExecution` requests for the "computer" tool. `fastmcp` routes incoming execution requests to this function, passing the arguments, and then sends the returned result (or error) back to the client.

### 6. Error Handling and Logging

*   **Error Handling:**
    *   **Parameter Validation:** The `execute` function checks for required parameters based on the action (e.g., `text` for `key` and `type` actions ([`mcp_servers/computer_use_mcp/src/index.ts:85`](mcp_servers/computer_use_mcp/src/index.ts:85), [`mcp_servers/computer_use_mcp/src/index.ts:99`](mcp_servers/computer_use_mcp/src/index.ts:99)); `coordinate` for `mouse_move` and `left_click_drag` ([`mcp_servers/computer_use_mcp/src/index.ts:117`](mcp_servers/computer_use_mcp/src/index.ts:117), [`mcp_servers/computer_use_mcp/src/index.ts:135`](mcp_servers/computer_use_mcp/src/index.ts:135))). Throws an `Error` if missing.
    *   **Coordinate Bounds Checking:** Before executing actions involving coordinates, it checks if the provided `coordinate` is within the screen dimensions obtained from `screen.width()` and `screen.height()`. Throws an `Error` if out of bounds ([`mcp_servers/computer_use_mcp/src/index.ts:74-80`](mcp_servers/computer_use_mcp/src/index.ts:74-80)).
    *   **Invalid Keys:** The `toKeys` function in [`xdotoolStringToKeys.ts`](mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:215) throws an `InvalidKeyError` if an unknown key string is provided.
    *   **Unknown Actions:** The `switch` statement for actions has a `default` case that throws an `Error` for any unhandled action string ([`mcp_servers/computer_use_mcp/src/index.ts:209-211`](mcp_servers/computer_use_mcp/src/index.ts:209-211)).
    *   Errors thrown within the `execute` function are expected to be caught by `fastmcp` and propagated to the MCP client as part of the tool execution response.
*   **Logging:**
    *   On successful startup, it logs "Computer control MCP server running on stdio" to `console.error` ([`mcp_servers/computer_use_mcp/src/index.ts:226`](mcp_servers/computer_use_mcp/src/index.ts:226)).
    *   There is a commented-out `console.warn` statement related to image resizing ([`mcp_servers/computer_use_mcp/src/index.ts:177`](mcp_servers/computer_use_mcp/src/index.ts:177)).
    *   Beyond startup, explicit logging within the tool's execution logic is minimal. `fastmcp` might provide its own logging for MCP communication.

### 7. Security Considerations

*   **Inherent High Risk:** This MCP server provides direct and powerful control over the host computer's mouse and keyboard, and can view the screen. This is inherently a high-security risk. An agent with access to this tool can perform almost any action that the user running the `mcp_super_tool` (and thus this MCP server) can perform. This includes accessing sensitive information, modifying files, interacting with any application, etc.
*   **Safeguards and Limitations:**
    *   **Coordinate Bounds Checking:** This is a minor safeguard, preventing mouse operations from targeting coordinates outside the visible screen area. It does not prevent malicious actions within the screen.
    *   **Execution Context:** The tool operates within the security context of the user session that launched `mcp_super_tool`. It does not elevate privileges on its own.
    *   **No Sandboxing:** There is no explicit sandboxing implemented within this MCP server itself. Security heavily relies on:
        *   The trustworthiness and programming of the AI agent using the tool.
        *   The security measures of the environment in which `mcp_super_tool` and `computer_use_mcp` are run.
    *   **Implicit Trust:** The design implies a high degree of trust in the controlling agent.
    *   The tool's description ([`mcp_servers/computer_use_mcp/src/index.ts:63-70`](mcp_servers/computer_use_mcp/src/index.ts:63-70)) provides operational guidance to the agent, which can be seen as a form of soft security/safety measure (e.g., "Always prefer using keyboard shortcuts," "consult a screenshot to determine the coordinates").

### 8. Potential Issues & Gaps

*   **Error Handling Robustness:**
    *   While basic input validation exists, errors from `@nut-tree-fork/nut-js` (e.g., if an OS-level input command fails unexpectedly, or if accessibility permissions are not granted for `nut-js` to operate) might not be explicitly caught and translated into user-friendly MCP error responses. The current implementation relies on `fastmcp` to propagate these.
    *   The `eslint-disable-next-line @typescript-eslint/switch-exhaustiveness-check` ([`mcp_servers/computer_use_mcp/src/index.ts:208`](mcp_servers/computer_use_mcp/src/index.ts:208)) above the default case in the action switch is present. While all current `ActionEnum` members *are* handled, this could mask issues if the enum were expanded without updating the switch.
*   **Security:**
    *   The most significant concern is the inherent power granted by this tool. There are no fine-grained permission controls (e.g., restricting actions to specific applications or screen regions). Such controls are likely beyond the scope of this individual MCP but are crucial for a secure system using such capabilities.
    *   The tool assumes the environment where `nut-js` runs has the necessary permissions (e.g., accessibility access on macOS). Failures due to permission issues might not be clearly reported.
*   **Screenshot Reliability and Performance:**
    *   The fixed `setTimeout(1000)` ([`mcp_servers/computer_use_mcp/src/index.ts:166`](mcp_servers/computer_use_mcp/src/index.ts:166)) before taking a screenshot is a heuristic to wait for UI updates. This may not be sufficient for slower applications or complex UI changes, potentially leading to the agent receiving stale screen information.
    *   Resizing and compressing screenshots are good for performance and token limits, but the fixed threshold (1366x768) might be too aggressive for some high-resolution displays where detail is important, or not aggressive enough for extremely large displays if the resulting image is still too large for the model's context window or MCP message limits.
*   **`xdotoolStringToKeys.ts` Completeness:**
    *   The `keyMap` ([`mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:3-206`](mcp_servers/computer_use_mcp/src/xdotoolStringToKeys.ts:3-206)) is extensive but might not cover every possible xdotool key string or alias, especially for less common keys or international keyboard layouts.
*   **Concurrency and State Management:**
    *   Rapidly sending multiple commands might lead to race conditions or unexpected behavior depending on how `@nut-tree-fork/nut-js` and the OS handle quick sequences of input events. The configured `autoDelayMs` ([`mcp_servers/computer_use_mcp/src/index.ts:17-19`](mcp_servers/computer_use_mcp/src/index.ts:17-19)) aims to mitigate this but might not cover all scenarios.
*   **Clarity of Tool Definitions (Internal):**
    *   The Zod schemas and inline descriptions are clear and helpful for understanding tool parameters.
*   **Graceful Shutdown:**
    *   A `SIGINT` handler is present (`process.on('SIGINT', () => { process.exit(0); })`) ([`mcp_servers/computer_use_mcp/src/index.ts:217-219`](mcp_servers/computer_use_mcp/src/index.ts:217-219)) for basic graceful shutdown. It doesn't appear to do any specific cleanup related to `nut-js` or `fastmcp`, relying on process exit to terminate them.

This concludes the analysis of the `computer_use_mcp` component.

I will now ask for your feedback on this report.