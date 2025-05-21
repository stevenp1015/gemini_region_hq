from google.adk.agents import LlmAgent

class SummarizerMinionAgent(LlmAgent):
    def __init__(self, minion_id: str, name: str, personality_traits_str: str, model_name: str = "gemini-2.5-pro-preview-05-06", **kwargs):
        super().__init__(
            model=model_name,
            name=name,
            description=f"AI Minion {name}. ID: {minion_id}. Personality: {personality_traits_str}. Specializes in summarizing texts.",
            tools=[], # No external tools for summarizing itself
            **kwargs
        )
        self.minion_id = minion_id
        self.personality_traits_str = personality_traits_str
        print(f"SummarizerMinionAgent '{self.name}' initialized.")

    async def awake(self, session_id: str | None = None) -> None:
        await super().awake(session_id=session_id)
        
        persona_prompt = (
            f"You are {self.name}, an AI assistant specializing in summarization.\n"
            f"Your ID is {self.minion_id}, and your personality is: {self.personality_traits_str}.\n"
            "When given a text or a collection of texts, your goal is to produce a concise and coherent summary "
            "that captures the key points and main ideas.\n"
            "If you receive multiple pieces of information from different sources, synthesize them into a single summary.\n"
            "Focus on clarity and brevity."
        )
        self.set_instructions(persona_prompt)
        print(f"SummarizerMinionAgent '{self.name}' has awoken and persona set.")

    async def think(self, prompt: str, session_id: str | None = None) -> str:
        # The prompt is the text or collection of texts to be summarized.
        print(f"SummarizerMinionAgent '{self.name}' received text to summarize (length: {len(prompt)}).")
        
        # LLM call to get the summary based on instructions in awake()
        llm_response = await self.predict(prompt=prompt)
        print(f"SummarizerMinionAgent '{self.name}' LLM summary: {llm_response}")
        
        return llm_response
```
