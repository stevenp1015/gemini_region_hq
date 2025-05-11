# In minion_core/task_decomposer.py
import json
from typing import List, Dict, Any, Optional
import uuid

class TaskDecomposer:
    """Decomposes complex tasks into subtasks that can be distributed among minions."""
    
    def __init__(self, llm_interface, logger=None):
        self.llm = llm_interface
        self.logger = logger
    
    async def decompose_task(self, task_description: str, available_minions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Decompose a complex task into subtasks assigned to specific minions.
        
        Args:
            task_description: The original task to decompose
            available_minions: List of minion info including ID, capabilities, etc.
            
        Returns:
            Dictionary with task plan, subtasks, and assignments
        """
        # Create a prompt for the LLM to decompose the task
        prompt = self._create_decomposition_prompt(task_description, available_minions)
        
        # Get decomposition from LLM
        try:
            response = self.llm.send_prompt(prompt)
            
            # Parse the response to extract the task decomposition
            decomposition = self._parse_decomposition_response(response)
            
            if not decomposition:
                if self.logger:
                    self.logger.error("Failed to parse task decomposition response")
                return self._create_fallback_decomposition(task_description, available_minions)
            
            return decomposition
            
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error decomposing task: {e}", exc_info=True)
            return self._create_fallback_decomposition(task_description, available_minions)
    
    def _create_decomposition_prompt(self, task_description: str, available_minions: List[Dict[str, Any]]) -> str:
        """Create a prompt for the LLM to decompose the task."""
        minion_descriptions = []
        for minion in available_minions:
            # Format each minion's info for the prompt
            skills = ", ".join([skill.get("name", "Unknown") for skill in minion.get("skills", [])])
            minion_descriptions.append(
                f"Minion ID: {minion.get('id')}\n"
                f"Name: {minion.get('name')}\n"
                f"Skills: {skills}\n"
            )
        
        minions_info = "\n".join(minion_descriptions)
        
        prompt = (
            f"You are an AI task planning system. You need to decompose a complex task into subtasks "
            f"that can be distributed among multiple AI minions.\n\n"
            f"TASK TO DECOMPOSE:\n{task_description}\n\n"
            f"AVAILABLE MINIONS:\n{minions_info}\n\n"
            f"Please decompose this task into 2-5 logical subtasks. For each subtask:\n"
            f"1. Provide a clear, detailed description\n"
            f"2. Assign it to the most appropriate minion based on their skills\n"
            f"3. Specify any dependencies between subtasks (which must complete before others)\n"
            f"4. Define clear success criteria\n\n"
            f"Format your response as a JSON object with this structure:\n"
            f"```json\n"
            f"{{\n"
            f'  "plan_summary": "Brief description of the overall approach",\n'
            f'  "subtasks": [\n'
            f'    {{\n'
            f'      "id": "subtask-1",\n'
            f'      "description": "Detailed description of the subtask",\n'
            f'      "assigned_to": "minion-id",\n'
            f'      "dependencies": [],\n'
            f'      "success_criteria": "Clear measures for completion"\n'
            f'    }},\n'
            f'    ...\n'
            f'  ]\n'
            f"}}\n```\n"
            f"Ensure your response contains only the JSON, not any additional text."
        )
        
        return prompt
    
    def _parse_decomposition_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Parse the LLM response to extract the task decomposition."""
        try:
            # Extract JSON from response (might be wrapped in ```json ... ```)
            json_text = response
            if "```json" in response:
                json_text = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_text = response.split("```")[1].split("```")[0]
            
            # Parse JSON
            decomposition = json.loads(json_text)
            
            # Validate required fields
            if "plan_summary" not in decomposition or "subtasks" not in decomposition:
                if self.logger:
                    self.logger.warning("Decomposition missing required fields")
                return None
            
            # Ensure subtasks have required fields
            for i, subtask in enumerate(decomposition["subtasks"]):
                if "description" not in subtask:
                    if self.logger:
                        self.logger.warning(f"Subtask {i} missing description")
                    return None
                
                # Ensure subtask has ID
                if "id" not in subtask:
                    subtask["id"] = f"subtask-{uuid.uuid4().hex[:8]}"
                
                # Ensure dependencies is a list
                if "dependencies" not in subtask:
                    subtask["dependencies"] = []
            
            return decomposition
            
        except json.JSONDecodeError as e:
            if self.logger:
                self.logger.error(f"Failed to parse JSON from response: {e}", exc_info=True)
            return None
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error parsing decomposition: {e}", exc_info=True)
            return None
    
    def _create_fallback_decomposition(self, task_description: str, available_minions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Create a simple fallback decomposition when LLM fails."""
        # Simple approach: assign the whole task to the first available minion
        if not available_minions:
            # No minions available!
            return {
                "plan_summary": "Unable to decompose task due to lack of available minions",
                "subtasks": []
            }
        
        return {
            "plan_summary": "Simple fallback plan: assign the entire task to one minion",
            "subtasks": [
                {
                    "id": f"subtask-{uuid.uuid4().hex[:8]}",
                    "description": task_description,
                    "assigned_to": available_minions[0]["id"],
                    "dependencies": [],
                    "success_criteria": "Complete the entire task"
                }
            ]
        }