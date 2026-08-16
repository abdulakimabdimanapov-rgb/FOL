"""Diagnostic tests for the FOL responder chain.

Reuses the helpers from ``scripts/diagnose_responder.py`` (health probes,
SSE parsing, canned-stub detection) so the standalone diagnostic and the
pytest suite share one source of truth.

Guarantees covered here (the regression this project hit):
  - The orchestrator's /chat and /command responses must be REAL natural
    language — never the canned stub ``"Сделано. Могу помочь с чем-то ещё?"``
    that the Response Formatter emits when the LLM chain produced nothing.
  - The stub-detection list must stay in sync with the formatter's actual
    fallback (if someone changes the fallback text, the test fails loudly).

Two tiers:
  - Deterministic unit tests — always run, no network.
  - Live integration tests — hit the running services (orchestrator 8420,
    FOL 8754) and assert responses are not stubs; automatically SKIP when
    the services are not up (so ``pytest`` stays green in CI without them).
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

# scripts/ must be importable (conftest already adds tests/, orchestrator/, root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import diagnose_responder as dr  # noqa: E402

from orchestrator.response_formatter import (  # noqa: E402
    _natural_final_fallback,
    format_final_response,
)

# ---------------------------------------------------------------------------
# Live-test gating
#
# Live tests hit the real services and the real LLM (slow, costs credits).
# They run by default when the services are up, and are skipped when:
#   - the service port is closed (services not running), or
#   - FOL_SKIP_LIVE_TESTS=1 is set (CI without live services / credits).
# ---------------------------------------------------------------------------

_SKIP_LIVE = os.environ.get("FOL_SKIP_LIVE_TESTS", "") in ("1", "true", "yes")


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


needs_orchestrator = pytest.mark.skipif(
    _SKIP_LIVE or not _port_open(8420),
    reason="orchestrator (8420) not running or FOL_SKIP_LIVE_TESTS=1 — skipping live check",
)
needs_fol = pytest.mark.skipif(
    _SKIP_LIVE or not _port_open(8754),
    reason="FOL API (8754) not running or FOL_SKIP_LIVE_TESTS=1 — skipping live check",
)


# ---------------------------------------------------------------------------
# Canned-stub detection (deterministic)
# ---------------------------------------------------------------------------

class TestIsCannedStub:
    """The stub detector must catch every canned fallback variant."""

    def test_detects_russian_stub(self):
        assert dr.is_canned_stub("Сделано. Могу помочь с чем-то ещё?")

    def test_detects_english_stub(self):
        assert dr.is_canned_stub("All set. Anything else I can help with?")

    def test_detects_llm_failure_stub(self):
        assert dr.is_canned_stub("All 1 model(s) failed")

    def test_detects_stub_embedded_in_longer_text(self):
        # Stub preceded/followed by noise must still be caught.
        assert dr.is_canned_stub("  Сделано. Могу помочь с чем-то ещё?   ")
        assert dr.is_canned_stub("[orchestrator] Сделано. Могу помочь с чем-то ещё? END")

    def test_real_answers_are_not_stubs(self):
        for text in (
            "Привет! У меня всё в порядке, спасибо. Как могу помочь?",
            "Открыл Safari.",
            "Сейчас 17:19 по всемирному времени (UTC).",
            "Искусственный интеллект — это область компьютерных наук...",
            "Калькулятор открыт.",
            "",
        ):
            assert not dr.is_canned_stub(text), text

    def test_empty_or_none_never_stub(self):
        assert not dr.is_canned_stub("")
        assert not dr.is_canned_stub(None)


class TestDetectorInSyncWithFormatter:
    """The detector list MUST match the formatter's actual fallback text.

    If ``_natural_final_fallback`` changes (e.g. reworded to "Готово. Что-то
    ещё?"), this test fails — forcing an update of ``_CANNED_FALLBACKS`` so
    the live auto-check keeps working.
    """

    def test_russian_fallback_is_detected(self):
        assert dr.is_canned_stub(_natural_final_fallback("ru"))

    def test_english_fallback_is_detected(self):
        assert dr.is_canned_stub(_natural_final_fallback("en"))


class TestFormatterProducesRealText:
    """format_final_response must yield real text for real model output."""

    def test_real_text_passes_through_unchanged(self):
        out = format_final_response("Привет! Всё хорошо, спасибо.", [], "ru")
        assert not dr.is_canned_stub(out)
        assert "Привет" in out

    def test_real_text_english(self):
        out = format_final_response("Everything is fine, thanks.", [], "en")
        assert not dr.is_canned_stub(out)

    def test_rebuilt_confirmation_is_not_stub(self):
        # Bare "Готово." + an executed tool → rebuilt to a natural confirmation.
        out = format_final_response("Готово.", [("open_app", {"name": "Safari"})], "ru")
        assert out == "Открыл Safari."
        assert not dr.is_canned_stub(out)


class TestFormatterFallbackIsStub:
    """The formatter's fallback for a dead LLM chain IS the stub — the live
    auto-check must fail loudly if a response comes back this way."""

    def test_empty_model_output_becomes_stub(self):
        out = format_final_response("", [], "ru")
        assert dr.is_canned_stub(out)  # must be caught by the detector

    def test_llm_unavailable_message_never_leaks_raw(self):
        # The raw engine message is technical state — it must be replaced by
        # friendly text. The friendly text is NOT the "Сделано…" stub (that
        # stub is only for empty output), but raw technical text must never
        # surface either.
        raw = "All LLM backends are unavailable. Please configure an API key or install mlx-lm."
        out = format_final_response(raw, [], "ru")
        assert out.strip()
        assert not dr.is_canned_stub(out)  # friendly replacement, not the stub
        assert "mlx-lm" not in out.lower()
        assert "backend" not in out.lower()


# ---------------------------------------------------------------------------
# Live integration checks (auto-skip when services are down)
# ---------------------------------------------------------------------------

@needs_fol
class TestLiveFolChat:
    """FOL web-UI chat (port 8754) must answer with real text, never a stub."""

    def test_time_command_returns_real_answer(self):
        st, data = dr.post(dr.FOL + "/api/chat", {"message": "time"}, timeout=60)
        assert st == 200
        resp = data.get("response", "") if isinstance(data, dict) else str(data)
        assert resp.strip()
        assert not dr.is_canned_stub(resp)

    def test_llm_question_returns_non_stub(self):
        st, data = dr.post(
            dr.FOL + "/api/chat",
            {"message": "Что такое искусственный интеллект? Ответь в одном предложении."},
            timeout=90,
        )
        assert st == 200
        resp = data.get("response", "") if isinstance(data, dict) else str(data)
        assert resp.strip()
        assert not resp.startswith("All LLM")
        assert not dr.is_canned_stub(resp)


@needs_orchestrator
class TestLiveOrchestrator:
    """Orchestrator chat (port 8420) must stream real text, never a stub."""

    def test_chat_sse_not_stub(self):
        st, events, _tail = dr.sse_post(dr.ORCH + "/chat", {"message": "Привет!"}, timeout=90)
        assert st == 200
        text = "".join(e.get("text", "") for e in events if e.get("text"))
        assert text.strip(), "no text tokens streamed"
        assert not dr.is_canned_stub(text)
        assert "<invoke>" not in text and "tool_use" not in text

    def test_command_not_stub(self):
        st, data = dr.post(dr.ORCH + "/command", {"task": "Который час?"}, timeout=90)
        assert st == 200
        resp = data.get("response", "") if isinstance(data, dict) else ""
        assert resp.strip()
        assert not dr.is_canned_stub(resp)
