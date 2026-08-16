"""Vector store — ChromaDB-based semantic search."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from config.constants import FOL_DIR
from modules.memory.base import AbstractMemoryStore, MemoryItem

logger = logging.getLogger(__name__)

try:
    import chromadb
    HAS_CHROMA = True
except ImportError:
    HAS_CHROMA = False


class VectorStore(AbstractMemoryStore):
    """ChromaDB-backed vector store for semantic memory."""

    name = "vector_store"

    def __init__(self, collection_name: str = "fol_memory", db_path: Path | None = None) -> None:
        self._collection_name = collection_name
        self._db_path = db_path or (FOL_DIR / "vector_db")
        self._client: Any = None
        self._collection: Any = None

    async def initialize(self) -> None:
        """Initialize ChromaDB client and collection."""
        if not HAS_CHROMA:
            logger.warning("chromadb not available, vector store disabled")
            return

        self._db_path.mkdir(parents=True, exist_ok=True)
        try:
            self._client = chromadb.PersistentClient(path=str(self._db_path))
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("VectorStore initialized", path=str(self._db_path))
        except Exception as exc:
            logger.error("Failed to init ChromaDB", error=str(exc))

    async def shutdown(self) -> None:
        self._client = None
        self._collection = None

    async def store(self, content: str, metadata: dict[str, Any] | None = None) -> UUID:
        """Store a document with metadata."""
        if self._collection is None:
            return uuid4()

        item_id = str(uuid4())
        meta = metadata or {}
        try:
            self._collection.add(
                documents=[content],
                metadatas=[meta],
                ids=[item_id],
            )
            logger.debug("Stored in vector DB", id=item_id, length=len(content))
            return UUID(item_id)
        except Exception as exc:
            logger.error("Vector store failed", error=str(exc))
            return uuid4()

    async def retrieve(self, query: str, limit: int = 10) -> list[MemoryItem]:
        """Semantic search for relevant documents."""
        if self._collection is None:
            return []

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(limit, self._collection.count() or 1),
            )
            items = []
            if results and results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}
                    dist = results["distances"][0][i] if results["distances"] else 0.0
                    items.append(MemoryItem(
                        content=doc,
                        metadata=meta,
                        score=1.0 - dist,  # Convert distance to similarity
                    ))
            return items
        except Exception as exc:
            logger.error("Vector retrieve failed", error=str(exc))
            return []

    async def delete(self, item_id: UUID) -> bool:
        """Delete a document by ID."""
        if self._collection is None:
            return False
        try:
            self._collection.delete(ids=[str(item_id)])
            return True
        except Exception as exc:
            logger.error("Vector delete failed", error=str(exc))
            return False

    @property
    def count(self) -> int:
        """Number of documents in the collection."""
        if self._collection is None:
            return 0
        return self._collection.count()
