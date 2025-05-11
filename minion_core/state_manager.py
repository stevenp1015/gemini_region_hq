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