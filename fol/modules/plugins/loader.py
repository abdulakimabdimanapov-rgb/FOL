"""Plugin loader — discovers and loads plugins from directories."""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path
from typing import Any

from modules.plugins.base import FOLPlugin, PluginManifest

logger = logging.getLogger(__name__)


class PluginLoader:
    """Discovers and loads FOL plugins from filesystem."""

    def __init__(self, plugin_dirs: list[Path] | None = None) -> None:
        self._dirs = plugin_dirs or []
        self._loaded_modules: dict[str, Any] = {}

    def add_directory(self, path: Path) -> None:
        """Add a directory to scan for plugins."""
        if path not in self._dirs:
            self._dirs.append(path)

    def discover(self) -> list[Path]:
        """Discover plugin directories containing manifest.json."""
        discovered = []
        for base_dir in self._dirs:
            if not base_dir.exists():
                continue
            for item in base_dir.iterdir():
                if item.is_dir():
                    manifest_path = item / "manifest.json"
                    if manifest_path.exists():
                        discovered.append(item)
        return discovered

    def load_plugin(self, plugin_dir: Path) -> tuple[FOLPlugin | None, PluginManifest | None]:
        """Load a plugin from a directory."""
        manifest_path = plugin_dir / "manifest.json"
        if not manifest_path.exists():
            logger.warning("No manifest.json in %s", plugin_dir)
            return None, None

        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = PluginManifest.from_dict(manifest_data)
        except Exception as exc:
            logger.error("Failed to parse manifest: %s", exc)
            return None, None

        # Find plugin.py or __init__.py
        plugin_file = plugin_dir / "plugin.py"
        if not plugin_file.exists():
            plugin_file = plugin_dir / "__init__.py"
        if not plugin_file.exists():
            logger.warning("No plugin.py or __init__.py in %s", plugin_dir)
            return None, manifest

        try:
            spec = importlib.util.spec_from_file_location(
                f"fol_plugin_{manifest.name}",
                str(plugin_file),
            )
            if spec is None or spec.loader is None:
                return None, manifest

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._loaded_modules[manifest.name] = module

            # Find FOLPlugin subclass
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, FOLPlugin)
                    and attr is not FOLPlugin
                ):
                    plugin_class = attr
                    break

            if plugin_class is None:
                logger.warning("No FOLPlugin subclass found in %s", plugin_dir)
                return None, manifest

            plugin = plugin_class()
            logger.info("Plugin loaded: %s v%s", manifest.name, manifest.version)
            return plugin, manifest

        except Exception as exc:
            logger.error("Failed to load plugin %s: %s", plugin_dir, exc)
            return None, manifest
