import os
import sys
import time # json import removed as it's no longer directly used here
import logging # Use standard logging for the runner itself

# Import the new ConfigManager instance
# Ensure system_configs is discoverable, e.g. by adding project root to PYTHONPATH if necessary
# or by adjusting sys.path here if run_a2a_server.py is not in the project root.
try:
    from system_configs.config_manager import config
except ImportError:
    # Fallback if system_configs is not directly in PYTHONPATH
    # This assumes run_a2a_server.py is in a subdirectory of the project root
    project_root_for_config = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    sys.path.insert(0, project_root_for_config)
    from system_configs.config_manager import config

# --- Initialize basic paths using ConfigManager ---
project_root = config.get_project_root()
logs_dir = config.get_path("global.logs_dir", "logs") # Uses project_root implicitly if relative
a2a_server_runner_log_file = os.path.join(logs_dir, "a2a_server_runner.log")

# Ensure logs directory exists
if not os.path.exists(logs_dir):
    try:
        os.makedirs(logs_dir)
    except OSError as e:
        # Use print for critical early errors before logger might be fully set up
        print(f"CRITICAL: Could not create logs directory {logs_dir}. Error: {e}", file=sys.stderr)
        sys.exit(1)

# Setup basic logging for this runner script
# The log level for this specific runner script can be INFO,
# while the A2A server components' log level will be read from config.
logging.basicConfig(
    level=logging.INFO, # Keep runner log level potentially separate
    format='%(asctime)s - A2A_SERVER_RUNNER - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(a2a_server_runner_log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout) # Also log to console
    ]
)
logger = logging.getLogger(__name__) # Logger for this runner script

# --- Add necessary paths for imports (e.g., for 'common' from a2a_framework) ---
# Path to a2a_framework/samples/python
a2a_samples_python_path = os.path.join(project_root, "a2a_framework", "samples", "python")
if a2a_samples_python_path not in sys.path:
    sys.path.insert(0, a2a_samples_python_path)
    logger.info(f"Added {a2a_samples_python_path} to sys.path for 'common' module imports.")

# --- Import the necessary classes AFTER setting path ---
try:
    from common.server.server import A2AServer
    from common.server.task_manager import TaskManager, InMemoryTaskManager # Base class and concrete implementation
    # Codex Omega Note: Using the base TaskManager. A concrete implementation might be needed
    # if the base class methods called by A2AServer are not implemented.
    # For now, assume base TaskManager is sufficient or has defaults.
    # A more robust implementation might use InMemoryTaskManager from demo/ui if suitable.
    from common.types import AgentCard, AgentCapabilities, AgentSkill # Added AgentCapabilities and AgentSkill
except ImportError as e:
    logger.critical(f"Failed to import necessary A2A classes: {e}. Check PYTHONPATH and file existence.", exc_info=True)
    sys.exit(1)
except Exception as e:
    logger.critical(f"An unexpected error occurred during imports: {e}", exc_info=True)
    sys.exit(1)


if __name__ == "__main__":
    logger.info("A2A Server Runner Initializing...")
    # project_root and logs_dir are already defined using the new config manager at the top of the script
    logger.info(f"Using Project Root: {project_root}")
    logger.info(f"Logs Directory: {logs_dir}")

    # --- Load configuration using ConfigManager ---
    # 'config' is the imported ConfigManager instance
    host = config.get_str("a2a_server.host", "127.0.0.1")
    port = config.get_int("a2a_server.port", 8080)
    
    # Get storage_path, ensuring it's absolute.
    # default_storage_path uses project_root from ConfigManager.
    default_storage_path = os.path.join(project_root, "system_data", "a2a_storage.json")
    storage_path = config.get_path("a2a_server.storage_path", default_storage_path)
    
    # Get log_level for A2A components, falling back to global, then to INFO.
    # This 'a2a_component_log_level_str' will be used in the try-except block below,
    # which was already correctly modified by the previous diff.
    a2a_component_log_level_str = config.get_str(
        "a2a_server.log_level",
        config.get_str("global.log_level", "INFO")
    ).upper()

    logger.info(f"A2A Server Config: Host={host}, Port={port}, StoragePath={storage_path}, ComponentLogLevel={a2a_component_log_level_str}")

    # Configure logging level for the A2A server components if possible
    # (The server.py script uses logging.getLogger(__name__))
    # This sets the level for loggers acquired *after* this point.
    try:
        log_level_enum = getattr(logging, a2a_component_log_level_str, logging.INFO)
        # Set level specifically for the "common" package logger,
        # or any other top-level logger used by the A2A server internals.
        logging.getLogger("common").setLevel(log_level_enum)
        # You might want to set levels for other specific loggers if known
        logger.info(f"Attempting to set log level for A2A components (e.g., 'common') to: {a2a_component_log_level_str}")
    except Exception as e:
        logger.warning(f"Could not set log level for A2A components from config: {e}", exc_info=True)


    # Ensure storage directory exists
    storage_dir = os.path.dirname(storage_path)
    if not os.path.exists(storage_dir):
        try:
            os.makedirs(storage_dir)
            logger.info(f"Created A2A storage directory: {storage_dir}")
        except OSError as e:
            logger.critical(f"Could not create A2A storage directory {storage_dir}. Error: {e}", exc_info=True)
            sys.exit(1)

    # --- Instantiate necessary components ---
    try:
        logger.info("Instantiating TaskManager...")
        # Using the base TaskManager. If it requires arguments or is abstract, this will fail.
        # A concrete implementation like InMemoryTaskManager might be needed.
        # For now, attempt with base class.
        task_manager_instance = InMemoryTaskManager() # Use concrete implementation, does not take storage_path
        logger.info("TaskManager instantiated.")

        logger.info("Creating AgentCard for the A2A Server itself...")
        # This card represents the server/registry agent itself.
        a2a_server_agent_card = AgentCard(
            name="A2A Registry Server",
            description="Central server for AI Minion Army agent registration and message routing.",
            url=f"http://{host}:{port}", # Added URL
            version="0.1.0", # Added version
            capabilities=AgentCapabilities( # Changed to AgentCapabilities object
                streaming=True,
                pushNotifications=False, # Assuming false for now, can be true if implemented
                stateTransitionHistory=True
            ),
            skills=[ # Added skills
                AgentSkill(
                    id="agent_registry_skill_001",
                    name="agent_registry",
                    description="Registers agents and provides agent lists."
                ),
                AgentSkill(
                    id="message_routing_skill_001",
                    name="message_routing",
                    description="Routes messages between registered agents."
                )
            ]
            # Note: 'id' is not a field in AgentCard model, it's usually part of TaskSendParams or similar.
            # The server itself doesn't have an 'id' in this context.
            # 'provider' and 'authentication' are optional and omitted for now.
        )
        logger.info("A2A Server AgentCard created.")

        logger.info("Instantiating A2AServer...")
        server_instance = A2AServer(
            host=host,
            port=port,
            agent_card=a2a_server_agent_card, # Pass the server's own card
            task_manager=task_manager_instance # Pass the task manager instance
        )
        logger.info("A2AServer instantiated.")

    except Exception as e:
        logger.critical(f"Failed during instantiation of A2AServer components: {e}", exc_info=True)
        sys.exit(1)

    # --- Start the server ---
    try:
        logger.info(f"Starting A2AServer on http://{host}:{port}...")
        # The start() method internally imports and runs uvicorn
        server_instance.start()
        # If start() returns (e.g., on shutdown), log it.
        logger.info("A2AServer start() method returned. Server has stopped.")

    except ImportError as e:
         logger.critical(f"ImportError during server start (likely uvicorn missing?): {e}. Ensure uvicorn is installed in the venv.", exc_info=True)
         sys.exit(1)
    except KeyboardInterrupt:
        logger.info("A2A Server runner received KeyboardInterrupt. Shutting down.")
    except Exception as e:
        logger.critical(f"An error occurred while running A2A Server: {e}", exc_info=True)
    finally:
        logger.info("A2A Server runner finished.")