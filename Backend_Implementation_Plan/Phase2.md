## Phase 2: System Improvements

### 1. Enhance State Management

**Issue:** Limited state serialization and persistence.

**Implementation Steps:**

1. Create a more robust state model:

```python
# In minion_core/state_manager.py
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Optional
import time
import json
import os
import logging

@dataclass
class TaskState:
    """State of a task being processed by a Minion."""
    task_id: str
    task_description: str
    start_time: float
    sender_id: str
    steps_completed: List[str] = field(default_factory=list)
    status: str = "pending"  # pending, running, paused, completed, failed
    progress_percentage: float = 0.0
    result: Optional[str] = None
    error: Optional[str] = None

@dataclass
class MinionState:
    """Complete state of a Minion that can be serialized/deserialized."""
    minion_id: str
    version: str = "1.0"
    is_paused: bool = False
    current_task: Optional[TaskState] = None
    pending_messages: List[Dict[str, Any]] = field(default_factory=list)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to a dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MinionState':
        """Create a MinionState instance from a dictionary."""
        # Handle nested TaskState if present
        if data.get('current_task') and isinstance(data['current_task'], dict):
            data['current_task'] = TaskState(**data['current_task'])
        return cls(**data)

class StateManager:
    """Manages serialization, persistence, and loading of Minion state."""
    
    def __init__(self, minion_id: str, storage_dir: str, logger=None):
        self.minion_id = minion_id
        self.storage_dir = storage_dir
        self.logger = logger or logging.getLogger(f"StateManager_{minion_id}")
        self.state_file_path = os.path.join(storage_dir, f"minion_state_{minion_id}.json")
        self.backup_dir = os.path.join(storage_dir, "backups")
        
        # Ensure directories exist
        os.makedirs(self.storage_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def save_state(self, state: MinionState) -> bool:
        """Serialize and save state to disk."""
        try:
            # Update timestamp
            state.last_updated = time.time()
            
            # First, create a backup of the existing state if it exists
            if os.path.exists(self.state_file_path):
                self._create_backup()
            
            # Write new state file
            with open(self.state_file_path, 'w') as f:
                json.dump(state.to_dict(), f, indent=2)
            
            self.logger.info(f"Saved state to {self.state_file_path}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to save state: {e}", exc_info=True)
            return False
    
    def load_state(self) -> Optional[MinionState]:
        """Load state from disk."""
        try:
            if os.path.exists(self.state_file_path):
                with open(self.state_file_path, 'r') as f:
                    data = json.load(f)
                self.logger.info(f"Loaded state from {self.state_file_path}")
                return MinionState.from_dict(data)
            else:
                self.logger.info(f"No state file found at {self.state_file_path}")
                return None
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding state file: {e}", exc_info=True)
            # Try to load from most recent backup
            return self._load_from_backup()
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}", exc_info=True)
            return None
    
    def _create_backup(self):
        """Create a backup of the current state file."""
        try:
            timestamp = int(time.time())
            backup_path = os.path.join(self.backup_dir, f"minion_state_{self.minion_id}_{timestamp}.json")
            
            with open(self.state_file_path, 'r') as src:
                content = src.read()
                
            with open(backup_path, 'w') as dst:
                dst.write(content)
                
            self.logger.debug(f"Created state backup at {backup_path}")
            
            # Cleanup old backups (keep only the 5 most recent)
            self._cleanup_old_backups(5)
        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}", exc_info=True)
    
    def _cleanup_old_backups(self, keep_count):
        """Keep only the most recent `keep_count` backups."""
        try:
            backup_files = [f for f in os.listdir(self.backup_dir) 
                           if f.startswith(f"minion_state_{self.minion_id}_") and f.endswith(".json")]
            
            if len(backup_files) <= keep_count:
                return
            
            # Sort by timestamp (newest first)
            backup_files.sort(reverse=True)
            
            # Remove older files beyond keep_count
            for file_to_remove in backup_files[keep_count:]:
                os.remove(os.path.join(self.backup_dir, file_to_remove))
                self.logger.debug(f"Removed old backup: {file_to_remove}")
        except Exception as e:
            self.logger.error(f"Error cleaning up old backups: {e}", exc_info=True)
    
    def _load_from_backup(self) -> Optional[MinionState]:
        """Attempt to load state from most recent backup."""
        try:
            backup_files = [f for f in os.listdir(self.backup_dir) 
                           if f.startswith(f"minion_state_{self.minion_id}_") and f.endswith(".json")]
            
            if not backup_files:
                self.logger.warning("No backup files found")
                return None
            
            # Sort by timestamp (newest first)
            backup_files.sort(reverse=True)
            most_recent = backup_files[0]
            backup_path = os.path.join(self.backup_dir, most_recent)
            
            with open(backup_path, 'r') as f:
                data = json.load(f)
            
            self.logger.info(f"Loaded state from backup: {backup_path}")
            return MinionState.from_dict(data)
        except Exception as e:
            self.logger.error(f"Failed to load from backup: {e}", exc_info=True)
            return None
```

2. Update the Minion class to use the new StateManager:

```python
# In main_minion.py

# Import the new StateManager
from minion_core.state_manager import StateManager, MinionState, TaskState

def __init__(self, minion_id, user_facing_name=None, personality_traits_str=None, a2a_server_url_override=None):
    # Existing initialization code...
    
    # Initialize StateManager
    minion_state_storage_dir = config.get_path("minion_state.storage_dir", 
                                               os.path.join(PROJECT_ROOT, "system_data", "minion_states"))
    self.state_manager = StateManager(minion_id=self.minion_id, 
                                     storage_dir=minion_state_storage_dir,
                                     logger=self.logger)
    
    # Try to load existing state
    loaded_state = self.state_manager.load_state()
    if loaded_state:
        self.logger.info(f"Found existing state. Minion was previously: {'paused' if loaded_state.is_paused else 'active'}")
        self._restore_from_state(loaded_state)
    else:
        # Initialize with default state
        self.current_state = MinionState(minion_id=self.minion_id)
        self.is_paused = False
        self.pending_messages_while_paused = []
        self.current_task_description = None
        self.current_status = MinionStatus.IDLE

def _restore_from_state(self, state: MinionState):
    """Restore minion state from a loaded MinionState object."""
    self.current_state = state
    self.is_paused = state.is_paused
    
    # Restore current task if any
    if state.current_task:
        self.current_task_description = state.current_task.task_description
        self.current_task = state.current_task.task_id
        self.current_status = MinionStatus.PAUSED if self.is_paused else MinionStatus.RUNNING
    else:
        self.current_task_description = None
        self.current_task = None
        self.current_status = MinionStatus.PAUSED if self.is_paused else MinionStatus.IDLE
    
    # Restore pending messages
    self.pending_messages_while_paused = state.pending_messages
    
    # Restore conversation history if needed
    if state.conversation_history:
        self.conversation_history = state.conversation_history
    
    self.logger.info(f"Successfully restored state. Minion is now {self.current_status.value}.")

def _save_current_state(self):
    """Capture and save the current state."""
    self.current_state.is_paused = self.is_paused
    self.current_state.pending_messages = self.pending_messages_while_paused
    self.current_state.conversation_history = self.conversation_history
    
    # Update current task state if applicable
    if self.current_task_description:
        if not self.current_state.current_task:
            # Create a new TaskState if none exists
            self.current_state.current_task = TaskState(
                task_id=self.current_task or str(uuid.uuid4()),
                task_description=self.current_task_description,
                start_time=time.time(),
                sender_id="unknown"  # Will be overwritten if we know it
            )
        
        # Update task status
        self.current_state.current_task.status = "paused" if self.is_paused else "running"
    else:
        self.current_state.current_task = None
    
    # Save to disk
    success = self.state_manager.save_state(self.current_state)
    if success:
        self.logger.info("Successfully saved current state")
    else:
        self.logger.error("Failed to save current state")
```

3. Update the pause/resume methods to use the new state management:

```python
def _pause_workflow(self):
    """Handles the logic to pause the minion's workflow."""
    if self.is_paused:
        self.logger.info("Minion is already paused. No action taken.")
        return

    self.logger.info("Pausing workflow...")
    self.current_status = MinionStatus.PAUSING
    self._send_state_update(self.current_status, "Attempting to pause workflow.")

    self.is_paused = True
    
    # Save state before fully pausing
    self._save_current_state()
    
    self.current_status = MinionStatus.PAUSED
    self.logger.info("Minion workflow paused.")
    self._send_state_update(self.current_status, "Minion successfully paused.")

def _resume_workflow(self):
    """Handles the logic to resume the minion's workflow."""
    if not self.is_paused:
        self.logger.warning("Resume called, but Minion is not paused. No action taken.")
        return

    self.logger.info("Resuming workflow...")
    self.current_status = MinionStatus.RESUMING
    self._send_state_update(self.current_status, "Attempting to resume workflow.")

    self.is_paused = False
    
    # Process pending messages
    if self.pending_messages_while_paused:
        self.logger.info(f"Processing {len(self.pending_messages_while_paused)} messages received while paused.")
        for msg in self.pending_messages_while_paused:
            self._process_stored_message(msg)
        
        self.pending_messages_while_paused = []
        self.logger.info("Cleared pending messages queue.")

    # Determine new status based on current task
    if self.current_task_description:
        self.current_status = MinionStatus.RUNNING
        self.logger.info(f"Resuming with task: {self.current_task_description}")
        
        # If we have a current task, update its status
        if self.current_state.current_task:
            self.current_state.current_task.status = "running"
    else:
        self.current_status = MinionStatus.IDLE
        self.logger.info("Resumed to idle state as no task was active.")
    
    # Save the resumed state
    self._save_current_state()
    
    self._send_state_update(self.current_status, "Minion successfully resumed.")
```

### 2. Implement Task Queue and Processing

**Issue:** Simplistic task processing without proper queueing.

**Implementation Steps:**

1. Create a TaskQueue class:

```python
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
```

2. Integrate the TaskQueue into the Minion class:

```python
# In main_minion.py

# Import TaskQueue
from minion_core.task_queue import TaskQueue, Task, TaskPriority, TaskStatus

def __init__(self, minion_id, user_facing_name=None, personality_traits_str=None, a2a_server_url_override=None):
    # Existing initialization code...
    
    # Initialize TaskQueue
    self.task_queue = TaskQueue(logger=self.logger)
    self.task_queue.add_task_listener(self._handle_task_status_change)
    
    # Rest of initialization...

def _handle_task_status_change(self, event_type: str, task: Task):
    """Handle task status changes from the TaskQueue."""
    if event_type == "task_started":
        self.current_status = MinionStatus.RUNNING
        self.current_task = task.id
        self.current_task_description = task.description
        self._send_state_update(self.current_status, f"Processing task: {task.description[:60]}...")
    
    elif event_type == "task_completed":
        if not self.task_queue.get_next_task():
            # No more tasks in queue
            self.current_status = MinionStatus.IDLE
            self.current_task = None
            self.current_task_description = None
            self._send_state_update(self.current_status, "Task completed, minion idle.")
    
    elif event_type == "task_failed":
        if not self.task_queue.get_next_task():
            # No more tasks in queue
            self.current_status = MinionStatus.ERROR
            self.current_task = None
            self.current_task_description = None
            self._send_state_update(self.current_status, f"Task failed: {task.error}")
    
    # Save state on significant events
    if event_type in ["task_completed", "task_failed", "task_paused", "task_canceled"]:
        self._save_current_state()

def handle_a2a_message(self, message_data):
    # Existing code...
    
    # Update for user_broadcast_directive
    elif message_type == "user_broadcast_directive" and content:
        if self.is_paused:
            self.logger.info(f"Received broadcast directive but Minion is paused. Queuing message.")
            self._store_message_while_paused({"type": "directive", "content": content, "sender": sender_id})
        else:
            self.logger.info(f"Received broadcast directive. Queuing task: {content[:60]}...")
            # Add to task queue instead of immediate processing
            self.task_queue.add_task(
                description=content, 
                sender_id=sender_id,
                priority=TaskPriority.NORMAL
            )
            
            # If no task is currently running, start processing the queue
            if not self.task_queue.running_task:
                self._process_next_task()
    
    # Rest of the method...

def _process_next_task(self):
    """Process the next task in the queue."""
    if self.is_paused:
        self.logger.info("Cannot process next task: Minion is paused")
        return
    
    task = self.task_queue.start_next_task()
    if not task:
        self.logger.info("No tasks in queue to process")
        return
    
    # Start a new thread for task processing
    task_thread = threading.Thread(
        target=self._execute_task,
        args=(task,)
    )
    task_thread.daemon = True
    task_thread.start()

def _execute_task(self, task: Task):
    """Execute a task from the queue."""
    try:
        self.logger.info(f"Executing task: {task.description[:100]}...")
        
        # Construct the full prompt for the LLM
        full_prompt = self._construct_prompt_from_history_and_task(task.description)
        
        # Send to LLM
        llm_response_text = self.llm.send_prompt(full_prompt)
        
        if llm_response_text.startswith("ERROR_"):
            self.logger.error(f"LLM processing failed: {llm_response_text}")
            self.task_queue.fail_current_task(f"LLM error: {llm_response_text}")
            return
        
        # Send response back to the original sender
        try:
            self.a2a_client.send_message(
                recipient_agent_id=task.sender_id,
                message_content=llm_response_text,
                message_type="directive_reply"
            )
            self.logger.info(f"Sent reply to {task.sender_id}")
        except Exception as e:
            self.logger.error(f"Failed to send reply: {e}", exc_info=True)
            # Continue anyway, as we processed the task
        
        # Mark task as completed
        self.task_queue.complete_current_task(result=llm_response_text)
        
        # Process next task if available
        self._process_next_task()
    
    except Exception as e:
        self.logger.error(f"Error executing task: {e}", exc_info=True)
        self.task_queue.fail_current_task(f"Execution error: {str(e)}")
        
        # Process next task if available
        self._process_next_task()
```

### 3. Implement Metrics Collection

**Issue:** No systematic metrics collection for monitoring.

**Implementation Steps:**

1. Create a metrics collector:

```python
# In minion_core/utils/metrics.py
import time
from typing import Dict, List, Any, Optional, Callable
from threading import Lock
import json
import os
from datetime import datetime

class MetricsCollector:
    """Collects and manages metrics for the Minion system."""
    
    def __init__(self, component_name: str, storage_dir: Optional[str] = None, logger=None):
        self.component_name = component_name
        self.storage_dir = storage_dir
        self.logger = logger
        self.lock = Lock()
        
        self.start_time = time.time()
        self.metrics = {
            "counters": {},     # Incrementing counters (e.g., tasks_processed)
            "gauges": {},       # Current values (e.g., queue_length)
            "histograms": {},   # Value distributions (e.g., response_time_ms)
            "timers": {}        # Active timers (start_time, label)
        }
        
        # Initialize storage
        if self.storage_dir:
            os.makedirs(self.storage_dir, exist_ok=True)
            self.metrics_file = os.path.join(self.storage_dir, f"{component_name}_metrics.json")
        else:
            self.metrics_file = None
    
    def inc_counter(self, name: str, value: int = 1, labels: Dict[str, str] = None):
        """Increment a counter metric."""
        with self.lock:
            key = self._get_key(name, labels)
            if key not in self.metrics["counters"]:
                self.metrics["counters"][key] = 0
            self.metrics["counters"][key] += value
    
    def set_gauge(self, name: str, value: float, labels: Dict[str, str] = None):
        """Set a gauge metric to a specific value."""
        with self.lock:
            key = self._get_key(name, labels)
            self.metrics["gauges"][key] = value
    
    def observe(self, name: str, value: float, labels: Dict[str, str] = None):
        """Add an observation to a histogram metric."""
        with self.lock:
            key = self._get_key(name, labels)
            if key not in self.metrics["histograms"]:
                self.metrics["histograms"][key] = []
            self.metrics["histograms"][key].append(value)
            
            # Limit the number of observations to prevent memory issues
            if len(self.metrics["histograms"][key]) > 1000:
                self.metrics["histograms"][key] = self.metrics["histograms"][key][-1000:]
    
    def start_timer(self, name: str, labels: Dict[str, str] = None) -> str:
        """Start a timer and return a timer ID."""
        timer_id = f"{time.time()}_{name}_{hash(str(labels))}"
        with self.lock:
            self.metrics["timers"][timer_id] = {
                "name": name,
                "labels": labels,
                "start_time": time.time()
            }
        return timer_id
    
    def stop_timer(self, timer_id: str) -> Optional[float]:
        """Stop a timer and record its duration in the histogram."""
        with self.lock:
            if timer_id not in self.metrics["timers"]:
                if self.logger:
                    self.logger.warning(f"Timer '{timer_id}' not found")
                return None
            
            timer = self.metrics["timers"].pop(timer_id)
            duration = time.time() - timer["start_time"]
            
            # Record in histogram
            self.observe(timer["name"], duration, timer["labels"])
            return duration
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get the current metrics as a dictionary."""
        with self.lock:
            # Calculate histogram statistics
            histogram_stats = {}
            for key, values in self.metrics["histograms"].items():
                if not values:
                    continue
                    
                sorted_values = sorted(values)
                n = len(sorted_values)
                histogram_stats[key] = {
                    "count": n,
                    "min": min(values),
                    "max": max(values),
                    "mean": sum(values) / n,
                    "median": sorted_values[n // 2],
                    "p90": sorted_values[int(n * 0.9)],
                    "p95": sorted_values[int(n * 0.95)],
                    "p99": sorted_values[int(n * 0.99)] if n >= 100 else None
                }
            
            return {
                "component": self.component_name,
                "timestamp": time.time(),
                "uptime_seconds": time.time() - self.start_time,
                "counters": dict(self.metrics["counters"]),
                "gauges": dict(self.metrics["gauges"]),
                "histograms": histogram_stats
            }
    
    def save_metrics(self) -> bool:
        """Save metrics to disk if storage_dir is set."""
        if not self.metrics_file:
            return False
            
        try:
            metrics = self.get_metrics()
            with open(self.metrics_file, 'w') as f:
                json.dump(metrics, f, indent=2)
            return True
        except Exception as e:
            if self.logger:
                self.logger.error(f"Failed to save metrics: {e}", exc_info=True)
            return False
    
    def _get_key(self, name: str, labels: Dict[str, str] = None) -> str:
        """Generate a key for a metric including its labels."""
        if not labels:
            return name
        
        # Sort labels by key for consistent keys
        sorted_labels = sorted(labels.items())
        labels_str = ",".join(f"{k}={v}" for k, v in sorted_labels)
        return f"{name}{{{labels_str}}}"
```

2. Integrate metrics collection throughout the Minion:

```python
# In main_minion.py

# Import MetricsCollector
from minion_core.utils.metrics import MetricsCollector

def __init__(self, minion_id, user_facing_name=None, personality_traits_str=None, a2a_server_url_override=None):
    # Existing initialization code...
    
    # Initialize metrics collector
    metrics_dir = config.get_path("metrics.storage_dir", os.path.join(PROJECT_ROOT, "system_data", "metrics"))
    self.metrics = MetricsCollector(
        component_name=f"Minion_{self.minion_id}",
        storage_dir=metrics_dir,
        logger=self.logger
    )
    
    # Schedule periodic metrics save
    self._start_metrics_save_thread()
    
    # Rest of initialization...

def _start_metrics_save_thread(self):
    """Start a thread to periodically save metrics."""
    def _save_metrics_loop():
        save_interval = config.get_int("metrics.save_interval_seconds", 60)
        while True:
            try:
                time.sleep(save_interval)
                self._update_and_save_metrics()
            except Exception as e:
                self.logger.error(f"Error in metrics save loop: {e}", exc_info=True)
    
    metrics_thread = threading.Thread(target=_save_metrics_loop, daemon=True)
    metrics_thread.start()

def _update_and_save_metrics(self):
    """Update and save current metrics."""
    # Update gauge metrics
    self.metrics.set_gauge("is_paused", 1 if self.is_paused else 0)
    self.metrics.set_gauge("queue_length", len(self.task_queue.queue))
    self.metrics.set_gauge("has_running_task", 1 if self.task_queue.running_task else 0)
    
    # Save metrics
    self.metrics.save_metrics()

def process_task(self, task_description: str, original_sender_id: str):
    # Start timer for task processing
    timer_id = self.metrics.start_timer("task_processing_time", {
        "sender_id": original_sender_id[:10]  # Truncate long IDs
    })
    
    # Existing code...
    
    # After task processing
    self.metrics.stop_timer(timer_id)
    self.metrics.inc_counter("tasks_processed")
    
    # Rest of the method...

def handle_a2a_message(self, message_data):
    # Track message receipt
    self.metrics.inc_counter("a2a_messages_received", labels={
        "type": message_data.get("message_type", "unknown")
    })
    
    # Existing code...

def send_message(self, recipient_agent_id, message_content, message_type="generic_text"):
    # Track message sending
    timer_id = self.metrics.start_timer("a2a_message_send_time", {
        "type": message_type
    })
    
    # Send message...
    
    # After sending
    self.metrics.stop_timer(timer_id)
    self.metrics.inc_counter("a2a_messages_sent", labels={
        "type": message_type
    })
```

3. Add metrics to LLMInterface:

```python
# In llm_interface.py

# Import MetricsCollector
from minion_core.utils.metrics import MetricsCollector

def __init__(self, minion_id, api_key=None, logger=None):
    # Existing initialization...
    
    # Initialize metrics
    metrics_dir = config.get_path("metrics.storage_dir", os.path.join(PROJECT_ROOT, "system_data", "metrics"))
    self.metrics = MetricsCollector(
        component_name=f"LLM_{minion_id}",
        storage_dir=metrics_dir,
        logger=self.logger
    )

def send_prompt(self, prompt_text, conversation_history=None):
    # Start timer
    timer_id = self.metrics.start_timer("llm_request_time")
    token_count = self._estimate_token_count(prompt_text)
    self.metrics.observe("prompt_token_count", token_count)
    
    # Existing code...
    
    try:
        # Make API call...
        
        # On success
        self.metrics.inc_counter("llm_requests_success")
        response_token_count = self._estimate_token_count(response_text)
        self.metrics.observe("response_token_count", response_token_count)
    except Exception as e:
        # On error
        self.metrics.inc_counter("llm_requests_error", labels={
            "error_type": type(e).__name__
        })
        raise
    finally:
        # Always stop timer
        self.metrics.stop_timer(timer_id)
    
    # Rest of the method...

def _estimate_token_count(self, text):
    """Estimate token count using a simple heuristic."""
    # Simple approximation: 4 chars per token
    return len(text) // 4
```
