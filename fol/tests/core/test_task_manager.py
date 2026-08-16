"""Tests for TaskManager."""

from __future__ import annotations

import pytest
from core.task_manager import TaskManager, TaskStatus


def test_create_task(task_manager: TaskManager):
    task = task_manager.create_task("test", "description")
    assert task.name == "test"
    assert task.status == TaskStatus.PENDING


def test_get_task(task_manager: TaskManager):
    task = task_manager.create_task("test")
    found = task_manager.get_task(task.id)
    assert found is not None
    assert found.name == "test"


def test_update_status(task_manager: TaskManager):
    task = task_manager.create_task("test")
    task_manager.update_status(task.id, TaskStatus.COMPLETED, result="done")
    found = task_manager.get_task(task.id)
    assert found is not None
    assert found.status == TaskStatus.COMPLETED
    assert found.result == "done"


def test_list_tasks(task_manager: TaskManager):
    task_manager.create_task("a")
    task_manager.create_task("b")
    task_manager.create_task("c")
    all_tasks = task_manager.list_tasks()
    assert len(all_tasks) == 3


def test_list_by_status(task_manager: TaskManager):
    t1 = task_manager.create_task("a")
    t2 = task_manager.create_task("b")
    task_manager.update_status(t1.id, TaskStatus.COMPLETED)
    completed = task_manager.list_tasks(status=TaskStatus.COMPLETED)
    assert len(completed) == 1
    assert completed[0].id == t1.id


def test_clear_completed(task_manager: TaskManager):
    t1 = task_manager.create_task("a")
    t2 = task_manager.create_task("b")
    task_manager.update_status(t1.id, TaskStatus.COMPLETED)
    removed = task_manager.clear_completed()
    assert removed == 1
    assert task_manager.get_task(t1.id) is None
    assert task_manager.get_task(t2.id) is not None
