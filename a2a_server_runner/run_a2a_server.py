import os
import sys
import json
import time
import logging # Use standard logging for the runner itself

# Define paths relative to the script or using environment variables
base_project_dir = os.getenv("BASE_PROJECT_DIR")
if not base_project_dir:
    print("CRITICAL: BASE_PROJECT_DIR environment variable not set.", file=sys.stderr)
    sys.exit(1)

a2a_framework_dir = os.path.join(base_project_dir, "a2a_framework")
a2a_python_path = os.path.join(a2a_framework_dir, "samples/python") # Path containing 'common'
config_path = os.path.join(base_project_dir, "system_configs/a2a_server_config.json")
logs_dir = os.path.join(base_project_dir, "logs")
a2a_server_runner_log_file = os.path.join(logs_dir, "a2a_server_runner.log")

# Ensure logs directory exists
if not os.path.exists(logs_dir):
    try:
        os.makedirs(logs_dir)
    except OSError as e:
        print(f"CRITICAL: Could not create logs directory {logs_dir}. Error: {e}", file=sys.stderr)
        sys.exit(1)

# Setup basic logging for this runner script
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - A2A_SERVER_RUNNER - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(a2a_server_runner_log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout) # Also log to console
    ]
)
logger = logging.getLogger(__name__)

# --- Add necessary paths for imports ---
# We need 'samples/python' in sys.path to find 'common'
if a2a_python_path not in sys.path:
    sys.path.insert(0, a2a_python_path)
    logger.info(f"Added {a2a_python_path} to sys.path for imports.")

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
    logger.info(f"Base Project Dir: {base_project_dir}")

    # Load config
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded A2A server config from {config_path}")
    except Exception as e:
        logger.critical(f"Failed to load A2A server config from {config_path}: {e}", exc_info=True)
        sys.exit(1)

    host = config.get("host", "127.0.0.1")
    port = config.get("port", 8080)
    storage_path = config.get("storage_path", os.path.join(base_project_dir, "system_data/a2a_storage.json"))
    log_level_str = config.get("log_level", "INFO").upper()

    # Configure logging level for the A2A server components if possible
    # (The server.py script uses logging.getLogger(__name__))
    # This sets the level for loggers acquired *after* this point.
    try:
        log_level_enum = getattr(logging, log_level_str, logging.INFO)
        # Set level for the root logger, affecting subsequent loggers unless they override
        # logging.getLogger().setLevel(log_level_enum)
        # Or specifically for the common package logger if needed:
        logging.getLogger("common").setLevel(log_level_enum)
        logger.info(f"Attempting to set log level for A2A components to: {log_level_str}")
    except Exception as e:
        logger.warning(f"Could not set log level from config: {e}")


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