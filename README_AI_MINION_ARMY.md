# AI Minion Army - ADK/React Edition

This project implements an AI Minion Army system using the Google Agent Development Kit (ADK) for the backend agents and a React-based GUI for user interaction.

## System Overview

The system is composed of two main parts:

1.  **Backend Agent System (`adk_minion_army/`)**:
    *   Built with the **Google Agent Development Kit (ADK)**.
    *   Contains various specialized AI agents designed to collaborate on complex tasks.
    *   **Key Agent Types**:
        *   `MinionAgent`: The core worker agent. Capable of using tools (via `ComputerUseMCP`), participating in chat, and exhibiting proactive behaviors based on its instructions.
        *   `LegionMasterAgent`: Acts as a high-level orchestrator. It can delegate tasks to other Minions, including specialized ones like the `DecomposerMinionAgent`. It uses chat for assigning and coordinating tasks among workers.
        *   `DecomposerMinionAgent`: A specialist agent responsible for breaking down complex user-provided tasks into smaller, manageable sub-tasks.
        *   `SummarizerMinionAgent`: A specialist agent that takes information collated from other Minions and synthesizes it into a coherent summary.
        *   `ChatCoordinatorAgent`: Manages chat channels, records conversation history (currently in-memory per session), and relays messages between participating agents.
    *   **Entry Point**: `adk_minion_army/main_adk.py` is the primary script for running and testing various backend scenarios and agent interactions. Different scenarios (e.g., proactive minion tests, multi-agent task decomposition, chat simulations) are typically orchestrated within this file's `main()` function.

2.  **Frontend GUI (`legionmaster-gui/`)**:
    *   A **React-based web application** designed to serve as the user interface for monitoring and interacting with the Minion army.
    *   **Key UI Components (Placeholders with Mock Data)**:
        *   `MainDashboard`: Main layout organizing different UI panels.
        *   `MinionList`: Displays available Minions and their (mocked) status.
        *   `ChannelList`: Shows available chat channels.
        *   `ChatWindow`: Area for displaying chat messages and sending new ones for a selected channel.
        *   `TaskInput`: Allows users to input tasks for LegionMaster or directives for specific Minions.
        *   `ActivityMonitor`: Displays a mock stream of system and agent activities.
    *   **Backend Interaction**: Currently connects to a mock API service (`src/services/apiService.js`) which simulates backend responses. Real API integration is a future step.

## Conceptual Interaction Flow

A typical complex task might flow through the system as follows:

1.  **User Input**: User submits a complex task via the `legionmaster-gui` (e.g., through the `TaskInput` component).
2.  **Task to LegionMaster**: The GUI (via its API service) sends the task to the `LegionMasterAgent`.
3.  **Decomposition**: `LegionMasterAgent`, recognizing a complex task, delegates it to its `DecomposerMinionAgent` sub-agent.
4.  **Sub-task Generation**: `DecomposerMinionAgent` breaks the task into several sub-tasks.
5.  **Chat-based Assignment**: `LegionMasterAgent` receives the decomposed steps and formulates a message to a designated chat channel (managed by `ChatCoordinatorAgent`), assigning these sub-tasks to available `MinionAgent`s (e.g., MinionAlpha, MinionBeta).
6.  **Task Execution**: `MinionAgent`s receive their assignments by "reading" the chat (orchestrated by `main_adk.py` delivering relayed messages). They execute their sub-tasks (potentially using tools or their LLM knowledge).
7.  **Results via Chat**: Worker `MinionAgent`s report their findings/results back to the chat channel.
8.  **Summarization**: `main_adk.py` (or a future supervising agent) collects these results from the chat. The collected results are then passed to `SummarizerMinionAgent`.
9.  **Final Report**: `SummarizerMinionAgent` generates a consolidated report.
10. **Display to User**: This final report would eventually be sent back to the GUI for the user to view.

## Running the System

### Backend (ADK Agents)

1.  **Prerequisites**:
    *   Python (3.9+ recommended).
    *   Required Python packages (typically managed via a `requirements.txt` or by installing them as needed; key dependencies include `google-agent-development-kit`, `google-generativeai`).
2.  **Environment Variables**:
    *   Ensure your Gemini API key is set as an environment variable: `GEMINI_API_KEY_LEGION`. This is loaded by `adk_minion_army/config_loader.py`.
3.  **Execution**:
    *   Navigate to the project root directory.
    *   Run: `python -m adk_minion_army.main_adk`
    *   **Note**: `adk_minion_army/main_adk.py` contains various test scenarios. You may need to comment/uncomment sections within its `async def main():` function to run the specific scenario you are interested in (e.g., proactive minion, chat tests, task decomposition flow).
4.  **MCP Server (if tool use is tested)**:
    *   The `MinionAgent` is configured to use `computer_use_mcp` tools. Ensure the Node.js server for this (`mcp_servers/computer_use_mcp/`) is running if scenarios involving these tools are being tested.
    *   Typically: `cd mcp_servers/computer_use_mcp && npm install && node dist/index.js` (or as per its own README).

### Frontend (React GUI)

1.  **Prerequisites**:
    *   Node.js (v16+ recommended) and npm.
2.  **Installation**:
    *   Navigate to the frontend directory: `cd legionmaster-gui`
    *   Install dependencies: `npm install`
3.  **Running the Development Server**:
    *   While in the `legionmaster-gui` directory, run: `npm start`
    *   This will typically open the GUI in your default web browser (e.g., at `http://localhost:3000`).

## Future Refinements & Development Areas

This project is an ongoing exploration of multi-agent systems with ADK. Key areas for future development include:

1.  **Robust Inter-Agent Communication**:
    *   Move beyond `main_adk.py`-based orchestration and string parsing for agent commands.
    *   Implement a system where agents can return structured action objects (e.g., `TransferAction`, `ChatMessageAction`) for more reliable control flow.
    *   Explore a dedicated message bus or enhance ADK `Runner`/`LlmAgent` for direct, robust inter-agent messaging and service calls.

2.  **Advanced Chat-Based Task Management**:
    *   Develop more sophisticated mechanisms for Minions to understand tasks assigned via chat (e.g., improved @mention handling, structured task formats within messages).
    *   Enable `ChatCoordinatorAgent` or a dedicated "ProjectManagerMinion" to actively track task progress from chat, manage deadlines, and automatically collate results.

3.  **ADK WorkflowAgent Integration**:
    *   Refactor the manual orchestration loops in `main_adk.py` (like the one for decomposition and sequential execution) to use ADK's `SequentialWorkflowAgent` and `ParallelWorkflowAgent`. This would provide more robust and scalable management of multi-step tasks.

4.  **Dynamic Agent Management**:
    *   Explore dynamic spawning, scaling, and termination of Minion agents based on workload, potentially managed by `LegionMasterAgent` or a dedicated scaling service.

5.  **Persistent State & Memory**:
    *   Implement persistent storage for chat history (beyond `InMemorySessionService`) using `ArtifactService` or external databases.
    *   Provide Minions with more sophisticated long-term memory capabilities.

6.  **Real Backend API for GUI**:
    *   Replace the mock `apiService.js` in `legionmaster-gui` with actual HTTP/WebSocket API calls to the ADK backend. This would involve creating ADK agents that expose API endpoints (e.g., using ADK's web server capabilities or integrating with a Python web framework).

7.  **Enhanced Tooling & Capabilities**:
    *   Expand the range of tools available to Minions.
    *   Allow Minions to potentially propose or even (under supervision) create new tools or scripts.

8.  **Testing and Evaluation Framework**:
    *   Develop a more formal framework for testing individual agent capabilities and complex multi-agent scenarios.

## Directory Structure Overview (Current)

- `README_AI_MINION_ARMY.md` (This file)
- `adk_minion_army/`
    - `__init__.py`
    - `main_adk.py` (Main backend scenario runner)
    - `config_loader.py`
    - `agents/`
        - `__init__.py`
        - `minion_agent.py`
        - `legion_master_agent.py`
        - `decomposer_minion_agent.py`
        - `summarizer_minion_agent.py`
        - `chat_coordinator_agent.py`
- `legionmaster-gui/` (React application)
    - `public/`
    - `src/`
        - `App.js`, `index.js`, `App.css`, etc.
        - `components/` (Dashboard, MinionDisplay, Chat, TaskControl)
        - `services/apiService.js` (Mock API)
    - `package.json`, etc.
- `mcp_servers/`
    - `computer_use_mcp/` (Node.js based tool server for Minions)
- `system_configs/` (Placeholder, actual config like API key is via env var)
- `logs/` (Placeholder, ADK/React might log here or to console)

This project aims to evolve into a powerful and flexible multi-agent system. Contributions and feedback are welcome.
```
