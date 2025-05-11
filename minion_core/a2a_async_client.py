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
        self.logger = logger or logging.getLogger(f"AsyncA2AClient_{self.minion_id}")
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