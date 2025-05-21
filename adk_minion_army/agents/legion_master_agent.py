from google.adk.agents import LlmAgent
from typing import List
# Assuming MinionAgent will be in the same directory or PYTHONPATH is set up correctly
# For direct relative import from a sibling file:
from .minion_agent import MinionAgent

from .decomposer_minion_agent import DecomposerMinionAgent # Import Decomposer

class LegionMasterAgent(LlmAgent):
    def __init__(self, 
                 name: str, 
                 sub_minions: List[LlmAgent], # Can include MinionAgent, DecomposerMinionAgent, etc.
                 decomposer_minion_name: str, # Explicit name for finding the decomposer
                 worker_minion_names: List[str], # Names of minions who can do sub-tasks
                 chat_channel_for_tasks: str, # e.g., "task_force_alpha_chat"
                 model_name: str = "gemini-2.5-pro-preview-05-06", 
                 **kwargs):
        
        super().__init__(
            name=name,
            model=model_name,
            description="I am LegionMaster. I receive complex tasks, oversee their decomposition, and coordinate their execution using my Minion horde via chat.",
            tools=[], 
            sub_agents=sub_minions, # All minions including decomposer are sub-agents
            **kwargs
        )
        self.decomposer_minion_name = decomposer_minion_name
        self.worker_minion_names = worker_minion_names
        self.chat_channel_for_tasks = chat_channel_for_tasks
        
        print(f"LegionMasterAgent '{name}' initialized.")
        print(f"  Decomposer: {self.decomposer_minion_name}")
        print(f"  Worker Minions: {', '.join(self.worker_minion_names)}")
        print(f"  Task Coordination Chat Channel: {self.chat_channel_for_tasks}")
        # print(f"  All sub-agents: {[sa.name for sa in self.sub_agents]}")


    async def awake(self, session_id: str | None = None) -> None:
        await super().awake(session_id=session_id)

        decomposer_description = ""
        worker_descriptions_list = []
        if self.sub_agents:
            for minion in self.sub_agents:
                if minion.name == self.decomposer_minion_name:
                    decomposer_description = getattr(minion, 'description', f"Minion {minion.name} (specialized in task decomposition)")
                elif minion.name in self.worker_minion_names:
                    worker_desc = getattr(minion, 'description', f"Minion {minion.name} (general worker)")
                    worker_descriptions_list.append(f"- {minion.name}: {worker_desc}")
        
        available_workers_str = "\n".join(worker_descriptions_list) if worker_descriptions_list else "No specific worker Minions listed."

        instructions = (
            f"You are {self.name}, the LegionMaster.\n"
            "Your primary roles are: \n"
            "1. Task Reception & Decomposition Planning: Receive complex tasks. If a task requires decomposition, "
            f"you MUST delegate it to your specialist sub-agent named '{self.decomposer_minion_name}'. "
            f"To do this, your response should be: 'TRANSFER_TO_AGENT: {self.decomposer_minion_name}; TASK: [original complex task verbatim]'.\n"
            "2. Task Assignment via Chat: Once you receive decomposed steps (the system will provide them to you as a new prompt if the decomposition was successful), "
            f"you MUST assign these steps to your worker minions ({', '.join(self.worker_minion_names)}) using the designated chat channel '{self.chat_channel_for_tasks}'. "
            "Your response for this should be a single CHAT message formatted as follows: "
            f"'CHAT: @{self.chat_channel_for_tasks} ATTENTION_TEAM New project assigned. Decomposed steps are:\n[Numbered list of all decomposed steps].\n"
            f"ASSIGNMENTS: {self.worker_minion_names[0]} will handle step 1. "
            f"{self.worker_minion_names[1] if len(self.worker_minion_names) > 1 else self.worker_minion_names[0]} will handle step 2 (and so on, distribute tasks among available workers). " # Simple distribution for now
            "Report your findings for each step back to this channel. {self.name} standing by.'\n"
            "3. Monitoring & Summarization Planning (Future Task): Later, you will monitor progress via chat and request summarization. For now, focus on decomposition and assignment.\n\n"
            f"Available specialist for decomposition: '{self.decomposer_minion_name}' (Description: {decomposer_description})\n"
            f"Available worker minions for executing sub-tasks:\n{available_workers_str}\n"
            f"Designated chat channel for task coordination: '{self.chat_channel_for_tasks}'\n\n"
            "IMPORTANT: \n"
            "- If the prompt is a complex task for you to manage, your *only* output should be the 'TRANSFER_TO_AGENT: ...' command for the decomposer.\n"
            "- If the prompt contains 'DECOMPOSED_STEPS:', your *only* output should be the 'CHAT: @channel ...' message assigning these tasks.\n"
            "- Do not add conversational fluff around these specific command outputs."
        )
        self.set_instructions(instructions)
        print(f"LegionMasterAgent '{self.name}' has awoken. Instructions set for decomposition and chat assignment. Session: {session_id}")

    async def think(self, prompt: str, session_id: str | None = None) -> str:
        print(f"LegionMaster '{self.name}' thinking about prompt: '{prompt}'")
        
        # LLM uses instructions from awake() to decide if this is a new complex task 
        # or if it's receiving decomposed steps.
        llm_response = await self.predict(prompt=prompt)
        
        # The llm_response should be one of the specific command formats.
        # No further processing needed here by LegionMaster's think(), main_adk.py will interpret.
        print(f"LegionMaster '{self.name}' LLM response: '{llm_response}'")
        return llm_response
