import os
import sys
import time
import json
import uuid
import argparse
import threading # Added for processing tasks in a new thread
import subprocess # For managing MCP Node service
from datetime import datetime, timezone
from enum import Enum
import json # Ensure json is imported, though it might be already

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
        self.logger = setup_logger(f"Minion_{self.minion_id}", self.log_file_path) # Default level for now
        self.logger.info(f"Minion {self.minion_id} (Name: {self.user_facing_name}) initializing...") # Initial log

        self.start_time = datetime.now(timezone.utc)
        self.mcp_bridge = None
        self.mcp_node_service_process = None # To store the subprocess if started

        # M2M Communication State
        self.pending_m2m_requests = {}
        self.m2m_retry_attempts = config.get_int("m2m_communication.default_retry_attempts", 3)
        self.m2m_default_timeout_seconds = config.get_int("m2m_communication.default_timeout_seconds", 60)
        self.m2m_max_delegation_depth = config.get_int("m2m_communication.max_delegation_depth", 5)
        self.logger.info(f"M2M Config: Retries={self.m2m_retry_attempts}, Timeout={self.m2m_default_timeout_seconds}s, MaxDepth={self.m2m_max_delegation_depth}")


        # State variables for pause/resume
        self.is_paused = False
        self.paused_state = {}
        self.pending_messages_while_paused = []
        self.current_status = MinionStatus.IDLE
        self.current_task_description = None # To store the description of the task being processed for serialization

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
                self.mcp_bridge = McpNodeBridge(base_url=mcp_node_service_base_url, logger=self.logger)
                self.logger.info(f"McpNodeBridge initialized with base URL: {mcp_node_service_base_url}")

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
        
        self.conversation_history = [{"role": "system", "content": self.system_prompt}]
        self.current_task = None
        self.is_idle = True
        
        self.logger.info(f"Minion {self.minion_id} (Name: {self.user_facing_name}) initialized successfully. Personality: {self.personality_traits}")
        self.logger.info(f"System Prompt: {self.system_prompt[:300]}...") # Log beginning

        # State file path and loading
        minion_state_storage_dir = config.get_path("minion_state.storage_dir", os.path.join(PROJECT_ROOT, "system_data", "minion_states"))
        os.makedirs(minion_state_storage_dir, exist_ok=True)
        self.state_file_path = os.path.join(minion_state_storage_dir, f"minion_state_{self.minion_id}.json")
        self._load_state_from_file() # Attempt to load state on init

    def _load_state_from_file(self):
        if os.path.exists(self.state_file_path):
            self.logger.info(f"Found existing state file: {self.state_file_path}. Attempting to load.")
            try:
                with open(self.state_file_path, 'r') as f:
                    loaded_state = json.load(f)
                
                self.paused_state = loaded_state.get("paused_state", {})
                # Deserialize state if it was saved in a paused state
                if self.paused_state: # Check if there's actually something to deserialize
                    self._deserialize_state() # This will set self.is_paused, self.current_task_description etc.
                    self.is_paused = loaded_state.get("is_paused", True) # Explicitly set is_paused from file, default to True if resuming
                    self.current_status = MinionStatus.PAUSED if self.is_paused else MinionStatus.IDLE
                    self.pending_messages_while_paused = loaded_state.get("pending_messages_while_paused", [])
                    self.logger.info(f"Successfully loaded state. Minion is now {self.current_status.value}.")
                    # Optionally, remove the state file after successful load if it's a one-time resume
                    # os.remove(self.state_file_path)
                    # self.logger.info(f"Removed state file {self.state_file_path} after loading.")
                else:
                    self.logger.info("State file loaded, but no 'paused_state' data found. Minion remains in its current initialized state.")

            except json.JSONDecodeError as e:
                self.logger.error(f"Error decoding JSON from state file {self.state_file_path}: {e}", exc_info=True)
            except Exception as e:
                self.logger.error(f"Failed to load state from {self.state_file_path}: {e}", exc_info=True)
        else:
            self.logger.info(f"No existing state file found at {self.state_file_path}. Starting fresh.")

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
            self.a2a_client.send_message(
                recipient_agent_id=self.gui_commander_id, # Defined in __init__
                message_content=message_content,
                message_type="minion_state_update"
            )
            self.logger.info(f"Sent minion_state_update: {status.value}, Details: {details}")
        except Exception as e:
            self.logger.error(f"Failed to send minion_state_update: {e}", exc_info=True)

    def handle_a2a_message(self, message_data):
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
            self.a2a_client.send_message(sender_id, ack_content, "control_pause_ack")
            # State update is handled within _pause_workflow

        elif message_type == "control_resume_request":
            self.logger.info("Received control_resume_request.")
            self._resume_workflow()
            # Acknowledge resume
            ack_content = {"minion_id": self.minion_id, "status": self.current_status.value, "timestamp": datetime.now(timezone.utc).isoformat()}
            self.a2a_client.send_message(sender_id, ack_content, "control_resume_ack")
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
                self.a2a_client.send_message(sender_id, ack_content, "message_to_paused_minion_ack")
                self.logger.info(f"Stored message while paused: {message_actual_content[:100]}...")
            else:
                self.logger.warning("Received message_to_paused_minion_request, but Minion is not paused. Ignoring.")
                # Optionally send a NACK or error
                nack_content = {"minion_id": self.minion_id, "status": "error", "detail": "Minion not paused", "timestamp": datetime.now(timezone.utc).isoformat()}
                self.a2a_client.send_message(sender_id, nack_content, "message_to_paused_minion_nack") # Assuming a NACK type

        elif message_type == "user_broadcast_directive" and content:
            if self.is_paused:
                self.logger.info(f"Received broadcast directive for task: {content[:60]}... but Minion is paused. Queuing message.")
                self._store_message_while_paused({"type": "directive", "content": content, "sender": sender_id})
            else:
                self.logger.info(f"Received broadcast directive. Starting task processing in a new thread for: {content[:60]}...")
                self.current_status = MinionStatus.RUNNING
                self._send_state_update(self.current_status, f"Starting task: {content[:60]}...")
                # Run process_task in a new thread to avoid blocking the A2A listener
                task_thread = threading.Thread(target=self.process_task, args=(content, sender_id))
                task_thread.daemon = True # Allow main program to exit even if threads are running
                task_thread.start()

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

    def _serialize_state(self):
        """Populates self.paused_state with all necessary information to resume later."""
        self.logger.info("Serializing minion state...")
        self.paused_state = {
            "current_task_description": self.current_task_description,
            "task_progress": {}, # Placeholder for V1 - more complex progress tracking needed
            "conversation_history": self.conversation_history, # Assuming this is JSON serializable
            "internal_variables": {
                # Add any other critical internal variables here
                # e.g., "some_counter": self.some_counter
            },
            "pending_messages_while_paused": list(self.pending_messages_while_paused) # Ensure it's a copy
        }
        self.logger.info(f"State serialized. Task: {self.current_task_description}, {len(self.pending_messages_while_paused)} pending messages.")
        return self.paused_state

    def _deserialize_state(self):
        """Restores the minion's operational attributes from self.paused_state."""
        if not self.paused_state:
            self.logger.warning("Attempted to deserialize state, but paused_state is empty.")
            return False

        self.logger.info("Deserializing minion state...")
        self.current_task_description = self.paused_state.get("current_task_description")
        # Restore task_progress - for V1, this is simple
        # self.task_progress = self.paused_state.get("task_progress", {})
        self.conversation_history = self.paused_state.get("conversation_history", [{"role": "system", "content": self.system_prompt}])
        
        # Restore internal_variables
        # internal_vars = self.paused_state.get("internal_variables", {})
        # self.some_counter = internal_vars.get("some_counter", 0)

        # pending_messages_while_paused is handled by _resume_workflow after deserialization
        # self.pending_messages_while_paused = list(self.paused_state.get("pending_messages_while_paused", []))
        
        self.logger.info(f"State deserialized. Restored task: {self.current_task_description}")
        # Clear paused_state after successful deserialization to prevent re-use unless repopulated
        # self.paused_state = {} # Cleared in _resume_workflow after full processing
        return True

    def _pause_workflow(self):
        """Handles the logic to pause the minion's workflow."""
        if self.is_paused:
            self.logger.info("Minion is already paused. No action taken.")
            return

        self.logger.info("Pausing workflow...")
        self.current_status = MinionStatus.PAUSING
        self._send_state_update(self.current_status, "Attempting to pause workflow.")

        self.is_paused = True
        self._serialize_state() # Save current operational context

        # In a more complex scenario, ensure this is called at a safe point.
        # For V1, we assume it can pause immediately between tasks or main loop iterations.
        
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

        if not self._deserialize_state():
            self.logger.error("Failed to deserialize state. Cannot resume. Minion remains paused.")
            self.current_status = MinionStatus.ERROR # Or back to PAUSED with error
            self._send_state_update(self.current_status, "Error during state deserialization. Resumption failed.")
            return

        self.is_paused = False
        self.logger.info("Minion workflow resumed.")

        # Process pending messages
        if self.pending_messages_while_paused:
            self.logger.info(f"Processing {len(self.pending_messages_while_paused)} messages received while paused.")
            for msg_content in self.pending_messages_while_paused:
                # This is a simplified handling. A more robust system might re-evaluate the current task
                # or integrate these messages into the conversation history more directly for the LLM.
                self.logger.info(f"Processing stored message: {str(msg_content)[:100]}...")
                if isinstance(msg_content, dict) and msg_content.get("type") == "directive":
                    # If it was a queued directive, try to process it now.
                    # This could be complex if a task was already in progress.
                    # For V1, we might just add it to history or log it.
                    # Or, if idle, start it.
                    self.logger.info(f"Queued directive found: {msg_content.get('content')}. Sender: {msg_content.get('sender')}")
                    # For now, just add to conversation history.
                    # A more sophisticated approach would be needed if a task was partially complete.
                    history_entry = f"[Message Processed After Resume from {msg_content.get('sender', 'Unknown')}({msg_content.get('type', 'unknown')})]: {msg_content.get('content')}"
                    self.add_to_conversation_history("user", history_entry)
                else: # Simple message
                    history_entry = f"[Message Processed After Resume]: {str(msg_content)[:200]}"
                    self.add_to_conversation_history("user", history_entry)
            self.pending_messages_while_paused.clear()
            self.logger.info("Cleared pending messages queue.")

        self.paused_state = {} # Clear the state after successful resumption and processing

        # Determine new status (running if task, idle if not)
        if self.current_task_description: # If a task was restored
            self.current_status = MinionStatus.RUNNING
            self.logger.info(f"Resuming with task: {self.current_task_description}")
            # The main loop should pick up this task.
            # Or, if process_task was designed to be re-entrant, call it.
            # For V1, assume main loop handles it.
        else:
            self.current_status = MinionStatus.IDLE
            self.logger.info("Resumed to idle state as no task was active.")
        
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
            self.a2a_client.send_message(
                recipient_agent_id=recipient_id,
                message_content=full_message,
                message_type=message_type
            )
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
            self.a2a_client.send_message(
                recipient_agent_id=recipient_id,
                message_content=full_nack_message,
                message_type="m2m_negative_acknowledgement"
            )
            self.logger.info(f"Sent NACK to {recipient_id} for original_msg_id {original_message_id}. Reason: {reason_code}. Details: {details}")
        except Exception as e:
            self.logger.error(f"Failed to send NACK to {recipient_id}: {e}", exc_info=True)


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


    def process_task(self, task_description: str, original_sender_id: str):
        if self.is_paused:
            self.logger.info(f"Task '{task_description[:60]}...' received but minion is paused. Storing.")
            self._store_message_while_paused({"type": "directive", "content": task_description, "sender": original_sender_id})
            # We don't send a state update here as the minion is already paused.
            return "Task stored due to paused state."

        self.is_idle = False
        self.current_task = task_description # Used by _send_state_update if it needs the generic task ID
        self.current_task_description = task_description # Specifically for serialization
        self.current_status = MinionStatus.RUNNING
        self._send_state_update(self.current_status, f"Processing task: {task_description[:60]}...")
        self.logger.info(f"Starting to process task: '{task_description[:100]}...'")
        
        # Construct the full prompt for the LLM
        full_prompt = self._construct_prompt_from_history_and_task(task_description)
        
        # Send to LLM
        llm_response_text = self.llm.send_prompt(full_prompt)
        
        if llm_response_text.startswith("ERROR_"):
            self.logger.error(f"LLM processing failed for task '{task_description[:100]}...'. Error: {llm_response_text}")
            self.current_status = MinionStatus.ERROR
            self._send_state_update(self.current_status, f"LLM error on task: {llm_response_text}")
            # BIAS_ACTION: Implement fallback or error reporting to Steven via GUI/A2A
            self.is_idle = True
            self.current_task = None # Clear generic task ID
            self.current_task_description = None # Clear specific task description for serialization
            return f"Failed to process task due to LLM error: {llm_response_text}"

        self.logger.info(f"LLM response for task '{task_description}': '{llm_response_text[:200]}...'")

        # Check for pause request *after* LLM response, before sending reply or doing more work.
        # This is a V1 safe point. More granular checks would be inside a multi-step task.
        if self.is_paused:
            self.logger.info("Pause detected after LLM response, before sending reply. Task progress will be saved.")
            # The current_task_description is already set.
            # The llm_response_text could be part of 'task_progress' in a more complex serialization.
            # For V1, we assume pausing here means this LLM response might be lost unless explicitly saved
            # in self.paused_state by _serialize_state (e.g. as an intermediate result).
            # _serialize_state currently doesn't store intermediate LLM responses, only the task description.
            # This means on resume, the LLM part might re-run unless process_task is made more granular.
            return "Task processing interrupted by pause."


        if llm_response_text:
            self.logger.info(f"Attempting to call self.a2a_client.send_message. Recipient: '{original_sender_id}', Content: '{llm_response_text[:100]}...'")
            try:
                reply_sent = self.a2a_client.send_message(
                    recipient_agent_id=original_sender_id,
                    message_content=llm_response_text, # Ensure param name matches 'send_message' definition
                    message_type="directive_reply"
                )
                # self.logger.info(f"Call to self.a2a_client.send_message completed. Result: {reply_sent}") # Redundant if next log is clear
            except Exception as e:
                self.logger.error(f"CRITICAL: Exception occurred DURING or IMMEDIATELY AFTER calling self.a2a_client.send_message: {e}", exc_info=True)
                reply_sent = False # Assume failure if exception

            if reply_sent:
                self.logger.info(f"Successfully sent reply via A2A to '{original_sender_id}'.")
            else:
                self.logger.error(f"Failed to send reply via A2A to '{original_sender_id}'. Check A2AClient logs for details if no exception here.")
        else:
            self.logger.warning("LLM response was empty, not sending a reply.")

        # For now, just return the LLM's raw response as the "result"
        # The actual "result" for the original caller of process_task might be less relevant
        # now that the primary output is an A2A message.
        self.is_idle = True
        self.current_task = None # Clear generic task ID
        self.current_task_description = None # Clear specific task description
        self.current_status = MinionStatus.IDLE
        self._send_state_update(self.current_status, "Task completed, minion idle.")
        return llm_response_text


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
            self.a2a_client.send_message(
                recipient_agent_id=item["recipient_id"],
                message_content=item["message_payload"], # Resend the original payload
                message_type=item["message_type"]
            )
            self.logger.info(f"Retried M2M '{item['message_type']}' to {item['recipient_id']} with request_id {request_id}. Retries left: {item['retries_left']}. Trace: {item['trace_id']}.")
        except Exception as e:
            self.logger.error(f"Failed to retry M2M '{item['message_type']}' to {item['recipient_id']}: {e}", exc_info=True)
            # If send fails on retry, it will timeout again or be NACKed.
            # Or, we could implement immediate removal if send fails catastrophically.
            # For now, rely on the next timeout cycle or NACK.

    def _save_state_to_file(self):
        """Saves the current operational state to a file, typically if paused."""
        # This method is called during shutdown if the minion is paused or has a populated paused_state.
        # Ensure self.paused_state is current if we are in a paused state.
        # If _pause_workflow was called, self.paused_state is already populated by _serialize_state.
        
        if not self.paused_state and not self.is_paused:
             self.logger.info("Minion not paused and no serialized state available. Skipping state file save on shutdown.")
             return
        
        # If is_paused is true, _serialize_state() should have been called by _pause_workflow().
        # If we are shutting down while paused, self.paused_state should be current.
        # If we are not technically 'is_paused' but paused_state got populated (e.g. error during resume), still save.
        
        # We construct the full object to save, including the is_paused flag itself.
        # If not currently paused but paused_state exists, we might be in an error state post-pause attempt.
        # In this case, is_paused might be False, but we still want to save the last known paused_state.
        # The `is_paused` flag in the file should reflect the minion's actual pause status at time of saving.
        
        # If self.is_paused is False, but self.paused_state is populated, it implies an issue.
        # For robustness, if self.paused_state has data, we save it, reflecting current self.is_paused.
        # This means if it failed to resume and is_paused became False, the file will show is_paused: false
        # but will contain the state from *before* the failed resume. This seems reasonable.

        state_to_save = {
            "is_paused": self.is_paused,
            "paused_state": self.paused_state, # This contains the actual operational data
            "pending_messages_while_paused": list(self.pending_messages_while_paused), # Ensure it's a copy
            "current_task_description": self.current_task_description, # Save this as well for context
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        try:
            # Ensure directory exists (though __init__ should create minion_state_storage_dir)
            os.makedirs(os.path.dirname(self.state_file_path), exist_ok=True)
            with open(self.state_file_path, 'w') as f:
                json.dump(state_to_save, f, indent=4)
            self.logger.info(f"Successfully saved minion state to {self.state_file_path}")
        except Exception as e:
            self.logger.error(f"Failed to save minion state to {self.state_file_path}: {e}", exc_info=True)


    def shutdown(self):
        self.logger.info(f"Minion {self.minion_id} shutting down...")
        
        # Save state if paused or if there's a populated paused_state (e.g. from a prior pause)
        if self.is_paused or self.paused_state:
            self.logger.info("Minion is paused or has a serialized state. Attempting to save state to file before shutdown.")
            if not self.paused_state and self.is_paused: # If is_paused but state not yet serialized (e.g. abrupt shutdown during pausing)
                self._serialize_state() # Try to capture current state
            self._save_state_to_file()

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
