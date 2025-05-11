from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, List, Optional
import time

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"

@dataclass
class HealthCheckResult:
    component: str
    status: HealthStatus
    details: Optional[Dict[str, Any]] = None
    timestamp: float = time.time()
    
    def as_dict(self):
        return {
            "component": self.component,
            "status": self.status.value,
            "details": self.details or {},
            "timestamp": self.timestamp
        }

class HealthCheckable:
    """Interface for components that can report health status."""
    
    def check_health(self) -> HealthCheckResult:
        """Perform a health check and return the result."""
        raise NotImplementedError("Subclasses must implement check_health")