"""Unit tests for analyze/_llm.py — provider selection and JSON parsing."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

import analyze._llm as llm


# ===========================================================================
# _get_config
# ===========================================================================


class TestGetConfig:
    """_get_config() reads LLM settings from environment."""

    def test_uses_env_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_MAX_TOKENS", "1500")
        monkeypatch.setenv("LLM_TEMPERATURE", "0")
        config = llm._get_config()
        assert config["model"] == "gpt-4o"

    def test_defaults_to_claude_sonnet(self) -> None:
        # Override the env so LLM_MODEL is not set (bypass .env file)
        with patch.dict(os.environ, {"LLM_MODEL": ""}, clear=True):
            with patch("analyze._llm.load_dotenv"):  # skip .env loading
                config = llm._get_config()
                assert config["model"] == "claude-sonnet-4-20250514"

    def test_uses_max_tokens_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_MAX_TOKENS", "3000")
        config = llm._get_config()
        assert config["max_tokens"] == "3000"

    def test_defaults_max_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.delenv("LLM_MAX_TOKENS", raising=False)
        config = llm._get_config()
        assert config["max_tokens"] == "1500"

    def test_uses_temperature_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.5")
        config = llm._get_config()
        assert config["temperature"] == "0.5"

    def test_defaults_temperature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "gpt-4o")
        monkeypatch.delenv("LLM_TEMPERATURE", raising=False)
        config = llm._get_config()
        assert config["temperature"] == "0"

    def test_strips_whitespace_from_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_MODEL", "  ollama/llama3  ")
        monkeypatch.setenv("LLM_MAX_TOKENS", "1500")
        config = llm._get_config()
        assert config["model"] == "ollama/llama3"

    def test_empty_model_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"LLM_MODEL": ""}, clear=True):
            with patch("analyze._llm.load_dotenv"):
                config = llm._get_config()
                assert config["model"] == "claude-sonnet-4-20250514"


# ===========================================================================
# _get_api_key_for_model
# ===========================================================================


class TestGetApiKeyForModel:
    """_get_api_key_for_model() maps model names to correct env var keys."""

    def test_anthropic_models_return_anthropic_key(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=False):
            result = llm._get_api_key_for_model("claude-sonnet-4-20250514")
            assert result == "sk-ant-test"

    def test_openai_models_return_openai_key(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai-test"}):
            result = llm._get_api_key_for_model("gpt-4o")
            assert result == "sk-openai-test"

    def test_ollama_models_return_local(self) -> None:
        result = llm._get_api_key_for_model("ollama/llama3.2:3b")
        assert result == "local"

    def test_local_prefix_returns_local(self) -> None:
        result = llm._get_api_key_for_model("local/my-model")
        assert result == "local"

    def test_vllm_prefix_returns_local(self) -> None:
        result = llm._get_api_key_for_model("vllm/mistral")
        assert result == "local"

    def test_gemini_models_return_gemini_key(self) -> None:
        with patch.dict(os.environ, {"GEMINI_API_KEY": "gemini-test"}):
            result = llm._get_api_key_for_model("gemini/gemini-2.0-flash")
            assert result == "gemini-test"

    def test_openrouter_models_return_openrouter_key(self) -> None:
        # Load .env may set OPENROUTER_API_KEY="", so use clear=True
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "or-test", "ANTHROPIC_API_KEY": ""}, clear=True):
            result = llm._get_api_key_for_model("openrouter/anthropic/claude-3.5-sonnet")
            assert result == "or-test"

    def test_deepseek_models_return_deepseek_key(self) -> None:
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "ds-test"}):
            result = llm._get_api_key_for_model("deepseek-chat")
            assert result == "ds-test"

    def test_groq_models_return_groq_key(self) -> None:
        with patch.dict(os.environ, {"GROQ_API_KEY": "gsk-test"}):
            result = llm._get_api_key_for_model("groq/llama3-70b-8192")
            assert result == "gsk-test"

    def test_together_models_return_together_key(self) -> None:
        with patch.dict(os.environ, {"TOGETHER_API_KEY": "tog-test"}):
            result = llm._get_api_key_for_model("together_ai/mistral")
            assert result == "tog-test"

    def test_lm_studio_returns_local(self) -> None:
        result = llm._get_api_key_for_model("lm-studio/local-model")
        assert result == "local"

    def test_fallback_to_anthropic(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-fallback"}):
            result = llm._get_api_key_for_model("unknown-model-v1")
            assert result == "sk-ant-fallback"

    def test_fallback_returns_none_when_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = llm._get_api_key_for_model("unknown-model")
            assert result is None

    def test_case_insensitive(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-oi-test"}):
            result = llm._get_api_key_for_model("GPT-4o-MINI")
            assert result == "sk-oi-test"

    def test_o1_models_use_openai(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-o1-test"}):
            result = llm._get_api_key_for_model("o1-preview")
            assert result == "sk-o1-test"

    def test_o3_models_use_openai(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-o3-test"}):
            result = llm._get_api_key_for_model("o3-mini")
            assert result == "sk-o3-test"


# ===========================================================================
# _strip_markdown_fences
# ===========================================================================


class TestStripMarkdownFences:
    """_strip_markdown_fences() removes ```json ... ``` blocks."""

    def test_no_fences_unchanged(self) -> None:
        assert llm._strip_markdown_fences("hello world") == "hello world"

    def test_strips_basic_fences(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        result = llm._strip_markdown_fences(text)
        assert result == '{"key": "value"}'

    def test_strips_without_json_label(self) -> None:
        text = '```\n{"key": "value"}\n```'
        result = llm._strip_markdown_fences(text)
        assert result == '{"key": "value"}'

    def test_strips_whitespace_before_fences(self) -> None:
        text = '  ```json\n{"key": "value"}\n```  '
        result = llm._strip_markdown_fences(text)
        assert result == '{"key": "value"}'

    def test_handles_empty_fence(self) -> None:
        text = '```json\n```'
        result = llm._strip_markdown_fences(text)
        assert result == ""

    def test_no_closing_fence(self) -> None:
        text = '```json\n{"key": "value"}\n'
        result = llm._strip_markdown_fences(text)
        assert result == '{"key": "value"}'

    def test_plain_text_inside_fence(self) -> None:
        text = "```\nsome plain text\n```"
        result = llm._strip_markdown_fences(text)
        assert result == "some plain text"

    def test_multiple_fences(self) -> None:
        text = '```json\n{"a": 1}\n```\n```json\n{"b": 2}\n```'
        result = llm._strip_markdown_fences(text)
        # Should only strip first fence pair
        assert '{"a": 1}' in result
        assert '{"b": 2}' in result


# ===========================================================================
# _is_rate_limit_error
# ===========================================================================


class TestIsRateLimitError:
    """_is_rate_limit_error() detects rate limit exceptions."""

    def test_detects_rate_limit_string(self) -> None:
        assert llm._is_rate_limit_error(Exception("rate_limit exceeded"))

    def test_detects_rate_limit_with_space(self) -> None:
        assert llm._is_rate_limit_error(Exception("rate limit hit"))

    def test_detects_429(self) -> None:
        assert llm._is_rate_limit_error(Exception("429 Too Many Requests"))

    def test_detects_quota_exceeded(self) -> None:
        assert llm._is_rate_limit_error(Exception("quota exceeded"))

    def test_detects_insufficient_quota(self) -> None:
        assert llm._is_rate_limit_error(Exception("insufficient_quota"))

    def test_detects_too_many_requests(self) -> None:
        assert llm._is_rate_limit_error(Exception("too many requests"))

    def test_returns_false_for_other_errors(self) -> None:
        assert not llm._is_rate_limit_error(Exception("connection timeout"))
        assert not llm._is_rate_limit_error(Exception("invalid API key"))
        assert not llm._is_rate_limit_error(Exception("bad request"))
        assert not llm._is_rate_limit_error(Exception(""))

    def test_case_insensitive(self) -> None:
        assert llm._is_rate_limit_error(Exception("RATE_LIMIT"))
        assert llm._is_rate_limit_error(Exception("Rate Limit"))


# ===========================================================================
# llm_call_json
# ===========================================================================


class TestLlmCallJson:
    """llm_call_json() parses LLM responses into JSON dicts."""

    @patch("analyze._llm.llm_call", return_value='{"name": "John", "age": 30}')
    def test_parses_valid_json(self, mock_call: MagicMock) -> None:
        result = llm.llm_call_json("extract", "John is 30")
        assert result == {"name": "John", "age": 30}

    @patch("analyze._llm.llm_call", return_value='```json\n{"name": "John"}\n```')
    def test_strips_markdown_fences(self, mock_call: MagicMock) -> None:
        result = llm.llm_call_json("extract", "John")
        assert result == {"name": "John"}

    @patch("analyze._llm.llm_call", return_value="")
    def test_empty_response_returns_empty_dict(self, mock_call: MagicMock) -> None:
        result = llm.llm_call_json("extract", "data")
        assert result == {}

    @patch("analyze._llm.llm_call")
    def test_retries_on_non_json(self, mock_call: MagicMock) -> None:
        """Should retry with higher temperature when JSON parsing fails."""
        mock_call.side_effect = [
            "not json at all",          # first attempt (temp=0) — fails
            '{"name": "John"}',          # second attempt (temp=0.3) — succeed
        ]
        result = llm.llm_call_json("extract", "John")
        assert result == {"name": "John"}
        assert mock_call.call_count == 2

    @patch("analyze._llm.llm_call")
    def test_wraps_list_in_data_key(self, mock_call: MagicMock) -> None:
        """Lists should be wrapped in a {'data': [...]} dict."""
        mock_call.return_value = '["a", "b", "c"]'
        result = llm.llm_call_json("extract", "data")
        assert result == {"data": ["a", "b", "c"]}

    @patch("analyze._llm.llm_call")
    def test_all_attempts_fail_returns_empty(self, mock_call: MagicMock) -> None:
        """When all retries fail, return {}."""
        mock_call.side_effect = ["not json", "also not json"]
        result = llm.llm_call_json("extract", "data")
        assert result == {}
        assert mock_call.call_count == 2

    @patch("analyze._llm.llm_call", return_value="null")
    def test_json_null_returns_empty(self, mock_call: MagicMock) -> None:
        """JSON null should return {} since it's not a dict."""
        result = llm.llm_call_json("extract", "data")
        assert result == {}

    @patch("analyze._llm.llm_call", return_value="123")
    def test_json_number_returns_empty(self, mock_call: MagicMock) -> None:
        result = llm.llm_call_json("extract", "data")
        assert result == {}

    def test_passes_max_tokens(self) -> None:
        with patch.object(llm, "llm_call", return_value='{"ok": true}') as mock_call:
            llm.llm_call_json("extract", "data", max_tokens=500)
            # llm_call has signature (prompt, text_block, max_tokens=None)
            # so max_tokens is passed as positional arg
            mock_call.assert_called_once_with("extract", "data", 500)

    @patch("analyze._llm.llm_call")
    def test_skips_retry_when_first_attempt_empty(self, mock_call: MagicMock) -> None:
        """If first attempt returns empty string, skip to second temperature."""
        mock_call.side_effect = ["", '{"ok": true}']
        result = llm.llm_call_json("extract", "data")
        assert result == {"ok": True}
        assert mock_call.call_count == 2


# ===========================================================================
# llm_call
# ===========================================================================


class TestLlmCall:
    """llm_call() sends prompts to LiteLLM."""

    def test_returns_empty_when_no_api_key(self) -> None:
        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value=None):
                result = llm.llm_call("prompt", "text")
        assert result == ""

    def test_passes_api_key_to_litellm(self) -> None:
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "hello"

        # litellm is imported dynamically inside llm_call().
        # We pre-populate sys.modules so the import picks up our mock.
        mock_litellm = MagicMock()
        mock_litellm.completion.return_value = mock_response
        mock_litellm.exceptions = MagicMock()  # prevent AttributeError on exception submodule

        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value="sk-test"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.llm_call("prompt", "text")

        assert result == "hello"
        mock_litellm.completion.assert_called_once()
        kwargs = mock_litellm.completion.call_args.kwargs
        assert kwargs["api_key"] == "sk-test"

    def test_local_model_passes_none_api_key(self) -> None:
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "OK"

        mock_litellm = MagicMock()
        mock_litellm.completion.return_value = mock_response
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "ollama/llama3", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value="local"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.llm_call("prompt", "text")

        assert result == "OK"
        kwargs = mock_litellm.completion.call_args.kwargs
        assert kwargs["api_key"] is None


# ===========================================================================
# _get_model_chain (model fallback chain)
# ===========================================================================


class TestGetModelChain:
    """_get_model_chain() builds the primary + fallback priority list."""

    def test_primary_only_when_no_fallbacks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value="sk-test"):
                assert llm._get_model_chain() == ["gpt-4o"]

    def test_appends_fallbacks_in_order(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "claude-sonnet-4-20250514, ollama/llama3.2:3b")
        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value="sk-test"):
                assert llm._get_model_chain() == ["gpt-4o", "claude-sonnet-4-20250514", "ollama/llama3.2:3b"]

    def test_skips_models_without_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            def _fake_key(model: str) -> str | None:
                return "sk-test" if model == "gpt-4o" else None
            with patch.object(llm, "_get_api_key_for_model", side_effect=_fake_key):
                assert llm._get_model_chain() == ["gpt-4o"]

    def test_deduplicates_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "gpt-4o")
        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value="sk-test"):
                assert llm._get_model_chain() == ["gpt-4o"]

    def test_empty_chain_when_no_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value=None):
                assert llm._get_model_chain() == []


# ===========================================================================
# llm_call fallback
# ===========================================================================


class TestLlmCallFallback:
    """llm_call() falls back to the next model when the primary fails."""

    def test_falls_back_to_next_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "from fallback"

        mock_litellm = MagicMock()
        # gpt-4o fails on BOTH temperature attempts (temp=0 and temp=0.3),
        # then the fallback model succeeds.
        mock_litellm.completion.side_effect = [
            Exception("connection error"), Exception("connection error"), mock_response,
        ]
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.llm_call("prompt", "text")

        assert result == "from fallback"
        models = [c.kwargs["model"] for c in mock_litellm.completion.call_args_list]
        assert models == ["gpt-4o", "gpt-4o", "ollama/llama3.2:3b"]

    def test_returns_empty_when_all_models_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        mock_litellm = MagicMock()
        mock_litellm.completion.side_effect = Exception("everything is down")
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.llm_call("prompt", "text")

        assert result == ""
        models = {c.kwargs["model"] for c in mock_litellm.completion.call_args_list}
        assert models == {"gpt-4o", "ollama/llama3.2:3b"}

    def test_returns_empty_when_chain_is_empty(self) -> None:
        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value=None):
                result = llm.llm_call("prompt", "text")
        assert result == ""

    def test_rate_limit_fails_fast_when_fallback_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Quota/429 on the primary must NOT sleep — fall back immediately."""
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "fallback answer"

        mock_litellm = MagicMock()
        mock_litellm.completion.side_effect = [
            Exception("insufficient_quota"),  # primary: rate limit -> fail fast
            mock_response,                     # fallback succeeds
        ]
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch("analyze._llm.time.sleep") as mock_sleep:
                    with patch.dict("sys.modules", {"litellm": mock_litellm}):
                        result = llm.llm_call("prompt", "text")

        assert result == "fallback answer"
        # Only ONE attempt on the primary (no temperature escalation),
        # no retry sleeps, straight to the fallback model.
        models = [c.kwargs["model"] for c in mock_litellm.completion.call_args_list]
        assert models == ["gpt-4o", "ollama/llama3.2:3b"]
        mock_sleep.assert_not_called()

    def test_falls_back_when_primary_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty model response is NOT an answer — the chain must move on
        (stress-test finding: empty primary previously short-circuited)."""
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        empty_response = MagicMock()
        empty_response.choices[0].message.content = ""
        fallback_response = MagicMock()
        fallback_response.choices[0].message.content = "fallback answer"

        mock_litellm = MagicMock()
        mock_litellm.completion.side_effect = [empty_response, fallback_response]
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.llm_call("prompt", "text")

        assert result == "fallback answer"
        models = [c.kwargs["model"] for c in mock_litellm.completion.call_args_list]
        assert models == ["gpt-4o", "ollama/llama3.2:3b"]

    def test_returns_empty_when_all_models_return_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """All models returning empty → graceful '' (never raises)."""
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        empty_response = MagicMock()
        empty_response.choices[0].message.content = ""

        mock_litellm = MagicMock()
        mock_litellm.completion.return_value = empty_response
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.llm_call("prompt", "text")

        assert result == ""


# ===========================================================================
# test_connection
# ===========================================================================


class TestTestConnection:
    """test_connection() checks if the configured model is reachable."""

    def test_returns_error_when_no_api_key(self) -> None:
        with patch.object(llm, "_get_api_key_for_model", return_value=None):
            with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
                result = llm.test_connection()
        assert "No API key" in result

    def test_success_with_local_model(self) -> None:
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "OK"

        mock_litellm = MagicMock()
        mock_litellm.completion.return_value = mock_response
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "ollama/llama3", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value="local"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.test_connection()
        assert "responds: OK" in result

    def test_returns_error_on_exception(self) -> None:
        mock_litellm = MagicMock()
        mock_litellm.completion.side_effect = Exception("timeout")
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "ollama/llama3", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value="local"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.test_connection()
        assert "failed" in result or "timeout" in result

    def test_falls_back_to_working_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_FALLBACK_MODELS", "ollama/llama3.2:3b")
        mock_ok = MagicMock()
        mock_ok.choices[0].message.content = "OK"

        mock_litellm = MagicMock()
        mock_litellm.completion.side_effect = [Exception("down"), mock_ok]
        mock_litellm.exceptions = MagicMock()

        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", side_effect=lambda m: "local" if m.startswith("ollama") else "sk-test"):
                with patch.dict("sys.modules", {"litellm": mock_litellm}):
                    result = llm.test_connection()

        assert "ollama/llama3.2:3b responds: OK" in result

    def test_connection_no_models(self) -> None:
        with patch.object(llm, "_get_config", return_value={"model": "gpt-4o", "max_tokens": "1500", "temperature": "0"}):
            with patch.object(llm, "_get_api_key_for_model", return_value=None):
                result = llm.test_connection()
        assert "No API key" in result
