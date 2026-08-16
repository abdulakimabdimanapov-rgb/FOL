"""Abstract base class for input modules."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4


@dataclass
class UserInput:
    """Represents processed user input."""

    text: str = ""
    source: str = "text"
    language: str = "ru"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)


class AbstractInputModule(abc.ABC):
    """Base class all input modules must implement."""

    name: str = "base_input"

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Initialize the module."""

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Shutdown and cleanup."""

    @abc.abstractmethod
    async def capture(self) -> UserInput:
        """Capture input from the source."""
