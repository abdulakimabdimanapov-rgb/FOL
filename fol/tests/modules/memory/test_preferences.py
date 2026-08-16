"""Tests for PreferencesStore."""

from __future__ import annotations

import pytest
from pathlib import Path
from modules.memory.preferences import PreferencesStore


@pytest.fixture
def prefs(tmp_path: Path) -> PreferencesStore:
    return PreferencesStore(prefs_path=tmp_path / "test_prefs.json")


@pytest.mark.asyncio
async def test_set_and_get(prefs: PreferencesStore):
    await prefs.set("language", "ru")
    assert await prefs.get("language") == "ru"


@pytest.mark.asyncio
async def test_get_default(prefs: PreferencesStore):
    assert await prefs.get("missing", "default") == "default"


@pytest.mark.asyncio
async def test_delete(prefs: PreferencesStore):
    await prefs.set("key", "value")
    assert await prefs.delete("key")
    assert await prefs.get("key") is None


@pytest.mark.asyncio
async def test_get_all(prefs: PreferencesStore):
    await prefs.set("a", "1")
    await prefs.set("b", "2")
    all_prefs = await prefs.get_all()
    assert all_prefs == {"a": "1", "b": "2"}


@pytest.mark.asyncio
async def test_set_defaults(prefs: PreferencesStore):
    await prefs.set("existing", "value")
    await prefs.set_defaults({"existing": "new", "new_key": "new_value"})
    assert await prefs.get("existing") == "value"  # Not overwritten
    assert await prefs.get("new_key") == "new_value"
