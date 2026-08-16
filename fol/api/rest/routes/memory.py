"""Memory routes — store and retrieve memories.

Canonical single path (Phase 4): orchestrator → FOL API → MemoryService
(``RAGMemoryService``). ``/context`` assembles a prompt-ready context block
and ``/episode`` records episodic memory; both go through the canonical
memory boundary so the orchestrator and the FOL pipeline never retrieve
the same context through independent paths.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.rest.models import (
    MemoryEpisodeRequest,
    MemoryItem,
    MemoryResponse,
    MemoryRetrieveRequest,
    MemoryStoreRequest,
)

router = APIRouter(prefix="/memory", tags=["memory"])


def _get_fol():
    import api.rest.server as server_module
    fol = getattr(server_module, "_fol_instance", None)
    if fol is None:
        raise HTTPException(status_code=503, detail="FOL not initialized")
    return fol


@router.post("/store")
async def store_memory(request: MemoryStoreRequest) -> dict[str, str]:
    """Store a memory item."""
    fol = _get_fol()
    try:
        rag = fol.orchestrator.get_module("rag")
        if rag:
            from uuid import uuid4
            memory_id = str(uuid4())
            await rag.vector_store.add(
                content=request.content,
                metadata=request.metadata,
                id=memory_id,
            )
            return {"id": memory_id, "status": "stored"}
        raise HTTPException(status_code=503, detail="RAG module not available")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/retrieve", response_model=MemoryResponse)
async def retrieve_memory(request: MemoryRetrieveRequest) -> MemoryResponse:
    """Retrieve memories by query."""
    fol = _get_fol()
    try:
        rag = fol.orchestrator.get_module("rag")
        if rag:
            results = await rag.vector_store.search(
                query=request.query,
                limit=request.limit,
            )
            items = [
                MemoryItem(
                    id=r.get("id", ""),
                    content=r.get("content", ""),
                    metadata=r.get("metadata", {}),
                    score=r.get("score"),
                )
                for r in results
            ]
            return MemoryResponse(results=items, total=len(items))
        raise HTTPException(status_code=503, detail="RAG module not available")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/context")
async def memory_context(request: MemoryRetrieveRequest) -> dict:
    """Assemble a prompt-ready memory context block via the canonical boundary.

    Uses ``MemoryService.retrieve_context`` (the single retrieval path — the
    RAG pipeline). Returns a compact context string that callers inject into
    their system/user prompt, or ``{"context": ""}`` when no memory store is
    available.
    """
    fol = _get_fol()
    try:
        memory_service = fol.orchestrator.get_module("memory_service")
        if memory_service is not None and hasattr(memory_service, "retrieve_context"):
            context = await memory_service.retrieve_context(
                request.query, max_tokens=1200
            )
            return {"context": context or "", "query": request.query}
        rag = fol.orchestrator.get_module("rag")
        if rag is not None and hasattr(rag, "retrieve_context"):
            context = await rag.retrieve_context(request.query, max_tokens=1200)
            return {"context": context or "", "query": request.query}
        return {"context": "", "query": request.query}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/episode")
async def record_episode(request: MemoryEpisodeRequest) -> dict:
    """Record an episodic memory via the canonical boundary.

    ``MemoryService.record_episode`` is the single memory-update path.
    """
    fol = _get_fol()
    try:
        memory_service = fol.orchestrator.get_module("memory_service")
        if memory_service is not None and hasattr(memory_service, "record_episode"):
            await memory_service.record_episode(
                request.event,
                context=request.context,
                importance=request.importance,
                metadata=request.metadata,
            )
            return {"status": "recorded"}
        return {"status": "skipped", "reason": "memory_service unavailable"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str) -> dict[str, str]:
    """Delete a memory by ID."""
    fol = _get_fol()
    try:
        rag = fol.orchestrator.get_module("rag")
        if rag:
            deleted = await rag.vector_store.delete(memory_id)
            if deleted:
                return {"status": "deleted", "id": memory_id}
            raise HTTPException(status_code=404, detail="Memory not found")
        raise HTTPException(status_code=503, detail="RAG module not available")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
