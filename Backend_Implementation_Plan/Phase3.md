## Phase 3: Advanced Features and Optimization ()

### 1. Implement Asyncio-Based Processing

**Issue:** Current threading approach is inefficient and lacks structured concurrency.

**Implementation Steps:**

1. Create a new asyncio-based message processing system:

```python
# In minion_core/a2a_async_client.py
import asyncio
import aiohttp
import json
import time
import logging
from typing import Dict, Any, Optional, Callable, List

class AsyncA2AClient:
    """Asynchronous implementation of the A2A client."""
    
    def __init__(self, minion_id: str, a2a_server_url: str, agent_card_data: Dict[str, Any],
                logger=None, message_callback: Optional[Callable] = None):
        self.minion_id = minion_id
        self.a2a_server_url = a2a_server_url.rstrip('/')
        self.agent_card = agent_card_data
        self.logger = logger or logging.getLogger(f"AsyncA2AClient_{minion_id}")
        self.message_callback = message_callback
        
        self.is_registered = False
        self.session = None  # aiohttp session
        self.polling_task = None  # asyncio task for polling
        self.stop_polling_event = asyncio.Event()
        self.processed_message_ids = set()
    
    async def start(self):
        """Start the client and create the aiohttp session."""
        self.session = aiohttp.ClientSession()
        registered = await self.register_agent()
        if registered and self.message_callback:
            self.polling_task = asyncio.create_task(self._message_polling_loop())
        return registered
    
    async def stop(self):
        """Stop the client and clean up resources."""
        if self.polling_task:
            self.stop_polling_event.set()
            try:
                await asyncio.wait_for(self.polling_task, timeout=5)
            except asyncio.TimeoutError:
                self.logger.warning("Polling task did not stop gracefully, cancelling")
                self.polling_task.cancel()
        
        if self.session:
            await self.session.close()
    
    async def register_agent(self) -> bool:
        """Register the agent with the A2A server."""
        if not self.session:
            self.session = aiohttp.ClientSession()
        
        endpoint = "/agents"
        url = f"{self.a2a_server_url}{endpoint}"
        
        try:
            async with self.session.post(url, json=self.agent_card) as response:
                if response.status in [200, 201, 204]:
                    self.is_registered = True
                    self.logger.info(f"Successfully registered agent {self.minion_id}")
                    
                    if response.status != 204:
                        data = await response.json()
                        if 'id' in data and data['id'] != self.minion_id:
                            self.logger.info(f"Server assigned different ID: {data['id']}. Updating.")
                            self.minion_id = data['id']
                    
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to register agent. Status: {response.status}, Response: {error_text}")
                    return False
        except Exception as e:
            self.logger.error(f"Exception during registration: {e}", exc_info=True)
            return False
    
    async def send_message(self, recipient_agent_id: str, message_content: Any, 
                          message_type: str = "generic_text") -> bool:
        """Send a message to another agent."""
        if not self.is_registered:
            self.logger.warning("Not registered. Attempting registration.")
            if not await self.register_agent():
                return False
        
        endpoint = f"/agents/{recipient_agent_id}/messages"
        url = f"{self.a2a_server_url}{endpoint}"
        
        payload = {
            "sender_id": self.minion_id,
            "content": message_content,
            "message_type": message_type,
            "timestamp": time.time()
        }
        
        try:
            async with self.session.post(url, json=payload) as response:
                if response.status in [200, 201, 202, 204]:
                    self.logger.info(f"Message sent to {recipient_agent_id}")
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(f"Failed to send message. Status: {response.status}, Response: {error_text}")
                    return False
        except Exception as e:
            self.logger.error(f"Exception sending message: {e}", exc_info=True)
            return False
    
    async def _message_polling_loop(self):
        """Poll for new messages using adaptive polling."""
        min_interval = 1.0  # Start with 1 second
        max_interval = 10.0  # Max 10 seconds
        current_interval = min_interval
        last_message_time = time.time()
        
        self.logger.info(f"Starting message polling loop for {self.minion_id}")
        
        while not self.stop_polling_event.is_set():
            try:
                endpoint = f"/agents/{self.minion_id}/messages"
                url = f"{self.a2a_server_url}{endpoint}"
                
                async with self.session.get(url) as response:
                    if response.status == 200:
                        messages = await response.json()
                        
                        if messages:
                            # Got messages, reset polling interval
                            current_interval = min_interval
                            last_message_time = time.time()
                            
                            for message in messages:
                                await self._process_message(message)
                        else:
                            # No messages, gradually increase polling interval
                            idle_time = time.time() - last_message_time
                            if idle_time > 30:  # After 30 seconds idle
                                current_interval = min(current_interval * 1.5, max_interval)
                    else:
                        error_text = await response.text()
                        self.logger.warning(f"Error polling messages: {response.status}, {error_text}")
            
            except Exception as e:
                self.logger.error(f"Exception in polling loop: {e}", exc_info=True)
            
            # Wait before next poll
            await asyncio.sleep(current_interval)
    
    async def _process_message(self, message):
        """Process a single message."""
        message_id = message.get('id', 'unknown')
        
        # Skip already processed messages
        if message_id in self.processed_message_ids:
            return
        
        self.processed_message_ids.add(message_id)
        
        # Cap the size of processed_message_ids
        if len(self.processed_message_ids) > 1000:
            self.processed_message_ids = set(list(self.processed_message_ids)[-500:])
        
        self.logger.debug(f"Processing message: {message_id}")
        
        # Call message callback
        if self.message_callback:
            try:
                # If callback is async
                if asyncio.iscoroutinefunction(self.message_callback):
                    await self.message_callback(message)
                else:
                    # Run sync callback in executor to avoid blocking
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, self.message_callback, message)
            except Exception as e:
                self.logger.error(f"Error in message callback: {e}", exc_info=True)
```

2. Create asyncio-based minion class:

```python
# In minion_core/async_minion.py
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
        
        # Asyncio stuff
        self.loop = None
        self.shutdown_event = None
        self.periodic_tasks = []
    
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
    
    def _create_agent_card(self):
        """Create the agent card for A2A registration."""
        # Implementation remains similar to the original Minion class
        # but simplified for brevity in this example
        return {
            "id": self.minion_id,
            "name": self.user_facing_name,
            "description": f"An AI Minion in Steven's Army. Personality: {self.personality_traits}",
            "url": f"{self.a2a_server_url}/agents/{self.minion_id}",
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitionHistory": False
            }
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
                self.logger.info(f"Received directive: {content[:60]}...")
                # Add to task queue
                task_id = self.task_queue.add_task(
                    description=content,
                    sender_id=sender_id,
                    priority=TaskPriority.NORMAL
                )
                # Start processing task queue
                asyncio.create_task(self._process_task_queue())
        
        # Handle other message types similarly...
    
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
    
    async def _process_task_queue(self):
        """Process tasks in the queue."""
        if self.current_status in [MinionStatus.PAUSED, MinionStatus.PAUSING, MinionStatus.SHUTTING_DOWN]:
            return
        
        # Get next task if none is running
        task = self.task_queue.start_next_task()
        if not task:
            return
        
        self.current_status = MinionStatus.RUNNING
        await self._send_state_update(self.current_status, f"Processing: {task.description[:60]}...")
        
        try:
            # Process the task
            self.logger.info(f"Processing task: {task.description[:100]}...")
            
            # Start metrics timer
            timer_id = self.metrics.start_timer("task_processing_time")
            
            # Construct prompt
            prompt = f"Task: {task.description}\n\nRespond with a detailed plan and solution."
            
            # Send to LLM
            response = self.llm.send_prompt(prompt)
            
            # Stop metrics timer
            self.metrics.stop_timer(timer_id)
            self.metrics.inc_counter("tasks_processed")
            
            # Send response to sender
            await self.a2a_client.send_message(
                recipient_agent_id=task.sender_id,
                message_content=response,
                message_type="directive_reply"
            )
            
            # Mark task as completed
            self.task_queue.complete_current_task(result=response)
            
            # Update status
            if not self.task_queue.get_next_task():
                self.current_status = MinionStatus.IDLE
                await self._send_state_update(self.current_status, "Idle")
        
        except Exception as e:
            self.logger.error(f"Error processing task: {e}", exc_info=True)
            self.task_queue.fail_current_task(error=str(e))
            self.current_status = MinionStatus.ERROR
            await self._send_state_update(self.current_status, f"Error: {str(e)}")
        
        # Process next task if available
        if self.task_queue.get_next_task():
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
            if not self.shutdown_event.is_set():
                await self.shutdown()
    
    async def shutdown(self):
        """Gracefully shut down the minion."""
        if self.current_status == MinionStatus.SHUTTING_DOWN:
            return
        
        self.logger.info("Shutting down...")
        self.current_status = MinionStatus.SHUTTING_DOWN
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
```

3. Update the spawner to use the new async minion:

```python
# In minion_spawner/spawn_legion.py

# Import AsyncMinion
from minion_core.async_minion import AsyncMinion

# Replace existing spawn_minion function with:
def spawn_minions(num_minions_to_spawn_arg, a2a_server_url_arg):
    # Existing validation code...
    
    processes = []
    spawned_minion_ids = []
    
    # Use minion definitions from config
    actual_minion_definitions = MINION_DEFINITIONS_FROM_CONFIG
    if not actual_minion_definitions:
        spawner_log("No minion definitions loaded from config. Cannot spawn minions.", level="ERROR")
        return [], []

    num_available_definitions = len(actual_minion_definitions)
    num_to_spawn_final = min(num_minions_to_spawn_arg, num_available_definitions)

    # Resolve names and make adjustments like in the original spawner...
    
    # Create a list to hold minion objects for the async version
    minions = []
    
    for i in range(num_to_spawn_final):
        minion_def = actual_minion_definitions[i]
        minion_id = minion_def.get("id")
        personality = minion_def.get("personality")
        
        # Resolve user_facing_name as in the original...
        
        if not minion_id or not personality:
            spawner_log(f"Skipping minion definition due to missing 'id' or 'personality': {minion_def}", level="WARNING")
            continue
        
        spawner_log(f"Creating Minion {minion_id} (Name: {user_facing_name}) with personality: {personality}...")
        
        # Set environment variables
        minion_env = os.environ.copy()
        minion_env["BASE_PROJECT_DIR"] = PROJECT_ROOT
        minion_env["PYTHONUNBUFFERED"] = "1"
        
        # Update PYTHONPATH
        a2a_python_path = os.path.join(PROJECT_ROOT, "a2a_framework", "samples", "python")
        current_pythonpath = minion_env.get("PYTHONPATH", "")
        if current_pythonpath:
            minion_env["PYTHONPATH"] = f"{a2a_python_path}{os.pathsep}{current_pythonpath}"
        else:
            minion_env["PYTHONPATH"] = a2a_python_path
        
        # For the asyncio version, we'll create and store minion objects
        # that we'll run in the main process using asyncio
        try:
            minion = AsyncMinion(
                minion_id=minion_id,
                user_facing_name=user_facing_name,
                personality_traits_str=personality,
                a2a_server_url_override=a2a_server_url_arg
            )
            minions.append(minion)
            spawned_minion_ids.append(minion_id)
            spawner_log(f"Created Minion {minion_id} object successfully")
        except Exception as e:
            spawner_log(f"Failed to create Minion {minion_id} object: {e}", level="ERROR")
    
    return minions, spawned_minion_ids

async def run_minions(minions):
    """Run multiple minions concurrently using asyncio."""
    spawner_log(f"Starting {len(minions)} minions using asyncio...")
    
    # Create tasks for each minion
    tasks = [minion.run() for minion in minions]
    
    # Wait for all minions to complete (or until interrupted)
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        spawner_log("Minion tasks cancelled", level="WARNING")
    except Exception as e:
        spawner_log(f"Error running minions: {e}", level="ERROR")
    
    spawner_log("All minions have stopped")

if __name__ == "__main__":
    # Parse arguments as in the original...
    
    spawner_log("Minion Spawner Initializing...")
    # Log initialization details...
    
    minions, active_ids = spawn_minions(args.count, a2a_server_url_to_use)
    
    if not minions:
        spawner_log("No Minion objects were created. Exiting.", level="ERROR")
        sys.exit(1)
    
    spawner_log(f"Created minions: {', '.join(active_ids)}. Starting async execution...")
    
    try:
        # Run the asyncio event loop
        asyncio.run(run_minions(minions))
    except KeyboardInterrupt:
        spawner_log("Spawner received KeyboardInterrupt. Shutting down...", level="INFO")
    finally:
        spawner_log("Minion Spawner shut down.")
```

### 2. Implement Collaborative Task Solving

**Issue:** Minions don't effectively collaborate on complex tasks.

**Implementation Steps:**

1. Create a task decomposition system:

```python
# In minion_core/task_decomposer.py
import json
from typing import List, Dict, Any, Optional
import uuid

class TaskDecomposer:
    """Decomposes complex tasks into subtasks that can be distributed among minions."""
    
    def __init__(self, llm_interface, logger=None):
        self.llm = llm_interface
        self.logger = logger
    
    async def decompose_task(self, task_description: str, available_minions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Decompose a complex task into subtasks assigned to specific minions.
        
        Args:
            task_description: The original task to decompose
            available_minions: List of minion info including ID, capabilities, etc.
            
        Returns:
            Dictionary with task plan, subtasks, and assignments
        """
        # Create a prompt for the LLM to decompose the task
        prompt = self._create_decomposition_prompt(task_description, available_minions)
        
        # Get decomposition from LLM
        try:
            response = self.llm.send_prompt(prompt)
            
            # Parse the response to extract the task decomposition
            decomposition = self._parse_decomposition_response(response)
            
            if not decomposition:
                if self.logger:
                    self.logger.error("Failed to parse task decomposition response")
                return self._create_fallback_decomposition(task_description, available_minions)
            
            return decomposition
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error decomposing task: {e}", exc_info=True)
            return self._create_fallback_decomposition(task_description, available_minions)
    
    def _create_decomposition_prompt(self, task_description: str, available_minions: List[Dict[str, Any]]) -> str:
        """Create a prompt for the LLM to decompose the task."""
        minion_descriptions = []
        for minion in available_minions:
            # Format each minion's info for the prompt
            skills = ", ".join([skill.get("name", "Unknown") for skill in minion.get("skills", [])])
            minion_descriptions.append(
                f"Minion ID: {minion.get('id')}\n"
                f"Name: {minion.get('name')}\n"
                f"Skills: {skills}\n"
            )
        
        minions_info = "\n".join(minion_descriptions)
        
        prompt = (
            f"You are an AI task planning system. You need to decompose a complex task into subtasks "
            f"that can be distributed among multiple AI minions.\n\n"
            f"TASK TO DECOMPOSE:\n{task_description}\n\n"
            f"AVAILABLE MINIONS:\n{minions_info}\n\n"
            f"Please decompose this task into 2-5 logical subtasks. For each subtask:\n"
            f"1. Provide a clear, detailed description\n"
            f"2. Assign it to the most appropriate minion based on their skills\n"
            f"3. Specify any dependencies between subtasks (which must complete before others)\n"
            f"4. Define clear success criteria\n\n"
            f"Format your response as a JSON object with this structure:\n"
            f"```json\n"
            f"{{\n"
            f'  "plan_summary": "Brief description of the overall approach",\n'
            f'  "subtasks": [\n'
            f'    {{\n'
            f'      "id": "subtask-1",\n'
            f'      "description": "Detailed description of the subtask",\n'
            f'      "assigned_to": "minion-id",\n'
            f'      "dependencies": [],\n'
            f'      "success_criteria": "Clear measures for completion"\n'
            f'    }},\n'
            f'    ...\n'
            f'  ]\n'
            f"}}\n```\n"
            f"Ensure your response contains only the JSON, not any additional text."
        )
        
        return prompt
    
    def _parse_decomposition_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse the LLM response to extract the task decomposition."""
        try:
            # Extract JSON from response (might be wrapped in ```json ... ```)
            json_text = response
            if "```json" in response:
                json_text = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_text = response.split("```")[1].split("```")[0]
            
            # Parse JSON
            decomposition = json.loads(json_text)
            
            # Validate required fields
            if "plan_summary" not in decomposition or "subtasks" not in decomposition:
                if self.logger:
                    self.logger.warning("Decomposition missing required fields")
                return None
            
            # Ensure subtasks have required fields
            for i, subtask in enumerate(decomposition["subtasks"]):
                if "description" not in subtask:
                    if self.logger:
                        self.logger.warning(f"Subtask {i} missing description")
                    return None
                
                # Ensure subtask has ID
                if "id" not in subtask:
                    subtask["id"] = f"subtask-{uuid.uuid4().hex[:8]}"
                
                # Ensure dependencies is a list
                if "dependencies" not in subtask:
                    subtask["dependencies"] = []
            
            return decomposition
            
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(f"Failed to parse JSON from response: {e}", exc_info=True)
            return None
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error parsing decomposition: {e}", exc_info=True)
            return None
    
    def _create_fallback_decomposition(self, task_description: str, available_minions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a simple fallback decomposition when LLM fails."""
        # Simple approach: assign the whole task to the first available minion
        if not available_minions:
            # No minions available!
            return {
                "plan_summary": "Unable to decompose task due to lack of available minions",
                "subtasks": []
            }
        
        return {
            "plan_summary": "Simple fallback plan: assign the entire task to one minion",
            "subtasks": [
                {
                    "id": f"subtask-{uuid.uuid4().hex[:8]}",
                    "description": task_description,
                    "assigned_to": available_minions[0]["id"],
                    "dependencies": [],
                    "success_criteria": "Complete the entire task"
                }
            ]
        }
```

2. Create a collaborative task coordinator:

```python
# In minion_core/task_coordinator.py
import asyncio
import time
from enum import Enum
from typing import Dict, List, Any, Optional, Set
import uuid

class SubtaskStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class CollaborativeTask:
    """Represents a collaborative task that involves multiple minions."""
    
    def __init__(self, task_id: str, description: str, requester_id: str, 
                decomposition: Dict[str, Any], logger=None):
        self.task_id = task_id
        self.description = description
        self.requester_id = requester_id
        self.decomposition = decomposition
        self.logger = logger
        
        self.start_time = time.time()
        self.end_time = None
        self.status = "in_progress"
        
        # Initialize subtasks
        self.subtasks = {}
        for subtask in decomposition.get("subtasks", []):
            self.subtasks[subtask["id"]] = {
                "description": subtask["description"],
                "assigned_to": subtask["assigned_to"],
                "dependencies": subtask["dependencies"],
                "success_criteria": subtask.get("success_criteria", ""),
                "status": SubtaskStatus.PENDING,
                "result": None,
                "error": None,
                "start_time": None,
                "end_time": None
            }
    
    def get_next_subtasks(self) -> List[Dict[str, Any]]:
        """Get the next subtasks that can be executed based on dependencies."""
        next_subtasks = []
        
        for subtask_id, subtask in self.subtasks.items():
            # Skip subtasks that are not pending
            if subtask["status"] != SubtaskStatus.PENDING:
                continue
            
            # Check if all dependencies are completed
            dependencies_met = True
            for dep_id in subtask["dependencies"]:
                if dep_id not in self.subtasks:
                    # Unknown dependency, log and skip
                    if self.logger:
                        self.logger.warning(f"Subtask {subtask_id} has unknown dependency {dep_id}")
                    dependencies_met = False
                    break
                
                dep_status = self.subtasks[dep_id]["status"]
                if dep_status != SubtaskStatus.COMPLETED:
                    dependencies_met = False
                    break
            
            if dependencies_met:
                next_subtasks.append({
                    "id": subtask_id,
                    "description": subtask["description"],
                    "assigned_to": subtask["assigned_to"],
                    "success_criteria": subtask["success_criteria"]
                })
        
        return next_subtasks
    
    def update_subtask(self, subtask_id: str, status: SubtaskStatus, 
                      result: Optional[Any] = None, error: Optional[str] = None) -> bool:
        """Update the status of a subtask."""
        if subtask_id not in self.subtasks:
            if self.logger:
                self.logger.warning(f"Attempted to update unknown subtask {subtask_id}")
            return False
        
        subtask = self.subtasks[subtask_id]
        subtask["status"] = status
        
        if status == SubtaskStatus.IN_PROGRESS:
            subtask["start_time"] = time.time()
        elif status in [SubtaskStatus.COMPLETED, SubtaskStatus.FAILED]:
            subtask["end_time"] = time.time()
            
            if status == SubtaskStatus.COMPLETED:
                subtask["result"] = result
            else:
                subtask["error"] = error
        
        # Check if all subtasks are completed or failed
        all_done = True
        for st in self.subtasks.values():
            if st["status"] not in [SubtaskStatus.COMPLETED, SubtaskStatus.FAILED]:
                all_done = False
                break
        
        if all_done:
            self.status = "completed"
            self.end_time = time.time()
        
        return True
    
    def get_results(self) -> Dict[str, Any]:
        """Get the results of all completed subtasks."""
        results = {}
        for subtask_id, subtask in self.subtasks.items():
            if subtask["status"] == SubtaskStatus.COMPLETED:
                results[subtask_id] = subtask["result"]
        
        return results
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the collaborative task."""
        pending_count = 0
        assigned_count = 0
        in_progress_count = 0
        completed_count = 0
        failed_count = 0
        
        for subtask in self.subtasks.values():
            if subtask["status"] == SubtaskStatus.PENDING:
                pending_count += 1
            elif subtask["status"] == SubtaskStatus.ASSIGNED:
                assigned_count += 1
            elif subtask["status"] == SubtaskStatus.IN_PROGRESS:
                in_progress_count += 1
            elif subtask["status"] == SubtaskStatus.COMPLETED:
                completed_count += 1
            elif subtask["status"] == SubtaskStatus.FAILED:
                failed_count += 1
        
        return {
            "task_id": self.task_id,
            "status": self.status,
            "total_subtasks": len(self.subtasks),
            "subtask_status": {
                "pending": pending_count,
                "assigned": assigned_count,
                "in_progress": in_progress_count,
                "completed": completed_count,
                "failed": failed_count
            },
            "elapsed_time": time.time() - self.start_time
        }

class TaskCoordinator:
    """Coordinates collaborative tasks among multiple minions."""
    
    def __init__(self, a2a_client, task_decomposer, logger=None):
        self.a2a_client = a2a_client
        self.task_decomposer = task_decomposer
        self.logger = logger
        
        self.tasks = {}  # task_id -> CollaborativeTask
        self.minion_registry = {}  # minion_id -> minion_info
    
    def register_minion(self, minion_id: str, minion_info: Dict[str, Any]):
        """Register a minion with the coordinator."""
        self.minion_registry[minion_id] = minion_info
        if self.logger:
            self.logger.info(f"Registered minion {minion_id}")
    
    def unregister_minion(self, minion_id: str):
        """Unregister a minion from the coordinator."""
        if minion_id in self.minion_registry:
            del self.minion_registry[minion_id]
            if self.logger:
                self.logger.info(f"Unregistered minion {minion_id}")
    
    async def create_collaborative_task(self, task_description: str, requester_id: str) -> str:
        """Create a new collaborative task."""
        # Generate task ID
        task_id = f"collab-{uuid.uuid4().hex[:8]}"
        
        if self.logger:
            self.logger.info(f"Creating collaborative task {task_id} for {requester_id}")
        
        # Get minion registry for decomposition
        available_minions = list(self.minion_registry.values())
        
        # Decompose task
        decomposition = await self.task_decomposer.decompose_task(
            task_description, 
            available_minions
        )
        
        # Create collaborative task
        task = CollaborativeTask(
            task_id=task_id,
            description=task_description,
            requester_id=requester_id,
            decomposition=decomposition,
            logger=self.logger
        )
        
        # Store task
        self.tasks[task_id] = task
        
        # Start processing
        asyncio.create_task(self._process_collaborative_task(task_id))
        
        return task_id
    
    async def update_subtask_status(self, task_id: str, subtask_id: str, 
                                  status: SubtaskStatus, result=None, error=None) -> bool:
        """Update the status of a subtask."""
        if task_id not in self.tasks:
            if self.logger:
                self.logger.warning(f"Attempted to update unknown task {task_id}")
            return False
        
        task = self.tasks[task_id]
        success = task.update_subtask(subtask_id, status, result, error)
        
        # If task is now completed, send summary to requester
        if task.status == "completed":
            await self._send_task_completion(task_id)
        
        # Process next subtasks if any become available
        if success and status == SubtaskStatus.COMPLETED:
            asyncio.create_task(self._process_collaborative_task(task_id))
        
        return success
    
    async def _process_collaborative_task(self, task_id: str):
        """Process a collaborative task by assigning and executing subtasks."""
        if task_id not in self.tasks:
            if self.logger:
                self.logger.warning(f"Attempted to process unknown task {task_id}")
            return
        
        task = self.tasks[task_id]
        
        # Get next subtasks to execute
        next_subtasks = task.get_next_subtasks()
        
        # No subtasks to execute
        if not next_subtasks:
            # Check if all subtasks are done
            if task.status == "completed":
                if self.logger:
                    self.logger.info(f"Task {task_id} completed")
            return
        
        # Assign and execute each subtask
        for subtask in next_subtasks:
            minion_id = subtask["assigned_to"]
            
            # Check if minion is available
            if minion_id not in self.minion_registry:
                if self.logger:
                    self.logger.warning(f"Minion {minion_id} not available for subtask {subtask['id']}")
                task.update_subtask(subtask["id"], SubtaskStatus.FAILED, 
                                   error="Assigned minion not available")
                continue
            
            # Mark subtask as assigned
            task.update_subtask(subtask["id"], SubtaskStatus.ASSIGNED)
            
            # Send subtask to minion
            if self.logger:
                self.logger.info(f"Assigning subtask {subtask['id']} to minion {minion_id}")
            
            message = {
                "collaborative_task_id": task_id,
                "subtask_id": subtask["id"],
                "description": subtask["description"],
                "success_criteria": subtask["success_criteria"],
                "original_task": task.description
            }
            
            try:
                await self.a2a_client.send_message(
                    recipient_agent_id=minion_id,
                    message_content=message,
                    message_type="collaborative_subtask_assignment"
                )
                
                # Mark subtask as in progress
                task.update_subtask(subtask["id"], SubtaskStatus.IN_PROGRESS)
                
                if self.logger:
                    self.logger.info(f"Subtask {subtask['id']} assigned to {minion_id}")
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to assign subtask {subtask['id']} to {minion_id}: {e}")
                task.update_subtask(subtask["id"], SubtaskStatus.FAILED, 
                                   error=f"Failed to assign: {str(e)}")
    
    async def _send_task_completion(self, task_id: str):
        """Send task completion notification to the requester."""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        
        # Compile results
        results = task.get_results()
        
        # Create summary
        summary = {
            "task_id": task_id,
            "description": task.description,
            "status": task.status,
            "subtask_count": len(task.subtasks),
            "subtasks_completed": sum(1 for s in task.subtasks.values() 
                                     if s["status"] == SubtaskStatus.COMPLETED),
            "subtasks_failed": sum(1 for s in task.subtasks.values() 
                                  if s["status"] == SubtaskStatus.FAILED),
            "elapsed_seconds": task.end_time - task.start_time if task.end_time else None,
            "results": results
        }
        
        # Send to requester
        try:
            await self.a2a_client.send_message(
                recipient_agent_id=task.requester_id,
                message_content=summary,
                message_type="collaborative_task_completed"
            )
            if self.logger:
                self.logger.info(f"Sent completion for task {task_id} to {task.requester_id}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to send completion for task {task_id}: {e}")
```

3. Integrate Collaborative Task Handling in AsyncMinion class:

```python
# Add imports
from minion_core.task_decomposer import TaskDecomposer
from minion_core.task_coordinator import TaskCoordinator, SubtaskStatus

# In AsyncMinion.__init__
def __init__(self, ...):
    # Existing initialization code...
    
    # Initialize task decomposer and coordinator (will be fully initialized in run())
    self.task_decomposer = None
    self.task_coordinator = None
    self.collaborative_subtasks = {}  # subtask_id -> task info

# In AsyncMinion.initialize_components
async def initialize_components(self):
    # Existing component initialization...
    
    # Initialize task decomposer and coordinator
    self.task_decomposer = TaskDecomposer(self.llm, logger=self.logger)
    self.task_coordinator = TaskCoordinator(
        a2a_client=self.a2a_client,
        task_decomposer=self.task_decomposer,
        logger=self.logger
    )
    
    # Register this minion with the coordinator
    minion_info = {
        "id": self.minion_id,
        "name": self.user_facing_name,
        "personality": self.personality_traits,
        "skills": []  # TODO: Populate with actual skills
    }
    self.task_coordinator.register_minion(self.minion_id, minion_info)

# In AsyncMinion.handle_a2a_message
async def handle_a2a_message(self, message_data):
    # Existing message handling...
    
    # Handle collaborative task messages
    if message_type == "collaborative_subtask_assignment":
        await self._handle_collaborative_subtask(content)
    elif message_type == "collaborative_subtask_result":
        await self._handle_collaborative_subtask_result(content)
    elif message_type == "collaborative_task_request":
        await self._handle_collaborative_task_request(content, sender_id)

# Add collaborative task handlers
async def _handle_collaborative_task_request(self, content, requester_id):
    """Handle a request to start a collaborative task."""
    if self.current_status == MinionStatus.PAUSED:
        self.logger.info("Received collaborative task request while paused. Storing.")
        # Store for later...
        return
    
    task_description = content.get("task_description")
    if not task_description:
        self.logger.warning("Collaborative task request missing description")
        return
    
    self.logger.info(f"Received collaborative task request: {task_description[:100]}...")
    
    # Create collaborative task
    task_id = await self.task_coordinator.create_collaborative_task(
        task_description=task_description,
        requester_id=requester_id
    )
    
    # Notify requester that we've started the task
    await self.a2a_client.send_message(
        recipient_agent_id=requester_id,
        message_content={
            "task_id": task_id,
            "status": "started",
            "coordinator_id": self.minion_id
        },
        message_type="collaborative_task_acknowledgement"
    )

async def _handle_collaborative_subtask(self, content):
    """Handle an assignment for a collaborative subtask."""
    if self.current_status == MinionStatus.PAUSED:
        self.logger.info("Received collaborative subtask while paused. Storing.")
        # Store for later...
        return
    
    task_id = content.get("collaborative_task_id")
    subtask_id = content.get("subtask_id")
    description = content.get("description")
    
    if not all([task_id, subtask_id, description]):
        self.logger.warning("Collaborative subtask missing required fields")
        return
    
    self.logger.info(f"Received collaborative subtask {subtask_id} for task {task_id}")
    
    # Store subtask info
    self.collaborative_subtasks[subtask_id] = content
    
    # Add to task queue with high priority
    self.task_queue.add_task(
        description=f"COLLABORATIVE SUBTASK: {description}",
        sender_id="collaborative_coordinator",
        priority=TaskPriority.HIGH,
        metadata={
            "type": "collaborative_subtask",
            "task_id": task_id,
            "subtask_id": subtask_id
        }
    )
    
    # Start processing task queue
    asyncio.create_task(self._process_task_queue())

async def _handle_collaborative_subtask_result(self, content):
    """Handle a result from a collaborative subtask."""
    task_id = content.get("collaborative_task_id")
    subtask_id = content.get("subtask_id")
    status = content.get("status")
    result = content.get("result")
    error = content.get("error")
    
    if not all([task_id, subtask_id, status]):
        self.logger.warning("Collaborative subtask result missing required fields")
        return
    
    self.logger.info(f"Received result for collaborative subtask {subtask_id} with status {status}")
    
    # Update subtask status in coordinator
    try:
        subtask_status = SubtaskStatus(status)
        await self.task_coordinator.update_subtask_status(
            task_id=task_id,
            subtask_id=subtask_id,
            status=subtask_status,
            result=result,
            error=error
        )
    except ValueError:
        self.logger.warning(f"Invalid subtask status: {status}")
    except Exception as e:
        self.logger.error(f"Error updating subtask status: {e}")

# Update task execution to handle collaborative subtasks
async def _execute_task(self, task):
    """Execute a task from the queue."""
    try:
        # Check if this is a collaborative subtask
        metadata = task.metadata or {}
        if metadata.get("type") == "collaborative_subtask":
            await self._execute_collaborative_subtask(task)
        else:
            # Regular task execution...
            pass
    except Exception as e:
        # Error handling...
        pass

async def _execute_collaborative_subtask(self, task):
    """Execute a collaborative subtask."""
    task_id = task.metadata.get("task_id")
    subtask_id = task.metadata.get("subtask_id")
    
    if not (task_id and subtask_id):
        self.logger.error("Missing task_id or subtask_id in collaborative subtask")
        self.task_queue.fail_current_task("Missing metadata")
        return
    
    # Get subtask details
    subtask_info = self.collaborative_subtasks.get(subtask_id)
    if not subtask_info:
        self.logger.error(f"Could not find subtask {subtask_id} details")
        self.task_queue.fail_current_task("Missing subtask info")
        return
    
    self.logger.info(f"Executing collaborative subtask {subtask_id}")
    
    # Start metrics timer
    timer_id = self.metrics.start_timer("collaborative_subtask_time")
    
    try:
        # Create prompt for subtask
        prompt = (
            f"You are executing a subtask as part of a collaborative task.\n\n"
            f"ORIGINAL TASK: {subtask_info.get('original_task', 'Unknown')}\n\n"
            f"YOUR SUBTASK: {subtask_info.get('description')}\n\n"
            f"SUCCESS CRITERIA: {subtask_info.get('success_criteria', 'Complete the subtask successfully')}\n\n"
            f"Provide a thorough, detailed response that fully addresses this subtask."
        )
        
        # Send to LLM
        response = self.llm.send_prompt(prompt)
        
        # Stop metrics timer
        self.metrics.stop_timer(timer_id)
        self.metrics.inc_counter("collaborative_subtasks_processed")
        
        # Update subtask status
        await self.a2a_client.send_message(
            recipient_agent_id=self.task_coordinator.minion_id,
            message_content={
                "collaborative_task_id": task_id,
                "subtask_id": subtask_id,
                "status": "completed",
                "result": response
            },
            message_type="collaborative_subtask_result"
        )
        
        # Mark task as completed
        self.task_queue.complete_current_task(result=response)
        
    except Exception as e:
        self.logger.error(f"Error executing subtask {subtask_id}: {e}", exc_info=True)
        
        # Send failure to coordinator
        await self.a2a_client.send_message(
            recipient_agent_id=self.task_coordinator.minion_id,
            message_content={
                "collaborative_task_id": task_id,
                "subtask_id": subtask_id,
                "status": "failed",
                "error": str(e)
            },
            message_type="collaborative_subtask_result"
        )
        
        # Mark task as failed
        self.task_queue.fail_current_task(error=str(e))
```

### 3. Implement Adaptive Resource Management

**Issue:** The system doesn't adapt to resource constraints or load.

**Implementation Steps:**

1. Create a resource monitor:

```python
# In minion_core/utils/resource_monitor.py
import psutil
import time
import threading
import logging
from typing import Dict, Any, Optional, Callable

class ResourceMonitor:
    """Monitor system resources and implement adaptive constraints."""
    
    def __init__(self, check_interval: float = 5.0, logger=None):
        self.check_interval = check_interval
        self.logger = logger or logging.getLogger(__name__)
        
        self.last_check = {}
        self.thresholds = {
            "cpu_percent": 80.0,
            "memory_percent": 80.0,
            "disk_percent": 90.0
        }
        
        self.alert_callbacks = []
        self.monitor_thread = None
        self.should_stop = threading.Event()
    
    def start(self):
        """Start the resource monitoring thread."""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        
        self.should_stop.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.logger.info("Resource monitor started")
    
    def stop(self):
        """Stop the resource monitoring thread."""
        if not (self.monitor_thread and self.monitor_thread.is_alive()):
            return
        
        self.should_stop.set()
        self.monitor_thread.join(timeout=2 * self.check_interval)
        if self.monitor_thread.is_alive():
            self.logger.warning("Resource monitor thread did not stop cleanly")
        else:
            self.logger.info("Resource monitor stopped")
    
    def check_resources(self) -> Dict[str, Any]:
        """Check current resource usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            memory_info = psutil.virtual_memory()
            disk_info = psutil.disk_usage('/')
            
            resource_info = {
                "timestamp": time.time(),
                "cpu_percent": cpu_percent,
                "memory_total": memory_info.total,
                "memory_available": memory_info.available,
                "memory_percent": memory_info.percent,
                "disk_total": disk_info.total,
                "disk_free": disk_info.free,
                "disk_percent": disk_info.percent
            }
            
            self.last_check = resource_info
            return resource_info
        
        except Exception as e:
            self.logger.error(f"Error checking resources: {e}", exc_info=True)
            return {}
    
    def is_system_overloaded(self) -> bool:
        """Check if system is overloaded based on thresholds."""
        if not self.last_check:
            return False
        
        cpu_overloaded = self.last_check.get("cpu_percent", 0) > self.thresholds["cpu_percent"]
        memory_overloaded = self.last_check.get("memory_percent", 0) > self.thresholds["memory_percent"]
        disk_overloaded = self.last_check.get("disk_percent", 0) > self.thresholds["disk_percent"]
        
        return cpu_overloaded or memory_overloaded or disk_overloaded
    
    def add_alert_callback(self, callback: Callable[[Dict[str, Any], bool], None]):
        """Add a callback to be called when resource alerts occur."""
        self.alert_callbacks.append(callback)
    
    def set_threshold(self, resource: str, value: float):
        """Set threshold for a specific resource."""
        if resource in self.thresholds:
            self.thresholds[resource] = value
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while not self.should_stop.is_set():
            try:
                resources = self.check_resources()
                if not resources:
                    time.sleep(self.check_interval)
                    continue
                
                is_overloaded = self.is_system_overloaded()
                
                if is_overloaded:
                    self.logger.warning(f"System overloaded: CPU {resources.get('cpu_percent')}%, "
                                       f"Memory {resources.get('memory_percent')}%, "
                                       f"Disk {resources.get('disk_percent')}%")
                
                # Call alert callbacks
                for callback in self.alert_callbacks:
                    try:
                        callback(resources, is_overloaded)
                    except Exception as e:
                        self.logger.error(f"Error in resource alert callback: {e}", exc_info=True)
                
                time.sleep(self.check_interval)
            
            except Exception as e:
                self.logger.error(f"Error in resource monitor loop: {e}", exc_info=True)
                time.sleep(self.check_interval)
```

2. Integrate resource monitoring with the minion manager:

```python
# Add to spawn_legion.py

from minion_core.utils.resource_monitor import ResourceMonitor

def init_resource_monitor():
    """Initialize the resource monitor."""
    monitor = ResourceMonitor(check_interval=10.0)
    
    def alert_handler(resources, is_overloaded):
        if is_overloaded:
            spawner_log(f"ALERT: System resources critical: "
                        f"CPU {resources.get('cpu_percent')}%, "
                        f"Memory {resources.get('memory_percent')}%, "
                        f"Disk {resources.get('disk_percent')}%", 
                        level="WARNING")
    
    monitor.add_alert_callback(alert_handler)
    monitor.start()
    return monitor

if __name__ == "__main__":
    # Parse arguments and initialize...
    
    # Initialize resource monitor
    resource_monitor = init_resource_monitor()
    
    try:
        # Start minions...
        asyncio.run(run_minions(minions))
    except KeyboardInterrupt:
        spawner_log("Spawner received KeyboardInterrupt. Shutting down...", level="INFO")
    finally:
        # Stop resource monitor
        resource_monitor.stop()
        spawner_log("Minion Spawner shut down.")
```

3. Add adaptive behavior to AsyncMinion:

```python
# In AsyncMinion

def __init__(self, ...):
    # Existing initialization...
    
    # Adaptive behavior settings
    self.adaptive_settings = {
        "llm_token_limit_normal": 8000,  # Normal token limit
        "llm_token_limit_reduced": 4000,  # Reduced token limit when resources low
        "parallel_tasks_normal": 3,       # Max parallel tasks normally
        "parallel_tasks_reduced": 1,      # Max parallel tasks when resources low
        "is_resource_constrained": False, # Current resource state
        "last_resource_update": 0         # Last time resource state was updated
    }

# In initialize_components
async def initialize_components(self):
    # Existing initialization...
    
    # Register with resource monitor if available
    try:
        from minion_core.utils.resource_monitor import ResourceMonitor
        # Look for existing monitor in global space
        # This is a simple approach - in a real implementation, might use a message queue or API
        if 'global_resource_monitor' in globals():
            monitor = globals()['global_resource_monitor']
            monitor.add_alert_callback(self._handle_resource_alert)
            self.logger.info("Registered with global resource monitor")
    except ImportError:
        self.logger.info("ResourceMonitor not available, adaptive constraints disabled")
    except Exception as e:
        self.logger.error(f"Error registering with resource monitor: {e}", exc_info=True)

def _handle_resource_alert(self, resources, is_overloaded):
    """Handle resource alerts from the monitor."""
    # Update resource state
    old_state = self.adaptive_settings["is_resource_constrained"]
    self.adaptive_settings["is_resource_constrained"] = is_overloaded
    self.adaptive_settings["last_resource_update"] = time.time()
    
    # Log state change
    if old_state != is_overloaded:
        if is_overloaded:
            self.logger.warning("Entering resource-constrained mode")
            # Update metrics
            self.metrics.inc_counter("resource_constraint_events")
        else:
            self.logger.info("Exiting resource-constrained mode")
    
    # Update metrics
    self.metrics.set_gauge("is_resource_constrained", 1 if is_overloaded else 0)
    
    # Apply adaptive behavior immediately if needed
    if is_overloaded and self.current_status == MinionStatus.RUNNING:
        self.logger.info("System resources low, applying adaptive constraints")
        # Could implement additional adaptive behaviors here
        # Such as pausing non-critical tasks, etc.

# Update LLM prompt construction to adapt to resource constraints
def _construct_prompt_for_task(self, task_description):
    """Construct an LLM prompt for a task, adapting to resource constraints."""
    # Basic prompt construction...
    prompt = f"Task: {task_description}\n\nRespond with a detailed plan and solution."
    
    # Apply token limits based on resource constraints
    if self.adaptive_settings["is_resource_constrained"]:
        token_limit = self.adaptive_settings["llm_token_limit_reduced"]
        self.logger.info(f"Using reduced token limit: {token_limit}")
        
        # Simple approach: estimate tokens and truncate if needed
        # A better implementation would use a proper tokenizer
        estimated_tokens = len(prompt) // 4  # Rough estimate
        
        if estimated_tokens > token_limit:
            # Truncate prompt
            max_chars = token_limit * 4
            prompt = prompt[:max_chars] + "\n\n[Note: Prompt truncated due to system resource constraints]"
    else:
        token_limit = self.adaptive_settings["llm_token_limit_normal"]
    
    return prompt

# Update task queue processing to adapt to resource constraints
async def _process_task_queue(self):
    """Process tasks in the queue, respecting resource constraints."""
    if self.current_status in [MinionStatus.PAUSED, MinionStatus.PAUSING, MinionStatus.SHUTTING_DOWN]:
        return
    
    # Determine max parallel tasks based on resource state
    if self.adaptive_settings["is_resource_constrained"]:
        max_parallel = self.adaptive_settings["parallel_tasks_reduced"]
    else:
        max_parallel = self.adaptive_settings["parallel_tasks_normal"]
    
    # Count currently running tasks
    running_count = sum(1 for task in self.task_queue.running_tasks if task is not None)
    
    # Start additional tasks if below limit
    tasks_to_start = max(0, max_parallel - running_count)
    
    for _ in range(tasks_to_start):
        task = self.task_queue.start_next_task()
        if not task:
            break  # No more tasks to start
        
        # Start task processing
        self.current_status = MinionStatus.RUNNING
        await self._send_state_update(self.current_status, f"Processing: {task.description[:60]}...")
        
        # Start in a new task
        asyncio.create_task(self._execute_task(task))
```

## Implementation Sequence and Dependencies

To implement these changes effectively, the following sequence is recommended:

1. **Phase 1: Critical Fixes ()**
   - Fix MCP Bridge Integration first
   - Then standardize error handling
   - Then fix configuration system
   - Finally add health checks and improve A2A Client

2. **Phase 2: System Improvements ()**
   - Enhance state management first (dependency for other improvements)
   - Implement task queue and processing (builds on improved state management)
   - Add metrics collection (independent improvement)

3. **Phase 3: Advanced Features ()**
   - Implement asyncio-based processing first (foundation for other advanced features)
   - Then implement collaborative task solving (depends on asyncio implementation)
   - Finally add adaptive resource management (enhances the whole system)

## Testing Strategy

For each phase of implementation, the following testing approach is recommended:

1. **Unit Tests**
   - Write tests for individual components before integration
   - Test error handling specifically with edge cases
   - Verify component initialization with various configuration options

2. **Integration Tests**
   - Test interaction between components (e.g., MCP Bridge and Minion)
   - Test state serialization/deserialization
   - Verify message passing between components

3. **End-to-End Tests**
   - Test complete workflows from user input to minion execution
   - Verify collaborative task execution with multiple minions
   - Test system under resource constraints

## Rollout Strategy

To minimize disruption and ensure a smooth transition, the following rollout strategy is recommended:

1. **Local Development & Testing**
   - Implement and test changes in a development environment
   - Create automated tests for each component

2. **Staged Rollout**
   - Roll out Phase 1 fixes completely before proceeding
   - For each subsequent phase, implement one component at a time
   - Test thoroughly after each component is implemented

3. **Monitoring & Iteration**
   - Use the metrics collection system to monitor performance
   - Iterate based on real-world usage patterns
   - Adjust resource thresholds and constraints based on observed behavior
