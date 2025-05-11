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