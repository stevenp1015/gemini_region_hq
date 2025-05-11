import psutil
import time
import threading
import logging
from typing import Dict, Any, Optional, Callable

class ResourceMonitor:
    """Monitor system resources and implement adaptive constraints."""

    def __init__(self, check_interval: float = 5.0, logger=None):
        self.check_interval = check_interval
        self.logger = logger or logging.getLogger(__name__)

        self.last_check = {}
        self.thresholds = {
            "cpu_percent": 80.0,
            "memory_percent": 80.0,
            "disk_percent": 90.0
        }

        self.alert_callbacks = []
        self.monitor_thread = None
        self.should_stop = threading.Event()

    def start(self):
        """Start the resource monitoring thread."""
        if self.monitor_thread and self.monitor_thread.is_alive():
            return

        self.should_stop.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        self.logger.info("Resource monitor started")

    def stop(self):
        """Stop the resource monitoring thread."""
        if not (self.monitor_thread and self.monitor_thread.is_alive()):
            return

        self.should_stop.set()
        self.monitor_thread.join(timeout=2 * self.check_interval)
        if self.monitor_thread.is_alive():
            self.logger.warning("Resource monitor thread did not stop cleanly")
        else:
            self.logger.info("Resource monitor stopped")

    def check_resources(self) -> Dict[str, Any]:
        """Check current resource usage."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.5)
            memory_info = psutil.virtual_memory()
            disk_info = psutil.disk_usage('/')

            resource_info = {
                "timestamp": time.time(),
                "cpu_percent": cpu_percent,
                "memory_total": memory_info.total,
                "memory_available": memory_info.available,
                "memory_percent": memory_info.percent,
                "disk_total": disk_info.total,
                "disk_free": disk_info.free,
                "disk_percent": disk_info.percent
            }

            self.last_check = resource_info
            return resource_info

        except Exception as e:
            self.logger.error(f"Error checking resources: {e}", exc_info=True)
            return {}

    def is_system_overloaded(self) -> bool:
        """Check if system is overloaded based on thresholds."""
        if not self.last_check:
            return False

        cpu_overloaded = self.last_check.get("cpu_percent", 0) > self.thresholds["cpu_percent"]
        memory_overloaded = self.last_check.get("memory_percent", 0) > self.thresholds["memory_percent"]
        disk_overloaded = self.last_check.get("disk_percent", 0) > self.thresholds["disk_percent"]

        return cpu_overloaded or memory_overloaded or disk_overloaded

    def add_alert_callback(self, callback: Callable[[Dict[str, Any], bool], None]):
        """Add a callback to be called when resource alerts occur."""
        self.alert_callbacks.append(callback)

    def set_threshold(self, resource: str, value: float):
        """Set threshold for a specific resource."""
        if resource in self.thresholds:
            self.thresholds[resource] = value

    def _monitor_loop(self):
        """Main monitoring loop."""
        while not self.should_stop.is_set():
            try:
                resources = self.check_resources()
                if not resources:
                    time.sleep(self.check_interval)
                    continue

                is_overloaded = self.is_system_overloaded()

                if is_overloaded:
                    self.logger.warning(f"System overloaded: CPU {resources.get('cpu_percent')}%, "
                                       f"Memory {resources.get('memory_percent')}%, "
                                       f"Disk {resources.get('disk_percent')}%")

                # Call alert callbacks
                for callback in self.alert_callbacks:
                    try:
                        callback(resources, is_overloaded)
                    except Exception as e:
                        self.logger.error(f"Error in resource alert callback: {e}", exc_info=True)

                time.sleep(self.check_interval)

            except Exception as e:
                self.logger.error(f"Error in resource monitor loop: {e}", exc_info=True)
                time.sleep(self.check_interval)