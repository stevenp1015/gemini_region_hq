import subprocess
import os
import json # For parsing structured output if Super-Tool provides it
from .utils.logger import setup_logger

# Assumes BASE_PROJECT_DIR is set as an environment variable or passed to Minion
BASE_DIR = os.getenv("BASE_PROJECT_DIR", "../..") # Adjust as needed
MCP_SUPER_TOOL_SCRIPT_PATH = os.path.join(BASE_DIR, "mcp_super_tool/src/main.js") # Corrected path to main.js
MCP_CONFIG_PATH_FOR_SUPER_TOOL = os.path.join(BASE_DIR, "system_configs/mcp_config.json")
SUPER_TOOL_ENV_PATH = os.path.join(BASE_DIR, "mcp_super_tool/.env") # .env for the super tool

class ToolManager:
    def __init__(self, minion_id, logger=None):
        self.minion_id = minion_id
        self.logger = logger if logger else setup_logger(f"ToolManager_{minion_id}", f"tool_manager_{minion_id}.log")
        
        # BIAS_CHECK: Validate paths to Super-Tool and its configs.
        if not os.path.exists(MCP_SUPER_TOOL_SCRIPT_PATH):
            self.logger.critical(f"MCP Super-Tool script not found at: {MCP_SUPER_TOOL_SCRIPT_PATH}")
            raise FileNotFoundError(f"MCP Super-Tool script not found: {MCP_SUPER_TOOL_SCRIPT_PATH}")
        if not os.path.exists(MCP_CONFIG_PATH_FOR_SUPER_TOOL):
            self.logger.critical(f"MCP Super-Tool config not found at: {MCP_CONFIG_PATH_FOR_SUPER_TOOL}")
            raise FileNotFoundError(f"MCP Super-Tool config not found: {MCP_CONFIG_PATH_FOR_SUPER_TOOL}")
        if not os.path.exists(SUPER_TOOL_ENV_PATH):
            self.logger.warning(f"MCP Super-Tool .env file not found at: {SUPER_TOOL_ENV_PATH}. Super-Tool might fail if API key is not globally available.")
            # It's a warning because the Node.js app might have other ways to get API key.

    def execute_super_tool_command(self, natural_language_command):
        """
        Executes a natural language command by invoking the Node.js MCP Super-Tool.
        The Super-Tool is expected to take the command, process it using its internal Gemini
        and MCP servers, and return a natural language result.
        """
        self.logger.info(f"Preparing to execute Super-Tool command: '{natural_language_command[:100]}...'")

        # BIAS_ACTION: Ensure command is passed securely and robustly.
        # Using subprocess.run for simplicity. For long-running tools or more complex IPC,
        # other methods like asyncio.create_subprocess_shell or dedicated IPC libraries might be better.
        # Codex Omega Decision: For V1, a synchronous subprocess call for each distinct task is acceptable.
        # The Super-Tool itself is a chat-like interface, so we need to pass the prompt.
        # Assuming the Node.js Super-Tool can accept a prompt via CLI argument.
        # This needs to align with how Steven's mcp_gemini_client_omega is actually invoked.
        # Common pattern: `node script.js --prompt "your command" --config "path" --env "path"`
        
        command_array = [
            "node", 
            MCP_SUPER_TOOL_SCRIPT_PATH,
            "--prompt", natural_language_command,
            "--config", MCP_CONFIG_PATH_FOR_SUPER_TOOL, # Super-Tool needs to know where its MCP servers are defined
            "--envFile", SUPER_TOOL_ENV_PATH # Super-Tool needs its own Gemini API key
        ]
        
        self.logger.debug(f"Executing Super-Tool with command: {' '.join(command_array)}")

        try:
            # Timeout for subprocess can be important for tools that might hang.
            # BIAS_CHECK: What's a reasonable timeout? Depends on expected Super-Tool task complexity.
            # Codex Omega Decision: Start with a generous timeout (e.g., 5 minutes = 300s) for V1.
            # This should be configurable in Minion guidelines or dynamically adjusted.
            timeout_seconds = 300 
            
            process = subprocess.run(
                command_array,
                capture_output=True,
                text=True,
                check=False, # Don't raise exception for non-zero exit; we'll handle it.
                timeout=timeout_seconds,
                cwd=os.path.dirname(MCP_SUPER_TOOL_SCRIPT_PATH) # Run from Super-Tool's directory for relative paths
            )

            if process.returncode == 0:
                self.logger.info(f"Super-Tool executed successfully. Output length: {len(process.stdout)}")
                self.logger.debug(f"Super-Tool stdout: {process.stdout[:500]}...")
                # BIAS_CHECK: Super-Tool might return structured JSON or plain text.
                # For now, assume natural language plain text. Minion can try to parse if needed.
                return process.stdout.strip()
            else:
                self.logger.error(f"Super-Tool execution failed with return code {process.returncode}.")
                self.logger.error(f"Super-Tool stderr: {process.stderr.strip()[:1000]}...") # Log substantial portion of stderr
                return f"ERROR_SUPER_TOOL_EXECUTION_FAILED: Code {process.returncode}. Stderr: {process.stderr.strip()}"

        except subprocess.TimeoutExpired:
            self.logger.error(f"Super-Tool command timed out after {timeout_seconds} seconds.")
            return "ERROR_SUPER_TOOL_TIMEOUT"
        except FileNotFoundError:
            self.logger.critical(f"'node' command not found or MCP Super-Tool script path incorrect. This should have been caught earlier.")
            return "ERROR_SUPER_TOOL_NODE_NOT_FOUND"
        except Exception as e:
            self.logger.critical(f"An unexpected error occurred while executing Super-Tool command: {e}")
            # BIAS_ACTION: Catch-all for unexpected issues during subprocess interaction.
            return f"ERROR_SUPER_TOOL_UNEXPECTED: {e}"

# Example usage (for testing this module directly, not part of Minion):
if __name__ == '__main__':
    # This requires BASE_PROJECT_DIR to be set in env for logger/config paths to work correctly
    # export BASE_PROJECT_DIR=$(pwd)/../.. # If running from minion_core
    print("Testing ToolManager (requires Node.js Super-Tool and configs to be set up)...")
    # Ensure necessary env vars are set if running this directly for testing
    if not os.getenv("BASE_PROJECT_DIR"):
        os.environ["BASE_PROJECT_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
        print(f"Temporarily set BASE_PROJECT_DIR to: {os.environ['BASE_PROJECT_DIR']}")

    test_logger = setup_logger("ToolManager_Test", os.path.join(os.environ["BASE_PROJECT_DIR"], "logs/tool_manager_test.log"))
    manager = ToolManager(minion_id="test_minion_007", logger=test_logger)
    
    # This command assumes your Super-Tool can handle a simple echo or version check.
    # Adjust this test command based on your Super-Tool's capabilities.
    # A common test for the computer-use MCP server might be listing files in a known directory.
    test_command = "List files in the current directory." 
    # test_command = "What is your version?" # If Super-Tool has such a command
    
    test_logger.info(f"Sending test command to Super-Tool: '{test_command}'")
    result = manager.execute_super_tool_command(test_command)
    test_logger.info(f"Test command result: {result}")
    print(f"Test command result: {result}")
