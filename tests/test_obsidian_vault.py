"""Unit tests for obsidian/vault.py — tags normalization in save_note.

Guards against the real-world bug where the LLM passes `tags` as a string
(or a nested list) instead of the documented list[str], which caused
``TypeError: can only concatenate str (not "list")`` in the agent loop.
"""

from __future__ import annotations

import json
from unittest.mock import patch


def _call_save_note(tags, content="Note body"):
    """Call save_note with write_note mocked to capture frontmatter.

    Returns the captured full markdown written to the vault.
    """
    from obsidian.vault import save_note

    captured = {}

    def _fake_write_note(vault_path, full_content):
        captured["path"] = vault_path
        captured["content"] = full_content
        return {"status": "ok"}

    with patch("obsidian.vault.write_note", side_effect=_fake_write_note):
        # auto_link spawns a daemon thread — patch it out for determinism
        with patch("obsidian.vault._run_auto_link"):
            result = save_note("Knowledge/test-note", content, tags=tags)

    assert result == {"status": "ok"}
    return captured


class TestSaveNoteTagsNormalization:
    """save_note should tolerate str, list, and nested-list tags."""

    def test_list_tags(self):
        """Documented list[str] input works unchanged."""
        captured = _call_save_note(["programming", "AI"])
        assert "tags: [programming, AI, fol]" in captured["content"]

    def test_string_tags(self):
        """String tags should be wrapped, not crash (the original bug)."""
        captured = _call_save_note("programming")
        assert "tags: [programming, fol]" in captured["content"]

    def test_none_tags(self):
        """None tags should fall back to just ['fol']."""
        captured = _call_save_note(None)
        assert "tags: [fol]" in captured["content"]

    def test_nested_list_tags(self):
        """Nested lists should be flattened to strings."""
        captured = _call_save_note([["programming", "AI"], "python"])
        assert "tags: [programming, AI, python, fol]" in captured["content"]

    def test_mixed_types_in_tags(self):
        """Non-string entries (numbers, dicts) should be stringified."""
        captured = _call_save_note(["python", 3, {"k": "v"}])
        assert "tags: [python, 3, {'k': 'v'}, fol]" in captured["content"]

    def test_empty_list_tags(self):
        """Empty list should fall back to just ['fol']."""
        captured = _call_save_note([])
        assert "tags: [fol]" in captured["content"]


class TestExecuteMemoryToolNormalization:
    """execute_memory_tool should also normalize non-string fields."""

    def test_save_to_obsidian_with_string_tags(self):
        """String tags + valid fields should not crash."""
        import asyncio

        from obsidian.tools import execute_memory_tool

        captured = {}

        def _fake_write_note(vault_path, full_content):
            captured["path"] = vault_path
            captured["content"] = full_content
            return {"status": "ok"}

        with patch("obsidian.vault.write_note", side_effect=_fake_write_note), \
             patch("obsidian.vault._run_auto_link"), \
             patch("utils.episodic_writer.append_event"), \
             patch("utils.daily_tracker.log_activity"):
            result = asyncio.run(execute_memory_tool("save_to_obsidian", {
                "folder": "Knowledge",
                "title": "My Note",
                "content": "Body text",
                "tags": "programming, AI",  # model passed a string!
            }))

        assert result is not None
        assert "obsidian" in result or "saved_to" in result

    def test_save_to_obsidian_with_list_content(self):
        """List content should be JSON-encoded instead of crashing."""
        import asyncio

        from obsidian.tools import execute_memory_tool

        captured = {}

        def _fake_write_note(vault_path, full_content):
            captured["content"] = full_content
            return {"status": "ok"}

        with patch("obsidian.vault.write_note", side_effect=_fake_write_note), \
             patch("obsidian.vault._run_auto_link"), \
             patch("utils.episodic_writer.append_event"), \
             patch("utils.daily_tracker.log_activity"):
            result = asyncio.run(execute_memory_tool("save_to_obsidian", {
                "folder": "Knowledge",
                "title": "Note",
                "content": ["point 1", "point 2"],  # list content
            }))

        parsed = json.loads(result)
        assert parsed.get("saved_to") in ("obsidian", "episodic_fallback")


class TestClientV5Contract:
    """The client must speak the v5 API contract.

    Live probes against plugin 5.0.2 proved:
    - write_note must send {"content": ..., "type": "file"} (raw text is rejected)
    - search is POST /search/simple/?query=... returning a bare array
    - PATCH target resolution requires an indexed file → fallback is essential
    """

    def test_write_note_sends_json_body(self):
        """write_note must PUT {"content", "type":"file"}, not raw text."""
        import json

        from obsidian.client import write_note

        captured = {}

        def _fake_request(method, url, body=None, content_type="application/json"):
            captured["method"] = method
            captured["url"] = url
            captured["body"] = body
            captured["content_type"] = content_type
            return {}

        with patch("obsidian.client._request", side_effect=_fake_request), \
             patch("obsidian.client.is_configured", return_value=True):
            write_note("Knowledge/test", "# body")

        assert captured["method"] == "PUT"
        assert isinstance(captured["body"], dict)
        assert captured["body"]["content"] == "# body"
        assert captured["body"]["type"] == "file"
        assert captured["content_type"] == "application/json"
        assert captured["url"].endswith("/vault/Knowledge/test.md")

    def test_write_note_appends_md_extension(self):
        """v5 requires a .md path — client normalizes it."""
        from obsidian.client import write_note

        captured = {}

        def _fake_request(method, url, body=None, content_type="application/json"):
            captured["url"] = url
            return {}

        with patch("obsidian.client._request", side_effect=_fake_request), \
             patch("obsidian.client.is_configured", return_value=True):
            write_note("Knowledge/test-note", "body")

        assert "/vault/Knowledge/test-note.md" in captured["url"]

    def test_search_uses_query_param_and_parses_array(self):
        """v5 search returns a bare array; client normalizes to dicts."""
        from obsidian.client import search

        captured = {}

        def _fake_request(method, url, body=None, content_type="application/json"):
            captured["method"] = method
            captured["url"] = url
            return [
                {
                    "filename": "Knowledge/ai.md",
                    "score": 0.9,
                    "matches": [
                        {"match": {"start": 0, "end": 2, "source": "filename"},
                         "context": "ai"}
                    ],
                }
            ]

        with patch("obsidian.client._request", side_effect=_fake_request), \
             patch("obsidian.client.is_configured", return_value=True):
            results = search("artificial intelligence", limit=5)

        assert captured["method"] == "POST"
        assert "query=artificial+intelligence" in captured["url"]
        assert results[0]["path"] == "Knowledge/ai.md"
        assert results[0]["content"] == "ai"
        assert results[0]["score"] == 0.9

    def test_patch_note_falls_back_on_404(self):
        """When PATCH target can't resolve (fresh file), read→modify→write."""
        from obsidian.client import (
            ObsidianNotFoundError,
            patch_note,
        )

        calls = []

        def _fake_patch(method, url, body=None, content_type="application/json"):
            calls.append(("patch", url))
            raise ObsidianNotFoundError("heading target not resolvable")

        def _fake_read(method, url, body=None, content_type="application/json"):
            calls.append(("read", url))
            return {"content": "# Section\n\nbase\n"}

        def _fake_write(method, url, body=None, content_type="application/json"):
            calls.append(("write", url, body))
            return {}

        with patch("obsidian.client._request", side_effect=_fake_patch), \
             patch("obsidian.client.read_note", return_value="# Section\n\nbase\n"), \
             patch("obsidian.client.write_note", return_value={"status": "ok"}) as mock_write, \
             patch("obsidian.client.is_configured", return_value=True):
            result = patch_note(
                "Test/Section",
                target_type="heading",
                target=["Section"],
                operation="append",
                content="\n- item",
            )

        assert result["method"] == "fallback"
        mock_write.assert_called_once()
        written = mock_write.call_args[0][1]
        assert "- item" in written

    def test_patch_fallback_inserts_under_heading(self):
        """Fallback must insert under the right heading, not at random spots."""
        from obsidian.client import _insert_after_heading

        doc = "# Alpha\n\n## Section\n\nbase\n\n## Other\n\ntext\n"
        out = _insert_after_heading(doc, ["Section"], "\n- item", "append")
        assert "## Section\n\nbase\n- item" in out or "## Section\n\nbase\n\n- item" in out
        assert "Other" in out

    def test_append_to_note_read_write(self):
        """append_to_note must read, append at end, and write back."""
        from obsidian.client import append_to_note

        with patch("obsidian.client.read_note", return_value="# Doc\n\nbody\n"), \
             patch("obsidian.client.write_note", return_value={"status": "ok"}) as mock_write, \
             patch("obsidian.client.is_configured", return_value=True):
            result = append_to_note("Doc", "\n\ntail")

        assert result["status"] == "ok"
        written = mock_write.call_args[0][1]
        assert written.endswith("tail\n")

    def test_list_notes_falls_back_to_disk_on_404(self):
        """Freshly created folders may 404 via API — disk fallback."""
        from obsidian.client import ObsidianNotFoundError, list_notes

        with patch("obsidian.client._request", side_effect=ObsidianNotFoundError("folder unknown")):
            with patch("obsidian.client._list_from_disk", return_value=["SecondSelf/a.md"]):
                out = list_notes("SecondSelf")
        assert out == ["SecondSelf/a.md"]

    def test_read_note_parses_dict_content(self):
        """v5 GET returns {"content": ...} — client must extract it."""
        from obsidian.client import read_note

        with patch("obsidian.client._request", return_value={"content": "# hi"}), \
             patch("obsidian.client.is_configured", return_value=True):
            assert read_note("Knowledge/hi") == "# hi"


class TestCheckConnection:
    """check_connection should accept the plugin's case-insensitive status.

    The Local REST API plugin (v5) returns {"status": "OK"} (uppercase) —
    the client used to compare to lowercase "ok" and always reported the
    vault as disconnected, silently disabling Obsidian memory.
    """

    def test_uppercase_ok(self):
        from obsidian.client import check_connection

        with patch("obsidian.client.is_configured", return_value=True), \
             patch("obsidian.client._request", return_value={"status": "OK"}):
            assert check_connection() is True

    def test_lowercase_ok(self):
        from obsidian.client import check_connection

        with patch("obsidian.client.is_configured", return_value=True), \
             patch("obsidian.client._request", return_value={"status": "ok"}):
            assert check_connection() is True

    def test_missing_status_is_not_connected(self):
        from obsidian.client import check_connection

        with patch("obsidian.client.is_configured", return_value=True), \
             patch("obsidian.client._request", return_value={"manifest": {}}):
            assert check_connection() is False

    def test_connection_error_is_not_connected(self):
        from obsidian.client import ObsidianConnectionError, check_connection

        with patch("obsidian.client.is_configured", return_value=True), \
             patch("obsidian.client._request", side_effect=ObsidianConnectionError("down")):
            assert check_connection() is False
