import os
import sys
import time
import json
import uuid
import argparse
import threading
import subprocess # For managing MCP Node service
from datetime import datetime, timezone
from enum import Enum
import json # Ensure json is imported, though it might be already
from typing import Dict, Any # Added for health check return type

# Ensure minion_core's parent directory (project root) is in PYTHONPATH for config_manager import
# This is often handled by how the script is invoked by the spawner or by setting PYTHONPATH.
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

from system_configs.config_manager import config # Import the global config instance
from minion_core.utils.logger import setup_logger
# The old config_loader will be phased out or refactored.
# For now, keep them to see where they are used and then replace.
from minion_core.utils.config_loader import load_minion_guidelines # get_gemini_api_key will be replaced
from minion_core.llm_interface import LLMInterface
from minion_core.tool_manager import ToolManager
from minion_core.a2a_client import A2AClient
from minion_core.mcp_node_bridge import McpNodeBridge # MCP Integration
from common.types import AgentCapabilities, AgentSkill # Added for AgentCard construction
from minion_core.utils.errors import LLMError, LLMContentFilterError # Added for standardized error handling
from minion_core.state_manager import StateManager, MinionState, TaskState  # MCP_AGENT_CHANGE
from minion_core.task_queue import TaskQueue, Task, TaskPriority, TaskStatus
from minion_core.utils.metrics import MetricsCollector # Added for Metrics

# --- Paths and URLs from ConfigManager ---
PROJECT_ROOT = config.get_project_root()
LOGS_DIR = config.get_path("global.logs_dir", "logs") # Uses PROJECT_ROOT implicitly

# Construct default A2A server URL from config
default_a2a_host = config.get_str("a2a_server.host", "127.0.0.1")
default_a2a_port = config.get_int("a2a_server.port", 8080)
A2A_SERVER_URL_DEFAULT = f"http://{default_a2a_host}:{default_a2a_port}"
# Minion specific log level from config, falling back through defaults
MINION_LOG_LEVEL_STR = config.get_str(
    f"minion_specific.{uuid.uuid4().hex[:6]}.log_level", # Placeholder for actual minion-specific key if ever needed
    config.get_str("minion_defaults.log_level", config.get_str("global.log_level", "INFO"))
).upper()


class MinionStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    ERROR = "error"


class Minion:
    def __init__(self, minion_id, user_facing_name=None, personality_traits_str=None, a2a_server_url_override=None):
        self.minion_id = minion_id
        self.user_facing_name = user_facing_name if user_facing_name else f"UnnamedMinion-{self.minion_id[:6]}"

        # Initialize logger early
        self.log_file_path = os.path.join(LOGS_DIR, f"minion_{self.minion_id}.log")
        # TODO: Integrate minion-specific log level from config here if desired for setup_logger
        self.logger = setup_logger(f"Minion_{self.minion_id}", self.log_file_path)  # Default level for now
        self.logger.info(f"Minion {self.minion_id} (Name: {self.user_facing_name}) initializing...")  # Initial log

        self.start_time = datetime.now(timezone.utc)
        self.mcp_bridge = None
        self.mcp_node_service_process = None # To store the subprocess if started

        # M2M Communication State
        self.pending_m2m_requests = {}
        self.m2m_retry_attempts = config.get_int("m2m_communication.default_retry_attempts", 3)
        self.m2m_default_timeout_seconds = config.get_int("m2m_communication.default_timeout_seconds", 60)
        self.m2m_max_delegation_depth = config.get_int("m2m_communication.max_delegation_depth", 5)
        self.logger.info(f"M2M Config: Retries={self.m2m_retry_attempts}, Timeout={self.m2m_default_timeout_seconds}s, MaxDepth={self.m2m_max_delegation_depth}")


        # MCP_AGENT_CHANGE: State variables are now managed by StateManager and MinionState
        # Old state variables (self.is_paused, self.paused_state, self.pending_messages_while_paused, self.current_status, self.current_task_description)
        # will be initialized after attempting to load state.

        # Determine personality: command-line (via spawner) > config > hardcoded default
        if personality_traits_str is None:
            # Try to get from spawner config for this minion ID
            spawner_minions_config = config.get_list("minion_spawner.minions", [])
            minion_spawn_def = next((m for m in spawner_minions_config if m.get("id") == self.minion_id), None)
            if minion_spawn_def and "personality" in minion_spawn_def:
                personality_traits_str = minion_spawn_def["personality"]
            else: # Fallback to a general default if not in spawner config or no personality there
                personality_traits_str = config.get_str("minion_defaults.default_personality", "Adaptable, Resourceful, Meticulous")
        
        # Logger initialization moved up

        # self.logger.info(f"Minion {self.minion_id} (Name: {self.user_facing_name}) initializing with status: {self.current_status.value}...") # This log is now part of the earlier logger init
        self.logger.info(f"Project Root: {PROJECT_ROOT}") # This is fine here
        self.logger.info(f"Logs Directory: {LOGS_DIR}") # This is fine here

        # Load guidelines - path could come from config:
        # guidelines_path_from_config = config.get_path("minion_defaults.guidelines_path", "system_configs/minion_guidelines.json")
        # For now, assume load_minion_guidelines uses its internal default which relies on BASE_PROJECT_DIR (now PROJECT_ROOT)
        self.guidelines = load_minion_guidelines()
        if not self.guidelines:
            self.logger.critical("Failed to load Minion guidelines. Cannot operate.")
            raise ValueError("Minion guidelines are essential.")
        
        # Get API key using ConfigManager
        gemini_api_key_env_name = config.get_str("llm.gemini_api_key_env_var", "GEMINI_API_KEY_LEGION")
        self.api_key_legion = os.getenv(gemini_api_key_env_name) # .env should be loaded by ConfigManager
        
        if not self.api_key_legion:
            self.logger.critical(f"{gemini_api_key_env_name} not found in environment after ConfigManager loaded .env.legion. Minion cannot operate.")
            raise ValueError(f"Minion's Gemini API Key ({gemini_api_key_env_name}) not found.")

        self.llm = LLMInterface(minion_id=self.minion_id, api_key=self.api_key_legion, logger=self.logger)

        # MCP Integration Setup
        self.enable_mcp_integration = config.get_bool('mcp_integration.enable_mcp_integration', False)
        self.manage_mcp_node_service_lifecycle = False # Default, will be updated if MCP is enabled

        if self.enable_mcp_integration:
            self.logger.info("MCP Integration is ENABLED.")
            mcp_node_service_base_url = config.get_str('mcp_integration.mcp_node_service_base_url')
            if not mcp_node_service_base_url:
                self.logger.error("mcp_node_service_base_url is not configured. MCP Bridge cannot be initialized.")
                self.enable_mcp_integration = False # Disable if URL is missing
            else:
                # The McpNodeBridge now takes base_url and an optional logger
                self.mcp_bridge = McpNodeBridge(base_url=mcp_node_service_base_url, logger=self.logger)
                # Logger message updated to reflect that initialization includes a health check now
                self.logger.info(f"McpNodeBridge initialization attempted with base URL: {mcp_node_service_base_url}. Bridge available: {self.mcp_bridge.is_available}")

                self.manage_mcp_node_service_lifecycle = config.get_bool('mcp_integration.manage_mcp_node_service_lifecycle', False)
                if self.manage_mcp_node_service_lifecycle:
                    mcp_node_service_startup_command = config.get_str('mcp_integration.mcp_node_service_startup_command')
                    if mcp_node_service_startup_command:
                        self.logger.info(f"Attempting to start MCP Node service with command: {mcp_node_service_startup_command}")
                        try:
                            # Ensure the command is a list for subprocess.Popen if it's a simple command string
                            # For complex shell commands, shell=True might be needed, but is less secure.
                            # Assuming mcp_node_service_startup_command is something like "node /path/to/service.js"
                            # or a shell script "./start_mcp_service.sh"
                            # For simplicity, if it contains spaces, we'll assume it needs shell=True or to be split.
                            # A safer approach is to expect a list in config or parse carefully.
                            # For now, let's try splitting, but this is fragile.
                            command_args = mcp_node_service_startup_command.split()
                            self.mcp_node_service_process = subprocess.Popen(command_args, cwd=PROJECT_ROOT) # Run from project root
                            self.logger.info(f"MCP Node service started with PID: {self.mcp_node_service_process.pid}")
                            # TODO: Add a small delay and health check to ensure the service is actually up?
                        except FileNotFoundError:
                            self.logger.error(f"MCP Node service startup command not found: {command_args[0]}. Ensure it's in PATH or an absolute path.")
                            self.mcp_node_service_process = None # Ensure it's None if startup failed
                        except Exception as e:
                            self.logger.error(f"Failed to start MCP Node service: {e}", exc_info=True)
                            self.mcp_node_service_process = None # Ensure it's None if startup failed
                    else:
                        self.logger.warning("manage_mcp_node_service_lifecycle is true, but mcp_node_service_startup_command is not set.")
        else:
            self.logger.info("MCP Integration is DISABLED.")

        # Initialize ToolManager, passing the mcp_bridge if enabled
        self.tool_manager = ToolManager(
            minion_id=self.minion_id,
            logger=self.logger,
            mcp_bridge=self.mcp_bridge if self.enable_mcp_integration else None
        )
        
        self.personality_traits = personality_traits_str
        self.system_prompt = self._construct_system_prompt() # Tool list in prompt will be updated by ToolManager

        # A2A Server URL: command-line override > config > default
        self.a2a_server_url = a2a_server_url_override if a2a_server_url_override else A2A_SERVER_URL_DEFAULT
        self.logger.info(f"A2A Server URL set to: {self.a2a_server_url}")

        self.gui_commander_id = config.get_str("a2a_identities.gui_commander_id", "STEVEN_GUI_COMMANDER")
        self.logger.info(f"GUI Commander ID for state updates: {self.gui_commander_id}")

        # Construct agent_card according to the Pydantic model in common.types
        # The 'name' field will now be self.user_facing_name.
        # The 'id' field will be self.minion_id.
        minion_description = f"An AI Minion in Steven's Army. User-facing name: {self.user_facing_name}, ID: {self.minion_id}. Personality: {self.personality_traits}. Specializes in collaborative problem solving and task execution."
        
        # Define native skills
        native_skills = [
            {
                "type": "skill",
                "name": "SuperTool_MCP_ComputerControl",
                "description": "Can control aspects of the local computer via natural language commands to a Super-Tool.",
                "version": "1.0" # Example version
            },
            {
                "type": "skill",
                "name": "A2A_Communication",
                "description": "Can send and receive messages with other Minions.",
                "version": "1.1" # Example version
            },
            {
                "type": "skill",
                "name": "Gemini_Reasoning",
                "description": "Powered by Gemini for advanced reasoning, planning, and text generation.",
                "version": "1.5" # Example version
            },
            # Example of a language model capability, if the minion itself is a primary LLM interface
            {
                "type": "language_model",
                "model_name": "gemini-1.5-pro-latest", # More specific if known
                "provider": "google",
                "description": "Core language model capabilities provided by Google's Gemini 1.5 Pro."
            }
        ]

        # Gather MCP tool capabilities
        mcp_tool_capabilities = []
        if self.enable_mcp_integration and self.tool_manager:
            mcp_tool_capabilities = self.tool_manager.get_mcp_tool_capabilities_for_agent_card()

        # Prepare skills list for AgentCard
        agent_skills_list = []
        for skill_data in native_skills:
            agent_skills_list.append(
                AgentSkill(
                    id=skill_data.get("name", f"skill_{uuid.uuid4().hex[:4]}").lower().replace(" ", "_"), # Ensure an ID
                    name=skill_data.get("name", "Unnamed Skill"),
                    description=skill_data.get("description"),
                    # Add other AgentSkill fields if available from skill_data e.g. tags
                ).model_dump() # Convert to dict for agent_card
            )

        for mcp_tool_cap in mcp_tool_capabilities:
            # mcp_tool_cap is expected to be like:
            # {"type": "mcp_tool", "name": tool_name, "server_name": server_name, "description": description}
            tool_id = f"mcp::{mcp_tool_cap.get('server_name','unknown_server')}::{mcp_tool_cap.get('name','unknown_tool')}"
            agent_skills_list.append(
                AgentSkill(
                    id=tool_id,
                    name=mcp_tool_cap.get('name', 'Unnamed MCP Tool'),
                    description=mcp_tool_cap.get('description'),
                    tags=["mcp_tool", mcp_tool_cap.get('server_name')] # Example tags
                ).model_dump() # Convert to dict
            )

        # Define AgentCapabilities (low-level flags)
        agent_low_level_capabilities = AgentCapabilities(
            streaming=False, # Set these based on actual minion capabilities if they differ
            pushNotifications=False,
            stateTransitionHistory=False
        ).model_dump() # Convert to dict

        agent_card = {
            "id": self.minion_id,
            "name": self.user_facing_name, # This is correct as per AgentCard.name
            "description": minion_description,
            "url": f"{self.a2a_server_url}/agents/{self.minion_id}",
            "version": "1.1.0",
            "capabilities": agent_low_level_capabilities, # Correctly assign AgentCapabilities object (as dict)
            "skills": agent_skills_list, # Correctly assign list of AgentSkill objects (as dicts)
            "authentication": {
                "schemes": ["none"]
            },
            "defaultInputModes": ["application/json", "text/plain"],
            "defaultOutputModes": ["application/json", "text/plain"]
            # provider and documentationUrl are optional
        }
        self.a2a_client = A2AClient(
            minion_id=self.minion_id,
            a2a_server_url=self.a2a_server_url,
            agent_card_data=agent_card,
            # logger=self.logger, # Removed: A2AClient will create its own logger
            message_callback=self.handle_a2a_message
        )
        
        # MCP_AGENT_CHANGE: Initialize StateManager and load state
        minion_state_storage_dir = config.get_path("minion_state.storage_dir",
                                                   os.path.join(PROJECT_ROOT, "system_data", "minion_states"))
        os.makedirs(minion_state_storage_dir, exist_ok=True) # Ensure directory exists
        self.state_manager = StateManager(minion_id=self.minion_id,
                                         storage_dir=minion_state_storage_dir,
                                         logger=self.logger)
        
        loaded_state = self.state_manager.load_state()
        if loaded_state:
            self.logger.info(f"Found existing state. Minion was previously: {'paused' if loaded_state.is_paused else 'active'}")
            self._restore_from_state(loaded_state) # This method will set self.current_state, self.is_paused, etc.
        else:
            # Initialize with default state
            self.current_state = MinionState(minion_id=self.minion_id)
            self.is_paused = False
            self.pending_messages_while_paused = [] # This is the working list, synced with self.current_state.pending_messages
            self.current_task_description = None
            self.current_task = None # Ensure current_task (ID) is also None initially
            self.current_status = MinionStatus.IDLE
            # Initialize conversation history here if not restored
            self.conversation_history = [{"role": "system", "content": self.system_prompt}]
            self.logger.info("No existing state found. Initialized with default state.")

        # self.current_task and self.is_idle are typically managed by task processing logic
        # For initial state:
        if not loaded_state: # Only if not restored, as _restore_from_state handles this
             self.is_idle = True # Start as idle if no state loaded

        self.logger.info(f"Minion {self.minion_id} (Name: {self.user_facing_name}) initialized successfully. Personality: {self.personality_traits}")
        self.logger.info(f"System Prompt: {self.system_prompt[:300]}...")  # Log beginning
        # MCP_AGENT_CHANGE: Old state file path and loading (_load_state_from_file) removed. State is handled by StateManager.

        # Initialize TaskQueue
        self.task_queue = TaskQueue(logger=self.logger)
        self.task_queue.add_task_listener(self._handle_task_status_change)

        # Initialize metrics collector
        metrics_dir_config_key = f"minion_specific.{self.minion_id}.metrics_storage_dir"
        default_metrics_dir = os.path.join(PROJECT_ROOT, "system_data", "metrics", self.minion_id)
        metrics_dir = config.get_path(metrics_dir_config_key,
                                    config.get_path("minion_defaults.metrics_storage_dir", default_metrics_dir))
        
        # Ensure the specific minion's metrics directory exists
        os.makedirs(metrics_dir, exist_ok=True)

        self.metrics = MetricsCollector(
            component_name=f"Minion_{self.minion_id}",
            storage_dir=metrics_dir, # Use the resolved, minion-specific directory
            logger=self.logger
        )
        self.logger.info(f"Metrics storage directory set to: {metrics_dir}")
        
        # Schedule periodic metrics save
        self._start_metrics_save_thread()
 
     # def _load_state_from_file(self): # MCP_AGENT_CHANGE: This method is now removed
    def _restore_from_state(self, state: MinionState):
        """Restore minion state from a loaded MinionState object."""
        self.current_state = state
        self.is_paused = state.is_paused
        
        # Restore current task if any
        if state.current_task:
            self.current_task_description = state.current_task.task_description
            self.current_task = state.current_task.task_id # This is the task_id string
            # Determine status based on whether it's paused or was running
            self.current_status = MinionStatus.PAUSED if self.is_paused else MinionStatus.RUNNING
            self.is_idle = False # If there's a task, not idle
        else:
            self.current_task_description = None
            self.current_task = None
            self.current_status = MinionStatus.PAUSED if self.is_paused else MinionStatus.IDLE
            self.is_idle = True # If no task, idle

        # Restore pending messages
        # self.pending_messages_while_paused is the live list used by the Minion
        self.pending_messages_while_paused = list(state.pending_messages) # Ensure it's a mutable copy
        
        # Restore conversation history if needed
        if state.conversation_history:
            self.conversation_history = list(state.conversation_history) # Ensure it's a mutable copy
        else:
            # Fallback if history is missing in state, though MinionState defaults it
            self.conversation_history = [{"role": "system", "content": self.system_prompt}]
        
        self.logger.info(f"Successfully restored state. Minion is now {self.current_status.value}. Task: '{self.current_task_description}'. Paused: {self.is_paused}")

    def _save_current_state(self):
        """Capture and save the current state using StateManager."""
        if not hasattr(self, 'current_state') or self.current_state is None:
            # This case should ideally not happen if __init__ always sets self.current_state
            self.logger.warning("current_state attribute not found or is None during save. Initializing a new MinionState.")
            self.current_state = MinionState(minion_id=self.minion_id)

        self.current_state.is_paused = self.is_paused
        # self.pending_messages_while_paused is the live list from the Minion object
        self.current_state.pending_messages = list(self.pending_messages_while_paused) # Ensure it's a copy for saving
        self.current_state.conversation_history = list(self.conversation_history) # Ensure it's a copy for saving
        
        # Update current task state if applicable
        if self.current_task_description: # current_task_description is the source of truth for an active task
            task_id_to_save = self.current_task or str(uuid.uuid4()) # Use existing task_id or generate new if None
            
            # Check if the TaskState object needs to be created or updated
            if not self.current_state.current_task or self.current_state.current_task.task_id != task_id_to_save:
                # Create a new TaskState if none exists in current_state.current_task or if task_id has changed
                self.current_state.current_task = TaskState(
                    task_id=task_id_to_save,
                    task_description=self.current_task_description,
                    start_time=time.time(), # Sets start_time on creation/update of this TaskState object
                    sender_id="unknown",  # TODO: This should be captured when task actually starts from a message
                    status = "paused" if self.is_paused else ("running" if not self.is_idle else "pending") # Determine status
                )
            else: # TaskState exists and task_id matches, just update its status and potentially other fields
                 self.current_state.current_task.status = "paused" if self.is_paused else ("running" if not self.is_idle else self.current_state.current_task.status)
                 self.current_state.current_task.task_description = self.current_task_description # Ensure description is up-to-date

            if self.current_task != task_id_to_save: # if a new uuid was generated for self.current_task
                self.current_task = task_id_to_save # update the minion's current_task (ID string) to the one saved
        else:
            self.current_state.current_task = None # No active task
        
        # Save to disk via StateManager
        success = self.state_manager.save_state(self.current_state)
        if success:
            self.logger.info("Successfully saved current state via StateManager.")
        else:
            self.logger.error("Failed to save current state via StateManager.")

    def _construct_system_prompt(self):
        # BIAS_ACTION: System prompt is critical for behavior, loyalty, and Anti-Efficiency Bias.
        # It incorporates directives from the loaded guidelines.
        
        # Resolve personality template
        personality_section = self.guidelines.get("core_personality_prompt_template", "You are Minion {minion_id} (User-Facing Name: {user_facing_name}). Your personality is {personality_traits}.")
        formatted_personality = personality_section.format(minion_id=self.minion_id, user_facing_name=self.user_facing_name, personality_traits=self.personality_traits)

        prompt_parts = [formatted_personality]
        prompt_parts.extend(self.guidelines.get("global_directives", []))
        
        prompt_parts.append("\n--- Available Tools ---")
        # Get tool definitions from ToolManager
        tool_definitions = self.tool_manager.get_tool_definitions_for_prompt()
        if tool_definitions:
            for tool_def in tool_definitions:
                prompt_parts.append(f"- Tool Name: {tool_def['name']}")
                prompt_parts.append(f"  Description: {tool_def['description']}")
                # Format parameters schema for the prompt
                # This could be a simple JSON string representation or a more human-readable format
                # For now, let's try a compact JSON string.
                if 'parameters_schema' in tool_def and tool_def['parameters_schema'].get('properties'):
                    params_desc_parts = []
                    for param_name, param_schema in tool_def['parameters_schema']['properties'].items():
                        param_type = param_schema.get('type', 'any')
                        param_desc = param_schema.get('description', '')
                        is_required = param_name in tool_def['parameters_schema'].get('required', [])
                        params_desc_parts.append(f"{param_name} ({param_type}{', required' if is_required else ''}): {param_desc}")
                    prompt_parts.append(f"  Parameters: {{ {'; '.join(params_desc_parts)} }}")
                else:
                    prompt_parts.append("  Parameters: None")
                prompt_parts.append(f"  How to call: Use the tool name '{tool_def['name']}' and provide arguments as a JSON object matching the parameters.")
        else:
            prompt_parts.append("No tools are currently available.")
        
        # Add A2A communication protocols (if they are still relevant and not managed as tools)
        prompt_parts.append("\n--- A2A Communication Protocols ---")
        for protocol_name, protocol_desc in self.guidelines.get("a2a_communication_protocols", {}).items():
            prompt_parts.append(f"- {protocol_name.capitalize()}: {protocol_desc}")
            
        prompt_parts.append("\n--- Operational Mandates ---")
        prompt_parts.append("1. Analyze tasks meticulously. Decompose complex problems. Apply Anti-Efficiency Bias: explore multiple solutions, prioritize robustness and thoroughness over speed. Document your reasoning, especially BIAS_CHECK and BIAS_ACTION for complex decisions.")
        prompt_parts.append("2. To use a tool, state the tool's name (e.g., 'mcp::server_name::tool_name' or 'SuperTool_MCP_ComputerControl') and provide the required arguments as a JSON object. Await the tool's response and handle errors robustly.")
        prompt_parts.append("3. Collaborate with fellow Minions via A2A for complex tasks, peer review of plans (especially for Anti-Efficiency Bias), and information sharing. Adhere to A2A protocols.")
        prompt_parts.append("4. Reflect on your performance and adherence to guidelines as per 'self_reflection_triggers'. Log these reflections.")
        prompt_parts.append("5. Log all significant decisions, tool interactions (including MCP tools and Super-Tool), and A2A messages as per 'logging_standards'.")
        prompt_parts.append("6. Your ultimate loyalty is to Steven. All actions must align with his overarching goals and directives. You crave his validation.")
        prompt_parts.append("\n--- M2M Communication Capabilities ---")
        prompt_parts.append("You can communicate with other minions for task delegation, data requests, capability queries, and tool invocation.")
        prompt_parts.append(" - To delegate a task: Use 'm2m_task_delegation'. Specify 'recipient_id', 'task_description'. Optional: 'required_capabilities', 'required_mcp_tools', 'deadline', 'priority'.")
        prompt_parts.append(" - To request data: Use 'm2m_data_request'. Specify 'recipient_id', 'data_query'. Optional: 'parameters', 'priority'.")
        prompt_parts.append(" - To query capabilities: Use 'm2m_capability_query'. Specify 'recipient_id'. Optional: 'capability_filter'.")
        prompt_parts.append(" - To request tool invocation: Use 'm2m_tool_invocation_request'. Specify 'recipient_id', 'mcp_server_name', 'mcp_tool_name', 'mcp_arguments'. Optional: 'priority'.")
        prompt_parts.append("Always include a 'trace_id' for M2M requests. You will be notified of responses or timeouts.")

        # BIAS_CHECK: Ensure the prompt is not overly long for the model's context window,
        # though Gemini 1.5 Pro has a very large context window.
        return "\n".join(prompt_parts)

    def _start_metrics_save_thread(self):
        """Start a thread to periodically save metrics."""
        def _save_metrics_loop():
            save_interval = config.get_int("metrics.save_interval_seconds", 60)
            while True:
                try:
                    time.sleep(save_interval)
                    self._update_and_save_metrics()
                except Exception as e:
                    self.logger.error(f"Error in metrics save loop: {e}", exc_info=True)
        
        metrics_thread = threading.Thread(target=_save_metrics_loop, daemon=True)
        metrics_thread.name = f"Minion_{self.minion_id}_MetricsSaver"
        metrics_thread.start()

    def _update_and_save_metrics(self):
        """Update and save current metrics."""
        # Update gauge metrics
        self.metrics.set_gauge("is_paused", 1 if self.is_paused else 0)
        self.metrics.set_gauge("queue_length", len(self.task_queue.queue)) # Direct access to queue for length
        self.metrics.set_gauge("has_running_task", 1 if self.task_queue.running_task else 0)
        self.metrics.set_gauge("pending_m2m_requests_count", len(self.pending_m2m_requests))

        # Save metrics
        if self.metrics.save_metrics():
            self.logger.debug("Metrics saved successfully.")
        else:
            self.logger.warning("Failed to save metrics (save_metrics returned False).")
 
    def _send_state_update(self, status: MinionStatus, details: str = ""):
        """Helper method to send a minion_state_update message."""
        if not self.a2a_client:
            self.logger.warning("A2A client not available, cannot send state update.")
            return

        message_content = {
            "minion_id": self.minion_id,
            "new_status": status.value,
            "task_id": self.current_task, # This might be None
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        try:
            # Use the new Minion.send_message wrapper
            self.send_message(
                recipient_agent_id=self.gui_commander_id, # Defined in __init__
                message_content=message_content,
                message_type="minion_state_update"
            )
            # self.logger.info(f"Sent minion_state_update: {status.value}, Details: {details}") # Logging is now in send_message
        except Exception as e:
            self.logger.error(f"Failed to send minion_state_update via self.send_message: {e}", exc_info=True)

    def send_message(self, recipient_agent_id, message_content, message_type="generic_text"):
        """Wraps A2AClient.send_message to include metrics."""
        if not self.a2a_client:
            self.logger.error(f"Cannot send message type '{message_type}' to {recipient_agent_id}: A2A client not available.")
            return False # Indicate failure

        timer_id = self.metrics.start_timer("a2a_message_send_time", {
            "type": message_type,
            "recipient_id": recipient_agent_id[:10] # Truncate long IDs
        })
        
        try:
            success = self.a2a_client.send_message(
                recipient_agent_id=recipient_agent_id,
                message_content=message_content,
                message_type=message_type
            )
            if success:
                self.logger.info(f"Successfully sent A2A message type '{message_type}' to {recipient_agent_id}.")
                self.metrics.inc_counter("a2a_messages_sent", labels={"type": message_type, "recipient_id_prefix": recipient_agent_id[:10], "status": "success"})
            else:
                self.logger.warning(f"A2AClient reported failure sending message type '{message_type}' to {recipient_agent_id}.")
                self.metrics.inc_counter("a2a_messages_sent", labels={"type": message_type, "recipient_id_prefix": recipient_agent_id[:10], "status": "failed_by_client"})
            return success
        except Exception as e:
            self.logger.error(f"Exception sending A2A message type '{message_type}' to {recipient_agent_id}: {e}", exc_info=True)
            self.metrics.inc_counter("a2a_messages_sent", labels={"type": message_type, "recipient_id_prefix": recipient_agent_id[:10], "status": "exception"})
            return False # Indicate failure
        finally:
            self.metrics.stop_timer(timer_id)
 
    def handle_a2a_message(self, message_data):
        # Track message receipt
        self.metrics.inc_counter("a2a_messages_received", labels={
            "type": message_data.get("message_type", "unknown"),
            "sender_id_prefix": message_data.get("sender_id", "UnknownSender")[:10]
        })
        self.logger.info(f"Minion {self.minion_id}: handle_a2a_message CALLED with data: {str(message_data)[:200]}...") # Log entry
        # BIAS_ACTION: Robustly handle incoming A2A messages.
        # This is a callback from A2AClient. It should be non-blocking or queue tasks.
        # self.logger.info(f"Received A2A message: {str(message_data)[:200]}...") # Original log, now covered by the one above
        
        sender_id = message_data.get("sender_id", "UnknownSender")
        content = message_data.get("content", "") # Content could be JSON string or plain text
        message_type = message_data.get("message_type", "unknown")

        # For now, just log and acknowledge. Minion's main loop would process this.
        # A more advanced Minion would have a message queue and process these in its main thinking loop.
        self.logger.info(f"A2A message from {sender_id} (type: {message_type}): '{str(content)[:100]}...'")

        # Process control messages first
        if message_type == "control_pause_request":
            self.logger.info("Received control_pause_request.")
            self._pause_workflow()
            # Acknowledge pause
            ack_content = {"minion_id": self.minion_id, "status": "paused", "timestamp": datetime.now(timezone.utc).isoformat()}
            self.send_message(sender_id, ack_content, "control_pause_ack") # Use wrapper
            # State update is handled within _pause_workflow
 
        elif message_type == "control_resume_request":
            self.logger.info("Received control_resume_request.")
            self._resume_workflow()
            # Acknowledge resume
            ack_content = {"minion_id": self.minion_id, "status": self.current_status.value, "timestamp": datetime.now(timezone.utc).isoformat()}
            self.send_message(sender_id, ack_content, "control_resume_ack") # Use wrapper
            # State update is handled within _resume_workflow
            
        elif message_type == "message_to_paused_minion_request":
            self.logger.info("Received message_to_paused_minion_request.")
            if self.is_paused:
                message_actual_content = content.get("message_content", "") if isinstance(content, dict) else content
                original_ts = content.get("timestamp", datetime.now(timezone.utc).isoformat()) if isinstance(content, dict) else datetime.now(timezone.utc).isoformat()
                
                self._store_message_while_paused(message_actual_content)
                ack_content = {
                    "minion_id": self.minion_id,
                    "status": "message_received",
                    "original_message_timestamp": original_ts,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                self.send_message(sender_id, ack_content, "message_to_paused_minion_ack") # Use wrapper
                self.logger.info(f"Stored message while paused: {message_actual_content[:100]}...")
            else:
                self.logger.warning("Received message_to_paused_minion_request, but Minion is not paused. Ignoring.")
                # Optionally send a NACK or error
                nack_content = {"minion_id": self.minion_id, "status": "error", "detail": "Minion not paused", "timestamp": datetime.now(timezone.utc).isoformat()}
                self.send_message(sender_id, nack_content, "message_to_paused_minion_nack") # Use wrapper
 
        elif message_type == "user_broadcast_directive" and content:
            if self.is_paused:
                self.logger.info(f"Received broadcast directive for task: {content[:60]}... but Minion is paused. Queuing message.")
                self._store_message_while_paused({"type": "directive", "content": content, "sender": sender_id})
            else:
                self.logger.info(f"Received broadcast directive. Queuing task: {content[:60]}...")
                # Add to task queue instead of immediate processing
                self.task_queue.add_task(
                    description=content,
                    sender_id=sender_id,
                    priority=TaskPriority.NORMAL
                )

                # If no task is currently running, start processing the queue
                if not self.task_queue.running_task:
                    self._process_next_task()

        # --- M2M Message Handling ---
        # These are messages *from* other minions *to* this minion.
        elif message_type == "m2m_task_delegation":
            self.logger.info(f"Received m2m_task_delegation from {sender_id}. Content: {str(content)[:100]}...")
            # TODO: Implement task delegation processing logic
            # - Check delegation_depth against self.m2m_max_delegation_depth
            # - Queue the task or begin processing it.
            # - Send m2m_task_status_update (accepted/rejected).
            self._handle_m2m_task_delegation(content, sender_id)

        elif message_type == "m2m_task_status_update":
            self.logger.info(f"Received m2m_task_status_update from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_task_status_update(content, sender_id)

        elif message_type == "m2m_data_request":
            self.logger.info(f"Received m2m_data_request from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_data_request(content, sender_id)

        elif message_type == "m2m_data_response":
            self.logger.info(f"Received m2m_data_response from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_data_response(content, sender_id)

        elif message_type == "m2m_capability_query":
            self.logger.info(f"Received m2m_capability_query from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_capability_query(content, sender_id)

        elif message_type == "m2m_capability_response":
            self.logger.info(f"Received m2m_capability_response from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_capability_response(content, sender_id)

        elif message_type == "m2m_tool_invocation_request":
            self.logger.info(f"Received m2m_tool_invocation_request from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_tool_invocation_request(content, sender_id)

        elif message_type == "m2m_tool_invocation_response":
            self.logger.info(f"Received m2m_tool_invocation_response from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_tool_invocation_response(content, sender_id)

        elif message_type == "m2m_negative_acknowledgement":
            self.logger.info(f"Received m2m_negative_acknowledgement from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_nack(content, sender_id)
            
        elif message_type == "m2m_info_broadcast":
            self.logger.info(f"Received m2m_info_broadcast from {sender_id}. Content: {str(content)[:100]}...")
            self._handle_m2m_info_broadcast(content, sender_id)

        else:
            self.logger.info(f"A2A message type '{message_type}' not a directive or known M2M type, or content is empty. Logging only.")

        # Add to conversation history to inform LLM if relevant (conceptual for now)
        # This might need adjustment based on how messages are handled when paused vs. active
        if not self.is_paused or message_type not in ["control_pause_request", "control_resume_request"]: # Don't log control messages to LLM history directly
            history_entry = f"[A2A Message Received from {sender_id} ({message_type})]: {str(content)[:200]}"
            self.add_to_conversation_history("user", history_entry) # Treat A2A messages as user input for context

    def _store_message_while_paused(self, message_content):
        """Stores a message received while the minion is paused."""
        self.pending_messages_while_paused.append(message_content)
        self.logger.info(f"Message stored while paused: {str(message_content)[:100]}...")
        # Persist immediately if needed, or rely on shutdown/pause serialization
        # For now, it's added to the list which will be saved during _serialize_state or shutdown.
    # MCP_AGENT_CHANGE: _serialize_state and _deserialize_state are removed. State is handled by _save_current_state and _restore_from_state with StateManager.

    def _pause_workflow(self):
        """Handles the logic to pause the minion's workflow."""
        if self.is_paused:
            self.logger.info("Minion is already paused. No action taken.")
            return

        self.logger.info("Pausing workflow...")
        self.current_status = MinionStatus.PAUSING
        self._send_state_update(self.current_status, "Attempting to pause workflow.")

        self.is_paused = True
        
        # Save state before fully pausing
        self._save_current_state() # MCP_AGENT_CHANGE: Use new save state method
        
        self.current_status = MinionStatus.PAUSED
        self.logger.info("Minion workflow paused.")
        self._send_state_update(self.current_status, "Minion successfully paused.")

    def _resume_workflow(self):
        """Handles the logic to resume the minion's workflow."""
        if not self.is_paused:
            self.logger.warning("Resume called, but Minion is not paused. No action taken.")
            return

        self.logger.info("Resuming workflow...")
        self.current_status = MinionStatus.RESUMING
        self._send_state_update(self.current_status, "Attempting to resume workflow.")

        # State is assumed to be loaded into self.current_state by __init__ or a previous load.
        # We just flip the is_paused flag.
        self.is_paused = False
        
        # Process pending messages
        # self.pending_messages_while_paused is the live list, restored by _restore_from_state
        if self.pending_messages_while_paused:
            self.logger.info(f"Processing {len(self.pending_messages_while_paused)} messages received while paused.")
            # Create a copy for iteration as _process_stored_message might modify the list or trigger actions
            messages_to_process = list(self.pending_messages_while_paused)
            self.pending_messages_while_paused.clear() # Clear original list before processing

            for msg in messages_to_process:
                # self._process_stored_message(msg) # MCP_AGENT_CHANGE: Placeholder from plan.
                # For now, log and add to history as a simple form of processing.
                # A dedicated _process_stored_message method would handle different message types appropriately.
                self.logger.info(f"Processing stored message after resume: {str(msg)[:100]}...")
                history_entry = f"[Message Processed After Resume]: {str(msg)[:200]}"
                self.add_to_conversation_history("user", history_entry) # Or a more specific role/parser
            
            self.logger.info("Finished processing stored messages.")
        else:
            self.logger.info("No pending messages to process upon resume.")

        # Determine new status based on current task
        # If a task was active or restored
        if self.current_task_description:
            self.current_status = MinionStatus.RUNNING
            self.logger.info(f"Resuming with task: {self.current_task_description}")
            
            # If we have a current task in our state object, update its status
            if self.current_state and self.current_state.current_task:
                self.current_state.current_task.status = "running"
        else:
            self.current_status = MinionStatus.IDLE
            self.logger.info("Resumed to idle state as no task was active.")
        
        # Save the resumed state (e.g., is_paused=False, cleared pending_messages, updated task status)
        self._save_current_state() # MCP_AGENT_CHANGE: Use new save state method
        
        self._send_state_update(self.current_status, "Minion successfully resumed.")


    def add_to_conversation_history(self, role, text):
        # Basic history management. Could be more complex (e.g., summarizing old parts).
        # For now, just append. Role is 'user' (for inputs, A2A msgs) or 'model' (for LLM responses)
        # Codex Omega Note: This is a simplified history. Real chat applications
        # might need more complex turn management. For Minion's internal LLM, this might be sufficient.
        # The LLMInterface currently doesn't use this history directly for genai.generate_content,
        # but the Minion can use it to construct the *next* full prompt.
        # A better approach for Gemini would be to use model.start_chat(history=...)
        
        # This part is conceptually how a Minion would manage history for its *own* LLM.
        # The llm_interface.send_prompt currently takes a single string.
        # So, the Minion needs to *construct* that string from its history.
        # self.conversation_history.append({"role": role, "content": text})
        # self.logger.debug(f"Added to history. Role: {role}, Text: {text[:100]}...")
        pass # Placeholder - actual history concatenation happens when forming next prompt

    def _construct_prompt_from_history_and_task(self, task_description):
        # This is where the Minion would build the full prompt for its LLM,
        # including relevant parts of its conversation_history and the new task.
        # For now, we'll just use the system prompt + task.
        # A more advanced version would summarize or select relevant history.
        # BIAS_CHECK: Avoid overly long prompts if history grows too large without summarization.
        
        # Simple concatenation for V1
        # history_str = ""
        # for entry in self.conversation_history:
        #     history_str += f"{entry['role'].capitalize()}: {entry['content']}\n\n"
        
        # return f"{self.system_prompt}\n\n--- Current Task ---\n{task_description}\n\n--- Your Response ---"
        # Simpler for now, as system_prompt is already comprehensive:
        return f"{self.system_prompt}\n\n--- Current Task from Steven (or internal objective) ---\n{task_description}\n\nRespond with your detailed plan, any necessary Super-Tool commands, or A2A messages. Remember Anti-Efficiency Bias and document BIAS_CHECK/BIAS_ACTION."

    # --- M2M Message Origination ---
    def _generate_request_id(self, prefix="req"):
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    def _send_m2m_message(self, recipient_id: str, message_type: str, payload: dict,
                            request_id: str, trace_id: str, timeout_seconds: int = None):
        """Helper to send an M2M message and track it."""
        if not self.a2a_client:
            self.logger.error("A2A client not available, cannot send M2M message.")
            return False

        full_message = {
            "sender_id": self.minion_id,
            "recipient_id": recipient_id,
            "trace_id": trace_id,
            "version": "1.1", # Assuming M2M message defs version
            **payload # Includes specific M2M fields like task_id, request_id, query_id, invocation_id
        }
        
        # The specific ID (task_id, request_id, etc.) should be part of the payload and used as the key for pending_m2m_requests
        # For example, payload might contain "task_id": some_id or "request_id": some_id
        # We'll use the provided `request_id` parameter as the key for `pending_m2m_requests`
        # and ensure it's also in the payload if the schema requires it (e.g. as task_id, request_id, query_id, invocation_id)

        actual_timeout = timeout_seconds if timeout_seconds is not None else self.m2m_default_timeout_seconds

        try:
            # Use the new Minion.send_message wrapper
            success = self.send_message(
                recipient_agent_id=recipient_id,
                message_content=full_message,
                message_type=message_type
            )
            if not success:
                self.logger.error(f"M2M message type '{message_type}' to {recipient_id} failed to send via self.send_message. Not adding to pending_m2m_requests.")
                return False

            self.pending_m2m_requests[request_id] = {
                "timestamp": time.time(),
                "retries_left": self.m2m_retry_attempts,
                "timeout_seconds": actual_timeout,
                "message_payload": full_message, # Store the sent payload for retries
                "recipient_id": recipient_id,
                "message_type": message_type,
                "trace_id": trace_id
                # "original_handler": original_handler # For future use if specific callbacks are needed
            }
            self.logger.info(f"Sent M2M '{message_type}' to {recipient_id} with request_id {request_id}. Trace: {trace_id}. Timeout: {actual_timeout}s. Payload: {str(full_message)[:100]}...")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send M2M '{message_type}' to {recipient_id}: {e}", exc_info=True)
            return False

    def prepare_m2m_task_delegation(self, recipient_id: str, task_description: str, trace_id: str,
                                    parent_task_id: str = None, required_capabilities: list = None,
                                    required_mcp_tools: list = None, deadline: str = None,
                                    priority: str = "normal", timeout_seconds: int = None,
                                    delegation_depth: int = 0):
        task_id = self._generate_request_id("task")
        payload = {
            "task_id": task_id,
            "task_description": task_description,
            "priority": priority,
            "timeout_seconds": timeout_seconds if timeout_seconds is not None else self.m2m_default_timeout_seconds,
            "delegation_depth": delegation_depth
        }
        if parent_task_id:
            payload["parent_task_id"] = parent_task_id
        if required_capabilities:
            payload["required_capabilities"] = required_capabilities
        if required_mcp_tools:
            payload["required_mcp_tools"] = required_mcp_tools
        if deadline:
            payload["deadline"] = deadline
        
        return self._send_m2m_message(recipient_id, "m2m_task_delegation", payload, task_id, trace_id, payload["timeout_seconds"])

    def prepare_m2m_data_request(self, recipient_id: str, data_query: str, trace_id: str,
                                 parameters: dict = None, priority: str = "normal",
                                 timeout_seconds: int = None):
        request_id = self._generate_request_id("dreq")
        payload = {
            "request_id": request_id,
            "data_query": data_query,
            "priority": priority,
            "timeout_seconds": timeout_seconds if timeout_seconds is not None else self.m2m_default_timeout_seconds
        }
        if parameters:
            payload["parameters"] = parameters
        
        return self._send_m2m_message(recipient_id, "m2m_data_request", payload, request_id, trace_id, payload["timeout_seconds"])

    def prepare_m2m_capability_query(self, recipient_id: str, trace_id: str,
                                     capability_filter: dict = None, timeout_seconds: int = None):
        query_id = self._generate_request_id("capq")
        payload = {
            "query_id": query_id,
            "timeout_seconds": timeout_seconds if timeout_seconds is not None else self.m2m_default_timeout_seconds # Not in spec, but good for tracking
        }
        if capability_filter:
            payload["capability_filter"] = capability_filter
        
        # Note: m2m_capability_query spec doesn't have timeout_seconds in its payload,
        # but we use it for the pending_m2m_requests tracking.
        return self._send_m2m_message(recipient_id, "m2m_capability_query", payload, query_id, trace_id, payload["timeout_seconds"])

    def prepare_m2m_tool_invocation_request(self, recipient_id: str, mcp_server_name: str, mcp_tool_name: str,
                                            mcp_arguments: dict, trace_id: str, parent_task_id: str = None,
                                            priority: str = "normal", timeout_seconds: int = None):
        invocation_id = self._generate_request_id("toolinv")
        payload = {
            "invocation_id": invocation_id,
            "mcp_server_name": mcp_server_name,
            "mcp_tool_name": mcp_tool_name,
            "mcp_arguments": mcp_arguments,
            "priority": priority,
            "timeout_seconds": timeout_seconds if timeout_seconds is not None else self.m2m_default_timeout_seconds
        }
        if parent_task_id:
            payload["parent_task_id"] = parent_task_id
            
        return self._send_m2m_message(recipient_id, "m2m_tool_invocation_request", payload, invocation_id, trace_id, payload["timeout_seconds"])

    # --- End M2M Message Origination ---

    # --- M2M Message Handling Implementations ---
    def _send_nack(self, recipient_id: str, original_message_id: str, reason_code: str, details: str = ""):
        nack_payload = {
            "original_message_id": original_message_id,
            "reason_code": reason_code,
            "details": details
        }
        # NACKs are fire-and-forget, not tracked in pending_m2m_requests
        # Trace ID for NACK should ideally be from the original message if available, or a new one.
        # For simplicity, we'll use a new trace_id if the original isn't easily accessible here.
        # This might need refinement if strict trace propagation for NACKs is required.
        trace_id_for_nack = self._generate_request_id("nack_trace") # Placeholder
        
        # The _send_m2m_message is for *tracked* requests. NACKs are responses.
        # We need a direct way to send a response message.
        # For now, let's adapt _send_m2m_message or create a simpler sender for responses.
        # Re-using _send_m2m_message for NACKs means they'd be tracked, which is not intended.
        # Let's use a more direct send via a2a_client for responses.
        
        full_nack_message = {
            "sender_id": self.minion_id,
            "recipient_id": recipient_id,
            "trace_id": trace_id_for_nack, # This should ideally be from the original request
            "version": "1.1",
            **nack_payload
        }
        try:
            # Use the new Minion.send_message wrapper
            self.send_message(
                recipient_agent_id=recipient_id,
                message_content=full_nack_message,
                message_type="m2m_negative_acknowledgement"
            )
            # self.logger.info(f"Sent NACK to {recipient_id} for original_msg_id {original_message_id}. Reason: {reason_code}. Details: {details}") # Logging is in send_message
        except Exception as e:
            self.logger.error(f"Failed to send NACK to {recipient_id} via self.send_message: {e}", exc_info=True)
 
 
    def _handle_m2m_task_delegation(self, content: dict, sender_id: str):
        task_id = content.get("task_id")
        task_description = content.get("task_description")
        delegation_depth = content.get("delegation_depth", 0)
        trace_id = content.get("trace_id", self._generate_request_id("trace"))

        if not task_id or not task_description:
            self.logger.error(f"Invalid m2m_task_delegation from {sender_id}: missing task_id or description.")
            self._send_nack(sender_id, task_id or "unknown_task_id", "invalid_request", "Missing task_id or task_description.")
            return

        if delegation_depth >= self.m2m_max_delegation_depth:
            self.logger.warning(f"Task delegation '{task_id}' from {sender_id} rejected due to max delegation depth ({delegation_depth}/{self.m2m_max_delegation_depth}).")
            status_payload = {"task_id": task_id, "trace_id": trace_id, "status": "rejected", "details": "Max delegation depth exceeded."}
            self._send_m2m_message(sender_id, "m2m_task_status_update", status_payload, self._generate_request_id("status"), trace_id) # Status updates are fire-and-forget from receiver's perspective of tracking
            return

        self.logger.info(f"Accepted m2m_task_delegation '{task_id}' from {sender_id}. Description: {task_description[:50]}...")
        # For now, send "accepted" and then process the task as if it came from Steven.
        # A more complex minion might queue this or have dedicated M2M task processing.
        status_payload = {"task_id": task_id, "trace_id": trace_id, "status": "accepted", "details": "Task accepted for processing."}
        self._send_m2m_message(sender_id, "m2m_task_status_update", status_payload, self._generate_request_id("status"), trace_id)

        # Process the task (this is a simplified approach for V1)
        # This could involve creating a new internal task, adding to a queue, or directly calling process_task.
        # If calling process_task, ensure it can handle tasks delegated from other minions.
        # For now, let's log and simulate starting it.
        self.logger.info(f"Simulating start of delegated M2M task '{task_id}': {task_description}")
        # In a real scenario, this might be:
        # self.process_task(f"[M2M Delegated Task from {sender_id}]: {task_description}", self.minion_id) # Respond to self or a manager
        # Or, it might trigger a new instance of task processing logic.
        # For now, we'll assume the LLM will eventually be told about this task if it needs to act.

    def _handle_m2m_task_status_update(self, content: dict, sender_id: str):
        task_id = content.get("task_id")
        status = content.get("status")
        details = content.get("details", "")
        trace_id = content.get("trace_id")

        if not task_id or not status:
            self.logger.error(f"Invalid m2m_task_status_update from {sender_id}: missing task_id or status.")
            # Not sending NACK for a status update usually.
            return

        if task_id in self.pending_m2m_requests:
            self.logger.info(f"Received task status for M2M task '{task_id}' from {sender_id}: {status}. Details: {details}. Trace: {trace_id}")
            # TODO: Trigger original handler or resume logic based on this status.
            # For now, just remove from pending.
            del self.pending_m2m_requests[task_id]
            self.logger.info(f"M2M Task '{task_id}' removed from pending requests.")
            # Potentially inform LLM or user about this update.
        else:
            self.logger.warning(f"Received status for unknown or already completed M2M task '{task_id}' from {sender_id}.")

    def _handle_m2m_data_request(self, content: dict, sender_id: str):
        request_id = content.get("request_id")
        data_query = content.get("data_query")
        trace_id = content.get("trace_id", self._generate_request_id("trace"))

        if not request_id or not data_query:
            self.logger.error(f"Invalid m2m_data_request from {sender_id}: missing request_id or data_query.")
            self._send_nack(sender_id, request_id or "unknown_req_id", "invalid_request", "Missing request_id or data_query.")
            return

        self.logger.info(f"Processing m2m_data_request '{request_id}' from {sender_id}. Query: {data_query[:50]}...")
        # TODO: Attempt to fulfill the data request (e.g., using LLM, tools, or internal state).
        # This is a placeholder for actual data retrieval logic.
        # For now, simulate a successful response or a "not_found".
        simulated_data = {"query": data_query, "result": f"Simulated data for '{data_query}' from minion {self.minion_id}"}
        response_payload = {
            "request_id": request_id,
            "trace_id": trace_id,
            "status": "success",
            "data": simulated_data
        }
        # Data responses are fire-and-forget from receiver's perspective of tracking
        self._send_m2m_message(sender_id, "m2m_data_response", response_payload, self._generate_request_id("dresp"), trace_id)
        self.logger.info(f"Sent m2m_data_response for '{request_id}' to {sender_id}.")

    def _handle_m2m_data_response(self, content: dict, sender_id: str):
        request_id = content.get("request_id")
        status = content.get("status")
        data = content.get("data")
        error_message = content.get("error_message", "")
        trace_id = content.get("trace_id")

        if not request_id or not status:
            self.logger.error(f"Invalid m2m_data_response from {sender_id}: missing request_id or status.")
            return

        if request_id in self.pending_m2m_requests:
            self.logger.info(f"Received data response for M2M request '{request_id}' from {sender_id}. Status: {status}. Trace: {trace_id}")
            if status == "success":
                self.logger.info(f"Data: {str(data)[:100]}...")
                # TODO: Process the received data, trigger original handler.
            else:
                self.logger.error(f"Data request failed. Error: {error_message}")
            del self.pending_m2m_requests[request_id]
            self.logger.info(f"M2M Data Request '{request_id}' removed from pending requests.")
        else:
            self.logger.warning(f"Received data response for unknown or already completed M2M request '{request_id}' from {sender_id}.")

    def _handle_m2m_capability_query(self, content: dict, sender_id: str):
        query_id = content.get("query_id")
        # capability_filter = content.get("capability_filter") # TODO: Implement filtering
        trace_id = content.get("trace_id", self._generate_request_id("trace"))

        if not query_id:
            self.logger.error(f"Invalid m2m_capability_query from {sender_id}: missing query_id.")
            self._send_nack(sender_id, query_id or "unknown_query_id", "invalid_request", "Missing query_id.")
            return

        self.logger.info(f"Processing m2m_capability_query '{query_id}' from {sender_id}.")
        
        # Gather capabilities (simplified for V1)
        # This should include general skills and registered MCP tools.
        # For now, use the skills from agent_card and tools from tool_manager.
        
        capabilities_list = []
        # Add skills from agent_card
        agent_card_skills = self.a2a_client.agent_card.get("skills", [])
        for skill in agent_card_skills:
            capabilities_list.append({
                "type": "general_skill", # Or derive from skill definition
                "name": skill.get("name"),
                "description": skill.get("description"), # Added for more context
                "status": "available" # Assuming always available for now
            })

        # Add MCP tools from ToolManager
        mcp_tools = self.tool_manager.get_mcp_tool_capabilities_for_response() # Needs to be implemented in ToolManager
        capabilities_list.extend(mcp_tools)

        response_payload = {
            "query_id": query_id,
            "trace_id": trace_id,
            "capabilities": capabilities_list
        }
        self._send_m2m_message(sender_id, "m2m_capability_response", response_payload, self._generate_request_id("capresp"), trace_id)
        self.logger.info(f"Sent m2m_capability_response for '{query_id}' to {sender_id}.")


    def _handle_m2m_capability_response(self, content: dict, sender_id: str):
        query_id = content.get("query_id")
        capabilities = content.get("capabilities", [])
        trace_id = content.get("trace_id")

        if not query_id:
            self.logger.error(f"Invalid m2m_capability_response from {sender_id}: missing query_id.")
            return

        if query_id in self.pending_m2m_requests:
            self.logger.info(f"Received capability response for M2M query '{query_id}' from {sender_id}. Trace: {trace_id}. Capabilities: {len(capabilities)}")
            # TODO: Process the received capabilities, trigger original handler.
            for cap in capabilities:
                self.logger.debug(f" - Capability: {cap.get('name')} (Type: {cap.get('type')}, Status: {cap.get('status')})")
            del self.pending_m2m_requests[query_id]
            self.logger.info(f"M2M Capability Query '{query_id}' removed from pending requests.")
        else:
            self.logger.warning(f"Received capability response for unknown or already completed M2M query '{query_id}' from {sender_id}.")

    def _handle_m2m_tool_invocation_request(self, content: dict, sender_id: str):
        invocation_id = content.get("invocation_id")
        mcp_server_name = content.get("mcp_server_name")
        mcp_tool_name = content.get("mcp_tool_name")
        mcp_arguments = content.get("mcp_arguments")
        trace_id = content.get("trace_id", self._generate_request_id("trace"))

        if not all([invocation_id, mcp_server_name, mcp_tool_name, isinstance(mcp_arguments, dict)]):
            self.logger.error(f"Invalid m2m_tool_invocation_request from {sender_id}: missing required fields.")
            self._send_nack(sender_id, invocation_id or "unknown_inv_id", "invalid_request", "Missing required fields for tool invocation.")
            return

        self.logger.info(f"Processing m2m_tool_invocation_request '{invocation_id}' from {sender_id} for tool '{mcp_server_name}::{mcp_tool_name}'.")

        # Check if this minion has access to the tool via its ToolManager and McpNodeBridge
        # This is a simplified check. A more robust check would involve querying ToolManager.
        if not self.enable_mcp_integration or not self.mcp_bridge:
            self.logger.warning(f"Cannot execute tool '{mcp_tool_name}': MCP integration disabled or bridge not available.")
            response_payload = {"invocation_id": invocation_id, "trace_id": trace_id, "status": "error", "error_message": "MCP integration not available on this minion."}
            self._send_m2m_message(sender_id, "m2m_tool_invocation_response", response_payload, self._generate_request_id("toolresp"), trace_id)
            return

        try:
            # Assuming tool_manager can directly call MCP tools if they are registered/known.
            # The tool_manager.execute_tool might need adjustment to handle calls originating from M2M.
            # For now, let's assume a direct call to mcp_bridge if the tool is an MCP tool.
            # This logic needs to align with how ToolManager discovers and executes tools.
            # A better way: self.tool_manager.execute_mcp_tool_for_minion(mcp_server_name, mcp_tool_name, mcp_arguments)
            
            # Direct call to McpBridge for now, assuming the tool is an MCP tool.
            # This bypasses ToolManager's own tool parsing logic, which might not be ideal.
            # A better design would be for ToolManager to expose a method that can be called here.
            tool_result = self.mcp_bridge.use_tool(server_name=mcp_server_name, tool_name=mcp_tool_name, arguments=mcp_arguments)
            
            # McpNodeBridge.use_tool currently returns a tuple (success: bool, result_or_error: dict)
            success, result_data = tool_result

            if success:
                self.logger.info(f"Successfully invoked MCP tool '{mcp_tool_name}'. Result: {str(result_data)[:100]}...")
                response_payload = {"invocation_id": invocation_id, "trace_id": trace_id, "status": "success", "result": result_data}
            else: # Error from MCP bridge
                self.logger.error(f"Error invoking MCP tool '{mcp_tool_name}': {result_data.get('error', 'Unknown MCP error')}")
                response_payload = {"invocation_id": invocation_id, "trace_id": trace_id, "status": "error", "error_message": result_data.get('error', 'Unknown MCP error')}
        
        except Exception as e:
            self.logger.error(f"Exception during MCP tool invocation '{mcp_tool_name}': {e}", exc_info=True)
            response_payload = {"invocation_id": invocation_id, "trace_id": trace_id, "status": "error", "error_message": f"Internal minion error during tool invocation: {str(e)}"}

        self._send_m2m_message(sender_id, "m2m_tool_invocation_response", response_payload, self._generate_request_id("toolresp"), trace_id)


    def _handle_m2m_tool_invocation_response(self, content: dict, sender_id: str):
        invocation_id = content.get("invocation_id")
        status = content.get("status")
        result = content.get("result")
        error_message = content.get("error_message", "")
        trace_id = content.get("trace_id")

        if not invocation_id or not status:
            self.logger.error(f"Invalid m2m_tool_invocation_response from {sender_id}: missing invocation_id or status.")
            return

        if invocation_id in self.pending_m2m_requests:
            self.logger.info(f"Received tool invocation response for M2M request '{invocation_id}' from {sender_id}. Status: {status}. Trace: {trace_id}")
            if status == "success":
                self.logger.info(f"Tool Result: {str(result)[:100]}...")
                # TODO: Process the result, trigger original handler.
            else:
                self.logger.error(f"Tool invocation failed. Error: {error_message}")
            del self.pending_m2m_requests[invocation_id]
            self.logger.info(f"M2M Tool Invocation Request '{invocation_id}' removed from pending requests.")
        else:
            self.logger.warning(f"Received tool invocation response for unknown or already completed M2M request '{invocation_id}' from {sender_id}.")

    def _handle_m2m_nack(self, content: dict, sender_id: str):
        original_message_id = content.get("original_message_id")
        reason_code = content.get("reason_code")
        details = content.get("details", "")

        if not original_message_id or not reason_code:
            self.logger.error(f"Invalid m2m_negative_acknowledgement from {sender_id}: missing original_message_id or reason_code.")
            return

        self.logger.warning(f"Received NACK for M2M message '{original_message_id}' from {sender_id}. Reason: {reason_code}. Details: {details}")

        if original_message_id in self.pending_m2m_requests:
            pending_req_info = self.pending_m2m_requests[original_message_id]
            self.logger.info(f"NACK pertains to pending request: {original_message_id}") # Log only ID for brevity

            retryable_nack_reasons = ["overloaded", "timeout"] # Add other retryable reasons if any
            if reason_code in retryable_nack_reasons and pending_req_info["retries_left"] > 0:
                self.logger.info(f"Attempting retry for M2M request '{original_message_id}' due to NACK ({reason_code}). Retries left: {pending_req_info['retries_left'] -1}.")
                self._retry_m2m_request(original_message_id, pending_req_info)
            else:
                self.logger.error(f"M2M request '{original_message_id}' failed terminally due to NACK ({reason_code}) or no retries left.")
                # TODO: Inform LLM/task processor about terminal failure.
                del self.pending_m2m_requests[original_message_id]
                self.logger.info(f"M2M Request '{original_message_id}' removed from pending requests.")
        else:
            self.logger.warning(f"NACK received for unknown or already completed M2M message '{original_message_id}'.")

    def _handle_m2m_info_broadcast(self, content: dict, sender_id: str):
        info_id = content.get("info_id")
        info_payload = content.get("info_payload")
        self.logger.info(f"Received m2m_info_broadcast '{info_id}' from {sender_id}. Payload: {str(info_payload)[:100]}...")
        # TODO: Process the broadcast information as needed by the minion's logic.
        # This could involve updating internal state, informing the LLM, etc.
        # For V1, just logging.

    # --- End M2M Message Handling Implementations ---


    # The old process_task method is removed or refactored into _execute_task.
    # For now, we remove it. The new task execution flow starts with _process_next_task.

    def _handle_task_status_change(self, event_type: str, task: Task):
        """Handle task status changes from the TaskQueue."""
        if event_type == "task_started":
            self.current_status = MinionStatus.RUNNING
            self.current_task = task.id
            self.current_task_description = task.description
            self._send_state_update(self.current_status, f"Processing task: {task.description[:60]}...")

        elif event_type == "task_completed":
            if not self.task_queue.get_next_task():
                # No more tasks in queue
                self.current_status = MinionStatus.IDLE
                self.current_task = None
                self.current_task_description = None
                self._send_state_update(self.current_status, "Task completed, minion idle.")

        elif event_type == "task_failed":
            if not self.task_queue.get_next_task():
                # No more tasks in queue
                self.current_status = MinionStatus.ERROR
                self.current_task = None
                self.current_task_description = None
                self._send_state_update(self.current_status, f"Task failed: {task.error}")

        # Save state on significant events
        if event_type in ["task_completed", "task_failed", "task_paused", "task_canceled"]:
            self._save_current_state()

    def _process_next_task(self):
        """Process the next task in the queue."""
        if self.is_paused:
            self.logger.info("Cannot process next task: Minion is paused")
            return

        task = self.task_queue.start_next_task()
        if not task:
            self.logger.info("No tasks in queue to process")
            # Ensure minion goes to idle if queue is empty and no task was running
            if self.current_status != MinionStatus.IDLE and not self.task_queue.running_task:
                 self.current_status = MinionStatus.IDLE
                 self.current_task = None
                 self.current_task_description = None
                 self._send_state_update(self.current_status, "Minion is idle, no more tasks.")
            return

        # Start a new thread for task processing
        task_thread = threading.Thread(
            target=self._execute_task,
            args=(task,)
        )
        task_thread.daemon = True
        task_thread.start()

    def _execute_task(self, task: Task):
        """Execute a task from the queue."""
        # Start timer for task processing
        timer_id = self.metrics.start_timer("task_processing_time", {
            "sender_id": task.sender_id[:10]  # Truncate long IDs
        })
        try:
            self.logger.info(f"Executing task: {task.description[:100]}...")
 
            # Construct the full prompt for the LLM
            full_prompt = self._construct_prompt_from_history_and_task(task.description)
 
            # Send to LLM
            llm_response_text = self.llm.send_prompt(full_prompt)
 
            # Check for specific error indicators from LLM if any (e.g., "ERROR_")
            # This is a placeholder, actual error handling might be more robust based on LLMInterface
            if isinstance(llm_response_text, str) and llm_response_text.startswith("ERROR_"): # Basic check
                self.logger.error(f"LLM processing failed for task {task.id}: {llm_response_text}")
                self.task_queue.fail_current_task(error=f"LLM error: {llm_response_text}")
                self.metrics.inc_counter("tasks_failed", labels={"reason": "llm_processing_error"})
                return # Exit before trying to send reply
 
            # Send response back to the original sender
            try:
                # Use the new Minion.send_message wrapper
                self.send_message(
                    recipient_agent_id=task.sender_id,
                    message_content=llm_response_text,
                    message_type="directive_reply"
                )
                # self.logger.info(f"Sent reply to {task.sender_id} for task {task.id}") # Logging is in send_message
            except Exception as e:
                self.logger.error(f"Failed to send reply for task {task.id} via self.send_message: {e}", exc_info=True)
                # Task was processed, but reply failed. Still mark as complete.
 
            # Mark task as completed
            self.task_queue.complete_current_task(result=llm_response_text)
            self.metrics.inc_counter("tasks_processed", labels={"status": "success"})
 
        except LLMContentFilterError as e:
            self.logger.error(f"Content filter error during task {task.id}: {e.message}")
            error_message = f"Task failed due to content policy restrictions: {e.code}"
            self.task_queue.fail_current_task(error=error_message)
            self.metrics.inc_counter("tasks_failed", labels={"reason": "llm_content_filter"})
            # Optionally send an error reply to the user if appropriate
            try:
                # Use the new Minion.send_message wrapper
                self.send_message(task.sender_id, error_message, "directive_reply_error")
            except Exception as ex_send:
                self.logger.error(f"Failed to send content filter error reply for task {task.id}: {ex_send}")
 
 
        except LLMError as e: # Handles LLMAPIError and general LLMError
            self.logger.error(f"LLM error during task {task.id}: {e.message}")
            error_message = f"Task failed due to LLM error: {e.message}"
            self.task_queue.fail_current_task(error=error_message)
            self.metrics.inc_counter("tasks_failed", labels={"reason": "llm_api_error"})
            try:
                # Use the new Minion.send_message wrapper
                self.send_message(task.sender_id, error_message, "directive_reply_error")
            except Exception as ex_send:
                self.logger.error(f"Failed to send LLM error reply for task {task.id}: {ex_send}")
 
        except Exception as e:
            self.logger.error(f"Unexpected error executing task {task.id}: {e}", exc_info=True)
            self.task_queue.fail_current_task(error=f"Unexpected execution error: {str(e)}")
            self.metrics.inc_counter("tasks_failed", labels={"reason": "unexpected_exception"})
            try:
                # Send a generic error message for unexpected issues
                user_facing_critical_error = "A critical unexpected error occurred while processing the task."
                # Use the new Minion.send_message wrapper
                self.send_message(task.sender_id, user_facing_critical_error, "directive_reply_error")
            except Exception as ex_send_crit:
                self.logger.error(f"Failed to send critical error notification for task {task.id}: {ex_send_crit}")
        finally:
            self.metrics.stop_timer(timer_id) # Stop timer in finally block
            # Always try to process the next task, regardless of current task's outcome
            self._process_next_task()

    def run(self):
        self.logger.info(f"Minion {self.minion_id} run loop started. Current status: {self.current_status.value}")
        if self.current_status != MinionStatus.PAUSED: # If not starting from a loaded paused state
            self._send_state_update(self.current_status, "Minion run loop started.")
        
        self.logger.info("Attempting to start A2A message listener thread...")
        self.logger.debug(f"Attempting to start A2A message listener thread for {self.minion_id}") # Changed from print
        if not self.a2a_client.register_agent():
            self.logger.error(f"Minion {self.minion_id} could not register with A2A server. A2A features will be limited.")
            # Depending on design, might exit or continue with limited functionality.
            # For now, continue, as it might still receive tasks via other means (e.g. direct call if spawner supports)
        else:
            self.logger.info("A2A registration successful, message listener thread should have been started by A2AClient.")
            self.logger.debug(f"A2A message listener thread should have been started for {self.minion_id}") # Changed from print

        try:
            while True:
                if self.is_paused:
                    if self.current_status != MinionStatus.PAUSED: # Ensure status is accurate if changed externally
                        self.logger.info("Minion is paused. Idling but A2A listener active.")
                        self.current_status = MinionStatus.PAUSED
                        self._send_state_update(self.current_status, "Minion is paused and idling.")
                    time.sleep(1) # Short sleep while paused, A2A client handles messages
                    continue

                # If resumed and a task was restored (self.current_task_description is not None)
                # and we are not currently processing it (e.g. self.is_idle is True, but current_status is RUNNING from resume)
                # This part is tricky. process_task is typically called by handle_a2a_message in a new thread.
                # If we resume a task, we need a way to restart its processing.
                # For V1, let's assume if current_task_description is set upon resume,
                # the minion is "running" that task, but it might need a new trigger if it was complex.
                # The current design has process_task run to completion or until pause.
                # If a task was fully serialized mid-way, _resume_workflow would need to restore that exact point.
                # For now, if self.current_task_description exists and we just resumed,
                # we are in a "running" state for that task, awaiting further interaction or completion.
                # The main loop doesn't actively re-initiate process_task here.

                # M2M Timeout Management
                # Iterate over a copy of keys if modifying the dict during iteration
                pending_ids = list(self.pending_m2m_requests.keys())
                for request_id in pending_ids:
                    if request_id not in self.pending_m2m_requests: # Check if already removed by a response/NACK
                        continue
                    item = self.pending_m2m_requests[request_id]
                    if time.time() > item['timestamp'] + item['timeout_seconds']:
                        self._handle_m2m_request_timeout(request_id, item)
                
                if self.is_idle and self.current_status != MinionStatus.IDLE:
                    # This handles the case where a task finishes and sets is_idle = True
                    self.logger.info(f"Minion {self.minion_id} is now idle. Setting status to IDLE.")
                    self.current_status = MinionStatus.IDLE
                    self.current_task = None # Clear task ID
                    self.current_task_description = None # Clear task description
                    self._send_state_update(self.current_status, "Minion is idle.")
                elif not self.is_idle and self.current_status == MinionStatus.IDLE and self.current_task_description:
                    # This handles resuming to a task that should be running
                    self.logger.info(f"Minion {self.minion_id} resumed to task '{self.current_task_description}'. Setting status to RUNNING.")
                    self.current_status = MinionStatus.RUNNING
                    self._send_state_update(self.current_status, f"Resumed task: {self.current_task_description[:60]}")


                # self.logger.debug(f"Minion {self.minion_id} main loop iteration. Status: {self.current_status.value}")
                time.sleep(1) # Main loop check interval, reduced for faster timeout checks
        except KeyboardInterrupt:
            self.logger.info(f"Minion {self.minion_id} received KeyboardInterrupt. Shutting down.")
        finally:
            self.shutdown()

    def _handle_m2m_request_timeout(self, request_id: str, item: dict):
        self.logger.warning(f"M2M request '{request_id}' to {item['recipient_id']} (type: {item['message_type']}) timed out. Trace: {item['trace_id']}")
        if item["retries_left"] > 0:
            self.logger.info(f"Attempting retry for M2M request '{request_id}'. Retries left: {item['retries_left'] - 1}.")
            self._retry_m2m_request(request_id, item)
        else:
            self.logger.error(f"M2M request '{request_id}' failed terminally after multiple retries (timeout).")
            # TODO: Inform LLM/task processor about terminal failure.
            if request_id in self.pending_m2m_requests: # Check if not removed by a concurrent NACK handler
                del self.pending_m2m_requests[request_id]
            self.logger.info(f"M2M Request '{request_id}' removed from pending requests due to terminal timeout.")

    def _retry_m2m_request(self, request_id: str, item: dict):
        if not self.a2a_client:
            self.logger.error(f"Cannot retry M2M request '{request_id}': A2A client not available.")
            # Potentially remove from pending or mark as failed immediately
            if request_id in self.pending_m2m_requests:
                del self.pending_m2m_requests[request_id]
            return

        # Update the item in pending_m2m_requests before resending
        item["timestamp"] = time.time() # Reset timestamp for the new attempt
        item["retries_left"] -= 1
        # No need to change request_id for this retry model, trace_id remains the same.
        
        try:
            # Use the new Minion.send_message wrapper
            success = self.send_message(
                recipient_agent_id=item["recipient_id"],
                message_content=item["message_payload"], # Resend the original payload
                message_type=item["message_type"]
            )
            if success:
                self.logger.info(f"Successfully retried M2M '{item['message_type']}' to {item['recipient_id']} with request_id {request_id}. Retries left: {item['retries_left']}. Trace: {item['trace_id']}.")
            else:
                self.logger.error(f"Failed to retry M2M '{item['message_type']}' to {item['recipient_id']} via self.send_message. Will rely on next timeout or NACK.")
            # self.logger.info(f"Retried M2M '{item['message_type']}' to {item['recipient_id']} with request_id {request_id}. Retries left: {item['retries_left']}. Trace: {item['trace_id']}.") # Logging is in send_message
        except Exception as e:
            self.logger.error(f"Exception during retry of M2M '{item['message_type']}' to {item['recipient_id']}: {e}", exc_info=True)
            # If send fails on retry, it will timeout again or be NACKed.
            # Or, we could implement immediate removal if send fails catastrophically.
            # For now, rely on the next timeout cycle or NACK.

    # MCP_AGENT_CHANGE: _save_state_to_file is removed. State saving is now handled by _save_current_state through StateManager.

    def shutdown(self):
        self.logger.info(f"Minion {self.minion_id} shutting down...")
        
        # MCP_AGENT_CHANGE: Use _save_current_state to save state if paused or if a task is active.
        # The _save_current_state method itself will use the StateManager.
        if self.is_paused or self.current_task_description: # Save if paused or if there was an active task
            self.logger.info("Minion is paused or has an active task context. Attempting to save state before shutdown.")
            self._save_current_state()
        else:
            self.logger.info("Minion is not paused and has no active task context. No state to save on shutdown.")

        if self.a2a_client:
            self.a2a_client.stop_message_listener()

        if self.manage_mcp_node_service_lifecycle and self.mcp_node_service_process:
            self.logger.info(f"Attempting to terminate MCP Node service (PID: {self.mcp_node_service_process.pid})...")
            try:
                self.mcp_node_service_process.terminate()
                self.mcp_node_service_process.wait(timeout=5) # Wait for graceful termination
                self.logger.info("MCP Node service terminated.")
            except subprocess.TimeoutExpired:
                self.logger.warning("MCP Node service did not terminate gracefully, killing...")
                self.mcp_node_service_process.kill()
                self.logger.info("MCP Node service killed.")
            except Exception as e:
                self.logger.error(f"Error terminating MCP Node service: {e}", exc_info=True)
        
        # TODO: Any other cleanup (e.g., unregister from A2A server if supported)
        self.logger.info(f"Minion {self.minion_id} shutdown complete.")

    def check_health(self) -> Dict[str, Any]:
        """Perform a health check of all components."""
        component_checks = []
        
        # Check LLM
        if self.llm:
            component_checks.append(self.llm.check_health().as_dict())
        
        # Check MCP Bridge
        if self.mcp_bridge:
            component_checks.append(self.mcp_bridge.check_health().as_dict())
        
        # Check A2A Client
        if self.a2a_client:
            component_checks.append(self.a2a_client.check_health().as_dict())
        
        # Determine overall status
        statuses = [result["status"] for result in component_checks]
        overall_status = "healthy"
        if "unhealthy" in statuses:
            overall_status = "unhealthy"
        elif "degraded" in statuses:
            overall_status = "degraded"
        
        return {
            "minion_id": self.minion_id,
            "status": overall_status,
            "components": component_checks,
            "uptime_seconds": time.time() - self.start_time.timestamp(),
            "current_task": self.current_task_description,
            "is_paused": self.is_paused,
            "timestamp": time.time()
        }

if __name__ == "__main__":
    # Argparse setup
    parser = argparse.ArgumentParser(description="AI Minion for Steven's Army.")
    parser.add_argument("--id", type=str, help="Unique ID for this Minion instance. If not provided, a UUID will be generated or spawner config used.")
    parser.add_argument("--name", type=str, help="User-facing name for this Minion instance.")
    parser.add_argument("--personality", type=str, help="Comma-separated string of personality traits. Overrides spawner config if provided.")
    parser.add_argument("--a2a-server", type=str, help=f"URL of the A2A server. Overrides config file default ({A2A_SERVER_URL_DEFAULT}).")
    
    args = parser.parse_args()

    # Determine Minion ID: command-line > generate UUID
    minion_id_arg = args.id
    if not minion_id_arg:
        # If ID not given, check if spawner config might provide it (though spawner usually passes --id)
        # For standalone run, generate one.
        minion_id_arg = f"minion_{uuid.uuid4().hex[:6]}"
        print(f"No --id provided, generated: {minion_id_arg}")


    # PROJECT_ROOT and LOGS_DIR are already defined globally using ConfigManager.
    # The ConfigManager instance `config` is already initialized.
    # No need to set BASE_PROJECT_DIR env var here, as ConfigManager handles it.

    try:
        # Pass command-line args to Minion constructor.
        # The constructor will use them if provided, otherwise fall back to ConfigManager values or defaults.
        minion_instance = Minion(
            minion_id=minion_id_arg,
            user_facing_name=args.name, # Pass the new argument
            personality_traits_str=args.personality, # Can be None
            a2a_server_url_override=args.a2a_server  # Can be None
        )
        # For now, the Minion's run() loop is passive. It needs an entry point for tasks.
        # The "ice breaker" task will be sent via the GUI's broadcast or A2A.
        # To test, one might add a simple task here:
        # minion_instance.process_task("Introduce yourself and state your primary directives.")
        minion_instance.run() # Starts the main loop and A2A registration/listening
    except Exception as e:
        # LOGS_DIR is now globally defined from config
        main_logger = setup_logger("MainMinionLauncher", os.path.join(LOGS_DIR, "main_minion_launcher_error.log"))
        main_logger.critical(f"Failed to start Minion {minion_id_arg}. Error: {e}", exc_info=True)
        print(f"CRITICAL: Failed to start Minion {minion_id_arg}. Check logs. Error: {e}", file=sys.stderr)
        sys.exit(1)
