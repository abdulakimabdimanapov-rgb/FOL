"""Phase 6 regression tests — agent-server runtime configuration.

Verifies the transport-level tool→endpoint mapping:
- lives outside the canonical ToolRegistry (no HTTP coupling in the core),
- is validated against the registry (every mapped tool is a real tool),
- endpoint values must be documented agent-server paths (typo protection),
- the agent-server base URL is env-configurable at runtime.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))

import pytest

import agent_transport
from agent_transport import (
    AGENT_SERVER_ENDPOINTS,
    TOOL_ENDPOINT_MAP,
    validate_endpoint_map,
)


def _registry():
    from tool_registry import get_orchestrator_registry

    return get_orchestrator_registry()


def test_every_mapped_tool_is_registered_canonical_tool():
    """Every key in TOOL_ENDPOINT_MAP must exist in the canonical registry."""
    registry = _registry()
    for tool_name in TOOL_ENDPOINT_MAP:
        assert registry.has(tool_name), f"{tool_name} is not a registered tool"


def test_every_endpoint_is_documented_agent_server_path():
    """Every endpoint value must be part of the agent-server contract."""
    for tool_name, endpoint in TOOL_ENDPOINT_MAP.items():
        assert endpoint in AGENT_SERVER_ENDPOINTS, f"bad endpoint for {tool_name}: {endpoint}"


def test_real_map_validates_clean():
    assert validate_endpoint_map(_registry()) == []


class _FakeRegistry:
    def __init__(self, names: set[str]) -> None:
        self._names = names

    def has(self, name: str) -> bool:
        return name in self._names


def test_validation_catches_unknown_tool():
    problems = validate_endpoint_map(
        _FakeRegistry({"browser_goto"}),
        endpoint_map={"browser_goto": "/browser/goto", "ghost_tool": "/browser/x"},
    )
    assert any("ghost_tool" in p and "not a registered" in p for p in problems)


def test_validation_catches_typo_endpoint():
    problems = validate_endpoint_map(
        _FakeRegistry({"browser_goto"}),
        endpoint_map={"browser_goto": "/browser/go2"},  # typo
    )
    assert any("not a documented" in p for p in problems)


def test_validation_catches_non_path_value():
    problems = validate_endpoint_map(
        _FakeRegistry({"notify"}),
        endpoint_map={"notify": "http://elsewhere/notify"},
    )
    assert any("not an HTTP path" in p for p in problems)


def test_agent_server_url_env_override(monkeypatch):
    """AGENT_SERVER_URL is read from the environment at import time."""
    default = agent_transport.AGENT_SERVER_URL
    assert default == "http://localhost:8421"
    monkeypatch.setenv("AGENT_SERVER_URL", "http://agent.internal:9999")
    reloaded = importlib.reload(agent_transport)
    assert reloaded.AGENT_SERVER_URL == "http://agent.internal:9999"


def test_transport_stays_out_of_registry():
    """The canonical ToolRegistry must have no HTTP endpoint knowledge."""
    registry = _registry()
    for spec in registry.specs():
        schema = spec.schema or {}
        assert "endpoint" not in schema.get("properties", {}), (
            f"tool {spec.name} leaks transport metadata into its schema"
        )
