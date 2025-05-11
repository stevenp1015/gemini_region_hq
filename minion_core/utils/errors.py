class MinionError(Exception):
    """Base class for all minion-related errors."""
    def __init__(self, message, code=None, details=None):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)

class LLMError(MinionError):
    """Errors related to LLM operations."""
    pass

class ToolError(MinionError):
    """Errors related to tool operations."""
    pass

class A2AError(MinionError):
    """Errors related to A2A operations."""
    pass

class ConfigError(MinionError):
    """Errors related to configuration."""
    pass

# More specific error classes
class LLMAPIError(LLMError):
    """Errors from the LLM API."""
    pass

class LLMContentFilterError(LLMError):
    """Errors due to content filtering."""
    pass

class ToolExecutionError(ToolError):
    """Errors during tool execution."""
    pass

class ToolNotFoundError(ToolError):
    """Errors when a tool is not found."""
    pass

class A2AConnectionError(A2AError):
    """Errors connecting to A2A server."""
    pass

class A2AMessageDeliveryError(A2AError):
    """Errors delivering A2A messages."""
    pass