import json
import os
from dotenv import load_dotenv
from .logger import setup_logger

# Path relative to this script's location might be fragile if script is moved.
# Better to use absolute paths or paths relative to a known project root.
# For this deployment, assuming BASE_PROJECT_DIR is accessible or passed.
# This will be refined when the Minion class uses it.

DEFAULT_GUIDELINES_PATH = os.path.join(os.getenv("BASE_PROJECT_DIR", "../.."), "system_configs/minion_guidelines.json") # Adjust path as needed
DEFAULT_ENV_PATH = os.path.join(os.getenv("BASE_PROJECT_DIR", "../.."), "system_configs/.env.legion")

# Logger for config loading issues
config_logger = setup_logger("ConfigLoader", os.path.join(os.getenv("BASE_PROJECT_DIR", "../.."), "logs/config_loader.log"))

def load_minion_guidelines(guidelines_path=None):
    """Loads the Minion guidelines JSON file."""
    path_to_load = guidelines_path if guidelines_path else DEFAULT_GUIDELINES_PATH
    try:
        with open(path_to_load, 'r', encoding='utf-8') as f:
            guidelines = json.load(f)
        config_logger.info(f"Successfully loaded Minion guidelines from: {path_to_load}")
        return guidelines
    except FileNotFoundError:
        config_logger.error(f"Minion guidelines file not found at: {path_to_load}")
    except json.JSONDecodeError:
        config_logger.error(f"Error decoding JSON from Minion guidelines file: {path_to_load}")
    except Exception as e:
        config_logger.error(f"An unexpected error occurred while loading guidelines from {path_to_load}: {e}")
    # BIAS_ACTION: Robust error handling for file loading. Return None on failure.
    return None

def get_gemini_api_key(env_path=None):
    """Loads the Gemini API key from the .env.legion file."""
    path_to_load = env_path if env_path else DEFAULT_ENV_PATH
    
    # load_dotenv will search for a .env file in the current directory or parent directories,
    # or a specific path if provided via dotenv_path.
    # For this script, we want to load a *specific* .env file.
    if os.path.exists(path_to_load):
        load_dotenv(dotenv_path=path_to_load, override=True) # Override ensures fresh load if called multiple times
        api_key = os.getenv("GEMINI_API_KEY_LEGION")
        if api_key:
            config_logger.info(f"Successfully loaded GEMINI_API_KEY_LEGION from {path_to_load}")
            return api_key
        else:
            config_logger.error(f"GEMINI_API_KEY_LEGION not found in {path_to_load} after loading.")
            return None
    else:
        config_logger.error(f".env file for Minion Legion not found at: {path_to_load}")
        return None

# BIAS_CHECK: Ensured API key loading is explicit and logs errors rather than failing silently or using a default.
