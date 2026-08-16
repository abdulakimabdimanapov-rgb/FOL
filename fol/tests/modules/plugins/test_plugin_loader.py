"""Tests for PluginLoader."""

from __future__ import annotations

import json
import pytest
from pathlib import Path
from modules.plugins.loader import PluginLoader


@pytest.fixture
def loader() -> PluginLoader:
    return PluginLoader()


def test_discover_empty(loader: PluginLoader, tmp_path: Path):
    loader.add_directory(tmp_path)
    discovered = loader.discover()
    assert discovered == []


def test_discover_plugin_dir(loader: PluginLoader, tmp_path: Path):
    plugin_dir = tmp_path / "my_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": "my_plugin"}))
    loader.add_directory(tmp_path)
    discovered = loader.discover()
    assert len(discovered) == 1


def test_load_plugin_missing_plugin_py(loader: PluginLoader, tmp_path: Path):
    plugin_dir = tmp_path / "bad_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "manifest.json").write_text(json.dumps({"name": "bad"}))
    loader.add_directory(tmp_path)
    plugin, manifest = loader.load_plugin(plugin_dir)
    assert plugin is None
    assert manifest is not None
