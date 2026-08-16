"""Memory module — canonical boundary + stores.

New orchestration code should depend on the ``MemoryService`` boundary from
``modules.memory.interface``; the concrete stores (RAG, vector, episodic,
long-term) remain the implementation layer.
"""

from modules.memory.base import MemoryItem, AbstractMemoryStore
from modules.memory.interface import MemoryService, RAGMemoryService

__all__ = [
    "MemoryItem",
    "AbstractMemoryStore",
    "MemoryService",
    "RAGMemoryService",
]
