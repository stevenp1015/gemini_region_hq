# In minion_core/task_queue.py
import time
import uuid
from typing import Dict, List, Any, Optional, Callable
from threading import Lock
from dataclasses import dataclass, field
from enum import Enum

class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"

@dataclass
class Task:
    id: str
    description: str
    sender_id: str
    created_at: float
    priority: TaskPriority = TaskPriority.NORMAL
    status: TaskStatus = TaskStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

class TaskQueue:
    """A priority-based task queue with task management capabilities."""
    
    def __init__(self, logger=None):
        self.queue = []  # List of pending tasks
        self.running_task = None  # Currently running task
        self.completed_tasks = []  # History of completed tasks
        self.lock = Lock()  # For thread safety
        self.logger = logger
        self.task_listeners = []  # Callbacks for task status changes
    
    def add_task(self, description: str, sender_id: str, priority: TaskPriority = TaskPriority.NORMAL, 
                metadata: Dict[str, Any] = None) -> str:
        """Add a task to the queue and return its ID."""
        task_id = str(uuid.uuid4())
        
        task = Task(
            id=task_id,
            description=description,
            sender_id=sender_id,
            created_at=time.time(),
            priority=priority,
            status=TaskStatus.PENDING,
            metadata=metadata or {}
        )
        
        with self.lock:
            # Insert based on priority (higher priority tasks come first)
            idx = 0
            while idx < len(self.queue) and self.queue[idx].priority.value >= priority.value:
                idx += 1
            self.queue.insert(idx, task)
        
        if self.logger:
            self.logger.info(f"Added task '{task_id}' to queue with priority {priority.name}")
        
        self._notify_listeners("task_added", task)
        return task_id
    
    def get_next_task(self) -> Optional[Task]:
        """Get the next task from the queue without removing it."""
        with self.lock:
            return self.queue[0] if self.queue else None
    
    def start_next_task(self) -> Optional[Task]:
        """Remove the next task from the queue and mark it as running."""
        with self.lock:
            if not self.queue:
                return None
            
            if self.running_task:
                if self.logger:
                    self.logger.warning(f"Cannot start next task, task '{self.running_task.id}' is already running")
                return None
            
            self.running_task = self.queue.pop(0)
            self.running_task.status = TaskStatus.RUNNING
            self.running_task.started_at = time.time()
        
        if self.logger:
            self.logger.info(f"Started task '{self.running_task.id}'")
        
        self._notify_listeners("task_started", self.running_task)
        return self.running_task
    
    def complete_current_task(self, result: Any = None) -> Optional[Task]:
        """Mark the current task as completed and move it to history."""
        with self.lock:
            if not self.running_task:
                if self.logger:
                    self.logger.warning("No running task to complete")
                return None
            
            self.running_task.status = TaskStatus.COMPLETED
            self.running_task.completed_at = time.time()
            self.running_task.result = result
            
            completed_task = self.running_task
            self.completed_tasks.append(completed_task)
            self.running_task = None
        
        if self.logger:
            self.logger.info(f"Completed task '{completed_task.id}'")
        
        self._notify_listeners("task_completed", completed_task)
        return completed_task
    
    def fail_current_task(self, error: str) -> Optional[Task]:
        """Mark the current task as failed and move it to history."""
        with self.lock:
            if not self.running_task:
                if self.logger:
                    self.logger.warning("No running task to fail")
                return None
            
            self.running_task.status = TaskStatus.FAILED
            self.running_task.completed_at = time.time()
            self.running_task.error = error
            
            failed_task = self.running_task
            self.completed_tasks.append(failed_task)
            self.running_task = None
        
        if self.logger:
            self.logger.info(f"Failed task '{failed_task.id}': {error}")
        
        self._notify_listeners("task_failed", failed_task)
        return failed_task
    
    def pause_current_task(self) -> Optional[Task]:
        """Pause the current task and return it to the queue."""
        with self.lock:
            if not self.running_task:
                if self.logger:
                    self.logger.warning("No running task to pause")
                return None
            
            self.running_task.status = TaskStatus.PAUSED
            
            # Re-add to queue based on priority
            paused_task = self.running_task
            self.queue.insert(0, paused_task)  # Insert at front to resume ASAP
            self.running_task = None
        
        if self.logger:
            self.logger.info(f"Paused task '{paused_task.id}'")
        
        self._notify_listeners("task_paused", paused_task)
        return paused_task
    
    def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task or the currently running task."""
        with self.lock:
            # Check if it's the running task
            if self.running_task and self.running_task.id == task_id:
                self.running_task.status = TaskStatus.CANCELED
                self.running_task.completed_at = time.time()
                
                canceled_task = self.running_task
                self.completed_tasks.append(canceled_task)
                self.running_task = None
                
                if self.logger:
                    self.logger.info(f"Canceled running task '{task_id}'")
                
                self._notify_listeners("task_canceled", canceled_task)
                return True
            
            # Check if it's in the queue
            for i, task in enumerate(self.queue):
                if task.id == task_id:
                    task.status = TaskStatus.CANCELED
                    task.completed_at = time.time()
                    
                    canceled_task = self.queue.pop(i)
                    self.completed_tasks.append(canceled_task)
                    
                    if self.logger:
                        self.logger.info(f"Canceled queued task '{task_id}'")
                    
                    self._notify_listeners("task_canceled", canceled_task)
                    return True
        
        if self.logger:
            self.logger.warning(f"Task '{task_id}' not found for cancellation")
        return False
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID from either the queue, running task, or history."""
        with self.lock:
            # Check running task
            if self.running_task and self.running_task.id == task_id:
                return self.running_task
            
            # Check queue
            for task in self.queue:
                if task.id == task_id:
                    return task
            
            # Check completed tasks
            for task in self.completed_tasks:
                if task.id == task_id:
                    return task
        
        return None
    
    def get_queue_status(self) -> Dict[str, Any]:
        """Get the current status of the task queue."""
        with self.lock:
            return {
                "queue_length": len(self.queue),
                "has_running_task": self.running_task is not None,
                "running_task_id": self.running_task.id if self.running_task else None,
                "completed_tasks": len(self.completed_tasks),
                "pending_by_priority": {
                    priority.name: sum(1 for task in self.queue if task.priority == priority)
                    for priority in TaskPriority
                }
            }
    
    def add_task_listener(self, callback: Callable[[str, Task], None]):
        """Add a listener for task status changes."""
        self.task_listeners.append(callback)
    
    def _notify_listeners(self, event_type: str, task: Task):
        """Notify all listeners of a task status change."""
        for listener in self.task_listeners:
            try:
                listener(event_type, task)
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Error in task listener: {e}", exc_info=True)