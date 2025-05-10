# Unified Configuration Management Strategy for AI Minion Army

**Version:** 1.0
**Date:** 2025-05-09
**Author:** Roo, AI Architect

## 1. Introduction

This document outlines a proposal for a unified and robust configuration management strategy for the AI Minion Army project. The current system, while functional, suffers from configuration sprawl, making it difficult to manage, discover, and maintain settings consistently across its various components (A2A Server, Minions, GUI, Spawner). This proposal aims to centralize configuration, improve ease of use, and enhance maintainability.

## 2. Summary of Current Configuration Practices & Limitations

### 2.1. Current Practices:

*   **A2A Server Runner:** Uses `system_configs/a2a_server_config.json` (for host, port, storage, log level) and the `BASE_PROJECT_DIR` environment variable.
*   **Minion Core:** Uses command-line arguments (ID, personality, A2A server URL), environment variables (`BASE_PROJECT_DIR`, `A2A_SERVER_HOST`/`PORT`), `system_configs/minion_guidelines.json` (behavior), and `system_configs/.env.legion` (API key).
*   **A2A Client (within Minion):** Uses environment variables (`A2A_CLIENT_POLLING_INTERVAL_SECONDS`, `BASE_PROJECT_DIR`) and parameters passed from `main_minion`.
*   **Management GUI:** Uses environment variables (`BASE_PROJECT_DIR`, `A2A_SERVER_HOST`/`PORT`, GUI polling interval, GUI host/port).
*   **Minion Spawner:** Uses command-line arguments (count, A2A server URL), environment variables (`BASE_PROJECT_DIR`), and a hardcoded list of minion definitions (ID, personality).

### 2.2. Limitations:

*   **Configuration Sprawl:** Settings are dispersed across JSON files, environment variables, hardcoded values in Python scripts, and command-line arguments.
*   **Discoverability Issues:** Difficult to locate where specific settings are defined.
*   **Inconsistent Configuration Methods:** Different components use different methods for the same logical setting (e.g., A2A server address).
*   **Risk of Errors:** High chance of inconsistencies leading to runtime issues.
*   **Poor User Experience:** Managing configurations is complex for the user (Steven).
*   **Lack of Schema/Validation:** JSON files are prone to errors without schemas.
*   **No Comments in JSON:** Reduces clarity of configuration files.

## 3. Proposed Configuration Strategy

The proposed strategy focuses on centralization, clear precedence, and ease of use, leveraging a combination of configuration files and environment variable overrides.

### 3.1. Central Configuration File(s)

*   **Format:** **TOML (Tom's Obvious, Minimal Language)**.
    *   **Reasoning:** TOML is chosen for its readability, ease of parsing, support for comments (unlike JSON), and clear hierarchical structure. It's well-suited for configuration files. YAML is another option but can be more complex with indentation and type interpretation. INI is simpler but less expressive for complex structures.
*   **Location:** A single, primary configuration file named `config.toml` will reside in the `system_configs/` directory: [`system_configs/config.toml`](system_configs/config.toml).
*   **Sensitive Data:** Secrets like API keys (`GEMINI_API_KEY_LEGION`) will continue to be managed in [`system_configs/.env.legion`](system_configs/.env.legion) and loaded via `python-dotenv`. The main `config.toml` can reference the *need* for these environment variables but should not store the secrets themselves.

### 3.2. Structure of `config.toml`

The `config.toml` file will be organized into sections for each major component and shared settings.

```toml
# system_configs/config.toml

# Global settings applicable to multiple components
[global]
base_project_dir = "." # Relative to project root, or allow override by env var BASE_PROJECT_DIR
log_level = "INFO"    # Default log level for components (can be overridden per component)
logs_dir = "logs"     # Relative to base_project_dir

[a2a_server]
host = "127.0.0.1"
port = 8080
storage_path = "system_data/a2a_storage.json" # Relative to base_project_dir
# log_level = "DEBUG" # Example of overriding global log_level

[gui]
host = "127.0.0.1"
port = 8081
# Polling intervals in seconds
commander_message_polling_interval = 10.0
server_status_polling_interval = 30.0
minion_list_polling_interval = 60.0
# a2a_server_url can be derived from [a2a_server] section or explicitly set if different

[minion_defaults]
# Default settings for all minions, can be overridden by specific minion configs or spawner
a2a_client_polling_interval_seconds = 5
# Personality and guidelines path could be specified here if not using spawner definitions
# default_personality = "Adaptable, Resourceful"
# guidelines_path = "system_configs/minion_guidelines.json" # Path to the existing guidelines

# Minion Spawner settings
[minion_spawner]
# Defines minions to be spawned. Replaces the hardcoded list in spawn_legion.py
# Each minion definition can override minion_defaults.
minions = [
    { id = "Alpha", personality = "Strategic, Analytical, CalmUnderPressure" },
    { id = "Bravo", personality = "Creative, Unconventional, Inquisitive" },
    { id = "Charlie", personality = "Meticulous, DetailOriented, Skeptical" },
    # { id = "Delta", personality = "Resourceful, Pragmatic", log_level = "DEBUG" }, # Example override
]

# LLM Configuration (if needed beyond just API key)
[llm]
# gemini_api_key_env_var = "GEMINI_API_KEY_LEGION" # Indicates which env var holds the key
# model_name = "gemini-1.5-pro-latest" # Example if we need to specify models

# Other component-specific sections can be added as needed
# [another_component]
# setting1 = "value"
```

The existing [`system_configs/minion_guidelines.json`](system_configs/minion_guidelines.json) will remain as is, as it contains complex structured data (prompts, directives) better suited to JSON than trying to embed it directly in TOML. The `config.toml` can point to its path if necessary, or the loader can assume its standard location.

### 3.3. Environment Variable Overrides

*   Environment variables will **always** take precedence over settings in `config.toml`.
*   A clear mapping should be established, e.g.:
    *   `BASE_PROJECT_DIR` overrides `global.base_project_dir`.
    *   `A2A_SERVER_HOST` overrides `a2a_server.host`.
    *   `A2A_SERVER_PORT` overrides `a2a_server.port`.
    *   `GUI_PORT` overrides `gui.port`.
    *   `MINION_ALPHA_LOG_LEVEL` could override `minion_defaults.log_level` or `global.log_level` for a specific minion. (Convention TBD, e.g., `MINION_ID_SETTING_NAME`).
*   This allows for flexibility in different deployment environments (dev, staging, prod) without altering the base config file.

### 3.4. Configuration Loading Mechanism

*   **New Python Module:** A dedicated module, e.g., `system_configs/config_manager.py`, will be created.
*   **Responsibilities:**
    1.  Load the `config.toml` file.
    2.  Load `.env.legion` for secrets.
    3.  Provide a simple API to access configuration values, automatically handling environment variable overrides.
    4.  Handle type conversions (e.g., string from env var to int/float).
    5.  Provide graceful defaults if a setting is missing from both the file and environment (though the TOML file should aim to be comprehensive for defaults).
    6.  Log its activities (e.g., which files were loaded, which overrides were applied).

*   **Example Usage (Conceptual):**

    ```python
    # In any component, e.g., main_minion.py
    from system_configs.config_manager import config

    a2a_host = config.get("a2a_server.host") # Gets from TOML or env override
    a2a_port = config.get_int("a2a_server.port")
    api_key = config.get_env("GEMINI_API_KEY_LEGION") # Specifically for env vars from .env

    minion_alpha_log_level = config.get("minions.Alpha.log_level", default=config.get("minion_defaults.log_level"))
    ```

*   **Libraries:** `toml` library for parsing TOML, `python-dotenv` for `.env` files.

*   **Mermaid Diagram of Config Loading:**

    ```mermaid
    graph TD
        A[Environment Variables] --> C{Config Value};
        B[system_configs/config.toml] --> C;
        D[system_configs/.env.legion] -- loads into --> A;
        C -- accessed by --> E[config_manager.py];
        E -- provides to --> F1[A2A Server];
        E -- provides to --> F2[Minion Core];
        E -- provides to --> F3[Management GUI];
        E -- provides to --> F4[Minion Spawner];

        subgraph Priority
            direction LR
            P1[Env Vars (Highest)] --> P2[config.toml (Default)]
        end
    ```

### 3.5. Key Settings to be Managed

*   **Global:** `base_project_dir`, `log_level`, `logs_dir`.
*   **A2A Server:** `host`, `port`, `storage_path`, `log_level`.
*   **GUI:** `host`, `port`, polling intervals, A2A server URL (can be derived or explicit).
*   **Minion Defaults:** A2A client polling interval, default log level.
*   **Minion Spawner:** List of minion definitions (ID, personality, specific overrides).
*   **LLM:** API Key environment variable name.
*   **Paths:** Paths to other critical files like `minion_guidelines.json` if they are not fixed relative to `BASE_PROJECT_DIR`.

Command-line arguments for scripts like `main_minion.py` and `spawn_legion.py` can still exist but should primarily be for settings that are highly dynamic per invocation (e.g., a specific minion ID to debug, or a temporary override not meant to be persisted). The config file should be the source of truth for most operational parameters.

### 3.6. Ease of Use (for Steven)

*   **Central Point of Truth:** Steven can primarily look at `system_configs/config.toml` to understand and modify the system's behavior.
*   **Clear Structure & Comments:** TOML's readability and comment support will make the configuration file self-documenting.
*   **Overrides:** Environment variables provide a standard way for advanced overrides without touching the base config.
*   **Reduced Hardcoding:** Moving settings from Python code into `config.toml` makes them easier to change without code modifications.

## 4. Dynamic Configuration (Future Consideration)

*   The proposed `config_manager.py` could be extended to support runtime updates if needed.
*   **Mechanism:**
    *   The `config_manager` could implement a mechanism to watch `config.toml` for changes (e.g., using a file system watcher library or periodic checks).
    *   Upon detecting a change, it could reload the configuration.
    *   Components would need to be designed to either re-query the `config_manager` for settings periodically or subscribe to configuration change events.
*   **GUI Integration:** The Management GUI could potentially provide an interface to modify `config.toml` (with appropriate safeguards and server-side validation).
*   **Initial Scope:** For the first pass, dynamic configuration is out of scope. The focus is on a robust static configuration system.

## 5. Impact and Benefits

*   **Improved Robustness:** Reduces risk of inconsistencies and errors from scattered configurations.
*   **Enhanced Ease of Use:** Simplifies configuration management for users and developers.
*   **Better Maintainability:** Easier to update and evolve configurations as the system grows.
*   **Increased Discoverability:** Settings are centralized and well-documented.
*   **Consistency:** Promotes uniform configuration practices across all components.

## 6. Migration Path (High-Level)

1.  Implement `system_configs/config_manager.py`.
2.  Create the initial `system_configs/config.toml` based on current defaults and settings.
3.  Refactor each component (`a2a_server_runner`, `minion_core`, `management_gui`, `minion_spawner`) one by one:
    *   Remove hardcoded values and direct environment variable reads for settings now in `config.toml`.
    *   Integrate with `config_manager.py` to fetch configurations.
    *   Update command-line argument parsing to potentially act as overrides or for settings not suitable for `config.toml`.
4.  Update documentation and any deployment scripts to reflect the new configuration strategy.

This new strategy will provide a solid foundation for managing the AI Minion Army's configuration effectively.