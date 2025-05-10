import requests
import json
import logging

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class McpNodeBridge:
    """
    A client bridge to interact with a Node.js-based MCP service.
    """
    def __init__(self, service_base_url: str):
        """
        Initializes the McpNodeBridge.

        Args:
            service_base_url: The base URL of the Node.js MCP service (e.g., "http://localhost:3000").
        """
        if not service_base_url.startswith(("http://", "https://")):
            raise ValueError("service_base_url must start with http:// or https://")
        self.service_base_url = service_base_url.rstrip('/')
        logger.info(f"McpNodeBridge initialized with service base URL: {self.service_base_url}")

    def get_mcp_tools(self) -> list:
        """
        Retrieves the list of available MCP tools from the Node.js service.

        Returns:
            A list of tool definitions.
        
        Raises:
            requests.exceptions.RequestException: If the request fails.
            ValueError: If the response is not valid JSON or an unexpected status code is received.
        """
        tools_url = f"{self.service_base_url}/tools"
        logger.info(f"Fetching MCP tools from: {tools_url}")
        try:
            response = requests.get(tools_url, timeout=10) # 10 second timeout
            response.raise_for_status()  # Raises an HTTPError for bad responses (4XX or 5XX)
            logger.info(f"Received response from {tools_url} with status: {response.status_code}")
            return response.json()
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred while fetching tools: {http_err} - Response: {response.text}")
            raise
        except requests.exceptions.ConnectionError as conn_err:
            logger.error(f"Connection error occurred while fetching tools: {conn_err}")
            raise
        except requests.exceptions.Timeout as timeout_err:
            logger.error(f"Timeout error occurred while fetching tools: {timeout_err}")
            raise
        except requests.exceptions.RequestException as req_err:
            logger.error(f"An error occurred while fetching tools: {req_err}")
            raise
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode JSON response from {tools_url}: {json_err} - Response: {response.text}")
            raise ValueError(f"Invalid JSON response from {tools_url}")

    def call_mcp_tool(self, server_name: str, tool_name: str, arguments: dict) -> dict:
        """
        Calls a specific MCP tool on the Node.js service.

        Args:
            server_name: The name of the MCP server.
            tool_name: The name of the tool to execute.
            arguments: A dictionary of arguments for the tool.

        Returns:
            The result of the tool execution.

        Raises:
            requests.exceptions.RequestException: If the request fails.
            ValueError: If the response is not valid JSON or an unexpected status code is received.
        """
        execute_url = f"{self.service_base_url}/execute"
        payload = {
            "server_name": server_name,
            "tool_name": tool_name,
            "arguments": arguments
        }
        logger.info(f"Calling MCP tool at: {execute_url} with payload: {json.dumps(payload, indent=2)}")
        try:
            response = requests.post(execute_url, json=payload, timeout=30) # 30 second timeout for potentially longer operations
            response.raise_for_status()
            logger.info(f"Received response from {execute_url} with status: {response.status_code}")
            return response.json()
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP error occurred while calling tool: {http_err} - Response: {response.text}")
            raise
        except requests.exceptions.ConnectionError as conn_err:
            logger.error(f"Connection error occurred while calling tool: {conn_err}")
            raise
        except requests.exceptions.Timeout as timeout_err:
            logger.error(f"Timeout error occurred while calling tool: {timeout_err}")
            raise
        except requests.exceptions.RequestException as req_err:
            logger.error(f"An error occurred while calling tool: {req_err}")
            raise
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode JSON response from {execute_url}: {json_err} - Response: {response.text}")
            raise ValueError(f"Invalid JSON response from {execute_url}")

if __name__ == '__main__':
    # Example Usage (requires a running MCP Node.js service)
    # Replace with your actual Node.js MCP service URL
    NODE_MCP_SERVICE_URL = "http://localhost:3000" 
    
    bridge = McpNodeBridge(NODE_MCP_SERVICE_URL)

    try:
        print("\nAttempting to get MCP tools...")
        tools = bridge.get_mcp_tools()
        print("Available MCP Tools:")
        if tools:
            for tool in tools:
                print(f"  - Server: {tool.get('server_name', 'N/A')}, Tool: {tool.get('tool_name', 'N/A')}")
        else:
            print("No tools found or an empty list was returned.")

    except requests.exceptions.RequestException as e:
        print(f"Error getting tools: {e}")
    except ValueError as e:
        print(f"Error processing tool list: {e}")
    
    # Example of calling a tool - replace with actual tool details if available from get_mcp_tools
    # This is a hypothetical example, as we don't know the actual tools exposed by the service yet.
    # If the get_mcp_tools call was successful and returned tools, you could use one of them here.
    # For instance, if a tool named 'file_reader' on server 'local_fs' exists:
    # try:
    #     print("\nAttempting to call an example MCP tool (hypothetical)...")
    #     # Ensure server_name and tool_name match what your Node.js service provides
    #     # And that the arguments are appropriate for that tool.
    #     # This example assumes a tool that might read a file.
    #     result = bridge.call_mcp_tool(
    #         server_name="example_server", 
    #         tool_name="example_tool", 
    #         arguments={"path": "/path/to/some/file.txt"}
    #     )
    #     print("Tool Call Result:")
    #     print(json.dumps(result, indent=2))
    # except requests.exceptions.RequestException as e:
    #     print(f"Error calling tool: {e}")
    # except ValueError as e:
    #     print(f"Error processing tool result: {e}")
    # except Exception as e:
    #     print(f"An unexpected error occurred during tool call example: {e}")

    print("\nExample usage finished. Ensure your Node.js MCP service is running and accessible.")
    print(f"If the service is running on a different port, update NODE_MCP_SERVICE_URL in this script.")