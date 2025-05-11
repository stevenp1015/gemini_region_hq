# GEMINI_LEGION_HQ Implementation Plan

## Introduction

This implementation plan provides a systematic approach to addressing the issues identified in the GEMINI_LEGION_HQ codebase. The plan is organized into three phases, each focusing on specific aspects of the system, with concrete code changes and improvements prioritized based on criticality and dependencies.

## Phase 1: Critical Fixes and Stability ()

### 1. Fix MCP Bridge Integration

**Issue:** Parameter mismatch between `McpNodeBridge.__init__` and its usage in `Minion`.

**Implementation Steps:**

1. Update `mcp_node_bridge.py` to accept a logger parameter:

```python
# Current implementation
def __init__(self, service_base_url: str):
    if not service_base_url.startswith(("http://", "https://")):
        raise ValueError("service_base_url must start with http:// or https://")
    self.service_base_url = service_base_url.rstrip('/')
    logger.info(f"McpNodeBridge initialized with service base URL: {self.service_base_url}")

# Updated implementation
def __init__(self, base_url: str, logger=None):
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("base_url must start with http:// or https://")
    self.service_base_url = base_url.rstrip('/')
    self.logger = logger if logger else logging.getLogger(__name__)
    self.logger.info(f"McpNodeBridge initialized with service base URL: {self.service_base_url}")
```

2. Update all method implementations to use `self.logger` instead of the global `logger`

3. Add connectivity validation at initialization:

```python
def __init__(self, base_url: str, logger=None):
    # Existing code...
    
    # Add connectivity check
    try:
        response = requests.get(f"{self.service_base_url}/health", timeout=5)
        if response.status_code == 200:
            self.logger.info("Successfully connected to MCP Node service")
            self.is_available = True
        else:
            self.logger.warning(f"MCP Node service responded with status {response.status_code}")
            self.is_available = False
    except Exception as e:
        self.logger.error(f"Failed to connect to MCP Node service: {e}")
        self.is_available = False
```

### 2. Standardize Error Handling

**Issue:** Inconsistent error models across components.

**Implementation Steps:**

1. Create a central error hierarchy in a new file `minion_core/utils/errors.py`:

```python
class MinionError(Exception):
    """Base class for all minion-related errors."""
    def __init__(self, message, code=None, details=None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)

class LLMError(MinionError):
    """Errors related to LLM operations."""
    pass

class ToolError(MinionError):
    """Errors related to tool operations."""
    pass

class A2AError(MinionError):
    """Errors related to A2A operations."""
    pass

class ConfigError(MinionError):
    """Errors related to configuration."""
    pass

# More specific error classes
class LLMAPIError(LLMError):
    """Errors from the LLM API."""
    pass

class LLMContentFilterError(LLMError):
    """Errors due to content filtering."""
    pass

class ToolExecutionError(ToolError):
    """Errors during tool execution."""
    pass

class ToolNotFoundError(ToolError):
    """Errors when a tool is not found."""
    pass

class A2AConnectionError(A2AError):
    """Errors connecting to A2A server."""
    pass

class A2AMessageDeliveryError(A2AError):
    """Errors delivering A2A messages."""
    pass
```

2. Update LLMInterface to use the new error classes:

```python
def send_prompt(self, prompt_text, conversation_history=None):
    # Existing code...
    
    try:
        response = self.model.generate_content(prompt_text)
        
        if not response.parts:
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                block_reason_message = response.prompt_feedback.block_reason_message or "No specific message."
                self.logger.error(f"Gemini API blocked response. Reason: {response.prompt_feedback.block_reason}. Message: {block_reason_message}")
                # Use new error class instead of string
                raise LLMContentFilterError(
                    f"Content filtered: {block_reason_message}",
                    code=response.prompt_feedback.block_reason,
                    details={"prompt": prompt_text[:100] + "..."}
                )
            else:
                self.logger.error("Gemini API returned an empty response with no parts and no clear block reason.")
                raise LLMError("Empty response from LLM")
        
        # Rest of the method...
    
    except LLMError:
        # Re-raise LLMError instances
        raise
    except Exception as e:
        # Wrap other exceptions
        raise LLMAPIError(f"API error: {str(e)}", details={"original_error": str(e)})
```

3. Update Minion.process_task to handle new error types:

```python
def process_task(self, task_description: str, original_sender_id: str):
    # Existing code...
    
    try:
        # Construct the full prompt for the LLM
        full_prompt = self._construct_prompt_from_history_and_task(task_description)
        
        # Send to LLM
        llm_response_text = self.llm.send_prompt(full_prompt)
        
        # Process response...
    
    except LLMContentFilterError as e:
        self.logger.error(f"Content filter error: {e.message}")
        self.current_status = MinionStatus.ERROR
        error_message = f"I cannot process this task due to content policy restrictions: {e.code}"
        self._send_state_update(self.current_status, error_message)
        self._send_error_response(original_sender_id, error_message)
        
    except LLMError as e:
        self.logger.error(f"LLM error: {e.message}")
        self.current_status = MinionStatus.ERROR
        error_message = "I encountered an error processing this task with my language model."
        self._send_state_update(self.current_status, error_message)
        self._send_error_response(original_sender_id, error_message)
    
    except Exception as e:
        self.logger.error(f"Unexpected error: {e}", exc_info=True)
        self.current_status = MinionStatus.ERROR
        error_message = "I encountered an unexpected error processing this task."
        self._send_state_update(self.current_status, error_message)
        self._send_error_response(original_sender_id, error_message)
    
    finally:
        # Cleanup
        self.is_idle = True
        self.current_task = None
        self.current_task_description = None
```

### 3. Fix Configuration System

**Issue:** Inconsistent use of configuration across components.

**Implementation Steps:**

1. Create a comprehensive default configuration file in `system_configs/default_config.toml`:

```toml
[global]
log_level = "INFO"
logs_dir = "logs"
project_name = "GEMINI_LEGION_HQ"

[minion_defaults]
default_personality = "Adaptable, Resourceful, Meticulous"
default_user_facing_name = "Minion"
log_level = "INFO"
a2a_client_polling_interval_seconds = 5.0
task_timeout_seconds = 300
guidelines_path = "system_configs/minion_guidelines.json"

[minion_spawner]
default_spawn_count = 3
minion_script_path = "minion_core/main_minion.py"
venv_python_path = "venv_legion/bin/python"
minions = [
  { id = "alpha", personality = "Analytical, Thorough, Detail-oriented" },
  { id = "bravo", personality = "Creative, Innovative, Adaptive" },
  { id = "charlie", personality = "Efficient, Practical, Solutions-focused" }
]

[minion_state]
storage_dir = "system_data/minion_states"
backup_enabled = true
backup_count = 3

[a2a_server]
host = "127.0.0.1"
port = 8080
log_level = "INFO"
storage_path = "system_data/a2a_storage.json"

[a2a_identities]
gui_commander_id = "STEVEN_GUI_COMMANDER"

[llm]
model_name = "gemini-2.5-pro-preview-05-06"
backup_model_name = "gemini-1.5-pro-latest"
gemini_api_key_env_var = "GEMINI_API_KEY_LEGION"
max_retries = 3
retry_delay_seconds = 5
timeout_seconds = 60

[mcp_integration]
enable_mcp_integration = true
mcp_node_service_base_url = "http://localhost:3000"
manage_mcp_node_service_lifecycle = true
mcp_node_service_startup_command = "node ./mcp_super_tool/src/index.js"
mcp_node_service_working_dir = "mcp_super_tool"

[m2m_communication]
default_retry_attempts = 3
default_timeout_seconds = 60
max_delegation_depth = 5
```

2. Update `config_manager.py` to load default configuration:

```python
def __init__(self):
    # Existing code...
    
    # Add default config path
    self.default_config_toml_path = os.path.join(self.project_root, "system_configs/default_config.toml")
    
    # Load defaults first, then user config
    self.config = {}
    self._load_default_config()
    self._load_config_toml() # This now merges with defaults instead of replacing
    self._load_dotenv()

def _load_default_config(self):
    try:
        if os.path.exists(self.default_config_toml_path):
            with open(self.default_config_toml_path, 'r', encoding='utf-8') as f:
                self.config = toml.load(f)
            config_manager_logger.info(f"Successfully loaded default configuration from: {self.default_config_toml_path}")
        else:
            config_manager_logger.warning(f"Default configuration file not found at: {self.default_config_toml_path}. Using empty defaults.")
            self.config = {}
    except Exception as e:
        config_manager_logger.error(f"Failed to load default configuration: {e}", exc_info=True)
        self.config = {}

def _load_config_toml(self):
    try:
        if os.path.exists(self.config_toml_path):
            with open(self.config_toml_path, 'r', encoding='utf-8') as f:
                user_config = toml.load(f)
                # Merge with defaults instead of replacing
                self._deep_merge(self.config, user_config)
            config_manager_logger.info(f"Successfully loaded and merged user configuration from: {self.config_toml_path}")
        else:
            config_manager_logger.warning(f"User configuration file not found at: {self.config_toml_path}. Using defaults only.")
    except Exception as e:
        config_manager_logger.error(f"Failed to load user configuration: {e}", exc_info=True)

def _deep_merge(self, base, override):
    """Recursively merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            self._deep_merge(base[key], value)
        else:
            base[key] = value
```

3. Update tool_manager.py to use config consistently:

```python
# Replace
BASE_DIR = os.getenv("BASE_PROJECT_DIR", "../..") # Adjust as needed
MCP_SUPER_TOOL_SCRIPT_PATH = os.path.join(BASE_DIR, "mcp_super_tool/src/main.js")
MCP_CONFIG_PATH_FOR_SUPER_TOOL = os.path.join(BASE_DIR, "system_configs/mcp_config.json")
SUPER_TOOL_ENV_PATH = os.path.join(BASE_DIR, "mcp_super_tool/.env")

# With
from system_configs.config_manager import config

# And later in __init__
self.mcp_super_tool_script_path = config.get_path("mcp_super_tool.script_path", "mcp_super_tool/src/main.js")
self.mcp_config_path = config.get_path("mcp_super_tool.config_path", "system_configs/mcp_config.json")
self.super_tool_env_path = config.get_path("mcp_super_tool.env_path", "mcp_super_tool/.env")
```

### 4. Add Health Checks

**Issue:** No systematic way to check component health.

**Implementation Steps:**

1. Create a base health check interface in `minion_core/utils/health.py`:

```python
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import time

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

@dataclass
class HealthCheckResult:
    component: str
    status: HealthStatus
    details: Optional[Dict[str, Any]] = None
    timestamp: float = time.time()
    
    def as_dict(self):
        return {
            "component": self.component,
            "status": self.status.value,
            "details": self.details or {},
            "timestamp": self.timestamp
        }

class HealthCheckable:
    """Interface for components that can report health status."""
    
    def check_health(self) -> HealthCheckResult:
        """Perform a health check and return the result."""
        raise NotImplementedError("Subclasses must implement check_health")
```

2. Implement health checks in each major component:

```python
# In McpNodeBridge
def check_health(self) -> HealthCheckResult:
    try:
        response = requests.get(f"{self.service_base_url}/health", timeout=5)
        if response.status_code == 200:
            return HealthCheckResult(
                component="McpNodeBridge",
                status=HealthStatus.HEALTHY,
                details={"url": self.service_base_url}
            )
        else:
            return HealthCheckResult(
                component="McpNodeBridge",
                status=HealthStatus.DEGRADED,
                details={
                    "url": self.service_base_url,
                    "status_code": response.status_code
                }
            )
    except Exception as e:
        return HealthCheckResult(
            component="McpNodeBridge",
            status=HealthStatus.UNHEALTHY,
            details={
                "url": self.service_base_url,
                "error": str(e)
            }
        )

# In LLMInterface
def check_health(self) -> HealthCheckResult:
    try:
        # Simple model query to check if API is working
        response = self.model.generate_content("Hello")
        if response and response.text:
            return HealthCheckResult(
                component="LLMInterface",
                status=HealthStatus.HEALTHY,
                details={"model": self.model.model_name}
            )
        else:
            return HealthCheckResult(
                component="LLMInterface",
                status=HealthStatus.DEGRADED,
                details={"model": self.model.model_name, "reason": "Empty response"}
            )
    except Exception as e:
        return HealthCheckResult(
            component="LLMInterface",
            status=HealthStatus.UNHEALTHY,
            details={"model": self.model.model_name, "error": str(e)}
        )

# In A2AClient
def check_health(self) -> HealthCheckResult:
    if not self.is_registered:
        return HealthCheckResult(
            component="A2AClient",
            status=HealthStatus.DEGRADED,
            details={
                "server_url": self.a2a_server_url,
                "reason": "Not registered with A2A server"
            }
        )
        
    try:
        # Check if server is responding
        response_obj = self._make_request('get', f"/agents/{self.minion_id}")
        if response_obj and response_obj.get("status_code") in [200, 204]:
            return HealthCheckResult(
                component="A2AClient",
                status=HealthStatus.HEALTHY,
                details={"server_url": self.a2a_server_url}
            )
        else:
            return HealthCheckResult(
                component="A2AClient",
                status=HealthStatus.DEGRADED,
                details={
                    "server_url": self.a2a_server_url,
                    "status_code": response_obj.get("status_code") if response_obj else None
                }
            )
    except Exception as e:
        return HealthCheckResult(
            component="A2AClient",
            status=HealthStatus.UNHEALTHY,
            details={"server_url": self.a2a_server_url, "error": str(e)}
        )
```

3. Add a health check endpoint to the Minion class:

```python
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
```

### 5. Improve A2A Client Message Handling

**Issue:** Inefficient polling and basic message handling.

**Implementation Steps:**

1. Update the A2A client's polling mechanism:

```python
def _message_listener_loop(self):
    """Polls the A2A server for new messages with adaptive polling."""
    last_poll_time = time.time() - 60
    last_message_time = time.time()
    
    # Adaptive polling - start with minimal interval but can extend when idle
    min_interval = self.polling_interval
    max_interval = min_interval * 6  # Up to 6x longer when idle
    current_interval = min_interval
    
    self.logger.info(f"A2A message listener started for {self.minion_id}")
    while not self.stop_listener_event.is_set():
        try:
            # Sleep first to prevent hammering the server on errors
            time.sleep(current_interval)
            
            # Attempt to get messages
            current_endpoint = f"/agents/{self.minion_id}/messages"
            response_obj = self._make_request('get', current_endpoint)
            
            if response_obj and response_obj.get("status_code") == 200 and isinstance(response_obj.get("data"), list):
                messages = response_obj["data"]
                
                if messages:
                    # Got messages, reset to minimum polling interval
                    current_interval = min_interval
                    last_message_time = time.time()
                    self.logger.info(f"Received {len(messages)} message(s)")
                    
                    # Process messages in priority order
                    sorted_messages = self._sort_messages_by_priority(messages)
                    for message in sorted_messages:
                        self._process_single_message(message)
                else:
                    # No messages, gradually increase polling interval up to max
                    idle_time = time.time() - last_message_time
                    if idle_time > 60:  # After 1 minute of no messages
                        current_interval = min(current_interval * 1.5, max_interval)
                        self.logger.debug(f"Increasing polling interval to {current_interval:.1f}s after {idle_time:.1f}s idle")
            else:
                # Error or unexpected response, log but don't change interval
                self.logger.warning(f"Unexpected response when polling: {response_obj}")
                
        except Exception as e:
            self.logger.error(f"Error in A2A message listener loop: {e}", exc_info=True)
            # Don't change interval here, we already sleep at the start of the loop
    
    self.logger.info(f"A2A message listener stopped for {self.minion_id}")

def _sort_messages_by_priority(self, messages):
    """Sort messages by priority based on message_type."""
    # Define priority order (lower number = higher priority)
    priority_order = {
        "control_pause_request": 1,
        "control_resume_request": 2,
        "m2m_task_status_update": 3,
        "m2m_negative_acknowledgement": 4,
        "user_broadcast_directive": 5,
        # Default priority for other types
        "default": 10
    }
    
    # Get priority for a message, defaulting to the "default" priority if type not found
    def get_priority(message):
        message_type = message.get("message_type", "unknown")
        return priority_order.get(message_type, priority_order["default"])
    
    # Sort messages by priority
    return sorted(messages, key=get_priority)

def _process_single_message(self, message_data):
    """Process a single message with proper error handling."""
    message_id = message_data.get('id', 'unknown')
    
    try:
        # Check for duplication
        if message_id in self.processed_message_ids:
            self.logger.info(f"Duplicate message ID {message_id} received. Skipping.")
            return
        
        self.processed_message_ids.add(message_id)
        
        # Cap the size of processed_message_ids to prevent unbounded growth
        if len(self.processed_message_ids) > 1000:
            # Keep the 500 most recent IDs
            self.processed_message_ids = set(list(self.processed_message_ids)[-500:])
        
        # Call the callback
        if self.message_callback:
            self.logger.debug(f"Calling message_callback with message ID {message_id}")
            self.message_callback(message_data)
        
    except Exception as e:
        self.logger.error(f"Error processing message ID {message_id}: {e}", exc_info=True)
```

## Phase 2: System Improvements ()

### 1. Enhance State Management

**Issue:** Limited state serialization and persistence.

**Implementation Steps:**

1. Create a more robust state model:

```python
# In minion_core/state_manager.py
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
import time
import json
import os
import logging

@dataclass
class TaskState:
    """State of a task being processed by a Minion."""
    task_id: str
    task_description: str
    start_time: float
    sender_id: str
    steps_completed: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, paused, completed, failed
    progress_percentage: float = 0.0
    result: Optional[str] = None
    error: Optional[str] = None

@dataclass
class MinionState:
    """Complete state of a Minion that can be serialized/deserialized."""
    minion_id: str
    version: str = "1.0"
    is_paused: bool = False
    current_task: Optional[TaskState] = None
    pending_messages: List[Dict[str, Any]] = field(default_factory=list)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to a dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MinionState':
        """Create a MinionState instance from a dictionary."""
        # Handle nested TaskState if present
        if data.get('current_task') and isinstance(data['current_task'], dict):
            data['current_task'] = TaskState(**data['current_task'])
        return cls(**data)

class StateManager:
    """Manages serialization, persistence, and loading of Minion state."""
    
    def __init__(self, minion_id: str, storage_dir: str, logger=None):
        self.minion_id = minion_id
        self.storage_dir = storage_dir
        self.logger = logger or logging.getLogger(f"StateManager_{minion_id}")
        self.state_file_path = os.path.join(storage_dir, f"minion_state_{minion_id}.json")
        self.backup_dir = os.path.join(storage_dir, "backups")
        
        # Ensure directories exist
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def save_state(self, state: MinionState) -> bool:
        """Serialize and save state to disk."""
        try:
            # Update timestamp
            state.last_updated = time.time()
            
            # First, create a backup of the existing state if it exists
            if os.path.exists(self.state_file_path):
                self._create_backup()
            
            # Write new state file
            with open(self.state_file_path, 'w') as f:
                json.dump(state.to_dict(), f, indent=2)
            
            self.logger.info(f"Saved state to {self.state_file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}", exc_info=True)
            return False
    
    def load_state(self) -> Optional[MinionState]:
        """Load state from disk."""
        try:
            if os.path.exists(self.state_file_path):
                with open(self.state_file_path, 'r') as f:
                    data = json.load(f)
                self.logger.info(f"Loaded state from {self.state_file_path}")
                return MinionState.from_dict(data)
            else:
                self.logger.info(f"No state file found at {self.state_file_path}")
                return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding state file: {e}", exc_info=True)
            # Try to load from most recent backup
            return self._load_from_backup()
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}", exc_info=True)
            return None
    
    def _create_backup(self):
        """Create a backup of the current state file."""
        try:
            timestamp = int(time.time())
            backup_path = os.path.join(self.backup_dir, f"minion_state_{self.minion_id}_{timestamp}.json")
            
            with open(self.state_file_path, 'r') as src:
                content = src.read()
                
            with open(backup_path, 'w') as dst:
                dst.write(content)
                
            self.logger.debug(f"Created state backup at {backup_path}")
            
            # Cleanup old backups (keep only the 5 most recent)
            self._cleanup_old_backups(5)
        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}", exc_info=True)
    
    def _cleanup_old_backups(self, keep_count):
        """Keep only the most recent `keep_count` backups."""
        try:
            backup_files = [f for f in os.listdir(self.backup_dir) 
                           if f.startswith(f"minion_state_{self.minion_id}_") and f.endswith(".json")]
            
            if len(backup_files) <= keep_count:
                return
            
            # Sort by timestamp (newest first)
            backup_files.sort(reverse=True)
            
            # Remove older files beyond keep_count
            for file_to_remove in backup_files[keep_count:]:
                os.remove(os.path.join(self.backup_dir, file_to_remove))
                self.logger.debug(f"Removed old backup: {file_to_remove}")
        except Exception as e:
            self.logger.error(f"Error cleaning up old backups: {e}", exc_info=True)
    
    def _load_from_backup(self) -> Optional[MinionState]:
        """Attempt to load state from most recent backup."""
        try:
            backup_files = [f for f in os.listdir(self.backup_dir) 
                           if f.startswith(f"minion_state_{self.minion_id}_") and f.endswith(".json")]
            
            if not backup_files:
                self.logger.warning("No backup files found")
                return None
            
            # Sort by timestamp (newest first)
            backup_files.sort(reverse=True)
            most_recent = backup_files[0]
            backup_path = os.path.join(self.backup_dir, most_recent)
            
            with open(backup_path, 'r') as f:
                data = json.load(f)
            
            self.logger.info(f"Loaded state from backup: {backup_path}")
            return MinionState.from_dict(data)
        except Exception as e:
            self.logger.error(f"Failed to load from backup: {e}", exc_info=True)
            return None
```

2. Update the Minion class to use the new StateManager:

```python
# In main_minion.py

# Import the new StateManager
from minion_core.state_manager import StateManager, MinionState, TaskState

def __init__(self, minion_id, user_facing_name=None, personality_traits_str=None, a2a_server_url_override=None):
    # Existing initialization code...
    
    # Initialize StateManager
    minion_state_storage_dir = config.get_path("minion_state.storage_dir", 
                                               os.path.join(PROJECT_ROOT, "system_data", "minion_states"))
    self.state_manager = StateManager(minion_id=self.minion_id, 
                                     storage_dir=minion_state_storage_dir,
                                     logger=self.logger)
    
    # Try to load existing state
    loaded_state = self.state_manager.load_state()
    if loaded_state:
        self.logger.info(f"Found existing state. Minion was previously: {'paused' if loaded_state.is_paused else 'active'}")
        self._restore_from_state(loaded_state)
    else:
        # Initialize with default state
        self.current_state = MinionState(minion_id=self.minion_id)
        self.is_paused = False
        self.pending_messages_while_paused = []
        self.current_task_description = None
        self.current_status = MinionStatus.IDLE

def _restore_from_state(self, state: MinionState):
    """Restore minion state from a loaded MinionState object."""
    self.current_state = state
    self.is_paused = state.is_paused
    
    # Restore current task if any
    if state.current_task:
        self.current_task_description = state.current_task.task_description
        self.current_task = state.current_task.task_id
        self.current_status = MinionStatus.PAUSED if self.is_paused else MinionStatus.RUNNING
    else:
        self.current_task_description = None
        self.current_task = None
        self.current_status = MinionStatus.PAUSED if self.is_paused else MinionStatus.IDLE
    
    # Restore pending messages
    self.pending_messages_while_paused = state.pending_messages
    
    # Restore conversation history if needed
    if state.conversation_history:
        self.conversation_history = state.conversation_history
    
    self.logger.info(f"Successfully restored state. Minion is now {self.current_status.value}.")

def _save_current_state(self):
    """Capture and save the current state."""
    self.current_state.is_paused = self.is_paused
    self.current_state.pending_messages = self.pending_messages_while_paused
    self.current_state.conversation_history = self.conversation_history
    
    # Update current task state if applicable
    if self.current_task_description:
        if not self.current_state.current_task:
            # Create a new TaskState if none exists
            self.current_state.current_task = TaskState(
                task_id=self.current_task or str(uuid.uuid4()),
                task_description=self.current_task_description,
                start_time=time.time(),
                sender_id="unknown"  # Will be overwritten if we know it
            )
        
        # Update task status
        self.current_state.current_task.status = "paused" if self.is_paused else "running"
    else:
        self.current_state.current_task = None
    
    # Save to disk
    success = self.state_manager.save_state(self.current_state)
    if success:
        self.logger.info("Successfully saved current state")
    else:
        self.logger.error("Failed to save current state")
```

3. Update the pause/resume methods to use the new state management:

```python
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
    self._save_current_state()
    
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

    self.is_paused = False
    
    # Process pending messages
    if self.pending_messages_while_paused:
        self.logger.info(f"Processing {len(self.pending_messages_while_paused)} messages received while paused.")
        for msg in self.pending_messages_while_paused:
            self._process_stored_message(msg)
        
        self.pending_messages_while_paused = []
        self.logger.info("Cleared pending messages queue.")

    # Determine new status based on current task
    if self.current_task_description:
        self.current_status = MinionStatus.RUNNING
        self.logger.info(f"Resuming with task: {self.current_task_description}")
        
        # If we have a current task, update its status
        if self.current_state.current_task:
            self.current_state.current_task.status = "running"
    else:
        self.current_status = MinionStatus.IDLE
        self.logger.info("Resumed to idle state as no task was active.")
    
    # Save the resumed state
    self._save_current_state()
    
    self._send_state_update(self.current_status, "Minion successfully resumed.")
```

### 2. Implement Task Queue and Processing

**Issue:** Simplistic task processing without proper queueing.

**Implementation Steps:**

1. Create a TaskQueue class:

```python
# In minion_core/task_queue.py
import time
import uuid
from typing import Dict, List, Any, Optional, Callable
from threading import Lock
from dataclasses import dataclass, field
from enum import Enum

class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

@dataclass
class Task:
    id: str
    description: str
    sender_id: str
    created_at: float
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class TaskQueue:
    """A priority-based task queue with task management capabilities."""
    
    def __init__(self, logger=None):
        self.queue = []  # List of pending tasks
        self.running_task = None  # Currently running task
        self.completed_tasks = []  # History of completed tasks
        self.lock = Lock()  # For thread safety
        self.logger = logger
        self.task_listeners = []  # Callbacks for task status changes
    
    def add_task(self, description: str, sender_id: str, priority: TaskPriority = TaskPriority.NORMAL, 
                metadata: Dict[str, Any] = None) -> str:
        """Add a task to the queue and return its ID."""
        task_id = str(uuid.uuid4())
        
        task = Task(
            id=task_id,
            description=description,
            sender_id=sender_id,
            created_at=time.time(),
            priority=priority,
            status=TaskStatus.PENDING,
            metadata=metadata or {}
        )
        
        with self.lock:
            # Insert based on priority (higher priority tasks come first)
            idx = 0
            while idx < len(self.queue) and self.queue[idx].priority.value >= priority.value:
                idx += 1
            self.queue.insert(idx, task)
        
        if self.logger:
            self.logger.info(f"Added task '{task_id}' to queue with priority {priority.name}")
        
        self._notify_listeners("task_added", task)
        return task_id
    
    def get_next_task(self) -> Optional[Task]:
        """Get the next task from the queue without removing it."""
        with self.lock:
            return self.queue[0] if self.queue else None
    
    def start_next_task(self) -> Optional[Task]:
        """Remove the next task from the queue and mark it as running."""
        with self.lock:
            if not self.queue:
                return None
            
            if self.running_task:
                if self.logger:
                    self.logger.warning(f"Cannot start next task, task '{self.running_task.id}' is already running")
                return None
            
            self.running_task = self.queue.pop(0)
            self.running_task.status = TaskStatus.RUNNING
            self.running_task.started_at = time.time()
        
        if self.logger:
            self.logger.info(f"Started task '{self.running_task.id}'")
        
        self._notify_listeners("task_started", self.running_task)
        return self.running_task
    
    def complete_current_task(self, result: Any = None) -> Optional[Task]:
        """Mark the current task as completed and move it to history."""
        with self.lock:
            if not self.running_task:
                if self.logger:
                    self.logger.warning("No running task to complete")
                return None
            
            self.running_task.status = TaskStatus.COMPLETED
            self.running_task.completed_at = time.time()
            self.running_task.result = result
            
            completed_task = self.running_task
            self.completed_tasks.append(completed_task)
            self.running_task = None
        
        if self.logger:
            self.logger.info(f"Completed task '{completed_task.id}'")
        
        self._notify_listeners("task_completed", completed_task)
        return completed_task
    
    def fail_current_task(self, error: str) -> Optional[Task]:
        """Mark the current task as failed and move it to history."""
        with self.lock:
            if not self.running_task:
                if self.logger:
                    self.logger.warning("No running task to fail")
                return None
            
            self.running_task.status = TaskStatus.FAILED
            self.running_task.completed_at = time.time()
            self.running_task.error = error
            
            failed_task = self.running_task
            self.completed_tasks.append(failed_task)
            self.running_task = None
        
        if self.logger:
            self.logger.info(f"Failed task '{failed_task.id}': {error}")
        
        self._notify_listeners("task_failed", failed_task)
        return failed_task
    
    def pause_current_task(self) -> Optional[Task]:
        """Pause the current task and return it to the queue."""
        with self.lock:
            if not self.running_task:
                if self.logger:
                    self.logger.warning("No running task to pause")
                return None
            
            self.running_task.status = TaskStatus.PAUSED
            
            # Re-add to queue based on priority
            paused_task = self.running_task
            self.queue.insert(0, paused_task)  # Insert at front to resume ASAP
            self.running_task = None
        
        if self.logger:
            self.logger.info(f"Paused task '{paused_task.id}'")
        
        self._notify_listeners("task_paused", paused_task)
        return paused_task
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task or the currently running task."""
        with self.lock:
            # Check if it's the running task
            if self.running_task and self.running_task.id == task_id:
                self.running_task.status = TaskStatus.CANCELED
                self.running_task.completed_at = time.time()
                
                canceled_task = self.running_task
                self.completed_tasks.append(canceled_task)
                self.running_task = None
                
                if self.logger:
                    self.logger.info(f"Canceled running task '{task_id}'")
                
                self._notify_listeners("task_canceled", canceled_task)
                return True
            
            # Check if it's in the queue
            for i, task in enumerate(self.queue):
                if task.id == task_id:
                    task.status = TaskStatus.CANCELED
                    task.completed_at = time.time()
                    
                    canceled_task = self.queue.pop(i)
                    self.completed_tasks.append(canceled_task)
                    
                    if self.logger:
                        self.logger.info(f"Canceled queued task '{task_id}'")
                    
                    self._notify_listeners("task_canceled", canceled_task)
                    return True
        
        if self.logger:
            self.logger.warning(f"Task '{task_id}' not found for cancellation")
        return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID from either the queue, running task, or history."""
        with self.lock:
            # Check running task
            if self.running_task and self.running_task.id == task_id:
                return self.running_task
            
            # Check queue
            for task in self.queue:
                if task.id == task_id:
                    return task
            
            # Check completed tasks
            for task in self.completed_tasks:
                if task.id == task_id:
                    return task
        
        return None
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get the current status of the task queue."""
        with self.lock:
            return {
                "queue_length": len(self.queue),
                "has_running_task": self.running_task is not None,
                "running_task_id": self.running_task.id if self.running_task else None,
                "completed_tasks": len(self.completed_tasks),
                "pending_by_priority": {
                    priority.name: sum(1 for task in self.queue if task.priority == priority)
                    for priority in TaskPriority
                }
            }
    
    def add_task_listener(self, callback: Callable[[str, Task], None]):
        """Add a listener for task status changes."""
        self.task_listeners.append(callback)
    
    def _notify_listeners(self, event_type: str, task: Task):
        """Notify all listeners of a task status change."""
        for listener in self.task_listeners:
            try:
                listener(event_type, task)
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error in task listener: {e}", exc_info=True)
```

2. Integrate the TaskQueue into the Minion class:

```python
# In main_minion.py

# Import TaskQueue
from minion_core.task_queue import TaskQueue, Task, TaskPriority, TaskStatus

def __init__(self, minion_id, user_facing_name=None, personality_traits_str=None, a2a_server_url_override=None):
    # Existing initialization code...
    
    # Initialize TaskQueue
    self.task_queue = TaskQueue(logger=self.logger)
    self.task_queue.add_task_listener(self._handle_task_status_change)
    
    # Rest of initialization...

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

def handle_a2a_message(self, message_data):
    # Existing code...
    
    # Update for user_broadcast_directive
    elif message_type == "user_broadcast_directive" and content:
        if self.is_paused:
            self.logger.info(f"Received broadcast directive but Minion is paused. Queuing message.")
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
    
    # Rest of the method...

def _process_next_task(self):
    """Process the next task in the queue."""
    if self.is_paused:
        self.logger.info("Cannot process next task: Minion is paused")
        return
    
    task = self.task_queue.start_next_task()
    if not task:
        self.logger.info("No tasks in queue to process")
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
    try:
        self.logger.info(f"Executing task: {task.description[:100]}...")
        
        # Construct the full prompt for the LLM
        full_prompt = self._construct_prompt_from_history_and_task(task.description)
        
        # Send to LLM
        llm_response_text = self.llm.send_prompt(full_prompt)
        
        if llm_response_text.startswith("ERROR_"):
            self.logger.error(f"LLM processing failed: {llm_response_text}")
            self.task_queue.fail_current_task(f"LLM error: {llm_response_text}")
            return
        
        # Send response back to the original sender
        try:
            self.a2a_client.send_message(
                recipient_agent_id=task.sender_id,
                message_content=llm_response_text,
                message_type="directive_reply"
            )
            self.logger.info(f"Sent reply to {task.sender_id}")
        except Exception as e:
            self.logger.error(f"Failed to send reply: {e}", exc_info=True)
            # Continue anyway, as we processed the task
        
        # Mark task as completed
        self.task_queue.complete_current_task(result=llm_response_text)
        
        # Process next task if available
        self._process_next_task()
    
    except Exception as e:
        self.logger.error(f"Error executing task: {e}", exc_info=True)
        self.task_queue.fail_current_task(f"Execution error: {str(e)}")
        
        # Process next task if available
        self._process_next_task()
```

### 3. Implement Metrics Collection

**Issue:** No systematic metrics collection for monitoring.

**Implementation Steps:**

1. Create a metrics collector:

```python
# In minion_core/utils/metrics.py
import time
from typing import Dict, List, Any, Optional, Callable
from threading import Lock
import json
import os
from datetime import datetime

class MetricsCollector:
    """Collects and manages metrics for the Minion system."""
    
    def __init__(self, component_name: str, storage_dir: Optional[str] = None, logger=None):
        self.component_name = component_name
        self.storage_dir = storage_dir
        self.logger = logger
        self.lock = Lock()
        
        self.start_time = time.time()
        self.metrics = {
            "counters": {},     # Incrementing counters (e.g., tasks_processed)
            "gauges": {},       # Current values (e.g., queue_length)
            "histograms": {},   # Value distributions (e.g., response_time_ms)
            "timers": {}        # Active timers (start_time, label)
        }
        
        # Initialize storage
        if self.storage_dir:
            os.makedirs(self.storage_dir, exist_ok=True)
            self.metrics_file = os.path.join(self.storage_dir, f"{component_name}_metrics.json")
        else:
            self.metrics_file = None
    
    def inc_counter(self, name: str, value: int = 1, labels: Dict[str, str] = None):
        """Increment a counter metric."""
        with self.lock:
            key = self._get_key(name, labels)
            if key not in self.metrics["counters"]:
                self.metrics["counters"][key] = 0
            self.metrics["counters"][key] += value
    
    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Set a gauge metric to a specific value."""
        with self.lock:
            key = self._get_key(name, labels)
            self.metrics["gauges"][key] = value
    
    def observe(self, name: str, value: float, labels: Dict[str, str] = None):
        """Add an observation to a histogram metric."""
        with self.lock:
            key = self._get_key(name, labels)
            if key not in self.metrics["histograms"]:
                self.metrics["histograms"][key] = []
            self.metrics["histograms"][key].append(value)
            
            # Limit the number of observations to prevent memory issues
            if len(self.metrics["histograms"][key]) > 1000:
                self.metrics["histograms"][key] = self.metrics["histograms"][key][-1000:]
    
    def start_timer(self, name: str, labels: Dict[str, str] = None) -> str:
        """Start a timer and return a timer ID."""
        timer_id = f"{time.time()}_{name}_{hash(str(labels))}"
        with self.lock:
            self.metrics["timers"][timer_id] = {
                "name": name,
                "labels": labels,
                "start_time": time.time()
            }
        return timer_id
    
    def stop_timer(self, timer_id: str) -> Optional[float]:
        """Stop a timer and record its duration in the histogram."""
        with self.lock:
            if timer_id not in self.metrics["timers"]:
                if self.logger:
                    self.logger.warning(f"Timer '{timer_id}' not found")
                return None
            
            timer = self.metrics["timers"].pop(timer_id)
            duration = time.time() - timer["start_time"]
            
            # Record in histogram
            self.observe(timer["name"], duration, timer["labels"])
            return duration
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get the current metrics as a dictionary."""
        with self.lock:
            # Calculate histogram statistics
            histogram_stats = {}
            for key, values in self.metrics["histograms"].items():
                if not values:
                    continue
                    
                sorted_values = sorted(values)
                n = len(sorted_values)
                histogram_stats[key] = {
                    "count": n,
                    "min": min(values),
                    "max": max(values),
                    "mean": sum(values) / n,
                    "median": sorted_values[n // 2],
                    "p90": sorted_values[int(n * 0.9)],
                    "p95": sorted_values[int(n * 0.95)],
                    "p99": sorted_values[int(n * 0.99)] if n >= 100 else None
                }
            
            return {
                "component": self.component_name,
                "timestamp": time.time(),
                "uptime_seconds": time.time() - self.start_time,
                "counters": dict(self.metrics["counters"]),
                "gauges": dict(self.metrics["gauges"]),
                "histograms": histogram_stats
            }
    
    def save_metrics(self) -> bool:
        """Save metrics to disk if storage_dir is set."""
        if not self.metrics_file:
            return False
            
        try:
            metrics = self.get_metrics()
            with open(self.metrics_file, 'w') as f:
                json.dump(metrics, f, indent=2)
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to save metrics: {e}", exc_info=True)
            return False
    
    def _get_key(self, name: str, labels: Dict[str, str] = None) -> str:
        """Generate a key for a metric including its labels."""
        if not labels:
            return name
        
        # Sort labels by key for consistent keys
        sorted_labels = sorted(labels.items())
        labels_str = ",".join(f"{k}={v}" for k, v in sorted_labels)
        return f"{name}{{{labels_str}}}"
```

2. Integrate metrics collection throughout the Minion:

```python
# In main_minion.py

# Import MetricsCollector
from minion_core.utils.metrics import MetricsCollector

def __init__(self, minion_id, user_facing_name=None, personality_traits_str=None, a2a_server_url_override=None):
    # Existing initialization code...
    
    # Initialize metrics collector
    metrics_dir = config.get_path("metrics.storage_dir", os.path.join(PROJECT_ROOT, "system_data", "metrics"))
    self.metrics = MetricsCollector(
        component_name=f"Minion_{self.minion_id}",
        storage_dir=metrics_dir,
        logger=self.logger
    )
    
    # Schedule periodic metrics save
    self._start_metrics_save_thread()
    
    # Rest of initialization...

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
    metrics_thread.start()

def _update_and_save_metrics(self):
    """Update and save current metrics."""
    # Update gauge metrics
    self.metrics.set_gauge("is_paused", 1 if self.is_paused else 0)
    self.metrics.set_gauge("queue_length", len(self.task_queue.queue))
    self.metrics.set_gauge("has_running_task", 1 if self.task_queue.running_task else 0)
    
    # Save metrics
    self.metrics.save_metrics()

def process_task(self, task_description: str, original_sender_id: str):
    # Start timer for task processing
    timer_id = self.metrics.start_timer("task_processing_time", {
        "sender_id": original_sender_id[:10]  # Truncate long IDs
    })
    
    # Existing code...
    
    # After task processing
    self.metrics.stop_timer(timer_id)
    self.metrics.inc_counter("tasks_processed")
    
    # Rest of the method...

def handle_a2a_message(self, message_data):
    # Track message receipt
    self.metrics.inc_counter("a2a_messages_received", labels={
        "type": message_data.get("message_type", "unknown")
    })
    
    # Existing code...

def send_message(self, recipient_agent_id, message_content, message_type="generic_text"):
    # Track message sending
    timer_id = self.metrics.start_timer("a2a_message_send_time", {
        "type": message_type
    })
    
    # Send message...
    
    # After sending
    self.metrics.stop_timer(timer_id)
    self.metrics.inc_counter("a2a_messages_sent", labels={
        "type": message_type
    })
```

3. Add metrics to LLMInterface:

```python
# In llm_interface.py

# Import MetricsCollector
from minion_core.utils.metrics import MetricsCollector

def __init__(self, minion_id, api_key=None, logger=None):
    # Existing initialization...
    
    # Initialize metrics
    metrics_dir = config.get_path("metrics.storage_dir", os.path.join(PROJECT_ROOT, "system_data", "metrics"))
    self.metrics = MetricsCollector(
        component_name=f"LLM_{minion_id}",
        storage_dir=metrics_dir,
        logger=self.logger
    )

def send_prompt(self, prompt_text, conversation_history=None):
    # Start timer
    timer_id = self.metrics.start_timer("llm_request_time")
    token_count = self._estimate_token_count(prompt_text)
    self.metrics.observe("prompt_token_count", token_count)
    
    # Existing code...
    
    try:
        # Make API call...
        
        # On success
        self.metrics.inc_counter("llm_requests_success")
        response_token_count = self._estimate_token_count(response_text)
        self.metrics.observe("response_token_count", response_token_count)
    except Exception as e:
        # On error
        self.metrics.inc_counter("llm_requests_error", labels={
            "error_type": type(e).__name__
        })
        raise
    finally:
        # Always stop timer
        self.metrics.stop_timer(timer_id)
    
    # Rest of the method...

def _estimate_token_count(self, text):
    """Estimate token count using a simple heuristic."""
    # Simple approximation: 4 chars per token
    return len(text) // 4
```

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

By following this systematic approach, the GEMINI_LEGION_HQ codebase can be incrementally improved while maintaining functionality and minimizing disruption.