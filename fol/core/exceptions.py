"""FOL custom exception hierarchy."""

from __future__ import annotations

from typing import Any


class FOLBaseError(Exception):
    """Base exception for all FOL errors."""

    def __init__(
        self,
        message: str,
        *,
        module: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.module = module
        self.details = details or {}
        super().__init__(message)


class ModuleLoadError(FOLBaseError):
    """Failed to load or initialize a module."""


class ModelNotReadyError(FOLBaseError):
    """ML model is not initialized yet."""


class ToolExecutionError(FOLBaseError):
    """Tool execution failed."""


class FOLRuntimeError(FOLBaseError):
    """General runtime error during FOL operation."""


class EventBusError(FOLBaseError):
    """Error in the event bus system."""


class ConfigurationError(FOLBaseError):
    """Invalid or missing configuration."""
