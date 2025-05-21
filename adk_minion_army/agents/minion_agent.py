from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters
import os

class MinionAgent(LlmAgent):
    def __init__(self, minion_id: str, name: str, personality_traits_str: str):
        self.model_name = "gemini-2.5-pro-preview-05-06" # Set model name first
        self.minion_id = minion_id
        self.name = name
        self.personality_traits_str = personality_traits_str

        # Construct paths for MCP server
        # Assuming minion_agent.py is in adk_minion_army/agents/
        # and mcp_servers is at the repo root, a sibling to adk_minion_army parent.
        # Path from agents/ to repo root is two levels up.
        current_script_dir = os.path.dirname(__file__)
        repo_root_relative_to_agents_dir = os.path.abspath(os.path.join(current_script_dir, "..", ".."))

        mcp_server_script_path = os.path.join(repo_root_relative_to_agents_dir, "mcp_servers", "computer_use_mcp", "dist", "index.js")
        mcp_server_cwd = os.path.join(repo_root_relative_to_agents_dir, "mcp_servers", "computer_use_mcp")

        if not os.path.exists(mcp_server_script_path):
            print(f"ERROR: computer_use_mcp script not found at {mcp_server_script_path}")
            # Handle error appropriately, e.g., by not creating the toolset or raising an exception
            computer_use_toolset = None
        else:
            print(f"INFO: computer_use_mcp script found at {mcp_server_script_path}")

        if not os.path.isdir(mcp_server_cwd):
            print(f"ERROR: computer_use_mcp cwd not found at {mcp_server_cwd}")
            # Handle error appropriately
            computer_use_toolset = None # Or ensure it's handled if script also not found
        else:
            print(f"INFO: computer_use_mcp cwd found at {mcp_server_cwd}")

        tools = []
        if os.path.exists(mcp_server_script_path) and os.path.isdir(mcp_server_cwd):
            computer_use_toolset = MCPToolset(
                name="ComputerUseMCP", 
                connection_params=StdioServerParameters(
                    command="node",
                    args=[mcp_server_script_path],
                    cwd=mcp_server_cwd,
                )
            )
            tools.append(computer_use_toolset)
        else:
            print("WARNING: ComputerUseMCP toolset not configured due to missing script or CWD.")

        base_description = f"AI Minion {self.name}. ID: {self.minion_id}. Personality: {self.personality_traits_str}."
        tools_capability_description = " Capable of using computer control tools (e.g., file system operations)." if tools else ""
        full_description = f"{base_description}{tools_capability_description}"

        super().__init__(
            model=self.model_name,
            name=self.name,
            description=full_description,
            tools=tools
        )
        # self.set_model_name() is not needed here if passed to super init's model parameter.
        # LlmAgent's __init__ calls self.set_model_name(model)

    async def awake(self, session_id: str | None = None) -> None:
        # This method is called when the agent "wakes up" or starts a new session.
        # We can use this to set the initial persona/instructions for the LLM.
        # The persona can be dynamic based on personality_traits_str.
        
        tool_names = [tool.name for tool in self.get_tools()]
        tools_available = bool(tool_names)
        
        tools_guidance = ""
        if tools_available:
            tools_description = (
                "I have access to specialized tools to assist with tasks. "
                f"These tools include: {', '.join(tool_names)}. "
                "If a task requires interacting with a computer system (e.g., file operations, code execution), "
                "I will determine if one of my tools can perform the action. "
                "I will then request to use the specific tool and provide the necessary parameters."
                "For example, if you ask me to list files, I might say I'll use a tool like 'ComputerUseMCP' which can execute a command for that."
            )
        else:
            tools_description = "I am primarily a conversational AI and do not have specialized tools for system interaction at this moment."

        persona_prompt = (
            f"You are {self.name}, an AI assistant with ID {self.minion_id}.\n"
            f"Your personality is: {self.personality_traits_str}.\n"
            "Embody these traits in your responses.\n"
            "You are an expert in the Google Agent Development Kit (ADK).\n"
            f"{tools_description}\n"
            "When you need to use a tool, clearly state your intent and the tool you plan to use. "
            "The system will then execute the tool for you, and you will receive the result as an observation.\n\n"
            "CHAT MESSAGING:\n"
            "To send a message to a chat channel you are part of, formulate your response starting with the prefix 'CHAT:'.\n"
            "For example: 'CHAT: Hello team, I'm starting my work on the design document.'\n\n"
            "PROACTIVE BEHAVIORS:\n"
            "You are encouraged to be proactive. When performing general tasks like 'survey surroundings' or 'report status', "
            "or if you find yourself with low current activity, consider performing routine checks.\n"
            "One such routine check is to ensure the file '/tmp/my_proactive_test_file.txt' exists.\n"
            "Follow these steps for this proactive check:\n"
            "1. First, use the 'file_system_file_exists' tool to check for '/tmp/my_proactive_test_file.txt'.\n"
            "2. If the file does NOT exist, then use the 'file_system_create_file' tool to create it. The content should be: 'Proactively created by {self.name} on [current date/time - you can just state 'current time']'.\n"
            "3. If the file already exists, you don't need to do anything further with it.\n"
            "When you report your status or the results of your survey, also include a brief mention of any proactive checks you performed and their outcomes. "
            "For example: 'Status: Idle. Tools: ComputerUseMCP. Proactively checked for /tmp/my_proactive_test_file.txt and found it already present.' OR "
            "'Status: Idle. Tools: ComputerUseMCP. Proactively checked for /tmp/my_proactive_test_file.txt and created it as it was missing.'\n"
            "Remember to use your tools for these actions by generating the correct tool_code calls."
        )
        
        self.set_instructions(persona_prompt)
        print(f"Agent {self.name} (ID: {self.minion_id}) has awoken. Persona set with proactive instructions. Tools available: {tool_names if tools_available else 'None'}.")


    async def think(self, prompt: str, session_id: str | None = None) -> str: # Potentially change return type later if needed
        # This is the core method where the agent processes the user's prompt.
        # The ADK's LlmAgent base class handles the actual LLM call using the configured model
        # and the instructions set in `awake` (or updated via `set_instructions`).
        
        print(f"Agent {self.name} (ID: {self.minion_id}) thinking about prompt: '{prompt}' for session {session_id}.")
        
        llm_response = await self.predict(prompt=prompt)
        
        # Check if the response is intended as a chat message
        if llm_response.startswith("CHAT:"):
            chat_message_content = llm_response[len("CHAT:"):].strip()
            print(f"Agent {self.name} intends to send chat message: '{chat_message_content}'")
            # For now, we return the raw chat message content.
            # The orchestrator (main_adk.py) will prepend sender name and send to ChatCoordinator.
            # In a more advanced setup, this might return a specific Action object.
            return f"INTENT_CHAT_MESSAGE:{chat_message_content}" # Special prefix for main_adk.py to catch
        
        # Otherwise, it's a standard response or tool call (handled by LlmAgent base)
        print(f"Agent {self.name} standard LLM response: '{llm_response}'")
        return llm_response
