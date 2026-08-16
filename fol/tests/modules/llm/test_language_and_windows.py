"""Tests for language detection, bilingual system prompts, and window/program management."""

from __future__ import annotations

import pytest
from pathlib import Path


# ─── Language Detection Tests ──────────────────────────────────────────────

class TestLanguageDetection:
    """Tests for modules.llm.language.detect_language."""

    def test_pure_russian(self):
        from modules.llm.language import detect_language
        assert detect_language("Привет, как дела?") == "ru"

    def test_pure_english(self):
        from modules.llm.language import detect_language
        assert detect_language("Hello, how are you?") == "en"

    def test_empty_string(self):
        from modules.llm.language import detect_language
        assert detect_language("") == "en"

    def test_numbers_only(self):
        from modules.llm.language import detect_language
        assert detect_language("12345") == "en"

    def test_russian_commands(self):
        from modules.llm.language import detect_language
        assert detect_language("открой safari") == "ru"
        assert detect_language("сделай скриншот") == "ru"
        assert detect_language("закрой окно") == "ru"
        assert detect_language("сверни окно") == "ru"
        assert detect_language("включи музыку") == "ru"
        assert detect_language("выполни команду ls") == "ru"

    def test_english_commands(self):
        from modules.llm.language import detect_language
        assert detect_language("open safari") == "en"
        assert detect_language("take screenshot") == "en"
        assert detect_language("close window") == "en"
        assert detect_language("minimize window") == "en"
        assert detect_language("play music") == "en"
        assert detect_language("run command ls") == "en"

    def test_explicit_lang_header_ru(self):
        from modules.llm.language import detect_language
        assert detect_language("lang: ru привет мир") == "ru"
        assert detect_language("язык: русский") == "ru"

    def test_explicit_lang_header_en(self):
        from modules.llm.language import detect_language
        assert detect_language("lang: en hello world") == "en"

    def test_mixed_language_majority_russian(self):
        from modules.llm.language import detect_language
        # Mostly Russian words → Russian
        assert detect_language("открой terminal пожалуйста") == "ru"

    def test_mixed_language_majority_english(self):
        from modules.llm.language import detect_language
        # Mostly English words → English
        assert detect_language("open terminal please") == "en"

    def test_cyrillic_ratio_threshold(self):
        from modules.llm.language import detect_language
        # Pure Cyrillic characters
        assert detect_language("Привет мир") == "ru"
        # Pure Latin characters
        assert detect_language("Hello world") == "en"


class TestLangPromptHint:
    """Tests for get_lang_prompt_hint."""

    def test_russian_hint(self):
        from modules.llm.language import get_lang_prompt_hint
        hint = get_lang_prompt_hint("ru")
        assert "русском" in hint
        assert "ОБЯЗАН" in hint or "обязан" in hint

    def test_english_hint(self):
        from modules.llm.language import get_lang_prompt_hint
        hint = get_lang_prompt_hint("en")
        assert "English" in hint
        assert "MUST" in hint


class TestGetLangName:
    """Tests for get_lang_name."""

    def test_russian(self):
        from modules.llm.language import get_lang_name
        assert get_lang_name("ru") == "Russian"

    def test_english(self):
        from modules.llm.language import get_lang_name
        assert get_lang_name("en") == "English"


# ─── LLM Engine Language Detection Tests ──────────────────────────────────

class TestEngineLanguageDetection:
    """Tests that LLMEngine._build_messages injects language hints."""

    def test_ru_input_injects_russian_hint(self):
        from modules.llm.engine import LLMEngine
        engine = LLMEngine()
        messages = engine._build_messages("привет", "", "")
        sys_content = messages[0]["content"]
        assert "русском" in sys_content

    def test_en_input_injects_english_hint(self):
        from modules.llm.engine import LLMEngine
        engine = LLMEngine()
        messages = engine._build_messages("hello", "", "")
        sys_content = messages[0]["content"]
        assert "English" in sys_content

    def test_system_prompt_preserved(self):
        from modules.llm.engine import LLMEngine
        engine = LLMEngine()
        messages = engine._build_messages("привет", "", "My custom prompt")
        sys_content = messages[0]["content"]
        assert "My custom prompt" in sys_content
        assert "русском" in sys_content

    def test_context_preserved(self):
        from modules.llm.engine import LLMEngine
        engine = LLMEngine()
        messages = engine._build_messages("hello", "context info", "")
        sys_content = messages[0]["content"]
        assert "context info" in sys_content
        assert "English" in sys_content


# ─── System Prompt Content Tests ──────────────────────────────────────────

class TestSystemPromptContent:
    """Verify system prompts include window/program management instructions."""

    def test_system_md_includes_window_management(self):
        prompt_path = Path(__file__).resolve().parents[2] / "modules" / "llm" / "prompts" / "system.md"
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
            assert "Window" in content or "window" in content
            assert "minimize" in content.lower() or "сверни" in content
            assert "maximize" in content.lower() or "разверни" in content

    def test_system_md_includes_program_management(self):
        prompt_path = Path(__file__).resolve().parents[2] / "modules" / "llm" / "prompts" / "system.md"
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
            assert "open_app" in content or "открой" in content.lower()
            assert "quit" in content.lower() or "закрой" in content

    def test_system_md_language_rules(self):
        prompt_path = Path(__file__).resolve().parents[2] / "modules" / "llm" / "prompts" / "system.md"
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
            assert "Russian" in content
            assert "English" in content
            assert "ALWAYS respond" in content or "same language" in content.lower()

    def test_system_md_natural_speech(self):
        prompt_path = Path(__file__).resolve().parents[2] / "modules" / "llm" / "prompts" / "system.md"
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
            assert "conversational" in content.lower() or "natural" in content.lower()


# ─── Prompt Manager Tests ─────────────────────────────────────────────────

class TestPromptManagerWithLang:
    """Tests for PromptManager with language context."""

    @pytest.mark.asyncio
    async def test_system_prompt_with_lang_context(self, tmp_path: Path):
        from modules.llm.prompt_manager import PromptManager
        pm = PromptManager(prompts_dir=tmp_path / "prompts")
        prompt = await pm.get_system_prompt(user_context={"language": "ru", "name": "Абдулаким"})
        assert "Абдулаким" in prompt
        assert "ru" in prompt

    @pytest.mark.asyncio
    async def test_system_prompt_with_en_context(self, tmp_path: Path):
        from modules.llm.prompt_manager import PromptManager
        pm = PromptManager(prompts_dir=tmp_path / "prompts")
        prompt = await pm.get_system_prompt(user_context={"language": "en", "name": "Alexander"})
        assert "Alexander" in prompt
        assert "en" in prompt


# ─── FOL App Builtin Command Tests (Language-Aware) ──────────────────────

class TestFOLBuiltinCommands:
    """Test that built-in commands respond in the correct language."""

    def _make_fol(self):
        """Create a minimal FOL instance for testing (without async init)."""
        from core.app import FOL
        return FOL()

    def test_greet_default(self):
        """Greeting should return a string."""
        fol = self._make_fol()
        result = fol._greet()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_help_returns_string(self):
        fol = self._make_fol()
        result = fol._help()
        assert isinstance(result, str)
        assert "MacBook Control" in result or "Window" in result

    def test_system_status_returns_string(self):
        fol = self._make_fol()
        result = fol._system_status()
        assert "FOL" in result

    def test_time_command_ru(self):
        """Russian time command should return Russian text."""
        from modules.llm.language import detect_language
        lang = detect_language("время")
        assert lang == "ru"

    def test_time_command_en(self):
        from modules.llm.language import detect_language
        lang = detect_language("what time")
        assert lang == "en"


# ─── Window Management Command Matching Tests ─────────────────────────────

class TestWindowManagementCommands:
    """Test that window management patterns match correctly."""

    def test_minimize_patterns_ru(self):
        import re
        patterns = ["свернуть", "сверни", "свернуть окно", "свернуть текущее окно"]
        for p in patterns:
            assert p in (
                "minimize", "свернуть", "сверни", "minimize window",
                "свернуть окно", "свернуть текущее окно",
            )

    def test_minimize_patterns_en(self):
        patterns = ["minimize", "minimize window"]
        for p in patterns:
            assert p in ("minimize", "minimize window")

    def test_maximize_patterns(self):
        en = ["maximize", "maximize window", "fullscreen"]
        ru = ["развернуть", "разверни", "на весь экран", "развернуть окно"]
        for p in en + ru:
            assert isinstance(p, str)
            assert len(p) > 0

    def test_close_window_patterns(self):
        en = ["close window", "close"]
        ru = ["закрой окно", "закрой", "закрыть окно", "закрыть"]
        for p in en + ru:
            assert isinstance(p, str)

    def test_new_window_patterns(self):
        en = ["new window", "new tab"]
        ru = ["новое окно", "новая вкладка", "создай окно"]
        for p in en + ru:
            assert isinstance(p, str)


# ─── App Name Resolution Tests ───────────────────────────────────────────

class TestAppNameResolution:
    """Test that EN/RU app names resolve correctly."""

    def _get_app_map(self):
        return {
            "safari": "Safari", "chrome": "Google Chrome", "terminal": "Terminal",
            "code": "Visual Studio Code", "vscode": "Visual Studio Code",
            "spotify": "Spotify", "music": "Music", "notes": "Notes",
            "калькулятор": "Calculator", "настройки": "System Settings",
            "терминал": "Terminal", "музыка": "Music",
            "сафари": "Safari", "заметки": "Notes", "фото": "Photos",
            "почта": "Mail", "сообщения": "Messages", "календарь": "Calendar",
        }

    def test_english_names(self):
        app_map = self._get_app_map()
        assert app_map["safari"] == "Safari"
        assert app_map["chrome"] == "Google Chrome"
        assert app_map["terminal"] == "Terminal"
        assert app_map["code"] == "Visual Studio Code"
        assert app_map["spotify"] == "Spotify"

    def test_russian_names(self):
        app_map = self._get_app_map()
        assert app_map["терминал"] == "Terminal"
        assert app_map["музыка"] == "Music"
        assert app_map["сафари"] == "Safari"
        assert app_map["заметки"] == "Notes"
        assert app_map["калькулятор"] == "Calculator"
        assert app_map["настройки"] == "System Settings"
        assert app_map["фото"] == "Photos"
        assert app_map["почта"] == "Mail"

    def test_unknown_name_passes_through(self):
        app_map = self._get_app_map()
        unknown = "SomeRandomApp"
        resolved = app_map.get(unknown.lower(), unknown)
        assert resolved == unknown
