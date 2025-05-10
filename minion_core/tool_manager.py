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
    def __init__(self, minion_id, logger=None, mcp_bridge=None):
        self.minion_id = minion_id
        self.logger = logger if logger else setup_logger(f"ToolManager_{minion_id}", f"logs/tool_manager_{minion_id}.log")
        self.mcp_bridge = mcp_bridge
        self.tools = {}  # Stores all registered tools {adapted_tool_name: tool_definition}

        # Validate paths for the legacy Super-Tool
        # This tool might be deprecated or integrated differently later
        self.legacy_super_tool_config_valid = True
        if not os.path.exists(MCP_SUPER_TOOL_SCRIPT_PATH):
            self.logger.warning(f"Legacy MCP Super-Tool script not found at: {MCP_SUPER_TOOL_SCRIPT_PATH}")
            self.legacy_super_tool_config_valid = False
        if not os.path.exists(MCP_CONFIG_PATH_FOR_SUPER_TOOL):
            self.logger.warning(f"Legacy MCP Super-Tool config not found at: {MCP_CONFIG_PATH_FOR_SUPER_TOOL}")
            self.legacy_super_tool_config_valid = False
        if not os.path.exists(SUPER_TOOL_ENV_PATH):
            self.logger.warning(f"Legacy MCP Super-Tool .env file not found at: {SUPER_TOOL_ENV_PATH}. Super-Tool might fail.")
            # Not setting legacy_super_tool_config_valid to False, as it might still work if env vars are global

        if self.mcp_bridge:
            self.logger.info("MCP Bridge provided. Discovering and registering MCP tools.")
            self._discover_and_register_mcp_tools(self.mcp_bridge)
        else:
            self.logger.info("No MCP Bridge provided. MCP tools will not be available.")

    def _discover_and_register_mcp_tools(self, mcp_bridge):
        self.logger.debug("Attempting to fetch MCP tools from the bridge...")
        try:
            mcp_tools_definitions = mcp_bridge.get_mcp_tools()
            if not mcp_tools_definitions:
                self.logger.warning("MCP Bridge returned no tool definitions.")
                return

            self.logger.info(f"Received {len(mcp_tools_definitions)} tool definition(s) from MCP bridge.")
            for tool_def in mcp_tools_definitions:
                server_name = tool_def.get("server_name")
                tool_name = tool_def.get("tool_name")
                description = tool_def.get("description", "No description provided.")
                # MCP standard is 'input_schema', but let's be flexible
                parameters_schema = tool_def.get("input_schema") or tool_def.get("parameters_schema") or tool_def.get("parameters") or {"type": "object", "properties": {}}


                if not server_name or not tool_name:
                    self.logger.warning(f"Skipping MCP tool due to missing server_name or tool_name: {tool_def}")
                    continue

                adapted_tool_name = f"mcp::{server_name}::{tool_name}"
                
                self.tools[adapted_tool_name] = {
                    "name": adapted_tool_name,
                    "description": description,
                    "parameters_schema": parameters_schema,
                    "is_mcp_tool": True,
                    "server_name": server_name,
                    "original_tool_name": tool_name # The name known by the MCP server/bridge
                }
                self.logger.info(f"Registered MCP tool: {adapted_tool_name}")

        except Exception as e:
            self.logger.error(f"Failed to discover or register MCP tools: {e}", exc_info=True)

    def get_tool_definitions_for_prompt(self):
        """
        Returns a list of tool definitions suitable for inclusion in an LLM prompt.
        This includes both MCP tools and any 'native' tools like the legacy Super-Tool.
        """
        tool_defs_for_prompt = []

        # Add definition for the legacy SuperTool if its configuration is valid
        # The name "SuperTool_MCP_ComputerControl" should match what the LLM is trained/prompted to use.
        if self.legacy_super_tool_config_valid:
            tool_defs_for_prompt.append({
                "name": "SuperTool_MCP_ComputerControl",
                "description": "A legacy tool that can control aspects of the local computer via natural language commands. Use this for general computer interaction tasks if no specific MCP tool is more suitable.",
                "parameters_schema": {
                    "type": "object",
                    "properties": {
                        "natural_language_command": {
                            "type": "string",
                            "description": "The full natural language command to be executed by the Super-Tool."
                        }
                    },
                    "required": ["natural_language_command"]
                }
            })

        # Add registered MCP tools
        for adapted_name, tool_info in self.tools.items():
            if tool_info.get("is_mcp_tool"):
                tool_defs_for_prompt.append({
                    "name": adapted_name,
                    "description": tool_info["description"],
                    "parameters_schema": tool_info["parameters_schema"]
                })
        
        self.logger.debug(f"Prepared {len(tool_defs_for_prompt)} tool definitions for LLM prompt.")
        return tool_defs_for_prompt

    def execute_tool(self, tool_name: str, arguments: dict):
        """
        Executes a specified tool by name with the given arguments.
        Differentiates between MCP tools and the legacy Super-Tool.
        """
        self.logger.info(f"Attempting to execute tool: '{tool_name}' with arguments: {str(arguments)[:100]}...")

        if tool_name in self.tools and self.tools[tool_name].get("is_mcp_tool"):
            tool_def = self.tools[tool_name]
            self.logger.debug(f"Executing MCP tool '{tool_name}' via bridge.")
            if not self.mcp_bridge:
                self.logger.error(f"Cannot execute MCP tool '{tool_name}': MCP bridge is not available.")
                return f"ERROR_MCP_BRIDGE_NOT_AVAILABLE"
            try:
                return self.mcp_bridge.call_mcp_tool(
                    server_name=tool_def["server_name"],
                    tool_name=tool_def["original_tool_name"],
                    arguments=arguments
                )
            except Exception as e:
                self.logger.error(f"Error calling MCP tool '{tool_name}': {e}", exc_info=True)
                return f"ERROR_MCP_TOOL_CALL_FAILED: {e}"

        elif tool_name == "SuperTool_MCP_ComputerControl":
            if not self.legacy_super_tool_config_valid:
                self.logger.error("Legacy Super-Tool configuration is invalid. Cannot execute.")
                return "ERROR_SUPER_TOOL_CONFIG_INVALID"
            
            nl_command = None
            if isinstance(arguments, dict):
                nl_command = arguments.get("natural_language_command")
            elif isinstance(arguments, str): # Should not happen if LLM follows schema
                self.logger.warning("Received string argument for SuperTool, expected dict. Using as command.")
                nl_command = arguments
            
            if not nl_command:
                self.logger.error(f"Invalid or missing 'natural_language_command' in arguments for SuperTool: {arguments}")
                return "ERROR_INVALID_ARGUMENTS_FOR_SUPER_TOOL: Missing 'natural_language_command'"
            
            self.logger.debug(f"Executing legacy Super-Tool with command: {nl_command[:100]}...")
            return self._execute_legacy_super_tool(nl_command)
        else:
            self.logger.error(f"Tool '{tool_name}' not found or not executable.")
            return f"ERROR_TOOL_NOT_FOUND: {tool_name}"

    def _execute_legacy_super_tool(self, natural_language_command: str):
        """
        Internal method to execute the legacy Node.js MCP Super-Tool.
        (Formerly execute_super_tool_command)
        """
        # This method's content is the same as the old execute_super_tool_command
        # Ensure self.legacy_super_tool_config_valid is checked before calling this.
        self.logger.info(f"Preparing to execute legacy Super-Tool command: '{natural_language_command[:100]}...'")
        
        command_array = [
            "node",
            MCP_SUPER_TOOL_SCRIPT_PATH,
            "--prompt", natural_language_command,
            "--config", MCP_CONFIG_PATH_FOR_SUPER_TOOL,
            "--envFile", SUPER_TOOL_ENV_PATH
        ]
        
        self.logger.debug(f"Executing legacy Super-Tool with command: {' '.join(command_array)}")

        try:
            timeout_seconds = 300
            process = subprocess.run(
                command_array,
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
                cwd=os.path.dirname(MCP_SUPER_TOOL_SCRIPT_PATH)
            )

            if process.returncode == 0:
                self.logger.info(f"Legacy Super-Tool executed successfully. Output length: {len(process.stdout)}")
                self.logger.debug(f"Legacy Super-Tool stdout: {process.stdout[:500]}...")
                return process.stdout.strip()
            else:
                self.logger.error(f"Legacy Super-Tool execution failed with return code {process.returncode}.")
                self.logger.error(f"Legacy Super-Tool stderr: {process.stderr.strip()[:1000]}...")
                return f"ERROR_SUPER_TOOL_EXECUTION_FAILED: Code {process.returncode}. Stderr: {process.stderr.strip()}"

        except subprocess.TimeoutExpired:
            self.logger.error(f"Legacy Super-Tool command timed out after {timeout_seconds} seconds.")
            return "ERROR_SUPER_TOOL_TIMEOUT"
        except FileNotFoundError: # Should be caught by self.legacy_super_tool_config_valid
            self.logger.critical(f"'node' command not found or legacy Super-Tool script path incorrect.")
            return "ERROR_SUPER_TOOL_NODE_NOT_FOUND"
        except Exception as e:
            self.logger.critical(f"An unexpected error occurred while executing legacy Super-Tool command: {e}", exc_info=True)
            return f"ERROR_SUPER_TOOL_UNEXPECTED: {e}"

    # Old execute_super_tool_command - to be removed or made private if execute_tool is the public interface
    # For now, renamed to _execute_legacy_super_tool and called by execute_tool

    def get_mcp_tool_capabilities_for_agent_card(self):
        """
        Returns a list of MCP tool capabilities formatted for the agent card.
        """
        mcp_capabilities = []
        for tool_name_adapted, tool_def in self.tools.items():
            if tool_def.get("is_mcp_tool"):
                capability = {
                    "type": "mcp_tool",
                    "name": tool_def.get("original_tool_name"), # The tool's actual name on the server
                    "server_name": tool_def.get("server_name"),
                    "description": tool_def.get("description", "No description provided.")
                    # "version": tool_def.get("version") # If version info becomes available
                }
                mcp_capabilities.append(capability)
        self.logger.debug(f"Prepared {len(mcp_capabilities)} MCP tool capabilities for agent card.")
        return mcp_capabilities

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
    
    # Mock McpNodeBridge for testing ToolManager standalone
    class MockMcpBridge:
        def get_mcp_tools(self):
            test_logger.info("MockMcpBridge.get_mcp_tools() called")
            return [
                {
                    "server_name": "test_server",
                    "tool_name": "echo_tool",
                    "description": "A simple echo tool for testing.",
                    "input_schema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                },
                {
                    "server_name": "another_server",
                    "tool_name": "calculator",
                    "description": "A simple calculator.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "num1": {"type": "number"},
                            "num2": {"type": "number"},
                            "operation": {"type": "string", "enum": ["add", "subtract"]}
                        },
                        "required": ["num1", "num2", "operation"],
                    },
                }
            ]
        def call_mcp_tool(self, server_name, tool_name, arguments):
            test_logger.info(f"MockMcpBridge.call_mcp_tool({server_name}, {tool_name}, {arguments}) called")
            if tool_name == "echo_tool":
                return f"Echo from {server_name}: {arguments.get('message')}"
            elif tool_name == "calculator":
                op = arguments.get("operation")
                n1 = arguments.get("num1")
                n2 = arguments.get("num2")
                if op == "add": return n1 + n2
                if op == "subtract": return n1 - n2
                return "Unknown operation"
            return "Unknown mock tool"

    mock_bridge_instance = MockMcpBridge()
    manager_with_mcp = ToolManager(minion_id="test_mcp_minion", logger=test_logger, mcp_bridge=mock_bridge_instance)

    test_logger.info("--- Testing MCP Tool Execution ---")
    mcp_tool_result = manager_with_mcp.execute_tool("mcp::test_server::echo_tool", {"message": "Hello MCP!"})
    test_logger.info(f"MCP echo_tool result: {mcp_tool_result}")
    print(f"MCP echo_tool result: {mcp_tool_result}")

    mcp_calc_result = manager_with_mcp.execute_tool("mcp::another_server::calculator", {"num1": 5, "num2": 3, "operation": "add"})
    test_logger.info(f"MCP calculator result: {mcp_calc_result}")
    print(f"MCP calculator result: {mcp_calc_result}")
    
    test_logger.info("--- Testing Tool Definitions for Prompt ---")
    prompt_tools = manager_with_mcp.get_tool_definitions_for_prompt()
    test_logger.info(f"Tools for prompt: {json.dumps(prompt_tools, indent=2)}")
    print(f"Tools for prompt: {json.dumps(prompt_tools, indent=2)}")

    test_logger.info("--- Testing Legacy Super-Tool Execution (if configured) ---")
    # This command assumes your Super-Tool can handle a simple echo or version check.
    # Adjust this test command based on your Super-Tool's capabilities.
    test_command_legacy = "List files in the current directory."
    
    if manager_with_mcp.legacy_super_tool_config_valid:
        legacy_result = manager_with_mcp.execute_tool("SuperTool_MCP_ComputerControl", {"natural_language_command": test_command_legacy})
        test_logger.info(f"Legacy Super-Tool command result: {legacy_result}")
        print(f"Legacy Super-Tool command result: {legacy_result}")
    else:
        test_logger.warning("Legacy Super-Tool not configured or paths invalid, skipping its execution test.")
        print("Legacy Super-Tool not configured or paths invalid, skipping its execution test.")

    test_logger.info("--- Testing Non-existent Tool ---")
    non_existent_result = manager_with_mcp.execute_tool("non_existent_tool", {"arg": "value"})
    test_logger.info(f"Non-existent tool result: {non_existent_result}")
    print(f"Non-existent tool result: {non_existent_result}")
