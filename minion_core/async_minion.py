import asyncio
import os
import sys
import time
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
import logging
import signal
from typing import Optional, Any, Dict, List, Callable # Added Any for task.description

# Import other necessary components
from system_configs.config_manager import config
from minion_core.utils.logger import setup_logger
from minion_core.utils.errors import MinionError, LLMError
from minion_core.llm_interface import LLMInterface
from minion_core.a2a_async_client import AsyncA2AClient
from minion_core.mcp_node_bridge import McpNodeBridge
from minion_core.task_queue import TaskQueue, TaskPriority
from minion_core.state_manager import StateManager, MinionState, TaskState
from minion_core.utils.metrics import MetricsCollector
from minion_core.task_decomposer import TaskDecomposer
from minion_core.task_coordinator import TaskCoordinator, SubtaskStatus
# TaskPriority is already imported from minion_core.task_queue
# TaskState is already imported from minion_core.state_manager

class MinionStatus(Enum):
    INITIALIZING = "initializing"
    IDLE = "idle"
    RUNNING = "running"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    ERROR = "error"
    SHUTTING_DOWN = "shutting_down"

class AsyncMinion:
    """Asynchronous implementation of the Minion class."""
    
    def __init__(self, minion_id: str, user_facing_name: Optional[str] = None, 
                personality_traits_str: Optional[str] = None, a2a_server_url_override: Optional[str] = None):
        self.minion_id = minion_id
        self.user_facing_name = user_facing_name or f"UnnamedMinion-{self.minion_id[:6]}"
        
        # Initialize logger
        logs_dir = config.get_path("global.logs_dir", "logs")
        os.makedirs(logs_dir, exist_ok=True)
        self.log_file_path = os.path.join(logs_dir, f"minion_{self.minion_id}.log")
        self.logger = setup_logger(f"Minion_{self.minion_id}", self.log_file_path)
        
        self.logger.info(f"Initializing Minion {self.minion_id} (Name: {self.user_facing_name})")
        
        # Basic properties
        self.start_time = datetime.now(timezone.utc)
        self.current_status = MinionStatus.INITIALIZING
        
        # Load configuration
        self._load_configuration(personality_traits_str, a2a_server_url_override)
        
        # Initialize StateManager
        minion_state_storage_dir = config.get_path("minion_state.storage_dir", 
                                                  os.path.join(config.get_project_root(), "system_data", "minion_states"))
        self.state_manager = StateManager(minion_id=self.minion_id, 
                                         storage_dir=minion_state_storage_dir,
                                         logger=self.logger)
        
        # Initialize MetricsCollector
        metrics_dir = config.get_path("metrics.storage_dir", 
                                     os.path.join(config.get_project_root(), "system_data", "metrics"))
        self.metrics = MetricsCollector(
            component_name=f"Minion_{self.minion_id}",
            storage_dir=metrics_dir,
            logger=self.logger
        )
        
        # Initialize TaskQueue
        self.task_queue = TaskQueue(logger=self.logger)
        
        # These components will be initialized in run()
        self.llm = None
        self.mcp_bridge = None
        self.a2a_client = None
        self.task_decomposer = None
        self.task_coordinator = None
        self.collaborative_subtasks = {}  # subtask_id -> task info (including coordinator_id)
        
        # Asyncio stuff
        self.loop = None
        self.shutdown_event = None
        self.periodic_tasks = []

        # Adaptive behavior settings
        self.adaptive_settings = {
            "llm_token_limit_normal": config.get_int("adaptive_resource_management.llm_token_limit_normal", 8000),
            "llm_token_limit_reduced": config.get_int("adaptive_resource_management.llm_token_limit_reduced", 4000),
            "parallel_tasks_normal": config.get_int("adaptive_resource_management.parallel_tasks_normal", 3),
            "parallel_tasks_reduced": config.get_int("adaptive_resource_management.parallel_tasks_reduced", 1),
            "is_resource_constrained": False,
            "last_resource_update": 0
        }
        self.active_tasks_count = 0 # For managing parallel tasks
    
    def _load_configuration(self, personality_traits_str, a2a_server_url_override):
        """Load configuration for the minion."""
        # Determine personality
        if personality_traits_str is None:
            # Try to get from spawner config
            spawner_minions_config = config.get_list("minion_spawner.minions", [])
            minion_spawn_def = next((m for m in spawner_minions_config if m.get("id") == self.minion_id), None)
            if minion_spawn_def and "personality" in minion_spawn_def:
                personality_traits_str = minion_spawn_def["personality"]
            else:
                personality_traits_str = config.get_str("minion_defaults.default_personality", 
                                                      "Adaptable, Resourceful, Meticulous")
        
        self.personality_traits = personality_traits_str
        self.logger.info(f"Personality: {self.personality_traits}")
        
        # Load MCP configuration
        self.enable_mcp_integration = config.get_bool('mcp_integration.enable_mcp_integration', False)
        self.mcp_node_service_base_url = config.get_str('mcp_integration.mcp_node_service_base_url')
        self.manage_mcp_node_service_lifecycle = config.get_bool('mcp_integration.manage_mcp_node_service_lifecycle', False)
        self.mcp_node_service_startup_command = config.get_str('mcp_integration.mcp_node_service_startup_command')
        
        # Load A2A configuration
        default_a2a_host = config.get_str("a2a_server.host", "127.0.0.1")
        default_a2a_port = config.get_int("a2a_server.port", 8080)
        default_a2a_url = f"http://{default_a2a_host}:{default_a2a_port}"
        self.a2a_server_url = a2a_server_url_override or default_a2a_url
        
        # Load other configuration
        self.gui_commander_id = config.get_str("a2a_identities.gui_commander_id", "STEVEN_GUI_COMMANDER")
        
        # M2M Communication configuration
        self.m2m_retry_attempts = config.get_int("m2m_communication.default_retry_attempts", 3)
        self.m2m_default_timeout_seconds = config.get_int("m2m_communication.default_timeout_seconds", 60)
        self.m2m_max_delegation_depth = config.get_int("m2m_communication.max_delegation_depth", 5)
    
    async def initialize_components(self):
        """Initialize and connect all components."""
        # Initialize LLM
        try:
            gemini_api_key_env_name = config.get_str("llm.gemini_api_key_env_var", "GEMINI_API_KEY_LEGION")
            api_key = os.getenv(gemini_api_key_env_name)
            if not api_key:
                raise ValueError(f"API key not found in environment variable {gemini_api_key_env_name}")
            
            self.llm = LLMInterface(minion_id=self.minion_id, api_key=api_key, logger=self.logger)
            self.logger.info("LLM interface initialized")
        except Exception as e:
            self.logger.critical(f"Failed to initialize LLM: {e}", exc_info=True)
            raise
        
        # Initialize MCP Bridge if enabled
        if self.enable_mcp_integration:
            try:
                if not self.mcp_node_service_base_url:
                    self.logger.error("MCP Node service URL not configured")
                    self.enable_mcp_integration = False
                else:
                    self.mcp_bridge = McpNodeBridge(base_url=self.mcp_node_service_base_url, logger=self.logger)
                    self.logger.info(f"MCP Bridge initialized with URL: {self.mcp_node_service_base_url}")
                    
                    if self.manage_mcp_node_service_lifecycle and self.mcp_node_service_startup_command:
                        # Start MCP service
                        await self._start_mcp_service()
            except Exception as e:
                self.logger.error(f"Failed to initialize MCP Bridge: {e}", exc_info=True)
                self.enable_mcp_integration = False
        
        # Initialize A2A Client
        try:
            agent_card = self._create_agent_card()
            self.a2a_client = AsyncA2AClient(
                minion_id=self.minion_id,
                a2a_server_url=self.a2a_server_url,
                agent_card_data=agent_card,
                logger=self.logger,
                message_callback=self.handle_a2a_message
            )
            
            registration_success = await self.a2a_client.start()
            if registration_success:
                self.logger.info("A2A client initialized and registered")
            else:
                self.logger.error("Failed to register with A2A server")
        except Exception as e:
            self.logger.error(f"Failed to initialize A2A client: {e}", exc_info=True)
            raise
        
        # Initialize task decomposer and coordinator
        self.task_decomposer = TaskDecomposer(self.llm, logger=self.logger)
        self.task_coordinator = TaskCoordinator(
            a2a_client=self.a2a_client,
            task_decomposer=self.task_decomposer,
            logger=self.logger
        )
        
        # Register this minion with its local coordinator
        # The coordinator will then know about this minion if it needs to assign tasks to itself
        # or if it's queried for available minions by its own decomposer.
        minion_info_dict = { # Renamed from minion_info to avoid conflict if plan meant a class
            "id": self.minion_id,
            "name": self.user_facing_name,
            "personality": self.personality_traits,
            "skills": self._get_minion_skills() # Placeholder for actual skill retrieval
        }
        self.task_coordinator.register_minion(self.minion_id, minion_info_dict)
        self.logger.info(f"Minion {self.minion_id} registered with its local TaskCoordinator.")

        # Register with resource monitor if available
        try:
            # Import locally to avoid circular dependency or issues if module not present
            from minion_core.utils.resource_monitor import ResourceMonitor
            if 'global_resource_monitor' in globals():
                monitor = globals()['global_resource_monitor']
                if isinstance(monitor, ResourceMonitor): # Check instance type
                    monitor.add_alert_callback(self._handle_resource_alert)
                    self.logger.info("Registered with global resource monitor")
                else:
                    self.logger.warning("Found 'global_resource_monitor' but it's not a ResourceMonitor instance.")
            else:
                self.logger.info("'global_resource_monitor' not found. Adaptive constraints based on global monitor disabled.")
        except ImportError:
            self.logger.info("ResourceMonitor utility not available, adaptive constraints based on global monitor disabled.")
        except Exception as e:
            self.logger.error(f"Error registering with resource monitor: {e}", exc_info=True)
    
    def _get_minion_skills(self) -> list:
        # Placeholder: In a real system, this would fetch defined skills.
        # For now, returning a generic skill.
        return [{"name": "general_problem_solving", "level": "proficient"}]

    def _create_agent_card(self):
        """Create the agent card for A2A registration."""
        # TODO: Populate skills with actual minion capabilities later
        skills_list = [
            {"id": "general_assistance", "name": "general_assistance", "description": "Can perform general tasks and follow instructions."},
            {"id": "llm_interaction", "name": "llm_interaction", "description": "Can interact with Large Language Models."},
        ]
        if hasattr(self, 'enable_mcp_integration') and self.enable_mcp_integration: # Conditionally add if MCP is enabled
             skills_list.append({"id": "mcp_tool_usage", "name": "mcp_tool_usage", "description": "Can utilize tools via the MCP bridge."})

        return {
            "id": self.minion_id,
            "name": self.user_facing_name,
            "version": "1.0.0",  # Added version
            "description": f"An AI Minion in Steven's Army. Personality: {self.personality_traits}",
            "url": f"{self.a2a_server_url}/agents/{self.minion_id}",
            "capabilities": {
                "streaming": False, # Assuming not implemented yet
                "pushNotifications": False, # Assuming not implemented yet
                "stateTransitionHistory": False # Assuming not implemented yet
            },
            "skills": skills_list # Added skills
        }
    
    async def _start_mcp_service(self):
        """Start the MCP Node.js service if configured to do so."""
        if not self.mcp_node_service_startup_command:
            self.logger.warning("No MCP Node service startup command configured")
            return
        
        self.logger.info(f"Starting MCP Node service with command: {self.mcp_node_service_startup_command}")
        
        try:
            # Create subprocess
            command_args = self.mcp_node_service_startup_command.split()
            process = await asyncio.create_subprocess_exec(
                *command_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            self.logger.info(f"MCP Node service started with PID: {process.pid}")
            
            # Start a task to monitor the process
            asyncio.create_task(self._monitor_mcp_service(process))
            
        except Exception as e:
            self.logger.error(f"Failed to start MCP Node service: {e}", exc_info=True)
    
    async def _monitor_mcp_service(self, process):
        """Monitor the MCP service process."""
        while True:
            if process.returncode is not None:
                self.logger.warning(f"MCP Node service exited with code: {process.returncode}")
                # Log output
                stdout, stderr = await process.communicate()
                if stdout:
                    self.logger.info(f"MCP Node service stdout: {stdout.decode()}")
                if stderr:
                    self.logger.error(f"MCP Node service stderr: {stderr.decode()}")
                break
            
            # Check again in 5 seconds
            await asyncio.sleep(5)
    
    async def handle_a2a_message(self, message_data):
        """Handle A2A messages (now as async function)."""
        self.logger.info(f"Received A2A message: {str(message_data)[:100]}...")
        
        # Track in metrics
        self.metrics.inc_counter("a2a_messages_received", labels={
            "type": message_data.get("message_type", "unknown")
        })
        
        sender_id = message_data.get("sender_id", "UnknownSender")
        content = message_data.get("content", "")
        message_type = message_data.get("message_type", "unknown")
        
        # Process message based on type
        if message_type == "control_pause_request":
            await self._pause_workflow()
            # Send acknowledgement
            await self.a2a_client.send_message(
                sender_id,
                {"minion_id": self.minion_id, "status": "paused"},
                "control_pause_ack"
            )
        
        elif message_type == "control_resume_request":
            await self._resume_workflow()
            # Send acknowledgement
            await self.a2a_client.send_message(
                sender_id,
                {"minion_id": self.minion_id, "status": self.current_status.value},
                "control_resume_ack"
            )
        
        elif message_type == "user_broadcast_directive" and content:
            if self.current_status == MinionStatus.PAUSED:
                self.logger.info("Received directive but minion is paused. Storing.")
                # Store message for later
                # Implementation depends on your state management approach
            else:
                self.logger.info(f"Received directive: {str(content)[:60]}...")
                # Add to task queue
                task_id = self.task_queue.add_task(
                    description=content,
                    sender_id=sender_id,
                    priority=TaskPriority.NORMAL
                )
                # Start processing task queue
                asyncio.create_task(self._process_task_queue())
        
        # Handle collaborative task messages
        elif message_type == "collaborative_task_request":
            await self._handle_collaborative_task_request(content, sender_id)
        elif message_type == "collaborative_subtask_assignment":
            await self._handle_collaborative_subtask(content, sender_id)
        elif message_type == "collaborative_subtask_result":
            await self._handle_collaborative_subtask_result(content)
        
        # Handle other message types similarly...
    
    async def _handle_collaborative_task_request(self, content: Dict[str, Any], requester_id: str):
        """Handle a request to start a collaborative task, coordinated by this minion."""
        if self.current_status == MinionStatus.PAUSED:
            self.logger.info("Received collaborative task request while paused. Will not process.")
            # Optionally, notify requester that minion is paused
            return
        
        task_description = content.get("task_description")
        if not task_description:
            self.logger.warning(f"Collaborative task request from {requester_id} missing description. Ignoring.")
            # Optionally, send error back to requester
            return
        
        self.logger.info(f"Received collaborative task request from {requester_id}: \"{task_description[:100]}...\"")
        
        try:
            task_id = await self.task_coordinator.create_collaborative_task(
                task_description=task_description,
                requester_id=requester_id
            )
            self.logger.info(f"Collaborative task {task_id} created and processing initiated by coordinator.")
            
            await self.a2a_client.send_message(
                recipient_agent_id=requester_id,
                message_content={
                    "task_id": task_id,
                    "original_request": task_description,
                    "status": "accepted_for_coordination",
                    "coordinator_id": self.minion_id,
                    "message": f"Task accepted and coordination started by {self.user_facing_name} ({self.minion_id})."
                },
                message_type="collaborative_task_acknowledgement"
            )
        except Exception as e:
            self.logger.error(f"Failed to create collaborative task for {requester_id}: {e}", exc_info=True)
            await self.a2a_client.send_message(
                recipient_agent_id=requester_id,
                message_content={
                    "original_request": task_description,
                    "status": "failed_to_coordinate",
                    "error": str(e)
                },
                message_type="collaborative_task_acknowledgement" # Or a specific error type
            )

    async def _handle_collaborative_subtask(self, content: Dict[str, Any], sender_id: str):
        """Handle an assignment for a collaborative subtask from a coordinator."""
        if self.current_status == MinionStatus.PAUSED:
            self.logger.info("Received collaborative subtask assignment while paused. Will not process.")
            # Optionally, notify coordinator that minion is paused
            return

        collaborative_task_id = content.get("collaborative_task_id")
        subtask_id = content.get("subtask_id")
        description = content.get("description")
        original_task_desc = content.get("original_task", "N/A")
        success_criteria = content.get("success_criteria", "N/A")

        if not all([collaborative_task_id, subtask_id, description]):
            self.logger.warning(f"Collaborative subtask assignment from {sender_id} missing required fields. Ignoring.")
            return
        
        self.logger.info(f"Received collaborative subtask {subtask_id} for main task {collaborative_task_id} from coordinator {sender_id}.")
        
        # Store subtask info, including coordinator_id (sender_id of this message)
        subtask_details = content.copy()
        subtask_details['coordinator_id'] = sender_id
        self.collaborative_subtasks[subtask_id] = subtask_details
        
        # Add to this minion's task queue with high priority
        self.task_queue.add_task(
            description=f"Execute collaborative subtask: {description}",
            sender_id=sender_id, # The coordinator who assigned this
            priority=TaskPriority.HIGH,
            metadata={
                "type": "collaborative_subtask",
                "collaborative_task_id": collaborative_task_id,
                "subtask_id": subtask_id,
                "coordinator_id": sender_id # Crucial for sending results back
            }
        )
        
        # Ensure task queue processing is triggered
        if self.current_status not in [MinionStatus.RUNNING, MinionStatus.PAUSED, MinionStatus.PAUSING, MinionStatus.SHUTTING_DOWN]:
             asyncio.create_task(self._process_task_queue())
        elif self.current_status == MinionStatus.RUNNING and not self.task_queue.is_processing():
             asyncio.create_task(self._process_task_queue())


    async def _handle_collaborative_subtask_result(self, content: Dict[str, Any]):
        """Handle a result/update for a subtask, intended for this minion's TaskCoordinator."""
        collaborative_task_id = content.get("collaborative_task_id")
        subtask_id = content.get("subtask_id")
        status_str = content.get("status")
        result_data = content.get("result")
        error_details = content.get("error")
        
        if not all([collaborative_task_id, subtask_id, status_str]):
            self.logger.warning(f"Collaborative subtask result message missing required fields. Ignoring. Content: {content}")
            return
            
        self.logger.info(f"Received result for subtask {subtask_id} (main task {collaborative_task_id}) with status: {status_str}.")

        try:
            subtask_status_enum = SubtaskStatus(status_str) # Convert string to Enum
            await self.task_coordinator.update_subtask_status(
                task_id=collaborative_task_id,
                subtask_id=subtask_id,
                status=subtask_status_enum,
                result=result_data,
                error=error_details
            )
            self.logger.info(f"TaskCoordinator updated for subtask {subtask_id}.")
        except ValueError:
            self.logger.error(f"Invalid status string '{status_str}' received for subtask {subtask_id}.", exc_info=True)
        except Exception as e:
            self.logger.error(f"Error updating TaskCoordinator for subtask {subtask_id}: {e}", exc_info=True)

    def _handle_resource_alert(self, resources: dict, is_overloaded: bool):
        """Handle resource alerts from the monitor."""
        # This method is called by the ResourceMonitor's thread,
        # so be careful with shared state if not using asyncio-safe mechanisms.
        # For now, simple updates and logging.
        old_state = self.adaptive_settings["is_resource_constrained"]
        self.adaptive_settings["is_resource_constrained"] = is_overloaded
        self.adaptive_settings["last_resource_update"] = time.time()

        if old_state != is_overloaded:
            if is_overloaded:
                self.logger.warning("Entering resource-constrained mode due to system load.")
                if hasattr(self, 'metrics'): # Check if metrics is initialized
                    self.metrics.inc_counter("resource_constraint_events")
            else:
                self.logger.info("Exiting resource-constrained mode as system load eased.")
        
        if hasattr(self, 'metrics'):
            self.metrics.set_gauge("is_resource_constrained", 1 if is_overloaded else 0)

        # Further actions (e.g., adjusting running tasks) should be scheduled
        # on the minion's event loop if they involve async operations or complex state changes.
        # For now, the _process_task_queue will pick up the new state.
        if is_overloaded:
             self.logger.info(f"System resources indicate overload. Minion {self.minion_id} will adapt. Details: CPU {resources.get('cpu_percent', 'N/A')}%, Mem {resources.get('memory_percent', 'N/A')}%")

    def _construct_adaptive_prompt(self, task_description: str, base_prompt_prefix: str = "Task: ") -> str:
        """Construct an LLM prompt for a task, adapting to resource constraints."""
        prompt = f"{base_prompt_prefix}{task_description}\n\nRespond with a detailed plan and solution."

        token_limit_key = "llm_token_limit_normal"
        if self.adaptive_settings["is_resource_constrained"]:
            token_limit_key = "llm_token_limit_reduced"
            self.logger.info(f"Using reduced token limit: {self.adaptive_settings[token_limit_key]} due to resource constraints.")

        token_limit = self.adaptive_settings[token_limit_key]

        # Simple approach: estimate tokens and truncate if needed
        # A better implementation would use a proper tokenizer (e.g., tiktoken for OpenAI models)
        # For Gemini, character count is a rough proxy but not accurate for actual tokens.
        # Assuming an average of 4 chars per token for this placeholder logic.
        estimated_tokens = len(prompt) // 4

        if estimated_tokens > token_limit:
            max_chars = token_limit * 4  # Approximate character limit
            prompt = prompt[:max_chars] + "\n\n[Note: Prompt truncated due to system resource constraints]"
            self.logger.warning(f"Prompt for task '{task_description[:50]}...' was truncated to fit token limit {token_limit}.")
        
        return prompt

    async def _send_state_update(self, status: MinionStatus, details: str = ""):
        """Send a state update message to the GUI commander."""
        if not self.a2a_client:
            return
        
        message_content = {
            "minion_id": self.minion_id,
            "new_status": status.value,
            "details": details,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        try:
            await self.a2a_client.send_message(
                recipient_agent_id=self.gui_commander_id,
                message_content=message_content,
                message_type="minion_state_update"
            )
            self.logger.info(f"Sent state update: {status.value}, {details}")
        except Exception as e:
            self.logger.error(f"Failed to send state update: {e}", exc_info=True)
    
    async def _pause_workflow(self):
        """Pause the minion's workflow."""
        if self.current_status == MinionStatus.PAUSED:
            self.logger.info("Already paused")
            return
        
        self.logger.info("Pausing workflow...")
        self.current_status = MinionStatus.PAUSING
        await self._send_state_update(self.current_status, "Pausing workflow...")
        
        # Implement pause logic here
        # ...
        
        self.current_status = MinionStatus.PAUSED
        await self._send_state_update(self.current_status, "Minion paused")
        self.logger.info("Workflow paused")
    
    async def _resume_workflow(self):
        """Resume the minion's workflow."""
        if self.current_status != MinionStatus.PAUSED:
            self.logger.info(f"Cannot resume from state: {self.current_status.value}")
            return
        
        self.logger.info("Resuming workflow...")
        self.current_status = MinionStatus.RESUMING
        await self._send_state_update(self.current_status, "Resuming workflow...")
        
        # Implement resume logic here
        # ...
        
        self.current_status = MinionStatus.IDLE
        await self._send_state_update(self.current_status, "Minion resumed")
        self.logger.info("Workflow resumed")
        
        # Process any pending tasks
        asyncio.create_task(self._process_task_queue())
    
    async def _execute_regular_task(self, task):
        """Executes a regular task from the queue."""
        self.logger.info(f"Executing regular task: {task.task_id} - \"{str(task.description)[:60]}...\"")
        timer_id = self.metrics.start_timer("regular_task_processing_time")
        
        try:
            # Construct adaptive prompt
            prompt = self._construct_adaptive_prompt(task.description)
            
            # Send to LLM
            # TODO: Consider making self.llm.send_prompt async if it involves I/O
            response = self.llm.send_prompt(prompt)
            
            self.metrics.stop_timer(timer_id)
            self.metrics.inc_counter("regular_tasks_processed_success")
            
            # Send response to original sender of the task
            if self.a2a_client and task.sender_id:
                await self.a2a_client.send_message(
                    recipient_agent_id=task.sender_id,
                    message_content={"response": response, "task_id": task.task_id, "status": "completed"},
                    message_type="directive_reply"
                )
            
            self.task_queue.complete_current_task(task_id=task.task_id, result=response) # Pass task_id
            self.logger.info(f"Regular task {task.task_id} completed.")

        except Exception as e:
            self.logger.error(f"Error executing regular task {task.task_id}: {e}", exc_info=True)
            self.metrics.stop_timer(timer_id) # Ensure timer stops on error
            self.metrics.inc_counter("regular_tasks_processed_failure")
            self.task_queue.fail_current_task(task_id=task.task_id, error=str(e)) # Pass task_id
            if self.a2a_client and task.sender_id:
                 await self.a2a_client.send_message(
                    recipient_agent_id=task.sender_id,
                    message_content={"error": str(e), "task_id": task.task_id, "status": "failed"},
                    message_type="directive_reply"
                )
        finally:
            self.active_tasks_count -= 1
            # Trigger task queue processing again in case this frees up a slot
            # and to update status if idle
            asyncio.create_task(self._process_task_queue())


    async def _process_task_queue(self):
        """Process tasks in the queue, respecting resource constraints and parallelism."""
        if self.current_status in [MinionStatus.PAUSED, MinionStatus.PAUSING, MinionStatus.SHUTTING_DOWN]:
            self.logger.debug(f"Task queue processing skipped due to status: {self.current_status.value}")
            return

        # Determine max parallel tasks based on resource state
        if self.adaptive_settings["is_resource_constrained"]:
            max_parallel = self.adaptive_settings["parallel_tasks_reduced"]
        else:
            max_parallel = self.adaptive_settings["parallel_tasks_normal"]

        while self.active_tasks_count < max_parallel:
            if self.current_status in [MinionStatus.PAUSED, MinionStatus.PAUSING, MinionStatus.SHUTTING_DOWN]:
                break # Stop trying to pick tasks if status changed

            task = self.task_queue.start_next_task() # This marks task as PENDING_EXECUTION
            if not task:
                break  # No more tasks to start or queue is locked

            self.active_tasks_count += 1
            
            if self.current_status != MinionStatus.RUNNING: # Set to running if we are picking up tasks
                self.current_status = MinionStatus.RUNNING
                await self._send_state_update(self.current_status, f"Starting task processing, active: {self.active_tasks_count}")

            self.logger.info(f"Picked task {task.id} for execution. Active tasks: {self.active_tasks_count}. Max parallel: {max_parallel}")
            await self._send_state_update(self.current_status, f"Processing: {str(task.description)[:60]}... (Active: {self.active_tasks_count})")
            
            metadata = task.metadata or {}
            if metadata.get("type") == "collaborative_subtask":
                asyncio.create_task(self._execute_collaborative_subtask(task))
            else:
                asyncio.create_task(self._execute_regular_task(task))
        
        # After attempting to fill parallel slots, check if minion should be idle
        # This check should happen regardless of whether new tasks were started in *this* call,
        # as a task might have finished, decrementing active_tasks_count.
        if self.active_tasks_count == 0 and (not self.task_queue.queue and self.task_queue.running_task is None) and self.current_status != MinionStatus.IDLE:
            if self.current_status not in [MinionStatus.PAUSED, MinionStatus.PAUSING, MinionStatus.SHUTTING_DOWN, MinionStatus.ERROR]:
                self.current_status = MinionStatus.IDLE
                await self._send_state_update(self.current_status, "Idle, task queue empty and no active tasks.")
                self.logger.info("Minion is now IDLE as task queue is empty and no tasks are active.")
    
    async def _execute_collaborative_subtask(self, task):
        """Executes a collaborative subtask received by this minion."""
        collaborative_task_id = task.metadata.get("collaborative_task_id")
        subtask_id = task.metadata.get("subtask_id")
        coordinator_id = task.metadata.get("coordinator_id")

        try:
            if not all([collaborative_task_id, subtask_id, coordinator_id]):
                self.logger.error(f"Collaborative subtask {task.id} missing crucial metadata. Metadata: {task.metadata}")
                self.task_queue.fail_current_task(error="Missing collaborative subtask metadata.")
                return

            subtask_info = self.collaborative_subtasks.get(subtask_id)
            if not subtask_info:
                self.logger.error(f"Details for collaborative subtask {subtask_id} (main task {collaborative_task_id}) not found.")
                self.task_queue.fail_current_task(error=f"Cached info for subtask {subtask_id} not found.")
                return

            self.logger.info(f"Executing collaborative subtask {subtask_id} for main task {collaborative_task_id}, reporting to coordinator {coordinator_id}.")
            timer_id = self.metrics.start_timer("collaborative_subtask_execution_time")

            # Construct adaptive prompt for the collaborative subtask
            prompt_text_for_llm = self._construct_adaptive_prompt(
                task_description=subtask_info.get('description'),
                base_prompt_prefix=(
                    f"You are an AI assistant executing a specific subtask as part of a larger collaborative project.\n"
                    f"The overall project (original task) is: \"{subtask_info.get('original_task', 'Not specified')}\"\n"
                    f"The success criteria for your subtask are: \"{subtask_info.get('success_criteria', 'Complete the subtask accurately and provide all necessary output.')}\"\n\n"
                    f"Your assigned subtask is: "
                )
            )
            
            llm_response = self.llm.send_prompt(prompt_text_for_llm)

            self.metrics.stop_timer(timer_id)
            self.metrics.inc_counter("collaborative_subtasks_executed_success")
            self.logger.info(f"Collaborative subtask {subtask_id} LLM execution successful.")

            if self.a2a_client:
                await self.a2a_client.send_message(
                    recipient_agent_id=coordinator_id,
                    message_content={
                        "collaborative_task_id": collaborative_task_id,
                        "subtask_id": subtask_id,
                        "status": SubtaskStatus.COMPLETED.value,
                        "result": llm_response
                    },
                    message_type="collaborative_subtask_result"
                )
            self.logger.info(f"Result for subtask {subtask_id} sent to coordinator {coordinator_id}.")
            self.task_queue.complete_current_task(result=llm_response)

        except Exception as e:
            self.logger.error(f"Error executing collaborative subtask {task.id} (original subtask ID {subtask_id}): {e}", exc_info=True)
            if 'timer_id' in locals() and self.metrics.is_timer_running(timer_id): # Check if timer_id was set and running
                self.metrics.stop_timer(timer_id)
            self.metrics.inc_counter("collaborative_subtasks_executed_failure")

            if self.a2a_client and coordinator_id and collaborative_task_id and subtask_id: # Ensure IDs are available for error reporting
                await self.a2a_client.send_message(
                    recipient_agent_id=coordinator_id,
                    message_content={
                        "collaborative_task_id": collaborative_task_id,
                        "subtask_id": subtask_id,
                        "status": SubtaskStatus.FAILED.value,
                        "error": str(e)
                    },
                    message_type="collaborative_subtask_result"
                )
            # These lines should be within the except block
            self.logger.info(f"Failure notification for subtask {subtask_id} sent to coordinator {coordinator_id}.")
            self.task_queue.fail_current_task(error=str(e))
        finally:
            self.active_tasks_count -= 1
            asyncio.create_task(self._process_task_queue())
    
    async def _update_metrics(self):
        """Periodic task to update and save metrics."""
        while not self.shutdown_event.is_set():
            try:
                # Update gauges
                self.metrics.set_gauge("is_paused", 1 if self.current_status == MinionStatus.PAUSED else 0)
                self.metrics.set_gauge("task_queue_length", len(self.task_queue.queue))
                self.metrics.set_gauge("is_running", 1 if self.current_status == MinionStatus.RUNNING else 0)
                
                # Save metrics
                self.metrics.save_metrics()
            except Exception as e:
                self.logger.error(f"Error updating metrics: {e}", exc_info=True)
            
            # Wait before next update
            await asyncio.sleep(30)
    
    async def run(self):
        """Main entry point for the minion."""
        # Set up asyncio
        self.loop = asyncio.get_event_loop()
        self.shutdown_event = asyncio.Event()
        
        # Set up signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            self.loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
        
        try:
            # Initialize all components
            await self.initialize_components()
            
            # Start metrics update task
            metrics_task = asyncio.create_task(self._update_metrics())
            self.periodic_tasks.append(metrics_task)
            
            # Set status to idle
            self.current_status = MinionStatus.IDLE
            await self._send_state_update(self.current_status, "Minion initialized and idle")
            
            # Process any tasks in queue
            asyncio.create_task(self._process_task_queue())
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
        except Exception as e:
            self.logger.critical(f"Error in main run loop: {e}", exc_info=True)
            self.current_status = MinionStatus.ERROR
            await self._send_state_update(self.current_status, f"Critical error: {str(e)}")
        finally:
            # Ensure cleanup happens
            if not self.shutdown_event.is_set(): # Check if shutdown_event is not None before calling is_set()
                await self.shutdown()
    
    async def shutdown(self):
        """Gracefully shut down the minion."""
        if self.current_status == MinionStatus.SHUTTING_DOWN:
            return
        
        self.logger.info("Shutting down...")
        self.current_status = MinionStatus.SHUTTING_DOWN
        if self.shutdown_event: # Check if shutdown_event is not None before calling set()
             self.shutdown_event.set()
        
        # Cancel all periodic tasks
        for task in self.periodic_tasks:
            if not task.done():
                task.cancel()
        
        # Stop A2A client
        if self.a2a_client:
            await self.a2a_client.stop()
        
        # Final metrics update
        if hasattr(self, 'metrics'):
            try:
                self.metrics.save_metrics()
            except Exception as e:
                self.logger.error(f"Error saving metrics during shutdown: {e}")
        
        self.logger.info("Shutdown complete")