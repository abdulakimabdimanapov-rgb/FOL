"""Knowledge graph — stores relationships between entities."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from config.constants import FOL_DIR

logger = logging.getLogger(__name__)


@dataclass
class Entity:
    """A named entity in the knowledge graph."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    entity_type: str = "unknown"
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if self.created_at == 0.0:
            self.created_at = time.time()


@dataclass
class Relation:
    """A relationship between two entities."""

    id: UUID = field(default_factory=uuid4)
    source_id: UUID = field(default_factory=uuid4)
    target_id: UUID = field(default_factory=uuid4)
    relation_type: str = "related_to"
    weight: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)


class KnowledgeGraph:
    """In-memory knowledge graph with persistence."""

    def __init__(self, graph_path: Path | None = None) -> None:
        self._path = graph_path or (FOL_DIR / "knowledge_graph.json")
        self._entities: dict[UUID, Entity] = {}
        self._relations: dict[UUID, Relation] = {}
        self._entity_index: dict[str, UUID] = {}  # name -> id

    async def initialize(self) -> None:
        """Load graph from disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for e_data in data.get("entities", []):
                    entity = Entity(
                        id=UUID(e_data["id"]),
                        name=e_data["name"],
                        entity_type=e_data.get("entity_type", "unknown"),
                        properties=e_data.get("properties", {}),
                        created_at=e_data.get("created_at", 0.0),
                    )
                    self._entities[entity.id] = entity
                    self._entity_index[entity.name.lower()] = entity.id
                for r_data in data.get("relations", []):
                    relation = Relation(
                        id=UUID(r_data["id"]),
                        source_id=UUID(r_data["source_id"]),
                        target_id=UUID(r_data["target_id"]),
                        relation_type=r_data.get("relation_type", "related_to"),
                        weight=r_data.get("weight", 1.0),
                        properties=r_data.get("properties", {}),
                    )
                    self._relations[relation.id] = relation
                logger.info("Knowledge graph loaded", entities=len(self._entities), relations=len(self._relations))
            except Exception as exc:
                logger.error("Failed to load knowledge graph", error=str(exc))

    async def shutdown(self) -> None:
        await self.save()

    async def save(self) -> None:
        """Save graph to disk."""
        try:
            data = {
                "entities": [
                    {
                        "id": str(e.id),
                        "name": e.name,
                        "entity_type": e.entity_type,
                        "properties": e.properties,
                        "created_at": e.created_at,
                    }
                    for e in self._entities.values()
                ],
                "relations": [
                    {
                        "id": str(r.id),
                        "source_id": str(r.source_id),
                        "target_id": str(r.target_id),
                        "relation_type": r.relation_type,
                        "weight": r.weight,
                        "properties": r.properties,
                    }
                    for r in self._relations.values()
                ],
            }
            self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("Failed to save knowledge graph", error=str(exc))

    async def add_entity(self, name: str, entity_type: str = "unknown", properties: dict[str, Any] | None = None) -> Entity:
        """Add or update an entity."""
        key = name.lower()
        if key in self._entity_index:
            entity = self._entities[self._entity_index[key]]
            if properties:
                entity.properties.update(properties)
            return entity

        entity = Entity(name=name, entity_type=entity_type, properties=properties or {})
        self._entities[entity.id] = entity
        self._entity_index[key] = entity.id
        return entity

    async def add_relation(
        self,
        source_name: str,
        target_name: str,
        relation_type: str = "related_to",
        weight: float = 1.0,
    ) -> Relation | None:
        """Add a relation between two entities."""
        src_key = source_name.lower()
        tgt_key = target_name.lower()

        # Auto-create entities if they don't exist
        if src_key not in self._entity_index:
            await self.add_entity(source_name)
        if tgt_key not in self._entity_index:
            await self.add_entity(target_name)

        source_id = self._entity_index[src_key]
        target_id = self._entity_index[tgt_key]

        relation = Relation(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            weight=weight,
        )
        self._relations[relation.id] = relation
        return relation

    async def get_entity(self, name: str) -> Entity | None:
        """Get entity by name."""
        key = name.lower()
        entity_id = self._entity_index.get(key)
        if entity_id:
            return self._entities.get(entity_id)
        return None

    async def get_relations(self, entity_name: str) -> list[tuple[Entity, Relation, Entity]]:
        """Get all relations involving an entity."""
        key = entity_name.lower()
        entity_id = self._entity_index.get(key)
        if not entity_id:
            return []

        results = []
        for relation in self._relations.values():
            if relation.source_id == entity_id:
                target = self._entities.get(relation.target_id)
                source = self._entities.get(relation.source_id)
                if target and source:
                    results.append((source, relation, target))
            elif relation.target_id == entity_id:
                source = self._entities.get(relation.source_id)
                target = self._entities.get(relation.target_id)
                if source and target:
                    results.append((source, relation, target))
        return results

    async def search(self, query: str, limit: int = 10) -> list[Entity]:
        """Search entities by name."""
        query_lower = query.lower()
        results = []
        for entity in self._entities.values():
            if query_lower in entity.name.lower():
                results.append(entity)
                if len(results) >= limit:
                    break
        return results

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def relation_count(self) -> int:
        return len(self._relations)
