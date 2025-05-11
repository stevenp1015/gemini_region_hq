# In minion_core/task_coordinator.py
import asyncio
import time
from enum import Enum
from typing import Dict, List, Any, Optional, Set
import uuid

class SubtaskStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class CollaborativeTask:
    """Represents a collaborative task that involves multiple minions."""
    
    def __init__(self, task_id: str, description: str, requester_id: str, 
                decomposition: Dict[str, Any], logger=None):
        self.task_id = task_id
        self.description = description
        self.requester_id = requester_id
        self.decomposition = decomposition
        self.logger = logger
        
        self.start_time = time.time()
        self.end_time = None
        self.status = "in_progress"
        
        # Initialize subtasks
        self.subtasks = {}
        for subtask in decomposition.get("subtasks", []):
            self.subtasks[subtask["id"]] = {
                "description": subtask["description"],
                "assigned_to": subtask["assigned_to"],
                "dependencies": subtask["dependencies"],
                "success_criteria": subtask.get("success_criteria", ""),
                "status": SubtaskStatus.PENDING,
                "result": None,
                "error": None,
                "start_time": None,
                "end_time": None
            }
    
    def get_next_subtasks(self) -> List[Dict[str, Any]]:
        """Get the next subtasks that can be executed based on dependencies."""
        next_subtasks = []
        
        for subtask_id, subtask in self.subtasks.items():
            # Skip subtasks that are not pending
            if subtask["status"] != SubtaskStatus.PENDING:
                continue
            
            # Check if all dependencies are completed
            dependencies_met = True
            for dep_id in subtask["dependencies"]:
                if dep_id not in self.subtasks:
                    # Unknown dependency, log and skip
                    if self.logger:
                        self.logger.warning(f"Subtask {subtask_id} has unknown dependency {dep_id}")
                    dependencies_met = False
                    break
                
                dep_status = self.subtasks[dep_id]["status"]
                if dep_status != SubtaskStatus.COMPLETED:
                    dependencies_met = False
                    break
            
            if dependencies_met:
                next_subtasks.append({
                    "id": subtask_id,
                    "description": subtask["description"],
                    "assigned_to": subtask["assigned_to"],
                    "success_criteria": subtask["success_criteria"]
                })
        
        return next_subtasks
    
    def update_subtask(self, subtask_id: str, status: SubtaskStatus, 
                      result: Optional[Any] = None, error: Optional[str] = None) -> bool:
        """Update the status of a subtask."""
        if subtask_id not in self.subtasks:
            if self.logger:
                self.logger.warning(f"Attempted to update unknown subtask {subtask_id}")
            return False
        
        subtask = self.subtasks[subtask_id]
        subtask["status"] = status
        
        if status == SubtaskStatus.IN_PROGRESS:
            subtask["start_time"] = time.time()
        elif status in [SubtaskStatus.COMPLETED, SubtaskStatus.FAILED]:
            subtask["end_time"] = time.time()
            
            if status == SubtaskStatus.COMPLETED:
                subtask["result"] = result
            else:
                subtask["error"] = error
        
        # Check if all subtasks are completed or failed
        all_done = True
        for st in self.subtasks.values():
            if st["status"] not in [SubtaskStatus.COMPLETED, SubtaskStatus.FAILED]:
                all_done = False
                break
        
        if all_done:
            self.status = "completed"
            self.end_time = time.time()
        
        return True
    
    def get_results(self) -> Dict[str, Any]:
        """Get the results of all completed subtasks."""
        results = {}
        for subtask_id, subtask in self.subtasks.items():
            if subtask["status"] == SubtaskStatus.COMPLETED:
                results[subtask_id] = subtask["result"]
        
        return results
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the collaborative task."""
        pending_count = 0
        assigned_count = 0
        in_progress_count = 0
        completed_count = 0
        failed_count = 0
        
        for subtask in self.subtasks.values():
            if subtask["status"] == SubtaskStatus.PENDING:
                pending_count += 1
            elif subtask["status"] == SubtaskStatus.ASSIGNED:
                assigned_count += 1
            elif subtask["status"] == SubtaskStatus.IN_PROGRESS:
                in_progress_count += 1
            elif subtask["status"] == SubtaskStatus.COMPLETED:
                completed_count += 1
            elif subtask["status"] == SubtaskStatus.FAILED:
                failed_count += 1
        
        return {
            "task_id": self.task_id,
            "status": self.status,
            "total_subtasks": len(self.subtasks),
            "subtask_status": {
                "pending": pending_count,
                "assigned": assigned_count,
                "in_progress": in_progress_count,
                "completed": completed_count,
                "failed": failed_count
            },
            "elapsed_time": time.time() - self.start_time
        }

class TaskCoordinator:
    """Coordinates collaborative tasks among multiple minions."""
    
    def __init__(self, a2a_client, task_decomposer, logger=None):
        self.a2a_client = a2a_client
        self.task_decomposer = task_decomposer
        self.logger = logger
        
        self.tasks = {}  # task_id -> CollaborativeTask
        self.minion_registry = {}  # minion_id -> minion_info
    
    def register_minion(self, minion_id: str, minion_info: Dict[str, Any]):
        """Register a minion with the coordinator."""
        self.minion_registry[minion_id] = minion_info
        if self.logger:
            self.logger.info(f"Registered minion {minion_id}")
    
    def unregister_minion(self, minion_id: str):
        """Unregister a minion from the coordinator."""
        if minion_id in self.minion_registry:
            del self.minion_registry[minion_id]
            if self.logger:
                self.logger.info(f"Unregistered minion {minion_id}")
    
    async def create_collaborative_task(self, task_description: str, requester_id: str) -> str:
        """Create a new collaborative task."""
        # Generate task ID
        task_id = f"collab-{uuid.uuid4().hex[:8]}"
        
        if self.logger:
            self.logger.info(f"Creating collaborative task {task_id} for {requester_id}")
        
        # Get minion registry for decomposition
        available_minions = list(self.minion_registry.values())
        
        # Decompose task
        decomposition = await self.task_decomposer.decompose_task(
            task_description, 
            available_minions
        )
        
        # Create collaborative task
        task = CollaborativeTask(
            task_id=task_id,
            description=task_description,
            requester_id=requester_id,
            decomposition=decomposition,
            logger=self.logger
        )
        
        # Store task
        self.tasks[task_id] = task
        
        # Start processing
        asyncio.create_task(self._process_collaborative_task(task_id))
        
        return task_id
    
    async def update_subtask_status(self, task_id: str, subtask_id: str, 
                                  status: SubtaskStatus, result=None, error=None) -> bool:
        """Update the status of a subtask."""
        if task_id not in self.tasks:
            if self.logger:
                self.logger.warning(f"Attempted to update unknown task {task_id}")
            return False
        
        task = self.tasks[task_id]
        success = task.update_subtask(subtask_id, status, result, error)
        
        # If task is now completed, send summary to requester
        if task.status == "completed":
            await self._send_task_completion(task_id)
        
        # Process next subtasks if any become available
        if success and status == SubtaskStatus.COMPLETED:
            asyncio.create_task(self._process_collaborative_task(task_id))
        
        return success
    
    async def _process_collaborative_task(self, task_id: str):
        """Process a collaborative task by assigning and executing subtasks."""
        if task_id not in self.tasks:
            if self.logger:
                self.logger.warning(f"Attempted to process unknown task {task_id}")
            return
        
        task = self.tasks[task_id]
        
        # Get next subtasks to execute
        next_subtasks = task.get_next_subtasks()
        
        # No subtasks to execute
        if not next_subtasks:
            # Check if all subtasks are done
            if task.status == "completed":
                if self.logger:
                    self.logger.info(f"Task {task_id} completed")
            return
        
        # Assign and execute each subtask
        for subtask in next_subtasks:
            minion_id = subtask["assigned_to"]
            
            # Check if minion is available
            if minion_id not in self.minion_registry:
                if self.logger:
                    self.logger.warning(f"Minion {minion_id} not available for subtask {subtask['id']}")
                task.update_subtask(subtask["id"], SubtaskStatus.FAILED, 
                                   error="Assigned minion not available")
                continue
            
            # Mark subtask as assigned
            task.update_subtask(subtask["id"], SubtaskStatus.ASSIGNED)
            
            # Send subtask to minion
            if self.logger:
                self.logger.info(f"Assigning subtask {subtask['id']} to minion {minion_id}")
            
            message = {
                "collaborative_task_id": task_id,
                "subtask_id": subtask["id"],
                "description": subtask["description"],
                "success_criteria": subtask["success_criteria"],
                "original_task": task.description
            }
            
            try:
                await self.a2a_client.send_message(
                    recipient_agent_id=minion_id,
                    message_content=message,
                    message_type="collaborative_subtask_assignment"
                )
                
                # Mark subtask as in progress
                task.update_subtask(subtask["id"], SubtaskStatus.IN_PROGRESS)
                
                if self.logger:
                    self.logger.info(f"Subtask {subtask['id']} assigned to {minion_id}")
                
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Failed to assign subtask {subtask['id']} to {minion_id}: {e}")
                task.update_subtask(subtask["id"], SubtaskStatus.FAILED, 
                                   error=f"Failed to assign: {str(e)}")
    
    async def _send_task_completion(self, task_id: str):
        """Send task completion notification to the requester."""
        if task_id not in self.tasks:
            return
        
        task = self.tasks[task_id]
        
        # Compile results
        results = task.get_results()
        
        # Create summary
        summary = {
            "task_id": task_id,
            "description": task.description,
            "status": task.status,
            "subtask_count": len(task.subtasks),
            "subtasks_completed": sum(1 for s in task.subtasks.values() 
                                     if s["status"] == SubtaskStatus.COMPLETED),
            "subtasks_failed": sum(1 for s in task.subtasks.values() 
                                  if s["status"] == SubtaskStatus.FAILED),
            "elapsed_seconds": task.end_time - task.start_time if task.end_time else None,
            "results": results
        }
        
        # Send to requester
        try:
            await self.a2a_client.send_message(
                recipient_agent_id=task.requester_id,
                message_content=summary,
                message_type="collaborative_task_completed"
            )
            if self.logger:
                self.logger.info(f"Sent completion for task {task_id} to {task.requester_id}")
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to send completion for task {task_id}: {e}")