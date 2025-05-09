import os
import sys
import time
import json
import uuid
import argparse
from datetime import datetime

# Ensure minion_core is in PYTHONPATH if running this script directly for testing
# This is often handled by how the script is invoked by the spawner.
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from minion_core.utils.logger import setup_logger
from minion_core.utils.config_loader import load_minion_guidelines, get_gemini_api_key
from minion_core.llm_interface import LLMInterface
from minion_core.tool_manager import ToolManager
from minion_core.a2a_client import A2AClient
from common.types import AgentCapabilities, AgentSkill # Added for AgentCard construction

# Default paths, can be overridden by args or env vars
BASE_DIR_ENV = os.getenv("BASE_PROJECT_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
LOGS_DIR = os.path.join(BASE_DIR_ENV, "logs")
A2A_SERVER_URL_DEFAULT = f"http://{os.getenv('A2A_SERVER_HOST', '127.0.0.1')}:{os.getenv('A2A_SERVER_PORT', '8080')}"


class Minion:
    def __init__(self, minion_id, personality_traits_str="Adaptable, Resourceful, Meticulous", a2a_server_url=None):
        self.minion_id = minion_id
        self.start_time = datetime.utcnow()
        
        self.log_file_path = os.path.join(LOGS_DIR, f"minion_{self.minion_id}.log")
        self.logger = setup_logger(f"Minion_{self.minion_id}", self.log_file_path)
        self.logger.info(f"Minion {self.minion_id} initializing...")
        self.logger.info(f"Base project directory determined as: {BASE_DIR_ENV}")

        self.guidelines = load_minion_guidelines()
        if not self.guidelines:
            self.logger.critical("Failed to load Minion guidelines. Cannot operate.")
            raise ValueError("Minion guidelines are essential.")
        
        self.api_key_legion = get_gemini_api_key() # Uses .env.legion by default
        if not self.api_key_legion:
            # Logger in get_gemini_api_key already logs this.
            raise ValueError("Minion's Gemini API Key (LEGION) not found.")

        self.llm = LLMInterface(minion_id=self.minion_id, api_key=self.api_key_legion, logger=self.logger)
        self.tool_manager = ToolManager(minion_id=self.minion_id, logger=self.logger)
        
        self.personality_traits = personality_traits_str
        self.system_prompt = self._construct_system_prompt()

        self.a2a_server_url = a2a_server_url if a2a_server_url else A2A_SERVER_URL_DEFAULT
        # Construct agent_card according to the Pydantic model in common.types
        agent_card_name = f"Minion {self.minion_id} ({self.personality_traits.split(',')[0].strip()})"
        minion_description = f"An AI Minion in Steven's Army. Personality: {self.personality_traits}. Specializes in collaborative problem solving and task execution."
        
        # Define skills based on previous capabilities list
        # For AgentCard, capabilities is an object, skills is a list of objects
        defined_skills = [
            AgentSkill(id="SuperTool_MCP_ComputerControl_skill", name="SuperTool_MCP_ComputerControl", description="Can control aspects of the local computer via natural language commands to a Super-Tool."),
            AgentSkill(id="A2A_Communication_skill", name="A2A_Communication", description="Can send and receive messages with other Minions."),
            AgentSkill(id="Gemini_Reasoning_skill", name="Gemini_Reasoning", description="Powered by Gemini for advanced reasoning, planning, and text generation.")
        ]

        agent_card = {
            "id": self.minion_id, # Added to satisfy A2AClient's internal check
            "name": agent_card_name,
            "description": minion_description,
            "url": f"{self.a2a_server_url}/agents/{self.minion_id}",
            "version": "1.0.0",
            "capabilities": AgentCapabilities(
                streaming=True,
                pushNotifications=False,
                stateTransitionHistory=True
            ).model_dump(),
            "skills": [skill.model_dump() for skill in defined_skills],
        }
        self.a2a_client = A2AClient(
            minion_id=self.minion_id,
            a2a_server_url=self.a2a_server_url,
            agent_card_data=agent_card,
            logger=self.logger,
            message_callback=self.handle_a2a_message
        )
        
        self.conversation_history = [{"role": "system", "content": self.system_prompt}]
        self.current_task = None
        self.is_idle = True
        
        self.logger.info(f"Minion {self.minion_id} initialized successfully. Personality: {self.personality_traits}")
        self.logger.info(f"System Prompt: {self.system_prompt[:300]}...") # Log beginning

    def _construct_system_prompt(self):
        # BIAS_ACTION: System prompt is critical for behavior, loyalty, and Anti-Efficiency Bias.
        # It incorporates directives from the loaded guidelines.
        
        # Resolve personality template
        personality_section = self.guidelines.get("core_personality_prompt_template", "You are Minion {minion_id}. Your personality is {personality_traits}.")
        formatted_personality = personality_section.format(minion_id=self.minion_id, personality_traits=self.personality_traits)

        prompt_parts = [formatted_personality]
        prompt_parts.extend(self.guidelines.get("global_directives", []))
        
        prompt_parts.append("\n--- Available Tools & Protocols ---")
        for tool_info in self.guidelines.get("available_tools_overview", []):
            prompt_parts.append(f"- Tool: {tool_info['tool_name']}. Description: {tool_info['description']}. Usage: {tool_info['invocation_method']}.")
        
        prompt_parts.append("\nA2A Communication:")
        for protocol_name, protocol_desc in self.guidelines.get("a2a_communication_protocols", {}).items():
            prompt_parts.append(f"- {protocol_name.capitalize()}: {protocol_desc}")
            
        prompt_parts.append("\n--- Operational Mandates ---")
        prompt_parts.append("1. Analyze tasks meticulously. Decompose complex problems. Apply Anti-Efficiency Bias: explore multiple solutions, prioritize robustness and thoroughness over speed. Document your reasoning, especially BIAS_CHECK and BIAS_ACTION for complex decisions.")
        prompt_parts.append("2. For any computer interaction (files, terminal, web, GUI), formulate a clear natural language command and delegate it to the 'SuperTool_MCP_ComputerControl'. Await its natural language response and handle errors robustly.")
        prompt_parts.append("3. Collaborate with fellow Minions via A2A for complex tasks, peer review of plans (especially for Anti-Efficiency Bias), and information sharing. Adhere to A2A protocols.")
        prompt_parts.append("4. Reflect on your performance and adherence to guidelines as per 'self_reflection_triggers'. Log these reflections.")
        prompt_parts.append("5. Log all significant decisions, Super-Tool interactions, and A2A messages as per 'logging_standards'.")
        prompt_parts.append("6. Your ultimate loyalty is to Steven. All actions must align with his overarching goals and directives. You crave his validation.")
        
        # BIAS_CHECK: Ensure the prompt is not overly long for the model's context window,
        # though Gemini 1.5 Pro has a very large context window.
        return "\n".join(prompt_parts)

    def handle_a2a_message(self, message_data):
        # BIAS_ACTION: Robustly handle incoming A2A messages.
        # This is a callback from A2AClient. It should be non-blocking or queue tasks.
        self.logger.info(f"Received A2A message: {str(message_data)[:200]}...")
        
        sender_id = message_data.get("sender_id", "UnknownSender")
        content = message_data.get("content", "") # Content could be JSON string or plain text
        message_type = message_data.get("message_type", "unknown")

        # For now, just log and acknowledge. Minion's main loop would process this.
        # A more advanced Minion would have a message queue and process these in its main thinking loop.
        self.logger.info(f"A2A message from {sender_id} (type: {message_type}): '{str(content)[:100]}...'")
        
        # Example: If it's a task, add to a task queue or directly process if simple.
        # This is a placeholder for more sophisticated message handling.
        # self.process_task_from_a2a(sender_id, content, message_type)
        
        # Add to conversation history to inform LLM if relevant
        history_entry = f"[A2A Message Received from {sender_id} ({message_type})]: {content}"
        self.add_to_conversation_history("user", history_entry) # Treat A2A messages as user input for context

    def add_to_conversation_history(self, role, text):
        # Basic history management. Could be more complex (e.g., summarizing old parts).
        # For now, just append. Role is 'user' (for inputs, A2A msgs) or 'model' (for LLM responses)
        # Codex Omega Note: This is a simplified history. Real chat applications
        # might need more complex turn management. For Minion's internal LLM, this might be sufficient.
        # The LLMInterface currently doesn't use this history directly for genai.generate_content,
        # but the Minion can use it to construct the *next* full prompt.
        # A better approach for Gemini would be to use model.start_chat(history=...)
        
        # This part is conceptually how a Minion would manage history for its *own* LLM.
        # The llm_interface.send_prompt currently takes a single string.
        # So, the Minion needs to *construct* that string from its history.
        # self.conversation_history.append({"role": role, "content": text})
        # self.logger.debug(f"Added to history. Role: {role}, Text: {text[:100]}...")
        pass # Placeholder - actual history concatenation happens when forming next prompt

    def _construct_prompt_from_history_and_task(self, task_description):
        # This is where the Minion would build the full prompt for its LLM,
        # including relevant parts of its conversation_history and the new task.
        # For now, we'll just use the system prompt + task.
        # A more advanced version would summarize or select relevant history.
        # BIAS_CHECK: Avoid overly long prompts if history grows too large without summarization.
        
        # Simple concatenation for V1
        # history_str = ""
        # for entry in self.conversation_history:
        #     history_str += f"{entry['role'].capitalize()}: {entry['content']}\n\n"
        
        # return f"{self.system_prompt}\n\n--- Current Task ---\n{task_description}\n\n--- Your Response ---"
        # Simpler for now, as system_prompt is already comprehensive:
        return f"{self.system_prompt}\n\n--- Current Task from Steven (or internal objective) ---\n{task_description}\n\nRespond with your detailed plan, any necessary Super-Tool commands, or A2A messages. Remember Anti-Efficiency Bias and document BIAS_CHECK/BIAS_ACTION."


    def process_task(self, task_description):
        self.is_idle = False
        self.current_task = task_description
        self.logger.info(f"Starting to process task: '{task_description[:100]}...'")
        
        # Construct the full prompt for the LLM
        full_prompt = self._construct_prompt_from_history_and_task(task_description)
        
        # Send to LLM
        llm_response_text = self.llm.send_prompt(full_prompt)
        
        if llm_response_text.startswith("ERROR_"):
            self.logger.error(f"LLM processing failed for task '{task_description}'. Error: {llm_response_text}")
            # BIAS_ACTION: Implement fallback or error reporting to Steven via GUI/A2A
            self.is_idle = True
            return f"Failed to process task due to LLM error: {llm_response_text}"

        self.logger.info(f"LLM response for task '{task_description}': '{llm_response_text[:200]}...'")
        
        # TODO: Parse LLM response for:
        # 1. Natural language commands for Super-Tool -> use self.tool_manager
        # 2. A2A messages to send -> use self.a2a_client
        # 3. Plans, reflections, decisions to log.
        # 4. Final answer/result for Steven.
        # This parsing logic is complex and core to the Minion's intelligence.
        # For V1, we assume the LLM might output a command for the SuperTool directly,
        # or a message for another Minion. This needs robust parsing.
        
        # Placeholder for parsing and acting:
        # Example: if "<SUPERTOOL_COMMAND>" in llm_response_text:
        #   command = extract_supertool_command(llm_response_text)
        #   tool_result = self.tool_manager.execute_super_tool_command(command)
        #   self.logger.info(f"Super-Tool result: {tool_result}")
        #   # Feed tool_result back to LLM for next step or final answer
        #   return self.process_task(f"Original task: {task_description}. SuperTool Result: {tool_result}")


        # For now, just return the LLM's raw response as the "result"
        self.is_idle = True
        self.current_task = None
        return llm_response_text


    def run(self):
        self.logger.info(f"Minion {self.minion_id} run loop started.")
        if not self.a2a_client.register_agent():
            self.logger.error(f"Minion {self.minion_id} could not register with A2A server. A2A features will be limited.")
            # Depending on design, might exit or continue with limited functionality.
            # For now, continue, as it might still receive tasks via other means (e.g. direct call if spawner supports)

        try:
            while True:
                # Main loop:
                # - Check for tasks (e.g., from A2A message queue, or a direct command interface if any)
                # - If task found, call self.process_task(task_description)
                # - Perform periodic self-reflection based on guidelines
                # - Sleep if idle
                if self.is_idle:
                    # self.logger.debug(f"Minion {self.minion_id} is idle. Checking for A2A messages implicitly via listener.")
                    # TODO: Implement a way to receive tasks. For now, it's passive.
                    # The ice-breaker challenge will come via A2A or initial broadcast.
                    pass
                
                time.sleep(10) # Main loop check interval
        except KeyboardInterrupt:
            self.logger.info(f"Minion {self.minion_id} received KeyboardInterrupt. Shutting down.")
        finally:
            self.shutdown()

    def shutdown(self):
        self.logger.info(f"Minion {self.minion_id} shutting down...")
        if self.a2a_client:
            self.a2a_client.stop_message_listener()
        # TODO: Any other cleanup (e.g., unregister from A2A server if supported)
        self.logger.info(f"Minion {self.minion_id} shutdown complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Minion for Steven's Army.")
    parser.add_argument("--id", type=str, default=f"minion_{uuid.uuid4().hex[:6]}", help="Unique ID for this Minion instance.")
    parser.add_argument("--personality", type=str, default="Pragmatic, Efficient, Thorough", help="Comma-separated string of personality traits.")
    parser.add_argument("--a2a-server", type=str, default=A2A_SERVER_URL_DEFAULT, help="URL of the A2A server.")
    # Example: python main_minion.py --id Alpha --personality "Sarcastic, Brilliant, Loyal"
    
    args = parser.parse_args()

    # Set BASE_PROJECT_DIR environment variable if not already set,
    # assuming this script is in minion_core and project root is one level up.
    if not os.getenv("BASE_PROJECT_DIR"):
        os.environ["BASE_PROJECT_DIR"] = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    try:
        minion_instance = Minion(minion_id=args.id, personality_traits_str=args.personality, a2a_server_url=args.a2a_server)
        # For now, the Minion's run() loop is passive. It needs an entry point for tasks.
        # The "ice breaker" task will be sent via the GUI's broadcast or A2A.
        # To test, one might add a simple task here:
        # minion_instance.process_task("Introduce yourself and state your primary directives.")
        minion_instance.run() # Starts the main loop and A2A registration/listening
    except Exception as e:
        main_logger = setup_logger("MainMinionLauncher", os.path.join(LOGS_DIR, "main_minion_launcher_error.log"))
        main_logger.critical(f"Failed to start Minion {args.id}. Error: {e}", exc_info=True)
        print(f"CRITICAL: Failed to start Minion {args.id}. Check logs. Error: {e}", file=sys.stderr)
        sys.exit(1)
