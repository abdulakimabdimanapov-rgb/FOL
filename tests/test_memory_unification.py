"""Phase 6 regression tests — memory unification.

Verifies that the active conversation/event memory flows route through the
canonical FOL API memory boundary via ``memory_bridge.record_activity``:
single scrub point, local episodic.md mirror preserved (the store the prompt
builder reads), canonical path always attempted, and no new storage path.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest


@pytest.fixture
def no_network():
    """Prevent real FOL API calls and real episodic.md writes."""
    with patch("orchestrator.memory_bridge._post", return_value={}), \
         patch("utils.episodic_writer.append_event") as mock_append:
        yield mock_append


# ---------------------------------------------------------------------------
# record_activity — the unified helper itself (canonical + mirror)
# ---------------------------------------------------------------------------


def test_record_activity_mirrors_locally_and_calls_canonical(no_network):
    from orchestrator.memory_bridge import record_activity

    mock_append = no_network
    with patch("orchestrator.memory_bridge._post",
               return_value={"status": "recorded"}) as mock_post:
        ok = record_activity(
            "Drafted email to Sarah", category="agent_action", source="chat",
        )
    assert ok is True
    # Local mirror (episodic.md — the store the prompt builder reads).
    assert mock_append.call_count == 1
    assert mock_append.call_args.kwargs["summary"] == "Drafted email to Sarah"
    assert mock_append.call_args.kwargs["source"] == "chat"
    # Canonical FOL API boundary (MemoryService.record_episode).
    assert mock_post.call_count == 1
    body = mock_post.call_args.args[1]
    assert body["event"] == "Drafted email to Sarah"
    assert body["metadata"]["source"] == "chat"


def test_record_activity_scrubs_secrets_before_persist(no_network):
    from orchestrator.memory_bridge import record_activity

    mock_append = no_network
    with patch("orchestrator.memory_bridge._post",
               return_value={"status": "recorded"}) as mock_post:
        ok = record_activity(
            "api key is gsk_abcdefghijklmnop", category="agent_action", source="chat",
        )
    assert ok is True
    scrubbed = mock_append.call_args.kwargs["summary"]
    assert "gsk_abcdefghijklmnop" not in scrubbed
    assert mock_post.call_args.args[1]["event"] == scrubbed


def test_record_activity_drops_secret_like_events(no_network):
    from orchestrator.memory_bridge import record_activity

    mock_append = no_network
    with patch("orchestrator.memory_bridge._post") as mock_post:
        ok = record_activity(
            "password=hunter2hunter2", category="agent_action", source="chat",
        )
    assert ok is False
    mock_append.assert_not_called()
    mock_post.assert_not_called()


def test_record_activity_never_raises(no_network):
    from orchestrator.memory_bridge import record_activity

    with patch("orchestrator.memory_bridge._post", side_effect=Exception("down")), \
         patch("utils.episodic_writer.append_event", side_effect=OSError("disk")):
        assert record_activity("event", source="x") is True


# ---------------------------------------------------------------------------
# orchestrator/server.py — routes through the unified helper
# ---------------------------------------------------------------------------


def test_orchestrator_episodic_event_uses_unified_path():
    """_log_episodic_event must go through record_activity, truncating to the
    documented 200 chars — never write to the episodic file directly."""
    from server import _log_episodic_event

    with patch("server.memory_record_activity") as mock_activity:
        _log_episodic_event("Long task " + "x" * 500)

    mock_activity.assert_called_once()
    args, kwargs = mock_activity.call_args
    assert len(args[0]) == 200
    assert kwargs["category"] == "agent_action"
    assert kwargs["source"] == "orchestrator"


def test_orchestrator_daily_activity_uses_unified_path():
    from server import _log_daily_activity

    with patch("server.memory_record_activity") as mock_activity:
        _log_daily_activity("Coding in VS Code", category="work")

    mock_activity.assert_called_once()
    args, kwargs = mock_activity.call_args
    assert args[0] == "Coding in VS Code"
    assert kwargs["category"] == "work"
    assert kwargs["source"] == "daily_tracker"


def test_orchestrator_heartbeat_uses_unified_path():
    """The daily heartbeat must not write the episodic file directly."""
    from server import _auto_log_daily_heartbeat

    with patch("server.memory_record_activity") as mock_activity:
        _auto_log_daily_heartbeat()

    mock_activity.assert_called_once()
    assert mock_activity.call_args.args[0].startswith("User active on ")


def test_server_has_no_direct_episodic_writer_import():
    """server.py no longer imports utils.episodic_writer directly — memory
    writes go through memory_bridge.record_activity."""
    import inspect

    import server as server_mod

    source = inspect.getsource(server_mod)
    assert "from utils.episodic_writer import append_event" not in source


# ---------------------------------------------------------------------------
# obsidian/tools.py — routes through the unified helper
# ---------------------------------------------------------------------------


def test_obsidian_memory_tool_uses_unified_path():
    """obsidian/tools.py memory writes route through record_activity
    (patched at the source, since the tool imports it lazily)."""
    from obsidian.tools import execute_memory_tool

    with patch("orchestrator.memory_bridge.record_activity") as mock_activity, \
         patch("utils.daily_tracker.log_activity"):
        result = asyncio.run(execute_memory_tool(
            "log_daily_activity", {"summary": "reading", "category": "learning"},
        ))
    assert '"status": "ok"' in result
    mock_activity.assert_called_once()
    assert mock_activity.call_args.kwargs["category"] == "learning"
    assert mock_activity.call_args.kwargs["source"] == "memory_tool"


def test_obsidian_tools_have_no_direct_episodic_writer_import():
    import inspect

    import obsidian.tools as tools_mod

    source = inspect.getsource(tools_mod)
    assert "from utils.episodic_writer import append_event" not in source
