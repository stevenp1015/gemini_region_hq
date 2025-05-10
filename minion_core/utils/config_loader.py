import json
import os
import sys # Added for sys.path manipulation if needed for config_manager import

# Ensure the project root is in sys.path to find system_configs.config_manager
project_root_for_imports = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root_for_imports not in sys.path:
    sys.path.insert(0, project_root_for_imports)

from system_configs.config_manager import config # Import the global config instance
from .logger import setup_logger


# Logger for this utility - its path can also be derived from global config
# However, this logger is specific to this file's operations.
# ConfigManager already logs its own activities.
_utils_logs_dir = config.get_path("global.logs_dir", os.path.join(config.get_project_root(), "logs"))
_utils_config_loader_log_file = os.path.join(_utils_logs_dir, "utils_config_loader.log")
config_loader_logger = setup_logger("UtilsConfigLoader", _utils_config_loader_log_file)


def load_minion_guidelines(guidelines_path_override=None):
    """
    Loads the Minion guidelines JSON file.
    The path can be specified in config.toml under 'minion_defaults.guidelines_path'.
    An explicit override path can also be provided as an argument.
    """
    default_guidelines_filename = "minion_guidelines.json"
    
    # Priority: argument override > config file path > default path construction
    path_to_load = guidelines_path_override
    
    if not path_to_load:
        # Try to get path from config.toml
        # Uses get_path which resolves relative to project_root
        path_from_config = config.get_path("minion_defaults.guidelines_path")
        if path_from_config:
            path_to_load = path_from_config
        else:
            # Fallback to default construction if not in config
            path_to_load = os.path.join(config.get_project_root(), "system_configs", default_guidelines_filename)
            config_loader_logger.debug(f"minion_defaults.guidelines_path not in config.toml, using default: {path_to_load}")

    config_loader_logger.info(f"Attempting to load Minion guidelines from: {path_to_load}")
    try:
        with open(path_to_load, 'r', encoding='utf-8') as f:
            guidelines = json.load(f)
        config_loader_logger.info(f"Successfully loaded Minion guidelines from: {path_to_load}")
        return guidelines
    except FileNotFoundError:
        config_loader_logger.error(f"Minion guidelines file not found at: {path_to_load}")
    except json.JSONDecodeError:
        config_loader_logger.error(f"Error decoding JSON from Minion guidelines file: {path_to_load}", exc_info=True)
    except Exception as e:
        config_loader_logger.error(f"An unexpected error occurred while loading guidelines from {path_to_load}: {e}", exc_info=True)
    return None

# get_gemini_api_key function is removed.
# The API key should be retrieved directly from environment variables (os.getenv)
# after ConfigManager has loaded the .env file.
# Example in main_minion.py:
#   gemini_api_key_env_name = config.get_str("llm.gemini_api_key_env_var", "GEMINI_API_KEY_LEGION")
#   api_key = os.getenv(gemini_api_key_env_name)
