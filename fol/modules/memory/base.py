"""Abstract base class for memory stores."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4


@dataclass
class MemoryItem:
    """A single memory entry."""

    id: UUID = field(default_factory=uuid4)
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp == 0.0:
            import time
            self.timestamp = time.time()


class AbstractMemoryStore(abc.ABC):
    """Base class for all memory stores."""

    name: str = "base_memory"

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Initialize the store."""

    @abc.abstractmethod
    async def shutdown(self) -> None:
        """Shutdown and cleanup."""

    @abc.abstractmethod
    async def store(self, content: str, metadata: dict[str, Any] | None = None) -> UUID:
        """Store an item. Returns its ID."""

    @abc.abstractmethod
    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """Search for relevant items."""

    @abc.abstractmethod
    async def delete(self, item_id: UUID) -> bool:
        """Delete an item by ID."""
