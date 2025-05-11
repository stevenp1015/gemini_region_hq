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
