"""Context Engine — определяет контекст пользователя.

Модули:
- app_monitor.py: активное приложение (через AppleScript)
- window_analyzer.py: заголовки окон
- browser_url.py: URL из браузеров
- project_detector.py: проект из IDE/Terminal
- snapshot.py: полный снимок контекста
"""

from context_engine.snapshot import get_snapshot, ContextSnapshot, format_context_for_prompt

__all__ = ["get_snapshot", "ContextSnapshot", "format_context_for_prompt"]
