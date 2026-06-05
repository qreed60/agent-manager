class AgentManagerError(Exception):
    """Base error for agent manager failures."""


class ProjectConfigError(AgentManagerError):
    """Raised when project registry configuration is invalid."""


class AdapterError(AgentManagerError):
    """Raised when a project adapter fails."""
