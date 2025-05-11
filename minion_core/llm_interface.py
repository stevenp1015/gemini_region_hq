import google.generativeai as genai
import time
import os
import sys

# Ensure the project root is in sys.path to find system_configs.config_manager
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

from system_configs.config_manager import config # Import the global config instance
from .utils.logger import setup_logger
from minion_core.utils.errors import LLMError, LLMAPIError, LLMContentFilterError
from minion_core.utils.health import HealthStatus, HealthCheckResult, HealthCheckable
from minion_core.utils.metrics import MetricsCollector # Added for Metrics
 
 # Logger setup will be handled by the Minion class that instantiates this.
# This module assumes a logger is passed or configured globally.

# Maximum retries for API calls
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5 # Initial delay, could be exponential backoff

class LLMInterface(HealthCheckable):
    def __init__(self, minion_id, api_key=None, logger=None):
        self.minion_id = minion_id
        self.logger = logger if logger else setup_logger(f"LLMInterface_{minion_id}", f"llm_interface_{minion_id}.log") # Fallback logger
        
        if api_key:
            self.api_key = api_key
        else:
            gemini_api_key_env_name = config.get_str("llm.gemini_api_key_env_var", "GEMINI_API_KEY_LEGION")
            self.api_key = os.getenv(gemini_api_key_env_name)

        if not self.api_key:
            self.logger.critical(f"Gemini API Key not found. Environment variable '{gemini_api_key_env_name}' is not set or no explicit API key was provided. LLMInterface cannot function.")
            raise ValueError(f"Gemini API Key is required for LLMInterface. Check environment variable: {gemini_api_key_env_name}")
            
        try:
            genai.configure(api_key=self.api_key)
            # Using a model suitable for complex reasoning and instruction following.
            # Codex Omega Note: "gemini-2.5-pro-preview-05-06" is chosen for its capabilities.
            # User should ensure this model is available to their API key.
            self.model = genai.GenerativeModel('gemini-2.5-pro-preview-05-06') 
            self.logger.info("LLMInterface initialized successfully with gemini-2.5-pro-preview-05-06.")
        except Exception as e:
            self.logger.critical(f"Failed to configure Gemini or initialize model: {e}")
            # BIAS_ACTION: Critical failure if model cannot be initialized.
            raise RuntimeError(f"LLMInterface initialization failed: {e}")

        # Initialize metrics
        # Use a minion_id specific subdirectory within the main metrics storage
        # Fallback to a generic "llm_interface_metrics" if PROJECT_ROOT is not easily determined here
        # However, config.get_path should handle PROJECT_ROOT correctly.
        metrics_storage_base_dir = config.get_path("metrics.storage_dir", os.path.join(project_root_for_imports, "system_data", "metrics"))
        llm_metrics_dir = os.path.join(metrics_storage_base_dir, f"llm_interface_{self.minion_id}")
        os.makedirs(llm_metrics_dir, exist_ok=True) # Ensure directory exists

        self.metrics = MetricsCollector(
            component_name=f"LLMInterface_{self.minion_id}", # Unique component name per minion
            storage_dir=llm_metrics_dir, # Store in its own subdirectory
            logger=self.logger
        )
        self.logger.info(f"LLMInterface metrics storage directory: {llm_metrics_dir}")
 
    def send_prompt(self, prompt_text, conversation_history=None):
        """
        Sends a prompt to the Gemini model and returns the response.
        Manages conversation history if provided.
        """
        self.logger.info(f"Sending prompt to Gemini. Prompt length: {len(prompt_text)} chars.")
        self.logger.debug(f"Full prompt: {prompt_text[:500]}...") # Log beginning of prompt

        # BIAS_CHECK: Ensure conversation history is handled correctly if present.
        # Gemini API supports chat sessions. For simplicity in this version,
        # we can either manage a simple list of {'role': 'user'/'model', 'parts': [text]}
        # or treat each call as a new conversation if history management becomes too complex
        # for the initial Minion design.
        # Codex Omega Decision: For V1, treat each send_prompt as potentially part of an ongoing
        # logical conversation, but the history is managed by the calling Minion logic.
        # This LLMInterface will just send the current prompt.
        # More sophisticated history/chat session can be added in Minion's meta_cognition.

        # Start timer
        timer_id = self.metrics.start_timer("llm_request_time")
        try:
            token_count = self._estimate_token_count(prompt_text)
            self.metrics.observe("prompt_token_count", token_count)

            for attempt in range(MAX_RETRIES):
                try:
                    # For simple prompts without explicit history:
                    response = self.model.generate_content(prompt_text)
                    
                    # BIAS_CHECK: Validate response structure. Gemini API might have safety settings
                    # that block responses. Need to handle this.
                    if not response.parts:
                        if response.prompt_feedback and response.prompt_feedback.block_reason:
                            block_reason_message = response.prompt_feedback.block_reason_message or "No specific message."
                            self.logger.error(f"Gemini API blocked response. Reason: {response.prompt_feedback.block_reason}. Message: {block_reason_message}")
                            # Use new error class instead of string
                            self.metrics.inc_counter("llm_requests_error", labels={"error_type": "ContentFilterError", "filter_reason": str(response.prompt_feedback.block_reason)})
                            raise LLMContentFilterError(
                                f"Content filtered: {block_reason_message}",
                                code=response.prompt_feedback.block_reason,
                                details={"prompt": prompt_text[:100] + "..."}
                            )
                        else:
                            self.logger.error("Gemini API returned an empty response with no parts and no clear block reason.")
                            self.metrics.inc_counter("llm_requests_error", labels={"error_type": "EmptyResponse"})
                            raise LLMError("Empty response from LLM")
    
                    response_text = response.text # Accessing .text directly
                    self.logger.info(f"Received response from Gemini. Response length: {len(response_text)} chars.")
                    self.logger.debug(f"Full response: {response_text[:500]}...")

                    # On success
                    self.metrics.inc_counter("llm_requests_success")
                    response_token_count = self._estimate_token_count(response_text)
                    self.metrics.observe("response_token_count", response_token_count)
                    return response_text
                except LLMError as e: # Includes LLMContentFilterError
                    # On error (already counted specific filter errors)
                    if not isinstance(e, LLMContentFilterError): # Avoid double counting if already handled
                         self.metrics.inc_counter("llm_requests_error", labels={"error_type": type(e).__name__})
                    raise # Re-raise LLMError instances
                except Exception as e:
                    # Wrap other exceptions
                    self.logger.error(f"Error communicating with Gemini API (Attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                    if attempt < MAX_RETRIES - 1:
                        self.logger.info(f"Retrying in {RETRY_DELAY_SECONDS} seconds...")
                        time.sleep(RETRY_DELAY_SECONDS * (attempt + 1)) # Exponential backoff could be better
                    else:
                        self.logger.critical(f"Max retries reached. Failed to get response from Gemini: {e}")
                        self.metrics.inc_counter("llm_requests_error", labels={"error_type": "MaxRetriesReached", "original_exception": type(e).__name__})
                        raise LLMAPIError(f"API error: {str(e)}", details={"original_error": str(e)})
            # This part should ideally not be reached if exceptions are raised correctly.
            # If it is, it means MAX_RETRIES was exceeded without a specific LLMError or LLMAPIError being raised.
            self.metrics.inc_counter("llm_requests_error", labels={"error_type": "MaxRetriesExceededUnknown"})
            raise LLMAPIError("Max retries exceeded for LLM API call", details={"attempts": MAX_RETRIES})
        finally:
            # Always stop timer
            self.metrics.stop_timer(timer_id)

    def _estimate_token_count(self, text: str) -> int:
        """Estimate token count using a simple heuristic."""
        # Simple approximation: 4 chars per token
        if not isinstance(text, str): # Handle cases where text might not be a string (e.g. if LLM returns non-text)
            return 0
        return len(text) // 4
 
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
