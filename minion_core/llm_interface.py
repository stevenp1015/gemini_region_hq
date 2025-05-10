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

# Logger setup will be handled by the Minion class that instantiates this.
# This module assumes a logger is passed or configured globally.

# Maximum retries for API calls
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5 # Initial delay, could be exponential backoff

class LLMInterface:
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
                        # BIAS_ACTION: Propagate specific error for Minion to handle.
                        return f"ERROR_GEMINI_BLOCKED: {response.prompt_feedback.block_reason} - {block_reason_message}"
                    else:
                        self.logger.error("Gemini API returned an empty response with no parts and no clear block reason.")
                        return "ERROR_GEMINI_EMPTY_RESPONSE"

                response_text = response.text # Accessing .text directly
                self.logger.info(f"Received response from Gemini. Response length: {len(response_text)} chars.")
                self.logger.debug(f"Full response: {response_text[:500]}...")
                return response_text
            except Exception as e:
                # BIAS_ACTION: Implement retry logic with backoff for transient API errors.
                self.logger.error(f"Error communicating with Gemini API (Attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    self.logger.info(f"Retrying in {RETRY_DELAY_SECONDS} seconds...")
                    time.sleep(RETRY_DELAY_SECONDS * (attempt + 1)) # Exponential backoff could be better
                else:
                    self.logger.critical(f"Max retries reached. Failed to get response from Gemini: {e}")
                    return f"ERROR_GEMINI_API_FAILURE: {e}"
        return "ERROR_GEMINI_MAX_RETRIES_EXCEEDED" # Should not be reached if logic above is correct
