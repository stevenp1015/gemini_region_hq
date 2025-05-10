import os
import toml
from dotenv import load_dotenv
import logging
from typing import Any, Optional, Union, List, Dict

# Setup a logger for the config manager
# Using a basic configuration for now, can be enhanced to use the project's standard logger if available
config_manager_logger = logging.getLogger("ConfigManager")
if not config_manager_logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    config_manager_logger.addHandler(handler)
config_manager_logger.setLevel(logging.INFO)


class ConfigManager:
    def __init__(self):
        self.base_project_dir_env: Optional[str] = os.getenv("BASE_PROJECT_DIR")
        if self.base_project_dir_env:
            self.project_root: str = os.path.abspath(self.base_project_dir_env)
            config_manager_logger.info(f"BASE_PROJECT_DIR environment variable found: {self.project_root}")
        else:
            # If BASE_PROJECT_DIR is not set, assume this file is in system_configs,
            # and the project root is one level up.
            self.project_root: str = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            config_manager_logger.info(f"BASE_PROJECT_DIR not set. Inferred project root: {self.project_root}")

        self.config_toml_path: str = os.path.join(self.project_root, "system_configs/config.toml")
        self.dotenv_path: str = os.path.join(self.project_root, "system_configs/.env.legion")
        
        self.config: Dict[str, Any] = {}
        self._load_config_toml()
        self._load_dotenv()

    def _load_config_toml(self):
        try:
            if os.path.exists(self.config_toml_path):
                with open(self.config_toml_path, 'r', encoding='utf-8') as f:
                    self.config = toml.load(f)
                config_manager_logger.info(f"Successfully loaded configuration from: {self.config_toml_path}")
            else:
                config_manager_logger.warning(f"Configuration file not found at: {self.config_toml_path}. Using defaults and environment variables only.")
                self.config = {} # Ensure self.config is an empty dict if file not found
        except toml.TomlDecodeError as e:
            config_manager_logger.error(f"Error decoding TOML from {self.config_toml_path}: {e}", exc_info=True)
            self.config = {}
        except Exception as e:
            config_manager_logger.error(f"An unexpected error occurred while loading {self.config_toml_path}: {e}", exc_info=True)
            self.config = {}

    def _load_dotenv(self):
        if os.path.exists(self.dotenv_path):
            loaded = load_dotenv(dotenv_path=self.dotenv_path, override=True)
            if loaded:
                config_manager_logger.info(f"Successfully loaded environment variables from: {self.dotenv_path}")
            else:
                config_manager_logger.warning(f"Dotenv file found at {self.dotenv_path}, but no variables were loaded. Check file content and permissions.")
        else:
            config_manager_logger.info(f"Dotenv file not found at: {self.dotenv_path}. Skipping .env loading.")

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieves a configuration value.
        The key should be in dot notation, e.g., "a2a_server.host".
        Environment variables take precedence. Env var name is derived from key:
        "section.key_name" -> "SECTION_KEY_NAME"
        "section.subsection.key_name" -> "SECTION_SUBSECTION_KEY_NAME"
        """
        env_var_name = key.upper().replace(".", "_")
        env_value = os.getenv(env_var_name)

        if env_value is not None:
            config_manager_logger.debug(f"Found value for '{key}' in environment variable '{env_var_name}': '{env_value}'")
            return env_value # Environment variables are always strings, type conversion is separate

        # Traverse the config dictionary using dot notation
        keys = key.split('.')
        value = self.config
        try:
            for k_part in keys:
                if isinstance(value, dict):
                    value = value[k_part]
                else: # If at any point value is not a dict, but we still have keys, it's a mismatch
                    raise KeyError(f"Path '{key}' not fully traversable in config.")
            config_manager_logger.debug(f"Found value for '{key}' in TOML config: '{value}'")
            return value
        except KeyError:
            config_manager_logger.debug(f"Key '{key}' not found in TOML config. Using default: '{default}'")
            return default
        except Exception as e:
            config_manager_logger.warning(f"Error accessing key '{key}' in TOML config: {e}. Using default: '{default}'")
            return default

    def get_str(self, key: str, default: Optional[str] = None) -> Optional[str]:
        value = self.get(key, default)
        return str(value) if value is not None else None

    def get_int(self, key: str, default: Optional[int] = None) -> Optional[int]:
        value_str = self.get(key) # Get as string first (env vars) or native type (TOML)
        if value_str is None:
            return default
        try:
            return int(value_str)
        except (ValueError, TypeError):
            config_manager_logger.warning(f"Could not convert value for '{key}' ('{value_str}') to int. Using default: {default}")
            return default

    def get_float(self, key: str, default: Optional[float] = None) -> Optional[float]:
        value_str = self.get(key)
        if value_str is None:
            return default
        try:
            return float(value_str)
        except (ValueError, TypeError):
            config_manager_logger.warning(f"Could not convert value for '{key}' ('{value_str}') to float. Using default: {default}")
            return default

    def get_bool(self, key: str, default: Optional[bool] = None) -> Optional[bool]:
        value_str = self.get(key)
        if value_str is None:
            return default
        
        if isinstance(value_str, bool): # If loaded from TOML as boolean
            return value_str
            
        if isinstance(value_str, str):
            if value_str.lower() in ('true', 'yes', '1', 'on'):
                return True
            elif value_str.lower() in ('false', 'no', '0', 'off'):
                return False
        
        config_manager_logger.warning(f"Could not convert value for '{key}' ('{value_str}') to bool. Using default: {default}")
        return default

    def get_list(self, key: str, default: Optional[List[Any]] = None) -> Optional[List[Any]]:
        value = self.get(key, default)
        if value is None:
            return default
        if isinstance(value, list):
            return value
        # Rudimentary support for comma-separated strings from env vars
        if isinstance(value, str):
            return [item.strip() for item in value.split(',')]
        config_manager_logger.warning(f"Value for '{key}' is not a list or comma-separated string. Using default: {default}")
        return default
        
    def get_dict(self, key: str, default: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        value = self.get(key, default)
        if value is None:
            return default
        if isinstance(value, dict):
            return value
        config_manager_logger.warning(f"Value for '{key}' is not a dictionary. Using default: {default}")
        return default

    def get_project_root(self) -> str:
        """Returns the determined project root directory."""
        return self.project_root

    def get_path(self, key: str, default: Optional[str] = None, relative_to_root: bool = True) -> Optional[str]:
        """
        Retrieves a path string. If relative_to_root is True,
        and the path is relative, it's made absolute to the project root.
        """
        path_str = self.get_str(key, default)
        if path_str is None:
            return None
        
        if relative_to_root and not os.path.isabs(path_str):
            return os.path.join(self.project_root, path_str)
        return path_str

# Global instance of ConfigManager
# This allows other modules to import 'config' directly:
# from system_configs.config_manager import config
config = ConfigManager()

if __name__ == '__main__':
    # Example usage and testing
    config_manager_logger.setLevel(logging.DEBUG)
    print(f"Project Root: {config.get_project_root()}")
    
    # Create a dummy config.toml for testing if it doesn't exist
    dummy_toml_path = os.path.join(config.get_project_root(), "system_configs/config.toml")
    if not os.path.exists(dummy_toml_path):
        print(f"Creating dummy {dummy_toml_path} for testing.")
        os.makedirs(os.path.dirname(dummy_toml_path), exist_ok=True)
        with open(dummy_toml_path, "w") as f:
            f.write("""
[global]
log_level = "INFO"
logs_dir = "logs_test"

[a2a_server]
host = "127.0.0.1"
port = 8080
feature_enabled = true
timeout_seconds = 30.5
retry_attempts = 3
alternate_hosts = ["server1", "server2"]

[gui]
port = 8081
            """)
        config._load_config_toml() # Reload after creating dummy

    # Create a dummy .env.legion for testing
    dummy_env_path = os.path.join(config.get_project_root(), "system_configs/.env.legion")
    if not os.path.exists(dummy_env_path):
         print(f"Creating dummy {dummy_env_path} for testing.")
         with open(dummy_env_path, "w") as f:
            f.write("GEMINI_API_KEY_LEGION=test_api_key_from_env_file\n")
            f.write("A2A_SERVER_HOST=override_host_from_env\n") # Test override
         config._load_dotenv()


    print(f"Global Log Level (TOML): {config.get_str('global.log_level', 'ERROR')}")
    print(f"A2A Server Host (TOML): {config.get_str('a2a_server.host')}")
    # Test override: Set A2A_SERVER_HOST env var if you want to test this part manually
    # os.environ["A2A_SERVER_HOST"] = "env_override_host"
    print(f"A2A Server Host (Effective): {config.get_str('a2a_server.host')}") # Should show override if env var set
    print(f"A2A Server Port (int): {config.get_int('a2a_server.port', 9000)}")
    print(f"GUI Port (int, from TOML): {config.get_int('gui.port')}")
    print(f"Non-existent key (default): {config.get_str('non_existent.key', 'default_value')}")
    print(f"Gemini API Key (from .env): {os.getenv('GEMINI_API_KEY_LEGION')}") # Direct check
    print(f"Gemini API Key (via config.get for env var): {config.get('GEMINI_API_KEY_LEGION')}")


    print(f"A2A Feature Enabled (bool): {config.get_bool('a2a_server.feature_enabled', False)}")
    print(f"A2A Timeout (float): {config.get_float('a2a_server.timeout_seconds', 10.0)}")
    print(f"A2A Retry Attempts (int): {config.get_int('a2a_server.retry_attempts', 1)}")
    print(f"A2A Alternate Hosts (list): {config.get_list('a2a_server.alternate_hosts')}")
    
    # Test path resolution
    print(f"Logs Directory (path): {config.get_path('global.logs_dir')}")
    print(f"Absolute Path Test (path): {config.get_path('global.abs_path_test', default='/tmp/abs_test')}")

    # Clean up dummy files
    # if os.path.exists(dummy_toml_path) and "dummy" in dummy_toml_path: os.remove(dummy_toml_path)
    # if os.path.exists(dummy_env_path) and "dummy" in dummy_env_path: os.remove(dummy_env_path)
    print("Run 'git clean -fd system_configs/' to remove dummy files if created.")