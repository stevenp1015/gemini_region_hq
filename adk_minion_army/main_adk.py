import asyncio
import os
import re # For parsing LegionMaster's TRANSFER_TO_AGENT command
import google.generativeai as genai

# Agent Imports
from agents.minion_agent import MinionAgent 
from agents.decomposer_minion_agent import DecomposerMinionAgent
from agents.summarizer_minion_agent import SummarizerMinionAgent
from agents.chat_coordinator_agent import ChatCoordinatorAgent 
from agents.legion_master_agent import LegionMasterAgent 

# Config and ADK Core Imports
from config_loader import get_gemini_api_key, load_minion_agent_config
from google.adk.runners import Runner
from google.adk.sessions import SessionService, InMemorySessionService
from google.adk.artifacts import ArtifactService, InMemoryArtifactService

# Helper function to extract task from LegionMaster's command
def parse_transfer_command(command: str):
    match = re.match(r"TRANSFER_TO_AGENT: (.*?); TASK: (.*)", command, re.DOTALL)
    if match:
        return match.group(1).strip(), match.group(2).strip() # agent_name, task_prompt
    return None, None

async def main():
    # 1. Configure Gemini API Key
    api_key = get_gemini_api_key()
    if not api_key:
        print("GEMINI_API_KEY_LEGION not found in environment. Please set it.")
        return
    genai.configure(api_key=api_key)
    print("Gemini API key configured.")

    # --- Orchestration for "Photosynthesis Report" Scenario ---
    try:
        session_service: SessionService = InMemorySessionService()
        artifact_service: ArtifactService = InMemoryArtifactService()

        # 2. Instantiate Agents
        print("\n--- Phase 0: Initializing Agents ---")
        decomposer_config = load_minion_agent_config("decomposer_main") # Ensure unique name for this instance
        decomposer_agent = DecomposerMinionAgent(
            minion_id=decomposer_config["minion_id"],
            name=decomposer_config["name"], # e.g., ADKMinion-decomposer_main
            personality_traits_str="Expert in task breakdown."
        )
        print(f"Decomposer Minion '{decomposer_agent.name}' instantiated.")

        minion_alpha_config = load_minion_agent_config("worker_alpha")
        minion_alpha = MinionAgent(
            minion_id=minion_alpha_config["minion_id"], name=minion_alpha_config["name"],
            personality_traits_str="Diligent researcher for scientific topics."
        )
        print(f"Worker Minion '{minion_alpha.name}' instantiated.")
        
        minion_beta_config = load_minion_agent_config("worker_beta")
        minion_beta = MinionAgent(
            minion_id=minion_beta_config["minion_id"], name=minion_beta_config["name"],
            personality_traits_str="Detail-oriented analyst for biological processes."
        )
        print(f"Worker Minion '{minion_beta.name}' instantiated.")

        # LegionMaster setup
        # Note: DecomposerAgent is a sub-agent of LegionMaster for this scenario.
        # MinionAlpha and MinionBeta are general workers LegionMaster will assign tasks to via chat.
        legion_master_config = load_minion_agent_config("legion_master_main")
        legion_master_agent = LegionMasterAgent(
            name=legion_master_config["name"], # e.g., ADKMinion-legion_master_main
            sub_minions=[decomposer_agent, minion_alpha, minion_beta], # Decomposer is a sub-agent
            decomposer_minion_name=decomposer_agent.name,
            worker_minion_names=[minion_alpha.name, minion_beta.name],
            chat_channel_for_tasks="photosynthesis_task_force_chat" # Specific chat channel
        )
        print(f"LegionMaster '{legion_master_agent.name}' instantiated.")

        # ChatCoordinator setup (will be used by LegionMaster via CHAT: messages)
        chat_channel_id = legion_master_agent.chat_channel_for_tasks
        chat_coordinator_config = load_minion_agent_config("chat_coord_photosynthesis")
        chat_coordinator = ChatCoordinatorAgent(
            chat_id=chat_channel_id,
            chat_title="Photosynthesis Task Force Coordination",
            initial_participants_names=[legion_master_agent.name, minion_alpha.name, minion_beta.name]
        )
        print(f"ChatCoordinator '{chat_coordinator.name}' for channel '{chat_channel_id}' instantiated.")
        
        # Summarizer Minion setup
        summarizer_config = load_minion_agent_config("summarizer_main")
        summarizer_agent = SummarizerMinionAgent(
            minion_id=summarizer_config["minion_id"], name=summarizer_config["name"],
            personality_traits_str="Expert in concise scientific summarization."
        )
        print(f"Summarizer Minion '{summarizer_agent.name}' instantiated.")
        
        # Create Runners (can be reused by re-assigning .agent if needed, or create new ones)
        # We'll use specific runners for clarity.
        legion_master_runner = Runner(session_service, artifact_service, legion_master_agent)
        decomposer_runner = Runner(session_service, artifact_service, decomposer_agent)
        minion_alpha_runner = Runner(session_service, artifact_service, minion_alpha)
        minion_beta_runner = Runner(session_service, artifact_service, minion_beta)
        chat_coordinator_runner = Runner(session_service, artifact_service, chat_coordinator)
        summarizer_runner = Runner(session_service, artifact_service, summarizer_agent)

        # --- Scenario Execution ---
        print("\n--- Phase 1: Task Delegation from User to LegionMaster ---")
        user_task_for_legionmaster = (
            "LegionMaster, please generate a comprehensive report on photosynthesis. "
            "Ensure it covers the chemical equation, light-dependent and light-independent reactions, "
            "and cellular structures involved. Coordinate with your team to accomplish this and "
            "provide me with a final summarized report."
        )
        legion_master_session_id = await session_service.create_session(agent_id=legion_master_agent.name)
        print(f"Prompting LegionMaster '{legion_master_agent.name}': '{user_task_for_legionmaster}'")

        legion_master_response_1 = None
        async for event in legion_master_runner.run_async(session_id=legion_master_session_id, prompt=user_task_for_legionmaster):
            print(f"LegionMaster Event 1 - Type: {event.type}, Data: {event.data}")
            if event.type == "agent_response" and event.data.get("output"):
                legion_master_response_1 = event.data["output"]
                break
        
        print(f"LegionMaster Initial Response: {legion_master_response_1}")

        # Phase 2: LegionMaster delegates to Decomposer
        target_decomposer_name, task_for_decomposer = parse_transfer_command(legion_master_response_1 or "")
        
        decomposed_steps_str = None
        if target_decomposer_name == decomposer_agent.name and task_for_decomposer:
            print(f"\n--- Phase 2: LegionMaster delegated to Decomposer '{target_decomposer_name}' ---")
            print(f"Task for Decomposer: '{task_for_decomposer}'")
            decomposer_session_id = await session_service.create_session(agent_id=decomposer_agent.name)
            async for event in decomposer_runner.run_async(session_id=decomposer_session_id, prompt=task_for_decomposer):
                print(f"Decomposer Event - Type: {event.type}, Data: {event.data}")
                if event.type == "agent_response" and event.data.get("output"):
                    decomposed_steps_str = event.data["output"] # This is "DECOMPOSED_STEPS: 1. ..."
                    break
            print(f"Decomposer Response: {decomposed_steps_str}")
        else:
            print("LegionMaster did not delegate to Decomposer as expected. Ending scenario.")
            return

        # Phase 3: Decomposed steps back to LegionMaster for chat assignment
        legion_master_chat_assignment_message = None
        if decomposed_steps_str and decomposed_steps_str.startswith("DECOMPOSED_STEPS:"):
            print(f"\n--- Phase 3: Sending Decomposed Steps back to LegionMaster for Chat Assignment ---")
            # The prompt to LegionMaster now includes the decomposed steps
            prompt_for_legionmaster_assignment = f"Received decomposed steps for Photosynthesis report: \n{decomposed_steps_str}\nPlease assign these to your worker minions via the designated chat channel."
            
            async for event in legion_master_runner.run_async(session_id=legion_master_session_id, prompt=prompt_for_legionmaster_assignment):
                print(f"LegionMaster Event 2 - Type: {event.type}, Data: {event.data}")
                if event.type == "agent_response" and event.data.get("output"):
                    legion_master_chat_assignment_message = event.data["output"]
                    break
            print(f"LegionMaster Chat Assignment Message: {legion_master_chat_assignment_message}")
        else:
            print("Decomposition failed or format incorrect. Ending scenario.")
            return

        # Phase 4: LegionMaster's CHAT message to ChatCoordinator
        # This part will be simplified. We assume LegionMaster's CHAT message is well-formed.
        # The actual execution by MinionAlpha/Beta and summarization will be complex to fully script here without more advanced Runner capabilities for multi-agent interaction.
        # We will simulate sending the assignment to chat and getting mock results.

        actual_chat_message_to_send = None
        if legion_master_chat_assignment_message and legion_master_chat_assignment_message.startswith(f"CHAT: @{chat_channel_id}"):
            actual_chat_message_to_send = legion_master_chat_assignment_message[len(f"CHAT: @{chat_channel_id}"):].strip()
            print(f"\n--- Phase 4: LegionMaster's assignment being sent to ChatCoordinator '{chat_coordinator.name}' ---")
            print(f"Message for channel '{chat_channel_id}': '{actual_chat_message_to_send}'")
            
            chat_session_id = f"session_for_{chat_channel_id}" # Consistent chat session
            await session_service.create_session(agent_id=chat_coordinator.name, session_id_override=chat_session_id)

            # ChatCoordinator processes LegionMaster's assignment message
            # The ChatCoordinator's output will be the relay of LegionMaster's message.
            async for event in chat_coordinator_runner.run_async(session_id=chat_session_id, prompt=f"{legion_master_agent.name}: {actual_chat_message_to_send}"):
                print(f"ChatCoordinator Event (LM Assignment) - Type: {event.type}, Data: {event.data}")
                if event.type == "agent_response" and event.data.get("output"):
                    print(f"ChatCoordinator Relayed LegionMaster's Assignment: {event.data['output']}")
                    break
            
            print("\n--- Simulation of MinionAlpha and MinionBeta executing tasks and reporting back ---")
            # Mock results from MinionAlpha and MinionBeta
            # In a full system, main_adk.py would now prompt MinionAlpha and MinionBeta with their tasks
            # (after receiving the relayed message from ChatCoordinator), then collect their CHAT responses.
            
            # Example: Extracting tasks (very simplified parsing of LegionMaster's assignment)
            # This parsing is fragile and for demo only. A real system needs robust task parsing.
            tasks = decomposer_agent.parse_decomposed_steps(decomposed_steps_str or "")
            mock_results = []
            if tasks:
                # MinionAlpha's mock execution for first half of tasks
                alpha_tasks_count = len(tasks) // 2 + (len(tasks) % 2) # Give Alpha more if odd
                minion_alpha_result_text = f"Report from {minion_alpha.name}:\n"
                for i in range(alpha_tasks_count):
                    minion_alpha_result_text += f"Completed '{tasks[i]}': [Detailed findings for task {i+1} by Alpha... e.g., Photosynthesis equation is CO2+H2O -> C6H12O6+O2]\n"
                mock_results.append(minion_alpha_result_text)
                print(f"Mock result from {minion_alpha.name} (sent to chat): {minion_alpha_result_text}")

                # MinionBeta's mock execution for second half of tasks
                if len(tasks) > alpha_tasks_count:
                    minion_beta_result_text = f"Report from {minion_beta.name}:\n"
                    for i in range(alpha_tasks_count, len(tasks)):
                         minion_beta_result_text += f"Completed '{tasks[i]}': [Detailed findings for task {i+1} by Beta... e.g., Light reactions occur in thylakoids...]\n"
                    mock_results.append(minion_beta_result_text)
                    print(f"Mock result from {minion_beta.name} (sent to chat): {minion_beta_result_text}")

            # Phase 5: Summarize results
            if mock_results:
                print(f"\n--- Phase 5: Summarizing All Results ---")
                combined_results_for_summary = "\n\n".join(mock_results)
                
                summarizer_session_id = await session_service.create_session(agent_id=summarizer_agent.name)
                summarizer_prompt = (
                    "Please synthesize the following reports from different Minions into a single, coherent, "
                    f"and comprehensive report on Photosynthesis, suitable for the LegionMaster. Original request was: '{user_task_for_legionmaster}'\n\n"
                    f"Combined Reports:\n{combined_results_for_summary}"
                )
                print(f"Prompting Summarizer Minion '{summarizer_agent.name}'.")

                final_summary = None
                async for event in summarizer_runner.run_async(session_id=summarizer_session_id, prompt=summarizer_prompt):
                    print(f"Summarizer Event - Type: {event.type}, Data: {event.data}")
                    if event.type == "agent_response" and event.data.get("output"):
                        final_summary = event.data["output"]
                        break
                
                if final_summary:
                    print(f"\n--- FINAL COMPREHENSIVE REPORT (from Summarizer Minion) ---")
                    print(final_summary)
                else:
                    print("Summarizer Minion did not provide a final summary.")
            else:
                print("No mock results to summarize.")
        else:
            print("LegionMaster did not formulate a CHAT assignment message as expected.")

    except Exception as e:
        print(f"\nAn error occurred during the integrated scenario: {e}")
        import traceback
        traceback.print_exc()
        print("Ensure GEMINI_API_KEY_LEGION is set and all agent definitions are correct.")

if __name__ == '__main__':
    asyncio.run(main())
```
