import json
import requests # For direct HTTP calls if using a simple A2A server
import time
import threading # For a simple polling listener
from .utils.logger import setup_logger

# These would come from a config file or Minion's main settings
# A2A_SERVER_BASE_URL = "http://127.0.0.1:8080" # Example

class A2AClient:
    def __init__(self, minion_id, a2a_server_url, agent_card_data, logger=None, message_callback=None):
        self.minion_id = minion_id
        self.logger = logger if logger else setup_logger(f"A2AClient_{minion_id}", f"a2a_client_{minion_id}.log")
        self.a2a_server_url = a2a_server_url.rstrip('/')
        self.agent_card = agent_card_data # Should include id, name, description, capabilities
        self.message_callback = message_callback # Function to call when a message is received
        self.is_registered = False
        self.listener_thread = None
        self.stop_listener_event = threading.Event()

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
        
        if response_obj and response_obj["status_code"] in [200, 201, 204]: # 201 Created, 200 OK, 204 No Content
            self.is_registered = True
            self.logger.info(f"Agent {self.minion_id} registered successfully with A2A server.")
            # Start listening for messages after successful registration if callback is provided
            if self.message_callback:
                self.start_message_listener()
            return True
        else:
            self.logger.error(f"Agent {self.minion_id} registration failed. Response: {response_obj}")
            self.is_registered = False
            return False

    def send_message(self, recipient_agent_id, message_content, message_type="generic_text"):
        """Sends a message to another agent via the A2A server."""
        if not self.is_registered:
            self.logger.warning("Agent not registered. Cannot send message. Attempting registration first.")
            if not self.register_agent():
                self.logger.error("Failed to register, cannot send message.")
                return False

        # Codex Omega Note: Endpoint and payload structure depend on A2A server implementation.
        # Google A2A sample uses POST /agents/{agent_id}/messages
        # Payload might be like: { "sender_id": self.minion_id, "content": message_content, "message_type": message_type }
        endpoint = f"/agents/{recipient_agent_id}/messages"
        payload = {
            "sender_id": self.minion_id,
            "content": message_content, # This could be a JSON string for structured messages
            "message_type": message_type,
            "timestamp": time.time()
        }
        self.logger.info(f"Sending message from {self.minion_id} to {recipient_agent_id} of type {message_type}.")
        self.logger.debug(f"Message payload: {payload}")
        
        response_obj = self._make_request('post', endpoint, payload=payload)
        
        if response_obj and response_obj["status_code"] in [200, 201, 202, 204]: # 202 Accepted
            self.logger.info(f"Message to {recipient_agent_id} sent successfully.")
            return True
        else:
            self.logger.error(f"Failed to send message to {recipient_agent_id}. Response: {response_obj}")
            return False

    def _message_listener_loop(self):
        """Polls the A2A server for new messages."""
        # Codex Omega Note: This is a simple polling mechanism.
        # A more robust solution might use WebSockets or Server-Sent Events if the A2A server supports it.
        # The Google A2A sample server has a GET /agents/{agent_id}/messages endpoint.
        endpoint = f"/agents/{self.minion_id}/messages"
        last_poll_time = time.time() - 60 # Poll for last minute of messages initially
        
        self.logger.info(f"A2A message listener started for {self.minion_id}.")
        while not self.stop_listener_event.is_set():
            try:
                # BIAS_ACTION: Add a small delay to polling to avoid spamming the server.
                time.sleep(5) # Poll every 5 seconds - configurable
                
                # Poll for messages since last poll time, or use server-side filtering if available
                # For simplicity, fetching all messages and filtering client-side if needed,
                # but this is inefficient for many messages.
                # A better server would support ?since=<timestamp>
                self.logger.debug(f"Polling for messages for {self.minion_id}...")
                response_obj = self._make_request('get', endpoint)

                if response_obj and response_obj["status_code"] == 200 and isinstance(response_obj["data"], list):
                    messages = response_obj["data"]
                    if messages:
                        self.logger.info(f"Received {len(messages)} new message(s) for {self.minion_id}.")
                    for msg in messages:
                        # Assuming message has a 'timestamp' field to avoid reprocessing
                        # And a 'content' field. Structure depends on A2A server.
                        # This basic poller might re-fetch old messages if not careful.
                        # A real implementation needs robust message handling (e.g., IDs, ack).
                        # For now, just pass all fetched messages to callback.
                        self.logger.debug(f"Raw message received: {msg}")
                        if self.message_callback:
                            try:
                                self.message_callback(msg) # Pass the raw message object
                            except Exception as e_cb:
                                self.logger.error(f"Error in A2A message_callback: {e_cb}")
                        # TODO: Implement message deletion or marking as read on the server if supported
                        # e.g., self._make_request('delete', f"{endpoint}/{msg['id']}")
                    # Update last_poll_time if server doesn't support 'since'
                    # last_poll_time = time.time() 
                elif response_obj:
                    self.logger.warning(f"Unexpected response when polling messages: {response_obj}")

            except Exception as e:
                self.logger.error(f"Error in A2A message listener loop: {e}")
                # BIAS_ACTION: Don't let listener die on transient errors.
                time.sleep(15) # Longer sleep on error
        self.logger.info(f"A2A message listener stopped for {self.minion_id}.")

    def start_message_listener(self):
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

# BIAS_CHECK: This A2A client is basic. Real-world use would need more robust error handling,
# message sequencing, acknowledgements, and potentially a more efficient transport than polling.
# For V1 of the Minion Army, this provides foundational A2A send/receive.
