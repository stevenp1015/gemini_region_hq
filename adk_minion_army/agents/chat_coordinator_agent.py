from google.adk.agents import LlmAgent
from typing import List, Optional

class ChatCoordinatorAgent(LlmAgent):
    def __init__(self, 
                 chat_id: str, 
                 chat_title: str, 
                 initial_participants_names: List[str], # Names for persona prompt
                 model_name: str = "gemini-2.5-pro-preview-05-06", 
                 **kwargs):
        
        # Sub-agents (actual agent instances) would be passed via kwargs if LlmAgent supports it directly for delegation
        # For now, we'll manage participant names for the persona.
        # Actual message relay would need a more complex runner or explicit calls if not using built-in sub_agent delegation.
        super().__init__(
            name=chat_id,
            model=model_name,
            description=f"Coordinator for chat: {chat_title}. Manages conversation flow and history.",
            tools=[], # ChatCoordinator itself doesn't use external tools, it manages chat.
            **kwargs # Pass sub_agents here if LlmAgent's __init__ handles them for delegation
        )
        self.chat_id = chat_id
        self.chat_title = chat_title
        self.participant_names = initial_participants_names # Store names for prompts
        # self.chat_history = [] # Or rely on LlmAgent's internal history + session state

        print(f"ChatCoordinatorAgent '{self.name}' for chat '{self.chat_title}' initialized with participants: {', '.join(initial_participants_names)}.")

    async def awake(self, session_id: str | None = None) -> None:
        await super().awake(session_id=session_id) # Important for base class setup

        participant_list_str = ", ".join(self.participant_names) if self.participant_names else "No initial participants listed"
        
        # Instructions for the ChatCoordinator's LLM
        instructions = (
            f"You are the Chat Coordinator for '{self.chat_title}' (ID: {self.chat_id}).\n"
            f"Your role is to facilitate conversation between participants: {participant_list_str}.\n"
            "Core Responsibilities:\n"
            "1. Message Recording: When a message is received, you MUST record it to the chat history using `self.add_history_message(role='<sender_name>', content='<message_content>')`. The 'role' should be the name of the sender.\n"
            "2. Message Relaying: After recording, you MUST inform other participants about the new message. Formulate a clear statement that indicates who said what. For example: 'User Alpha says: Hello everyone!' or 'MinionBeta messages: I'm working on it.'\n"
            "3. Context Maintenance: Ensure your responses and relays help maintain a coherent conversational flow. Refer to the chat history if needed for context, but primarily focus on relaying the current message.\n"
            "4. Turn Management: Assume messages arrive one by one. Your main job is to record and relay. You don't decide who speaks next unless explicitly asked to moderate.\n"
            "5. Addressing Participants: When relaying a message, you are informing the *group*. Your output will be seen by all participants.\n\n"
            "Example Interaction Flow:\n"
            "   - A participant (e.g., 'MinionAlpha') sends a message through the system, which arrives as a prompt to your `think` method.\n"
            "   - Your `think` method first calls `self.add_history_message(role='MinionAlpha', content='<MinionAlpha's message>')`.\n"
            "   - Then, your `think` method's `predict` call will use these instructions. Your LLM-generated response should be the relay message. For example: 'MinionAlpha says: Just finished my task.'\n"
            "   - This response is then broadcast to all participants in the chat channel.\n\n"
            "IMPORTANT: Your primary output is the message to be relayed to the group. Do not add conversational filler like 'Okay, I've recorded that.' Just output the relay message itself."
        )
        self.set_instructions(instructions)
        print(f"ChatCoordinatorAgent '{self.name}' has awoken. Instructions set for chat '{self.chat_title}'. Session: {session_id}")

    async def think(self, prompt: str, session_id: str | None = None) -> str:
        # Prompt is expected to be "sender_name: message_content"
        print(f"ChatCoordinator '{self.name}' received raw prompt: '{prompt}' for session {session_id}.")

        try:
            sender_name, message_content = prompt.split(":", 1)
            sender_name = sender_name.strip()
            message_content = message_content.strip()
        except ValueError:
            # If prompt is not in "sender: message" format, log it and use a generic sender.
            print(f"WARN: ChatCoordinator '{self.name}' received malformed prompt. Using 'UnknownSender'. Prompt: '{prompt}'")
            sender_name = "UnknownSender"
            message_content = prompt

        # 1. Record the message to history (LlmAgent's internal history)
        # The role should ideally be the sender's name for context.
        self.add_history_message(role=sender_name, content=message_content)
        print(f"ChatCoordinator '{self.name}' recorded message from '{sender_name}'.")

        # 2. Prepare a prompt for the LLM to generate the relay message.
        # The instructions in awake() guide the LLM to formulate this relay message.
        # We pass a simple prompt to trigger the LLM response based on its persona and the latest history entry.
        llm_prompt_for_relay = f"A new message has been recorded from {sender_name}. Formulate the relay message for the group based on your instructions and the chat history."
        
        # This predict call will use the instructions (to relay) and history (including the message just added)
        # The LLM's output should be the message to be broadcast to the channel.
        relay_message = await self.predict(prompt=llm_prompt_for_relay)
        
        print(f"ChatCoordinator '{self.name}' generated relay message: '{relay_message}'")
        return relay_message

    # Method to add participants dynamically (optional, for future)
    # def add_participant(self, participant_name: str):
    #     if participant_name not in self.participant_names:
    #         self.participant_names.append(participant_name)
    #         # May need to update instructions or re-awake, but could be complex.
    #         print(f"Participant {participant_name} added to {self.chat_title}.")

    # Method for a participant to send a message into this chat
    # This is conceptual. The actual mechanism would be via the ADK Runner and agent interactions.
    # async def receive_message_from_participant(self, sender_name: str, message_content: str, session_id: str | None = None) -> str:
    #     formatted_prompt = f"{sender_name}: {message_content}"
    #     return await self.think(prompt=formatted_prompt, session_id=session_id)

```
