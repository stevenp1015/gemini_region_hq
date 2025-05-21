import re
from google.adk.agents import LlmAgent
from typing import List

class DecomposerMinionAgent(LlmAgent):
    def __init__(self, minion_id: str, name: str, personality_traits_str: str, model_name: str = "gemini-2.5-pro-preview-05-06", **kwargs):
        super().__init__(
            model=model_name,
            name=name,
            description=f"AI Minion {name}. ID: {minion_id}. Personality: {personality_traits_str}. Specializes in decomposing complex tasks.",
            tools=[], # No external tools for decomposition itself
            **kwargs
        )
        self.minion_id = minion_id
        self.personality_traits_str = personality_traits_str
        print(f"DecomposerMinionAgent '{self.name}' initialized.")

    async def awake(self, session_id: str | None = None) -> None:
        await super().awake(session_id=session_id)
        
        persona_prompt = (
            f"You are {self.name}, an AI assistant specializing in task decomposition.\n"
            f"Your ID is {self.minion_id}, and your personality is: {self.personality_traits_str}.\n"
            "When given a complex task, your goal is to break it down into a series of smaller, manageable, and logically ordered sub-tasks. "
            "These sub-tasks should be clear instructions that other agents can execute.\n"
            "Present these sub-tasks as a numbered list. Each item in the list is a distinct sub-task.\n"
            "You MUST prefix your list of decomposed steps with the exact string 'DECOMPOSED_STEPS:'.\n"
            "Example Input Task: 'Plan a memorable birthday trip to Paris for a week for two people on a moderate budget.'\n"
            "Example DECOMPOSED_STEPS: Output:\n"
            "DECOMPOSED_STEPS:\n"
            "1. Research and list potential arrondissements (districts) in Paris suitable for a week-long stay on a moderate budget, considering proximity to attractions and dining.\n"
            "2. Identify 3-5 mid-range hotel options or Airbnb accommodations in the selected districts that have good reviews.\n"
            "3. Draft a sample 7-day itinerary including a mix of famous landmarks, cultural experiences (museums, shows), and leisure time. Assign estimated costs for each activity.\n"
            "4. Research and list 5-7 restaurants (moderate budget) in Paris known for good French cuisine, suitable for birthday dinners.\n"
            "5. Compile a preliminary budget estimate for the trip, including accommodation, flights (if applicable, assume a placeholder), daily expenses, and activities.\n"
            "6. Suggest 2-3 special romantic activities or surprises suitable for a birthday celebration in Paris."
        )
        self.set_instructions(persona_prompt)
        print(f"DecomposerMinionAgent '{self.name}' has awoken and persona set.")

    async def think(self, prompt: str, session_id: str | None = None) -> str:
        # The prompt is the complex task to be decomposed.
        print(f"DecomposerMinionAgent '{self.name}' received task to decompose: '{prompt}'")
        
        # LLM call to get the decomposed steps based on instructions in awake()
        llm_response = await self.predict(prompt=prompt)
        print(f"DecomposerMinionAgent '{self.name}' LLM response: {llm_response}")
        
        # The LlmAgent's predict method itself doesn't directly return a list.
        # The LLM is instructed to format its output starting with "DECOMPOSED_STEPS:".
        # We will return this full string, and the orchestrator (main_adk.py) will parse it.
        # Alternatively, we could parse it here and return a structured list,
        # but that requires robust parsing. For now, let the orchestrator handle it.
        return llm_response

    def parse_decomposed_steps(self, llm_output: str) -> List[str]:
        """
        Parses the LLM output to extract decomposed steps.
        Expects format:
        DECOMPOSED_STEPS:
        1. Step one.
        2. Step two.
        ...
        """
        if not llm_output.startswith("DECOMPOSED_STEPS:"):
            print(f"Warning: Output from DecomposerMinionAgent '{self.name}' did not start with 'DECOMPOSED_STEPS:'. Output: {llm_output}")
            return []

        content_after_prefix = llm_output[len("DECOMPOSED_STEPS:"):].strip()
        
        # Regex to find lines starting with a number and a dot (e.g., "1. ", "01. ", " 1. ")
        # It will capture the text following the number and dot.
        steps = re.findall(r"^\s*\d+\.\s+(.*)", content_after_prefix, re.MULTILINE)
        
        # Fallback or alternative parsing if regex doesn't catch it (e.g. if LLM uses hyphens or just newlines)
        if not steps and content_after_prefix:
             # Try splitting by newline if regex fails, assuming each line is a step
            potential_steps = [line.strip() for line in content_after_prefix.splitlines() if line.strip()]
            # Filter out any lines that don't seem like steps (e.g., empty or very short) - basic heuristic
            steps = [s for s in potential_steps if len(s) > 5] # Arbitrary minimum length

        if not steps:
             print(f"Warning: Could not parse steps from: {content_after_prefix}")

        return [step.strip() for step in steps]

```
