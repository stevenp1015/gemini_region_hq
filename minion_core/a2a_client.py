import json
import os
import sys # Added for sys.path manipulation
import requests
import time
import threading
import logging
from .utils.logger import setup_logger
from minion_core.utils.health import HealthStatus, HealthCheckResult, HealthCheckable

# Ensure the project root is in sys.path to find system_configs.config_manager
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

from system_configs.config_manager import config # Import the global config instance

# Define LOGS_DIR using ConfigManager
LOGS_DIR_FOR_A2A_CLIENT = config.get_path("global.logs_dir", os.path.join(config.get_project_root(), "logs"))


class A2AClient(HealthCheckable):
    def __init__(self, minion_id, a2a_server_url, agent_card_data, logger=None, message_callback=None):
        self.minion_id = minion_id
        
        # Logger setup must happen before it's used.
        log_file_name = f"a2a_client_{self.minion_id}.log"
        # Use LOGS_DIR_FOR_A2A_CLIENT defined above
        self.log_file_path = os.path.join(LOGS_DIR_FOR_A2A_CLIENT, log_file_name)
        
        if logger:
            self.logger = logger
        else:
            logger_name = f"A2AClient_{self.minion_id}"
            self.logger = setup_logger(logger_name, self.log_file_path, level=logging.DEBUG)
        
        self.logger.debug(f"Initializing for minion_id: {self.minion_id}")
        self.logger.debug(f"Attempting to set up logger for {self.minion_id} with log file: {self.log_file_path}")
        self.logger.info("A2AClient logger initialized successfully (now at DEBUG level).")
        self.logger.debug(f"Logger for {self.minion_id} set up with DEBUG level.")

        self.a2a_server_url = a2a_server_url.rstrip('/')
        self.agent_card = agent_card_data # Should include id, name, description, capabilities
        self.message_callback = message_callback # Function to call when a message is received
        self.is_registered = False
        self.listener_thread = None
        self.stop_listener_event = threading.Event()
        self.processed_message_ids = set() # For client-side message de-duplication

        # Configure polling interval using ConfigManager
        default_polling_interval = 5.0  # Default to 5.0 seconds (float)
        polling_interval_from_config = config.get_float(
            "minion_defaults.a2a_client_polling_interval_seconds",
            default_polling_interval
        )
        
        if polling_interval_from_config is not None and polling_interval_from_config > 0:
            self.polling_interval = polling_interval_from_config
        else:
            self.logger.warning(
                f"Invalid or non-positive polling interval from config ('{polling_interval_from_config}'). "
                f"Using default: {default_polling_interval}s."
            )
            self.polling_interval = default_polling_interval
            
        self.logger.info(f"A2AClient for {self.minion_id} using polling interval: {self.polling_interval} seconds.")

        # BIAS_CHECK: Ensure agent card is sufficiently detailed for discovery by other Minions.
        if not all(k in self.agent_card for k in ["id", "name", "description"]):
            self.logger.error("Agent card is missing required fields (id, name, description).")
            # raise ValueError("Agent card incomplete.") # Might be too strict for V1

    def _make_request(self, method, endpoint, payload=None, params=None):
        url = f"{self.a2a_server_url}/{endpoint.lstrip('/')}"
        self.logger.debug(f"A2A Request: {method.upper()} {url} Payload: {payload} Params: {params}")
        try:
            if method.lower() == 'get':
                response = requests.get(url, params=params, timeout=10)
            elif method.lower() == 'post':
                response = requests.post(url, json=payload, params=params, timeout=10)
            else:
                self.logger.error(f"Unsupported HTTP method: {method}")
                return None
            
            response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
            
            # BIAS_ACTION: Handle empty response body gracefully, common for POSTs or if server returns 204
            if response.status_code == 204 or not response.content:
                self.logger.debug(f"A2A Response: {response.status_code} (No Content)")
                return {"status_code": response.status_code, "data": None} # Return status for no-content success

            # Try to parse JSON, but gracefully handle if it's not JSON
            try:
                data = response.json()
                self.logger.debug(f"A2A Response: {response.status_code} Data: {str(data)[:200]}...")
                return {"status_code": response.status_code, "data": data}
            except json.JSONDecodeError:
                self.logger.warning(f"A2A Response for {url} was not valid JSON. Status: {response.status_code}. Raw: {response.text[:200]}...")
                return {"status_code": response.status_code, "data": response.text}


        except requests.exceptions.RequestException as e:
            self.logger.error(f"A2A request to {url} failed: {e}")
            return None # Or raise a custom A2AError

    def register_agent(self):
        """Registers the agent with the A2A server using its agent card."""
        # Codex Omega Note: The A2A spec and sample server will define the exact endpoint.
        # Assuming a POST to /agents or /register
        # The Google A2A sample server (samples/python/common/server/server.py) uses POST /agents
        endpoint = "/agents" 
        payload = self.agent_card
        
        self.logger.info(f"Attempting to register agent {self.minion_id} with A2A server...")
        response_obj = self._make_request('post', endpoint, payload=payload)
        
        # Check if response_obj is not None before trying to access its keys
        if response_obj:
            status_code = response_obj.get("status_code")
            response_data = response_obj.get("data")

            if status_code == 201 and response_data and 'id' in response_data:
                server_assigned_id = response_data['id']
                if self.minion_id != server_assigned_id:
                    self.logger.info(f"Agent ID mismatch: Initial ID was '{self.minion_id}', server assigned '{server_assigned_id}'. Updating to server-assigned ID.")
                    self.minion_id = server_assigned_id # CRUCIAL UPDATE
                else:
                    self.logger.info(f"Server confirmed agent ID: '{self.minion_id}'")
                self.logger.info(f"Agent '{self.minion_id}' registered successfully with A2A server (201 Created).")
                self.is_registered = True
                if self.message_callback:
                    self.start_message_listener()
                return True
            elif status_code == 200 and response_data and 'id' in response_data: # Handle if server returns 200 for already registered
                server_assigned_id = response_data['id']
                if self.minion_id != server_assigned_id:
                     self.logger.warning(f"Agent was already registered. Initial ID '{self.minion_id}', server has '{server_assigned_id}'. Updating to server-assigned ID.")
                     self.minion_id = server_assigned_id # CRUCIAL UPDATE
                else:
                    self.logger.info(f"Agent '{self.minion_id}' was already registered (confirmed by server with 200 OK).")
                self.is_registered = True
                if self.message_callback:
                    self.start_message_listener()
                return True
            # Handle 204 No Content separately as it won't have response_data['id']
            elif status_code == 204:
                self.logger.info(f"Agent {self.minion_id} registration acknowledged with 204 No Content. Assuming ID '{self.minion_id}' is accepted.")
                self.is_registered = True
                if self.message_callback:
                    self.start_message_listener()
                return True
            else:
                self.logger.error(f"Failed to register agent '{self.minion_id}'. Status: {status_code}, Response: {str(response_data)[:500]}")
                self.is_registered = False
                return False
        else: # This handles the case where _make_request returned None (e.g., network error)
            self.logger.error(f"Agent {self.minion_id} registration failed. No response from server (_make_request returned None).")
            self.is_registered = False
            return False

    def send_message(self, recipient_agent_id, message_content, message_type="generic_text"):
        """Sends a message to another agent via the A2A server."""
        self.logger.debug(f"send_message called. Recipient: '{recipient_agent_id}', Type: '{message_type}', Content: '{message_content[:100]}...'") # Log snippet of content
        if not self.is_registered:
            self.logger.warning("Agent not registered. Cannot send message. Attempting registration first.")
            if not self.register_agent():
                self.logger.error("Failed to register, cannot send message.")
                return False

        # Codex Omega Note: Endpoint and payload structure depend on A2A server implementation.
        # Google A2A sample uses POST /agents/{agent_id}/messages
        # Payload might be like: { "sender_id": self.minion_id, "content": message_content, "message_type": message_type }
        self.logger.debug(f"send_message: Preparing payload. self.minion_id (sender): '{self.minion_id}'")
        endpoint = f"/agents/{recipient_agent_id}/messages"
        payload = {
            "sender_id": self.minion_id,
            "content": message_content, # This could be a JSON string for structured messages
            "message_type": message_type,
            "timestamp": time.time()
        }
        self.logger.debug(f"send_message: Attempting to POST to endpoint: '{endpoint}' with payload: {payload}")
        self.logger.info(f"Sending message from {self.minion_id} to {recipient_agent_id} of type {message_type}.")
        self.logger.debug(f"Message payload: {payload}")
        
        response_obj = self._make_request('post', endpoint, payload=payload)
        
        if response_obj:
            self.logger.debug(f"send_message: _make_request response. Status: {response_obj.get('status_code')}, Data: {str(response_obj.get('data'))[:200]}")
            if response_obj.get("status_code") in [200, 201, 202, 204]: # 202 Accepted
                self.logger.info(f"Message to {recipient_agent_id} sent successfully.")
                return True
            else:
                self.logger.error(f"Failed to send message to {recipient_agent_id}. Status: {response_obj.get('status_code')}, Response: {str(response_obj.get('data'))[:500]}")
                return False
        else: # _make_request returned None
            self.logger.error(f"Failed to send message to {recipient_agent_id}. No response from server (_make_request returned None).")
            return False

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
                self.logger.info(f"Duplicate message ID {message_id} received for {self.minion_id}. Skipping.")
                return

            self.processed_message_ids.add(message_id)

            # Cap the size of processed_message_ids to prevent unbounded growth
            if len(self.processed_message_ids) > 1000:
                # Keep the 500 most recent IDs
                self.processed_message_ids = set(list(self.processed_message_ids)[-500:])

            # Call the callback
            if self.message_callback:
                self.logger.debug(f"Calling message_callback for {self.minion_id} with message ID {message_id}: {str(message_data)[:100]}")
                self.message_callback(message_data)

        except Exception as e:
            self.logger.error(f"Error processing message ID {message_id} for {self.minion_id}: {e}", exc_info=True)

    def _message_listener_loop(self):
        """Polls the A2A server for new messages with adaptive polling."""
        last_message_time = time.time()

        # Adaptive polling - start with minimal interval but can extend when idle
        min_interval = self.polling_interval
        max_interval = min_interval * 6  # Up to 6x longer when idle
        current_interval = min_interval

        self.logger.info(f"A2A message listener started for {self.minion_id} with adaptive polling: min_interval={min_interval}s, max_interval={max_interval}s.")
        while not self.stop_listener_event.is_set():
            try:
                # Sleep first to prevent hammering the server on errors
                self.logger.debug(f"Message listener ({self.minion_id}) sleeping for {current_interval:.1f}s.")
                time.sleep(current_interval)

                # Attempt to get messages
                self.logger.debug(f"Polling for messages for {self.minion_id}. Current interval: {current_interval:.1f}s")
                current_endpoint = f"/agents/{self.minion_id}/messages"
                response_obj = self._make_request('get', current_endpoint)

                if response_obj and response_obj.get("status_code") == 200 and isinstance(response_obj.get("data"), list):
                    messages = response_obj["data"]

                    if messages:
                        # Got messages, reset to minimum polling interval
                        self.logger.info(f"Received {len(messages)} message(s) for {self.minion_id}. Resetting poll interval to {min_interval}s.")
                        current_interval = min_interval
                        last_message_time = time.time()
                        
                        # Process messages in priority order
                        sorted_messages = self._sort_messages_by_priority(messages)
                        for message_data in sorted_messages:
                            self._process_single_message(message_data)
                    else:
                        # No messages, gradually increase polling interval up to max
                        idle_time = time.time() - last_message_time
                        if idle_time > 60: # After 1 minute of no messages
                            new_interval = min(current_interval * 1.5, max_interval)
                            if new_interval > current_interval:
                                current_interval = new_interval
                                self.logger.debug(f"No messages for {self.minion_id}. Increasing polling interval to {current_interval:.1f}s after {idle_time:.1f}s idle.")
                            else:
                                self.logger.debug(f"No messages for {self.minion_id}. Polling interval remains at max {current_interval:.1f}s after {idle_time:.1f}s idle.")
                        else:
                            self.logger.debug(f"No messages for {self.minion_id}. Current interval {current_interval:.1f}s. Idle time {idle_time:.1f}s < 60s.")
                elif response_obj: # response_obj exists but status is not 200 or data is not list
                    self.logger.warning(f"Unexpected response when polling messages for {self.minion_id}. Status: {response_obj.get('status_code')}, Data: {str(response_obj.get('data'))[:200]}. Interval unchanged.")
                else: # _make_request returned None
                    self.logger.warning(f"No response from server when polling messages for {self.minion_id} (_make_request returned None). Interval unchanged.")
            except Exception as e:
                self.logger.error(f"Error in A2A message listener loop for {self.minion_id}: {e}", exc_info=True)
                # Don't change interval here, we already sleep at the start of the loop
        
        self.logger.info(f"A2A message listener stopped for {self.minion_id}.")

    def start_message_listener(self):
        self.logger.info("start_message_listener called.")
        self.logger.debug(f"start_message_listener called for {self.minion_id}") # Changed from print
        if not self.message_callback:
            self.logger.warning("No message_callback provided, A2A message listener will not start.")
            return
        if self.listener_thread and self.listener_thread.is_alive():
            self.logger.info("A2A message listener already running.")
            return

        self.stop_listener_event.clear()
        self.listener_thread = threading.Thread(target=self._message_listener_loop, daemon=True)
        self.listener_thread.start()

    def stop_message_listener(self):
        self.logger.info(f"Attempting to stop A2A message listener for {self.minion_id}...")
        self.stop_listener_event.set()
        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=10) # Wait for thread to finish
            if self.listener_thread.is_alive():
                self.logger.warning("A2A message listener thread did not stop in time.")
        self.is_registered = False # Assume re-registration needed if listener stops

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

# BIAS_CHECK: This A2A client is basic. Real-world use would need more robust error handling,
# message sequencing, acknowledgements, and potentially a more efficient transport than polling.
# For V1 of the Minion Army, this provides foundational A2A send/receive.
