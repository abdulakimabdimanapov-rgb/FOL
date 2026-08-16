"""Task planning and management."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


class TaskStatus(enum.Enum):
    """Task statuses."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Represents a unit of work."""

    id: UUID = field(default_factory=uuid4)
    name: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    parent_id: UUID | None = None
    subtasks: list[UUID] = field(default_factory=list)


class TaskManager:
    """Manages tasks and their lifecycle."""

    def __init__(self) -> None:
        self._tasks: dict[UUID, Task] = {}

    def create_task(self, name: str, description: str = "", parent_id: UUID | None = None) -> Task:
        """Create a new task."""
        task = Task(name=name, description=description, parent_id=parent_id)
        self._tasks[task.id] = task
        if parent_id and parent_id in self._tasks:
            self._tasks[parent_id].subtasks.append(task.id)
        logger.info("Task created", task_id=str(task.id), name=name)
        return task

    def get_task(self, task_id: UUID) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def update_status(self, task_id: UUID, status: TaskStatus, result: Any = None, error: str | None = None) -> None:
        """Update task status."""
        task = self._tasks.get(task_id)
        if task:
            task.status = status
            task.result = result
            task.error = error
            logger.info("Task updated", task_id=str(task_id), status=status.value)

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """List all tasks, optionally filtered by status."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return tasks

    def clear_completed(self) -> int:
        """Remove completed tasks. Returns count removed."""
        to_remove = [tid for tid, t in self._tasks.items() if t.status == TaskStatus.COMPLETED]
        for tid in to_remove:
            del self._tasks[tid]
        return len(to_remove)
