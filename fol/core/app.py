"""Main FOL application class — entry point for the system.

Unified FOL with all JARVIS capabilities:
- Speech (TTS/STT with wake word)
- Vision (screenshots, OCR, active window)
- Long-term memory (knowledge triples, episodes)
- Rich CLI commands (bilingual RU/EN)
- LLM inference (MLX local + cloud backends)
- Tool execution (system, files, browser, mouse/keyboard)
- Plugin system
- REST API + WebSocket
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import platform
import random
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from config.settings import settings
from config.logging import setup_logging
from core.event_bus import Event, EventBus, EventType
from core.lifecycle import LifecycleManager
from core.task_manager import TaskManager
from core.context_manager import ContextManager
from core.orchestrator import Orchestrator
from modules.llm.language import detect_language
from modules.llm.personality import (
    contextual_confirmation,
    is_terse_response,
    polish_response,
)
from modules.tools.system.universal_executor import UniversalExecutor
from modules.brain.startup import BrainStartupManager

logger = logging.getLogger(__name__)

START_TIME = time.time()
FOL_DIR = Path.home() / ".fol"


class FOL:
    """FOL — Friendly Obedient Listener.

    Personal AI assistant with JARVIS-level capabilities:
    voice, vision, memory, tools, and intelligence.
    """

    def __init__(self) -> None:
        self.version = "2.0.0"
        self.start_time = time.time()
        self.config = settings
        self.event_bus = EventBus()
        self.task_manager = TaskManager()
        self.context_manager = ContextManager()
        self.lifecycle = LifecycleManager()
        self.orchestrator = Orchestrator(
            event_bus=self.event_bus,
            task_manager=self.task_manager,
            context_manager=self.context_manager,
        )

        # Core modules
        self._llm = None
        self._tools = None
        self._tts_output = None

        # Brain startup and health management
        self._brain_manager: Any = None
        self._brain_interface: Any = None
        self._brain_status: dict[str, Any] = {"state": "unknown"}

        # JARVIS capabilities
        self._voice: Any = None
        self._vision: Any = None
        self._long_term_memory: Any = None
        self._obsidian: Any = None
        self._brain: Any = None
        self._telegram: Any = None
        self._identity: Any = None
        self._tts_enabled = True
        self._voice_enabled = False

        # State
        self._conversation_history: list[dict[str, str]] = []
        self._max_history: int = 100  # max turns kept in memory
        self._memories: list[dict[str, Any]] = []
        self._preferences: dict[str, Any] = {}
        self._knowledge: dict[str, Any] = {}
        self._universal_executor: Any = None
        # Current conversation topic — lets follow-ups like "А какая самая
        # важная?" reference the previous turn (Context Conversation, Stage 1).
        self._topic: str = ""
        # Conversation mode (ROADMAP Этап 2): companion / assistant / agent /
        # focus. Focus = minimal talk, maximum action; Agent = complex
        # multi-step tasks. Switched by voice or text ("режим фокус").
        self._mode: str = "companion"
        # Last executed tool (name, args) — used by the Personality Layer to
        # build a contextual confirmation when the raw answer is terse.
        self._last_tool: tuple[str, dict[str, Any]] | None = None
        # Proactive Mode (ROADMAP Etap 5) — ambient suggestions runtime state.
        # Initialized in _init_proactive() during startup (or lazily).
        self._proactive: Any = None
        # Canonical ConfirmationGate — created in _on_startup once the tool
        # registry exists. The proactive execute path consults it so a
        # suggestion can never bypass normal tool safety (Phase 8).
        self._gate: Any = None

        # Ensure directories exist
        FOL_DIR.mkdir(parents=True, exist_ok=True)
        (FOL_DIR / "screenshots").mkdir(exist_ok=True)
        (FOL_DIR / "memory_db").mkdir(exist_ok=True)

        # Initialize long-term memory
        self._init_long_term_memory()

        # Initialize Obsidian memory
        self._init_obsidian()

        # Initialize the Freebuff Brain (persistent memory that survives
        # model changes — everything we do is journaled in Obsidian)
        self._init_brain()

        # Initialize Telegram
        self._init_telegram()

        # Initialize Identity Layers
        self._init_identity()

        # Register lifecycle hooks
        self.lifecycle.on_startup(self._on_startup)
        self.lifecycle.on_shutdown(self._on_shutdown)

    def _init_long_term_memory(self) -> None:
        """Initialize the long-term memory system."""
        try:
            from modules.memory.long_term import LongTermMemory
            self._long_term_memory = LongTermMemory()
            logger.info("Long-term memory initialized")
        except Exception as exc:
            logger.warning("Failed to init long-term memory: %s", exc)

    def _init_obsidian(self) -> None:
        """Initialize Obsidian persistent memory."""
        try:
            from modules.memory.obsidian import ObsidianMemory
            vault_path = getattr(settings, "obsidian_vault", None)
            self._obsidian = ObsidianMemory(vault_path=vault_path)
            stats = self._obsidian.get_stats()
            logger.info("Obsidian memory initialized", vault=str(self._obsidian._vault), notes=stats["total"])
        except Exception as exc:
            logger.warning("Failed to init Obsidian memory: %s", exc)

    def _init_brain(self) -> None:
        """Initialize the Freebuff Brain — persistent Obsidian memory that
        survives model changes. Every interaction is journaled and the most
        relevant context is injected into the LLM prompt, so a fresh model
        already knows the user.

        Disabled when Obsidian is disabled (FOL_OBSIDIAN_ENABLED=false) or
        explicitly via FOL_BRAIN_ENABLED=false (tests). Never raises."""
        try:
            if os.environ.get("FOL_BRAIN_ENABLED", "1") == "0":
                logger.debug("Freebuff Brain disabled (FOL_BRAIN_ENABLED=0)")
                return
            if not getattr(settings, "obsidian_enabled", True):
                logger.debug("Freebuff Brain disabled (obsidian_enabled=false)")
                return
            from modules.memory.brain import Brain
            vault_path = getattr(settings, "obsidian_vault", None)
            shared_vault = getattr(settings, "brain_vault", None)
            self._brain = Brain(vault_path=vault_path, shared_vault=shared_vault)
            logger.info(
                "Freebuff Brain initialized (shared_vault=%s)",
                shared_vault or "none",
            )
        except Exception as exc:
            logger.warning("Failed to init Brain: %s", exc)

    def _init_telegram(self) -> None:
        """Initialize Telegram bot."""
        try:
            from modules.output.telegram import get_telegram_bot
            token = getattr(settings, "telegram_bot_token", "")
            chat_id = getattr(settings, "telegram_chat_id", "")
            self._telegram = get_telegram_bot()
            if token:
                self._telegram.configure(token, chat_id)
                logger.info("Telegram bot initialized")
        except Exception as exc:
            logger.warning("Failed to init Telegram: %s", exc)

    def _init_identity(self) -> None:
        """Initialize identity layers (digital-twin style)."""
        try:
            from modules.memory.identity.layers import IdentityLayers
            self._identity = IdentityLayers()
            logger.info("Identity layers initialized")
        except Exception as exc:
            logger.warning("Failed to init identity: %s", exc)

    def _load_obsidian_context(self) -> None:
        """Load Obsidian memories into FOL's working context."""
        if not self._obsidian:
            return
        stats = self._obsidian.get_stats()
        if stats["total"] > 0:
            logger.info("Loaded %d notes from Obsidian vault", stats["total"])

    def _init_vision(self) -> None:
        """Initialize the vision system."""
        if self._vision is None:
            try:
                from modules.input.vision import ScreenAnalyzer
                self._vision = ScreenAnalyzer()
                logger.info("Vision system initialized")
            except Exception as exc:
                logger.warning("Failed to init vision: %s", exc)

    async def _on_startup(self) -> None:
        """Startup hook — initialize all modules."""
        logger.info("FOL starting up", version=self.version)

        # Initialize Brain Engine — unified LLM through BrainInterface.
        # Uses get_brain() which reads FOL_BRAIN env (current / freebuff / codebuff)
        # and routes through the canonical BrainRouter with automatic fallback.
        # This replaces the legacy LLMEngine which had its own parallel routing.
        from core.brain_engine import BrainEngineAdapter
        self._llm = BrainEngineAdapter(config={
            "llm_max_tokens": self.config.llm_max_tokens,
        })
        await self._llm.initialize()
        self.orchestrator.register_module("llm", self._llm)

        # Record the active model in the Brain so the model history is
        # always up to date (a later model swap is visible to the next one).
        if self._brain:
            try:
                active = self._llm.active_model or self.config.llm_model
                self._brain.record_model_change(str(active))
            except Exception as exc:
                logger.debug("Brain model record failed: %s", exc)

        # Load Obsidian memories into context
        self._load_obsidian_context()

        # Initialize Tool Registry
        from modules.tools.registry import ToolRegistry
        from modules.tools.system.execute_command import ExecuteCommand
        from modules.tools.system.open_app import OpenApp
        from modules.tools.system.file_ops import SearchFiles, ReadFile, WriteFile
        from modules.tools.system.system_info import SystemInfo
        from modules.tools.system.clipboard import ReadClipboard, WriteClipboard
        from modules.tools.mouse_keyboard.mouse_controller import MoveMouse, Click, Drag
        from modules.tools.mouse_keyboard.keyboard_controller import TypeText, PressKey
        from modules.tools.browser.browser_automation import BrowserNavigate, BrowserSearch, GetPageContent
        from modules.tools.browser.browser_interact import (
            BrowserOpen, BrowserClick, BrowserType,
            BrowserScroll, BrowserScreenshot, BrowserExtract, BrowserClose, BrowserRefresh, BrowserPressKey,
        )
        from modules.tools.browser.web_scraper import WebScraper
        from modules.tools.browser.bookmarks import BookmarksTool
        from modules.tools.automation.scheduler import SchedulerTool
        from modules.tools.desktop.agent_tools import (
            DesktopClick, DesktopType, DesktopHotkey, DesktopScroll,
            DesktopScreenshot, DesktopMoveMouse, DesktopScreenSize,
            EmailTool, CalendarTool,
        )

        self._tools = ToolRegistry()
        for tool_cls in [ExecuteCommand, OpenApp, SearchFiles, ReadFile, WriteFile, SystemInfo,
                         ReadClipboard, WriteClipboard, MoveMouse, Click, Drag, TypeText, PressKey,
                         BrowserNavigate, BrowserSearch, GetPageContent,
                         BrowserOpen, BrowserClick, BrowserType, BrowserScroll,
                         BrowserScreenshot, BrowserExtract, BrowserClose, BrowserRefresh, BrowserPressKey,
                         WebScraper, BookmarksTool, SchedulerTool,
                         DesktopClick, DesktopType, DesktopHotkey, DesktopScroll,
                         DesktopScreenshot, DesktopMoveMouse, DesktopScreenSize,
                         EmailTool, CalendarTool]:
            self._tools.register(tool_cls())
        self.orchestrator.register_module("tools", self._tools)

        # Canonical ConfirmationGate over the real registry — the single place
        # that decides whether a tool call may execute (Phase 8 wiring).
        from modules.tools.gate import ConfirmationGate
        self._gate = ConfirmationGate(self._tools)
        self.orchestrator.register_module("gate", self._gate)

        # Initialize Brain Backend (Freebuff with auto-start and health checks)
        try:
            def _brain_status_callback(status: dict[str, Any]) -> None:
                """Callback when brain status changes."""
                self._brain_status = status
                logger.info("Brain status changed: %s", status)
                # Emit event for UI/Dynamic Island updates
                self.event_bus.emit(EventType.BRAIN_STATUS_CHANGED, source="app", payload=status)

            self._brain_manager = BrainStartupManager(
                primary_brain="freebuff",
                fallback_brains=["current"],
                auto_start=getattr(settings, "brain_auto_start", True),
                status_callback=_brain_status_callback,
            )
            
            # Initialize brain backends (start Freebuff if available)
            self._brain_interface = await self._brain_manager.initialize()
            logger.info("Brain backend initialized: %s", self._brain_interface.name)
            self.orchestrator.register_module("brain", self._brain_interface)
        except Exception as exc:
            logger.error("Failed to initialize Brain backend: %s", exc)
            self._brain_manager = None
            self._brain_interface = None

        # Initialize Universal Executor
        self._universal_executor = UniversalExecutor(llm_engine=self._llm, tool_registry=self._tools)

        # Initialize TTS output
        from modules.output.tts import TTSModule
        self._tts_output = TTSModule()
        await self._tts_output.initialize()
        self.orchestrator.register_module("tts", self._tts_output)

        # Initialize Vision
        self._init_vision()

        # Initialize Memory modules
        from modules.memory.conversation import ConversationHistory
        from modules.memory.knowledge_graph import KnowledgeGraph
        from modules.memory.preferences import PreferencesStore
        from modules.memory.episodic_memory import EpisodicMemory
        from modules.memory.rag import RAGPipeline
        from modules.memory.vector_store import VectorStore

        self._conversation = ConversationHistory()
        await self._conversation.initialize()
        # Preload recent turns from the shared conversation store so FOL Core
        # sees the orchestrator's chat history (unified conversation across
        # both interfaces: SwiftUI chat and CLI).
        if not self._conversation_history:
            try:
                recent_turns = self._conversation.load_recent_sync(self._max_history)
                if recent_turns:
                    self._conversation_history = [
                        {"user": t.user_input, "assistant": t.assistant_response}
                        for t in recent_turns
                        if t.user_input or t.assistant_response
                    ]
                    logger.info("Preloaded %d messages from shared conversation history", len(self._conversation_history))
            except Exception as exc:
                logger.debug("Could not preload shared history: %s", exc)
        self._kg = KnowledgeGraph()
        await self._kg.initialize()
        self._preferences_store = PreferencesStore()
        await self._preferences_store.initialize()
        self._episodic = EpisodicMemory()
        await self._episodic.initialize()
        self._vector_store = VectorStore()
        await self._vector_store.initialize()
        self._rag = RAGPipeline(
            vector_store=self._vector_store,
            conversation_history=self._conversation,
            knowledge_graph=self._kg,
            preferences=self._preferences_store,
        )
        self.orchestrator.register_module("rag", self._rag)

        # Canonical memory boundary (Phase 2) — orchestrator talks to memory
        # through the MemoryService interface, not the stores directly.
        from modules.memory.interface import RAGMemoryService
        self._memory_service = RAGMemoryService(
            rag=self._rag,
            vector_store=self._vector_store,
            episodic=self._episodic,
            long_term=self._long_term_memory,
        )
        self.orchestrator.register_module("memory_service", self._memory_service)

        # Initialize Voice (JARVIS feature)
        await self._init_voice()

        # Initialize Proactive Mode (ROADMAP Etap 5) — ambient suggestions.
        self._init_proactive()

        self.event_bus.emit(EventType.SYSTEM_STARTUP, source="app")
        logger.info("FOL modules initialized", backends=self._llm.available_backends if self._llm else [], brain=self._brain_interface.name if self._brain_interface else "none")

        # JARVIS-style startup greeting
        await self._speak_startup_greeting()

    async def _init_voice(self) -> None:
        """Initialize the voice assistant."""
        try:
            from modules.input.speech import VoiceAssistant
            self._voice = VoiceAssistant()
            status = self._voice.status
            if status["tts_available"]:
                self._tts_enabled = True
            if status["stt_available"]:
                self._voice_enabled = True
            logger.info("Voice system initialized", status=status)
        except Exception as exc:
            logger.warning("Voice init failed: %s", exc)

    async def _speak_startup_greeting(self) -> None:
        """Speak a JARVIS-style startup greeting."""
        if not self._tts_output or not self._tts_enabled:
            return
        try:
            hour = datetime.now().hour
            if 5 <= hour < 12:
                greeting = "Good morning. All systems online."
            elif 12 <= hour < 17:
                greeting = "Good afternoon. All systems online."
            elif 17 <= hour < 22:
                greeting = "Good evening. All systems online."
            else:
                greeting = "Good evening. All systems online."
            await self._tts_output.send(greeting)
            logger.info("Startup greeting spoken: %s", greeting)
        except Exception as exc:
            logger.debug("Startup greeting skipped: %s", exc)

    async def _on_shutdown(self) -> None:
        """Shutdown hook."""
        logger.info("FOL shutting down")
        
        # Shutdown Brain startup manager (gracefully stop Freebuff if owned)
        if self._brain_manager:
            try:
                await self._brain_manager.shutdown()
            except Exception as exc:
                logger.error("Error shutting down brain manager: %s", exc)
        
        if self._llm:
            # BrainEngineAdapter.shutdown() is a no-op (BrainInterface handles its own lifecycle)
            await self._llm.shutdown()
        if self._tts_output:
            await self._tts_output.shutdown()
        self.event_bus.emit(EventType.SYSTEM_SHUTDOWN, source="app")

    async def start(self) -> None:
        await self.lifecycle.start()

    async def stop(self) -> None:
        await self.lifecycle.stop()

    async def process(self, user_input: str) -> str:
        """Process user input — main entry point for all interactions.

        The response from any source (builtin commands, tools, LLM) passes
        through the Personality Layer (``_polish``), which turns terse
        "Done."/"Готово." answers into natural contextual confirmations.
        """
        user_input = self._sanitize_input(user_input)
        if not user_input:
            return "I didn't catch that. Could you repeat?"

        # Reset per-request tool context so the Personality Layer never
        # reuses a tool from a previous request.
        self._last_tool = None

        # Feed the ProactiveService session stats (command counting) so the
        # repeated-command / long-session rules see real activity.
        self._record_proactive_stats(user_input)

        # Screen Awareness: explicit screen requests and context-aware screen
        # follow-ups ("Посмотри, что там" after opening an app). Analysis
        # only — never an action. Returns None when not a screen request.
        screen_resp = await self._screen_response(user_input)
        if screen_resp is not None:
            final = self._polish(user_input, screen_resp)
            self._record_turn(user_input, final)
            return final

        # Proactive Mode: on-demand request ("предложи что-нибудь") — a real
        # suggestion, delivered through the same EventBus path as the ambient
        # tick. Never fires when the feature is off.
        proactive_resp = await self._proactive_request(user_input)
        if proactive_resp is not None:
            final = self._polish(user_input, proactive_resp)
            self._record_turn(user_input, final)
            return final

        # Check built-in commands first
        builtin = self._handle_builtin_command(user_input)
        if builtin is not None:
            final = self._polish(user_input, builtin)
            self._record_turn(user_input, final)
            return final

        # Context Conversation: "а теперь YouTube" after "Открой Safari" —
        # the follow-up refers to the previous action, so resolve it before
        # the generic tool matching.
        action_followup = await self._resolve_action_followup(user_input)
        if action_followup is not None:
            final = self._polish(user_input, action_followup)
            self._record_turn(user_input, final)
            return final

        # Try tool execution
        tool_response = await self._try_tools(user_input)
        if tool_response is not None:
            final = self._polish(user_input, tool_response)
            self._record_turn(user_input, final)
            return final

        # Generate response via LLM or fallback. Small local models default to
        # generic offers of help ("How can I help you?") instead of answering;
        # retry once with a direct-answer directive before the Personality Layer
        # rebuilds the response as a last resort.
        response = await self._generate_response(user_input)
        from modules.llm.personality import _is_generic_help_offer
        if _is_generic_help_offer(response):
            response = await self._generate_response(user_input, direct_answer=True)
        final = self._polish(user_input, response)
        # Never repeat the previous answer verbatim (repeated-prompt guard): a
        # stuttering model gets one more direct-answer attempt.
        if self._conversation_history and final == self._conversation_history[-1]["assistant"]:
            retry = await self._generate_response(user_input, direct_answer=True)
            if retry and not _is_generic_help_offer(retry):
                final = self._polish(user_input, retry)

        # Store conversation (the FINAL, polished text — what the user saw)
        self._record_turn(user_input, final)

        # Store in long-term memory
        if self._long_term_memory:
            self._long_term_memory.store_conversation(user_input, final)
            self._long_term_memory.extract_and_store(user_input)

        # Auto-save important things to Obsidian
        self._auto_save_to_obsidian(user_input, final)

        # Auto-extract identity layers
        if self._identity:
            self._identity.extract_from_conversation(user_input)

        return final

    def _record_turn(self, user_input: str, response: str) -> None:
        """Record a conversation turn so follow-ups keep context.

        Every path (builtin command, tool, LLM) goes through this so the
        conversation history stays complete — a follow-up like "а теперь
        YouTube" after "Открой Safari" can reference the earlier turn.
        Control tokens (__SHUTDOWN__, __VOICE_MODE__) are internal and never
        recorded.
        """
        if response.startswith("__"):
            return
        self._conversation_history.append({"user": user_input, "assistant": response})
        # Trim to max — prevent unbounded memory growth in long sessions.
        if len(self._conversation_history) > self._max_history:
            self._conversation_history = self._conversation_history[-self._max_history:]
        # Mirror into the core ContextManager so the follow-up machinery
        # (is_follow_up / get_current_topic / get_follow_up_context) sees the
        # same history as the live chat path.
        self.context_manager.add_turn(user_input, response)
        self._update_topic(user_input)
        # Journal every turn into the Freebuff Brain (Obsidian) — the memory
        # that survives model changes. Best-effort, never raises.
        if self._brain:
            try:
                self._brain.record_turn(user_input, response)
            except Exception as exc:
                logger.debug("Brain turn record failed: %s", exc)

    # ─── Proactive Mode (ROADMAP Etap 5) ─────────────────────────────────

    def _init_proactive(self) -> None:
        """Initialize Proactive Mode. Best-effort, never raises.

        The runtime service wraps the rules engine (``ProactiveAssistant``)
        with the ON/OFF toggle, cooldown and per-hour cap. Reads its defaults
        from settings (``FOL_PROACTIVE_ENABLED`` etc.)."""
        if self._proactive is not None:
            return
        try:
            from modules.llm.proactive import ProactiveService
            self._proactive = ProactiveService(
                enabled=getattr(self.config, "proactive_enabled", False),
                cooldown_minutes=getattr(self.config, "proactive_cooldown_minutes", 5),
                max_per_hour=getattr(self.config, "proactive_max_per_hour", 3),
            )
            self.orchestrator.register_module("proactive", self._proactive)
            logger.info("Proactive Mode initialized (enabled=%s)", self._proactive.enabled)
        except Exception as exc:
            logger.warning("Proactive init failed: %s", exc)

    def _record_proactive_stats(self, user_input: str) -> None:
        """Feed session statistics into the ProactiveService (best-effort)."""
        if self._proactive is None:
            return
        try:
            self._proactive.record_command(user_input)
        except Exception:
            pass

    def _proactive_on(self, lang: str = "en") -> str:
        """Enable proactive suggestions (RU/EN)."""
        self._init_proactive()
        if self._proactive is None:
            return "Proactive mode unavailable." if lang == "en" else "Проактивный режим недоступен."
        self._proactive.set_enabled(True)
        # NOTE: runtime toggle state lives ONLY on the ProactiveService — the
        # settings singleton is not mutated, so tests and restarts never
        # inherit a stale flag from a previous session.
        self.event_bus.emit(
            EventType.PROACTIVE_TOGGLED, source="app", payload={"enabled": True}
        )
        return (
            "Proactive mode enabled. I'll suggest actions and reminders. Say 'proactive off' to disable."
            if lang == "en"
            else "Проактивный режим включён. Буду предлагать действия и напоминания. Выключить: «проактивность выкл»."
        )

    def _proactive_off(self, lang: str = "en") -> str:
        """Disable proactive suggestions (RU/EN)."""
        self._init_proactive()
        if self._proactive is None:
            return "Proactive mode unavailable." if lang == "en" else "Проактивный режим недоступен."
        self._proactive.set_enabled(False)
        # See _proactive_on — the settings singleton is never mutated.
        self.event_bus.emit(
            EventType.PROACTIVE_TOGGLED, source="app", payload={"enabled": False}
        )
        return (
            "Proactive mode disabled. Say 'proactive on' to enable it again."
            if lang == "en"
            else "Проактивный режим выключен. Включить: «проактивность вкл»."
        )

    def _proactive_status(self, lang: str = "en") -> str:
        """Show proactive mode status (RU/EN)."""
        self._init_proactive()
        if self._proactive is None:
            return "Proactive mode unavailable." if lang == "en" else "Проактивный режим недоступен."
        stats = self._proactive.stats()
        last = stats["last_suggestion"] or ("none yet" if lang == "en" else "пока нет")
        if lang == "en":
            return (
                f"Proactive mode: {'on' if stats['enabled'] else 'off'}\n"
                f"  Session commands: {stats['total_commands']}\n"
                f"  Session minutes: {stats['session_minutes']}\n"
                f"  Emitted this hour: {stats['emitted_this_hour']}/{stats['max_per_hour']}\n"
                f"  Rules: {stats['rules']}\n"
                f"  Last suggestion: {last}"
            )
        return (
            f"Проактивный режим: {'включён' if stats['enabled'] else 'выключен'}\n"
            f"  Команд в сессии: {stats['total_commands']}\n"
            f"  Минут в сессии: {stats['session_minutes']}\n"
            f"  Предложений за час: {stats['emitted_this_hour']}/{stats['max_per_hour']}\n"
            f"  Правил: {stats['rules']}\n"
            f"  Последнее предложение: {last}"
        )

    def _is_proactive_request(self, lower: str) -> bool:
        """On-demand proactive request forms (RU/EN)."""
        return lower in (
            "proactive now", "suggest", "suggest something",
            "give me a suggestion", "предложи", "предложи что-нибудь",
            "предложи идею", "что предложишь", "что посоветуешь",
        )

    async def _proactive_request(self, user_input: str) -> str | None:
        """Handle an explicit "предложи что-нибудь" request.

        Returns a chat-ready suggestion string, or ``None`` when the input is
        not a proactive request. When the feature is off, explains how to
        enable it instead of silently doing nothing."""
        lower = user_input.lower().strip()
        if not self._is_proactive_request(lower):
            return None
        self._init_proactive()
        lang = detect_language(user_input)
        if self._proactive is None:
            return "Proactive mode unavailable." if lang == "en" else "Проактивный режим недоступен."
        if not self._proactive.enabled:
            return (
                "Proactive mode is off. Say 'proactive on' to enable it."
                if lang == "en"
                else "Проактивный режим выключен. Скажите «проактивность вкл», чтобы включить."
            )
        suggestion = await self.proactive_tick(force=True)
        if suggestion is None:
            return (
                "Nothing to suggest right now — everything looks calm."
                if lang == "en"
                else "Пока ничего не придумал — всё выглядит спокойно."
            )
        return f"💡 {suggestion.title}\n{suggestion.description}"

    async def proactive_tick(self, *, force: bool = False) -> Any:
        """Run one proactive evaluation (ambient tick or on-demand).

        Publishes the suggestion on the EventBus (``PROACTIVE_SUGGESTION``,
        awaited so subscribers receive it before this returns) — the single
        canonical delivery path; the ambient scheduler and on-demand request
        never need a parallel channel. ``force=True`` bypasses the cooldown
        and the hourly cap (explicit user request is never "nagging"). Never
        raises.
        """
        if self._proactive is None:
            return None
        try:
            suggestion = await self._proactive.check(force=force)
        except Exception as exc:
            logger.debug("Proactive tick failed: %s", exc)
            return None
        if suggestion is not None:
            try:
                await self.event_bus.publish(Event(
                    type=EventType.PROACTIVE_SUGGESTION,
                    source="app",
                    payload={"suggestion": suggestion},
                ))
            except Exception as exc:
                logger.debug("Proactive event publish failed: %s", exc)
        return suggestion

    # ─── Proactive action execution (Phase 8) ─────────────────────────────

    # Deterministic, CLOSED mapping from a proactive suggestion's semantic
    # ``action`` to a real user command. Unknown actions are never executed
    # (fail closed) — the proactive system physically cannot reach shell or
    # other risky tools through this table. ``tool``/``args`` feed the
    # ConfirmationGate pre-check when present.
    _PROACTIVE_ACTIONS: dict[str, dict[str, Any]] = {
        "open_mail": {
            "command": "открой почту",
            "tool": "open_app",
            "args": {"name": "Mail"},
        },
        "open_editor": {
            "command": "открой vscode",
            "tool": "open_app",
            "args": {"name": "Visual Studio Code"},
        },
        "show_schedule": {
            "command": "статус",
            "tool": None,
            "args": {},
        },
        # Informational actions — shown to the user, never executed.
        "suggest_break": {"command": None, "tool": None, "args": {}},
        "suggest_automation": {"command": None, "tool": None, "args": {}},
        "suggest_organization": {"command": None, "tool": None, "args": {}},
        "suggest_bookmarks": {"command": None, "tool": None, "args": {}},
        "set_reminder": {"command": None, "tool": None, "args": {}},
        "set_meeting_reminder": {"command": None, "tool": None, "args": {}},
        "none": {"command": None, "tool": None, "args": {}},
    }

    async def execute_proactive_action(self, action: str) -> dict[str, Any]:
        """Execute a proactive suggestion's action through the SAFE path.

        - Unknown action → fail closed (never executed).
        - Informational action (no command) → no execution.
        - Known low-risk command → routed through ``process()`` — the exact
          same path as a typed chat message (builtins, tool matching, LLM).
        - Before executing, the canonical ConfirmationGate is consulted for
          the target tool: a CONFIRM decision blocks execution until the user
          approves via :meth:`confirm_proactive_action`.

        Returns a dict: ``executed``, ``needs_confirmation``, ``action_id``,
        ``response``. Never raises.
        """
        entry = self._PROACTIVE_ACTIONS.get(action or "")
        if entry is None:
            return {
                "executed": False,
                "needs_confirmation": False,
                "action_id": None,
                "response": "This suggestion has no safe executable action.",
            }
        command = entry.get("command")
        if not command:
            return {
                "executed": False,
                "needs_confirmation": False,
                "action_id": None,
                "response": "This suggestion is informational — nothing to execute.",
            }
        # Gate pre-check: risky tools require explicit user approval.
        gate = self._gate
        tool_name = entry.get("tool")
        if gate is not None and tool_name:
            try:
                from modules.tools.gate import GateDecision
                decision, action_id = gate.check(tool_name, entry.get("args") or {})
                if decision == GateDecision.CONFIRM:
                    return {
                        "executed": False,
                        "needs_confirmation": True,
                        "action_id": action_id,
                        "response": "This action needs your confirmation.",
                    }
                if decision == GateDecision.REJECT:
                    return {
                        "executed": False,
                        "needs_confirmation": False,
                        "action_id": None,
                        "response": "This action is not allowed.",
                    }
            except Exception as exc:
                logger.debug("Proactive gate check failed: %s", exc)
        # Safe path — identical to a chat message.
        try:
            response = await self.process(command)
        except Exception as exc:
            logger.warning("Proactive execute failed: %s", exc)
            return {
                "executed": False,
                "needs_confirmation": False,
                "action_id": None,
                "response": f"Action failed: {exc}",
            }
        return {
            "executed": True,
            "needs_confirmation": False,
            "action_id": None,
            "response": response,
        }

    async def confirm_proactive_action(self, action_id: str, action: str) -> dict[str, Any]:
        """Approve a gated proactive action and execute it.

        The ConfirmationGate approval is bound to the exact tool-call
        signature, so the follow-up execution passes the gate (OK) without
        weakening it for any other call.
        """
        if self._gate is None or not self._gate.approve(action_id):
            return {
                "executed": False,
                "needs_confirmation": False,
                "action_id": None,
                "response": "Confirmation expired or invalid.",
            }
        return await self.execute_proactive_action(action)

    # ─── Personality Layer ────────────────────────────────────────────────

    def _polish(self, user_input: str, response: str) -> str:
        """Final-response layer — sanitize and naturalize FOL's answer.

        Control tokens (__SHUTDOWN__, __VOICE_MODE__...) pass through
        untouched; everything else goes through the Personality Layer.

        Context Conversation: when the LLM answers tersely ("Done.") and the
        user's message is a follow-up that references the conversation topic
        ("А какая самая важная?"), reply with a topic-aware response instead
        of a generic confirmation.
        """
        if response.startswith("__"):
            return response
        tool_name, tool_args = self._last_tool or (None, None)
        polished = polish_response(user_input, response, tool_name=tool_name, tool_args=tool_args)
        if is_terse_response(response):
            followup = self._followup_response(user_input)
            if followup:
                return followup
        return polished

    async def _execute_tool(self, name: str, params: dict[str, Any]) -> Any:
        """Execute a tool, remembering it for the Personality Layer.

        The recorded (name, args) lets the Personality Layer build a natural
        contextual confirmation when the raw tool output is terse.
        """
        self._last_tool = (name, params)
        # Feed tool usage into the ProactiveService (recent_tool_count rules).
        if self._proactive is not None:
            try:
                self._proactive.record_tool_use(name)
            except Exception:
                pass
        return await self._tools.execute(name, params)

    # ─── Built-in Commands ────────────────────────────────────────────────

    # ─── Shell command extraction (EN + RU) ───────────────────────────

    _SHELL_CMD_PREFIXES: tuple[str, ...] = (
        # Longest / most specific first — alternation order matters!
        # NOTE: "запусти команду"/"запусти" are handled by app_match (which
        # runs earlier) — it routes "запусти команду X" here as a command.
        "run command",
        "выполни команду",
        "выполнить команду",
        "run the command",
        "execute command",
        "выполни в терминале",
        "выполни в консоли",
        "terminal command",
        "команда в терминале",
        "выполни",
        "выполнить",
        "execute",
        "run",
        "terminal",
        "терминал",
    )

    # Dangerous shell patterns — blocked before execution (fail-closed).
    # These are matched against the EXTRACTED command, not the full user input.
    _DANGEROUS_CMD_PATTERNS: frozenset[str] = frozenset({
        "rm -rf /", "rm -rf /*", "rm -fr /", "rm -fr /*",
        "rm -r /", "rm -r /*",
        ":(){ :|:& };:",  # fork bomb
        "dd if=/dev/zero of=/dev/disk", "dd if=/dev/random of=/dev/disk",
        "mkfs.",
        "> /dev/sda",
        "chmod -R 777 /", "chmod -R 777 /*",
        "chown -R", "chown root",
        "curl .*/|sh", "curl .*/|bash", "wget .*/|sh", "wget .*/|bash",
        "curl .*/|sudo", "wget .*/|sudo",
        "eval ",
        "nc -l", "ncat -l",  # reverse shell listeners
        "python -c 'import os'",
        "python3 -c 'import os'",
        "perl -e 'exec'",
        "ruby -e 'exec'",
        "shutdown", "reboot", "halt", "poweroff",
        "launchctl remove",  # kill system services
        "security delete-keychain",
        "diskutil eraseDisk",
        "defaults delete /",
    })

    # Trailing filler that must never become part of the shell command.
    _SHELL_CMD_TAIL_NOISE = (
        " в терминале пожалуйста", " in the terminal please",
        " в терминале", " в терминал", " в консоли", " в консоль",
        " в командной строке", " в шелле", " в shell",
        " in terminal", " in the terminal", " in console", " in the console",
        " пожалуйста", " please", " pls",
    )

    def _extract_shell_command(self, lower: str) -> str | None:
        """Extract the shell command from a user phrase, or None.

        Matches the LONGEST prefix first (so "выполни команду pwd" yields
        "pwd", not "команду pwd"), then strips trailing filler like
        "в терминале" / "пожалуйста" (repeatedly, so compound phrases
        "в терминале пожалуйста" fully collapse) and sentence punctuation
        ("выполни команду pwd." → "pwd"). Returns ``None`` when the input
        does not look like a command request.
        """
        lower = lower.strip()
        for prefix in self._SHELL_CMD_PREFIXES:
            if lower == prefix:
                return None  # "выполни" alone — no command
            if lower.startswith(prefix + " "):
                cmd = lower[len(prefix):].strip()
                # Drop an accidental leading "команду"/"command".
                cmd = re.sub(r"^(?:команду|команда|command)\s+", "", cmd).strip()
                # Strip filler repeatedly until nothing more to remove.
                changed = True
                while changed and cmd:
                    changed = False
                    for noise in self._SHELL_CMD_TAIL_NOISE:
                        if cmd.endswith(noise):
                            cmd = cmd[: -len(noise)].strip()
                            changed = True
                            break
                # Sentence punctuation: "pwd." / "ls!" — but keep "ls ." intact
                # (the dot is a real argument there, separated by a space).
                cmd = re.sub(r"(?<=[a-zA-Zа-яА-ЯёЁ0-9)])[.!?…]+$", "", cmd).strip()
                if not cmd:
                    return None
                # Security: block dangerous shell patterns (fail-closed).
                # This is defense-in-depth — the ConfirmationGate (Level 5)
                # catches most of these, but some pipe/eval patterns slip
                # through when the command doesn't contain shell markers.
                cmd_lower = cmd.lower()
                for pattern in self._DANGEROUS_CMD_PATTERNS:
                    if pattern in cmd_lower:
                        logger.warning(
                            "Blocked dangerous shell command: pattern=%r in cmd=%r",
                            pattern, cmd,
                        )
                        return None
                # Pipe to shell is always dangerous: "curl ... | sh"
                if re.search(r"\|\s*(?:sh|bash|zsh|fish)\b", cmd_lower):
                    logger.warning("Blocked pipe-to-shell command: %s", cmd)
                    return None
                return cmd
        return None

    def _handle_builtin_command(self, text: str) -> str | None:
        lower = text.lower().strip()

        # Voice commands
        if lower in ("voice on", "enable voice", "включи голос", "голос вкл"):
            return self._voice_on()
        if lower in ("voice off", "disable voice", "выключи голос", "голос выкл"):
            return self._voice_off()
        if lower in ("voice status", "голос статус"):
            return self._voice_status()
        if lower in ("listen", "слушай"):
            return self._listen_once()
        if lower.startswith("say ") or lower.startswith("скажи "):
            return self._speak_text(text)
        if lower in ("voices", "list voices", "список голосов"):
            return self._list_voices()
        if lower in ("voice mode", "talk mode", "режим голоса", "режим голосового общения"):
            return "__VOICE_MODE__"
        if lower in ("voice mode off", "exit voice mode", "выйти из голосового режима"):
            return "__VOICE_MODE_STOP__"

        # Vision commands
        if lower in ("screenshot", "скриншот", "снимок экрана", "сделай скриншот", "take screenshot"):
            return self._take_screenshot()
        if ("на экране" in lower or "что открыто" in lower or "анализ экрана" in lower
                or re.search(r"on\s+(?:the\s+|my\s+)?screen", lower)
                or re.search(r"что\s+(?:у\s+меня\s+)?(?:сейчас\s+)?на\s+экране", lower)):
            return self._analyze_screen(detect_language(text))
        if lower in ("active window", "какое приложение", "активное окно", "what app", "что за приложение"):
            return self._get_active_window()
        if lower in ("running apps", "запущенные приложения", "что запущено", "what's running", "what apps are running"):
            return self._get_running_apps()
        if lower in ("read screen", "прочитай экран", "ocr", "прочитай текст с экрана", "what text is on screen"):
            return self._read_screen_text()

        # Long-term memory commands
        if lower in ("memory", "memory status", "память", "статус памяти", "состояние памяти", "long term memory"):
            return self._memory_status()
        if lower.startswith("search memory ") or lower.startswith("найти в памяти ") or lower.startswith("поищи в памяти "):
            return self._search_memory(text)

        if lower in ("memory stats", "statistics", "статистика", "статистика памяти"):
            return self._memory_stats()
        if lower in ("recent conversations", "недавние диалоги", "последние диалоги", "recent chats"):
            return self._recent_conversations()
        if lower in ("clear memory", "очистить память", "очисти память", "reset memory"):
            return self._clear_long_term_memory(detect_language(text))
        if lower.startswith("learn ") or lower.startswith("запомни навсегда ") or lower.startswith("запомни что "):
            return self._learn_forever(text)
        if lower in ("what do you know", "что ты знаешь", "что помнишь", "what do you remember"):
            return self._what_i_know()

        # Obsidian commands
        if lower.startswith("obsidian ") or lower.startswith("vault "):
            return self._obsidian_command(text)
        if lower in ("obsidian stats", "vault stats"):
            return self._obsidian_stats()
        if lower.startswith("obsidian search ") or lower.startswith("найти в vault "):
            return self._obsidian_search(text)
        if lower.startswith("save to vault ") or lower.startswith("сохрани в vault "):
            return self._obsidian_save(text)

        # Freebuff Brain commands
        if lower in ("мозг", "brain", "мозг статус", "brain status", "статус мозга"):
            return self._brain_status()
        if lower in ("итоги дня", "итоги", "мозг итоги", "резюме дня", "daily summary", "summary"):
            return self._brain_daily_summary()
        # «что мы делали вчера?» / «что мы делали позавчера?» — read Work-Log
        if re.search(r"(?:вчера|позавчера|yesterday)", lower) and re.search(
            r"(?:дел|did|do|было|произошл)", lower
        ):
            return self._brain_what_we_did(lower)
        # «над чем мы работаем?» — projects + recent work log
        if re.search(r"(?:над чем|чем мы|what are we|what.*working)", lower) and re.search(
            r"(?:работ|занима|work|project|проект)", lower
        ):
            return self._brain_current_work()
        # «поищи в мозгу <текст>» / «search brain <text>» — full-text search
        m = re.match(
            r"^(?:поищи|найди|search|look up)\s+(?:в\s+)?(?:мозгу|мозге|brain)\s+(.+)$",
            lower,
        )
        if m:
            return self._brain_search(m.group(1).strip())

        # Proactive Mode (ROADMAP Etap 5) — toggle + status are sync; the
        # on-demand "предложи что-нибудь" request is async (handled in process()).
        if lower in ("proactive on", "проактивность вкл", "проактивный режим вкл"):
            return self._proactive_on(detect_language(text))
        if lower in ("proactive off", "проактивность выкл", "проактивный режим выкл"):
            return self._proactive_off(detect_language(text))
        if lower in ("proactive status", "статус проактивности", "проактивность статус", "проактивность"):
            return self._proactive_status(detect_language(text))

        # Telegram commands
        if lower.startswith("telegram send ") or lower.startswith("отправь в телеграм "):
            return self._telegram_send(text)
        if lower.startswith("telegram ") or lower.startswith("tg "):
            return self._telegram_command(text)

        # Profile commands
        if lower in ("my profile", "about me", "мой профиль", "обо мне", "who am i", "кто я"):
            return self._my_profile()
        if lower in ("my goals", "мои цели"):
            return self._my_goals()
        if lower in ("my projects", "мои проекты"):
            return self._my_projects()
        if lower in ("my tech", "мои технологии", "мой стек"):
            return self._my_tech()
        if lower in ("my rules", "мои правила"):
            return self._my_rules()

        # Greetings
        if lower in ("hello", "hi", "hey", "hey fol", "fol", "привет"):
            return self._greet(detect_language(text))

        # Status
        if lower in ("status", "system status", "состояние"):
            return self._system_status()

        # Time
        if lower in ("time", "what time", "время", "который час"):
            t = datetime.now().strftime('%H:%M:%S')
            lang = detect_language(text)
            return f"Сейчас {t}." if lang == "ru" else f"The current time is {t}."

        # Date
        if lower in ("date", "today", "дата", "сегодня"):
            d = datetime.now().strftime('%A, %B %d, %Y')
            lang = detect_language(text)
            return f"Сегодня {d}." if lang == "ru" else f"Today is {d}."

        # Help
        if lower in ("help", "commands", "помощь", "команды"):
            return self._help()

        # Remember — comma-tolerant: "запомни, что …", "remember that …",
        # "запомни что …" all persist the reminder (never confirm without
        # storing). NB: must stay AFTER the _learn_forever checks above, which
        # catch "запомни навсегда …" / "запомни что …" for long-term memory.
        rem = re.match(r"^(?:remember|запомни)[,\s]+(?:that|что)?\s*(.*)$", lower)
        if rem:
            content = rem.group(1).strip().lstrip(",:;")
            return self._remember(content, detect_language(text))

        # Recall
        if lower in ("recall", "what do you remember", "что ты помнишь"):
            return self._recall(detect_language(text))

        # Notes
        if lower in ("notes", "show notes", "заметки"):
            return self._show_notes(detect_language(text))

        # Clear
        if lower in ("clear", "clear history", "очистить"):
            return self._clear_history(detect_language(text))

        # Preferences
        if lower.startswith("set ") and "=" in lower:
            return self._set_preference(text)
        if lower.startswith("get "):
            return self._get_preference(text)

        # Modes (ROADMAP Этап 2) — "режим фокус" / "mode focus" / "какой режим".
        # NB: "режим голоса" / "voice mode" is handled ABOVE (voice section),
        # so it never reaches this branch.
        # Tolerate the wake word ("FOL, режим фокус" — the voice form promised
        # by the ROADMAP) and trailing politeness ("режим фокус пожалуйста").
        mode_text = re.sub(r"^(?:fol|фол|f\.o\.l\.)[,:\s]+", "", lower).strip()
        mode_text = mode_text.replace(",", " ").replace(".", " ")
        mode_text = re.sub(r"\s+", " ", mode_text).strip()
        if (
            re.match(r"^(?:режим|mode)\s*$", mode_text)
            or "какой режим" in mode_text
            or "каком режиме" in mode_text
            or "какой сейчас режим" in mode_text
        ):
            return self._mode_status(detect_language(text))
        # "mode focus" (prefix) or "focus mode" (suffix) both work.
        mode_match = re.match(
            r"^(?:режим|mode)\s+([a-zа-яё]+?)(?:\s+(?:пожалуйста|please))?$",
            mode_text,
        )
        if not mode_match:
            mode_match = re.match(
                r"^([a-zа-яё]+?)\s+mode(?:\s+(?:пожалуйста|please))?$",
                mode_text,
            )
        if mode_match:
            target = mode_match.group(1)
            mapped = self._MODE_ALIASES.get(target)
            if mapped:
                return self._set_mode(mapped, detect_language(text))
            # Unknown mode → show the current one and what's available.
            return self._mode_status(detect_language(text))

        # Email intent (S5) — "напиши письмо преподавателю": ask for the
        # address when unknown, confirm with the real one when known.
        if self._is_email_intent(lower):
            return self._email_response(text)

        # Tasks intent (S9) — "какие задачи я должен сделать завтра?":
        # return real tasks from memory/Obsidian or say nothing is scheduled.
        if self._is_tasks_intent(lower):
            return self._tasks_response(text)

        # Shutdown
        if lower in ("shutdown", "exit", "quit", "выход", "выключись"):
            return "__SHUTDOWN__"

        return None

    def _is_email_intent(self, lower: str) -> bool:
        """Deterministic email-intent detection (RU + EN)."""
        return bool(re.search(
            r"(?:напиши|написать|составить|отправь|отправить|создай|создать|сделай|"
            r"write|send|compose|draft|make)\s+(?:an?\s+|a\s+)?(?:письмо|письма|email|e-?mail|letter|mail)",
            lower,
        )) or bool(re.search(
            r"(?:письмо|email|e-?mail)\s+(?:преподавател|учител|профессор|руководител|"
            r"начальник|ментор|наставник|коллег|друг|teacher|professor|supervisor|manager|"
            r"boss|mentor|colleague|friend)",
            lower,
        ))

    def _is_tasks_intent(self, lower: str) -> bool:
        """Deterministic tasks-intent detection (RU + EN)."""
        return bool(re.search(
            r"(?:какие задачи|что я должен|что мне нужно|мои задачи|задачи на (?:завтра|сегодня)|"
            r"план на завтра|список дел|дела на завтра|to-?do|what tasks|my tasks|"
            r"what do i need to do|tasks for (?:tomorrow|today)|plan for (?:tomorrow|today))",
            lower,
        ))

    def _localized_fallback(self, user_input: str, ru_text: str, en_text: str) -> str:
        """Return the right language version based on user input."""
        lang = detect_language(user_input) if user_input else "en"
        return ru_text if lang == "ru" else en_text

    # ─── Greeting & Help ─────────────────────────────────────────────────

    def _greet(self, lang: str = "en") -> str:
        """Generate a greeting in the user's language — no forced honorific."""
        hour = datetime.now().hour
        name = str(self._preferences.get("name", "")).strip()
        uptime = self._format_uptime()
        address = f", {name}" if name else ""
        if lang == "ru":
            if 5 <= hour < 12:
                greeting = "Доброе утро"
            elif 12 <= hour < 17:
                greeting = "Добрый день"
            elif 17 <= hour < 22:
                greeting = "Добрый вечер"
            else:
                greeting = "Доброй ночи"
            return f"{greeting}{address}. Все системы онлайн. Время работы: {uptime}. Чем могу помочь?"
        else:
            if 5 <= hour < 12:
                greeting = "Good morning"
            elif 12 <= hour < 17:
                greeting = "Good afternoon"
            elif 17 <= hour < 22:
                greeting = "Good evening"
            else:
                greeting = "Good night"
            return f"{greeting}{address}. All systems online. Uptime: {uptime}. How may I assist you?"

    def _help(self) -> str:
        return """FOL Commands:

General:
  hello / hi              - Greet FOL
  status                  - System status
  time                    - Current time
  date                    - Today's date
  help / commands         - Show this help

Voice:
  voice on / off          - Enable/disable voice output
  voice mode              - Enter voice conversation mode
  voice status            - Show voice status
  listen                  - Listen once for voice input
  say <text>              - Speak text aloud
  voices                  - List available voices

Vision:
  screenshot              - Take a screenshot
  what's on screen        - Analyze screen content
  active window           - Get active window info
  running apps            - List running applications
  read screen             - OCR text from screen

Memory:
  remember <text>         - Store a memory
  recall                  - What do you remember?
  notes                   - Show saved notes
  memory                  - Long-term memory status
  search memory <query>   - Search long-term memory
  learn <text>            - Store permanently
  what do you know        - Show what FOL knows

Obsidian:
  vault stats             - Vault statistics
  vault list              - List all notes
  vault search <query>    - Search vault
  save to vault <text>    - Save to Obsidian vault

Brain:
  мозг / brain            - Freebuff Brain status (persistent memory)
  итоги дня               - Write today's summary to Obsidian
  что мы делали вчера      - Read yesterday's journal from the Brain
  над чем мы работаем      - Projects + recent activity
  поищи в мозгу <text>     - Full-text search over the Work-Log

Proactive:
  proactive on / off      - Enable/disable proactive suggestions (проактивность вкл/выкл)
  proactive status        - Show proactive mode status (статус проактивности)
  предложи что-нибудь      - Ask for a suggestion right now

Profile:
  my profile / about me   - Show your profile
  my goals                - Show your goals
  my projects             - Show your projects
  my tech                 - Show your tech stack
  my rules                - Show communication rules

Telegram:
  telegram send <msg>     - Send message via Telegram
  telegram status         - Check Telegram connection

Tools:
  run <command>           - Execute a shell command
  open <app>              - Open an application
  search <query>          - Search the web
  screenshot              - Take a screenshot

MacBook Control:
  open <app>              - Launch application
  play music              - Start music
  play <song/artist>      - Play specific music
  pause / next / previous - Media controls
  volume up/down <N>      - Adjust volume
  volume to <N>           - Set volume (0-100)
  mute / unmute           - Toggle mute
  brightness up/down <N>  - Adjust brightness
  minimize / maximize     - Window management
  close window            - Close current window
  new window              - New window/tab
  sleep / wake up         - Sleep/wake Mac
  lock                    - Lock screen

System:
  set <key> = <value>     - Set a preference
  get <key>               - Get a preference
  clear                   - Clear conversation history
  shutdown / exit         - Shutdown FOL

Modes:
  режим / mode            - Show current mode
  режим компаньон         - Companion: casual conversation (default)
  режим ассистент         - Assistant: perform tasks on Mac directly
  режим агент             - Agent: complex multi-step tasks
  режим фокус             - Focus: minimal talk, maximum action"""

    # ─── Voice Methods ───────────────────────────────────────────────────

    def _voice_on(self) -> str:
        self._tts_enabled = True
        if self._voice:
            self._voice.tts.set_enabled(True)
        return "Voice output enabled."

    def _voice_off(self) -> str:
        self._tts_enabled = False
        if self._voice:
            self._voice.tts.set_enabled(False)
        return "Voice output disabled."

    def _voice_status(self) -> str:
        if not self._voice:
            return "Voice system not initialized."
        status = self._voice.status
        return (
            f"Voice Status:\n"
            f"  TTS: {'Available' if status['tts_available'] else 'Not available'}\n"
            f"  STT: {'Available' if status['stt_available'] else 'Not available'}\n"
            f"  Listening: {'Yes' if status['is_listening'] else 'No'}\n"
            f"  Voice: {status['voice']}\n"
            f"  Language: {status['language']}"
        )

    def _listen_once(self) -> str:
        if not self._voice or not self._voice.stt.is_available:
            return "Voice input not available."
        try:
            text = self._voice.stt.listen(timeout=5.0)
            return f"I heard: {text}" if text else "I didn't catch anything."
        except Exception as exc:
            return f"Error listening: {exc}"

    def _speak_text(self, text: str) -> str:
        text = re.sub(r"^(say|скажи)\s+", "", text, flags=re.IGNORECASE)
        if not text:
            return "What should I say?"
        if self._voice and self._voice.tts.is_available:
            self._voice.tts.speak(text)
            return f"Speaking: {text}"
        return "TTS not available."

    def _list_voices(self) -> str:
        if self._voice and self._voice.tts.is_available:
            voices = self._voice.tts.list_voices()
            if voices:
                return "Available voices:\n" + "\n".join(f"  - {v}" for v in voices[:20])
            return "No voices found."
        return "TTS not available."

    # ─── Vision Methods ──────────────────────────────────────────────────

    def _take_screenshot(self) -> str:
        self._init_vision()
        if not self._vision:
            return "Vision system not available."
        path = self._vision.capture_screenshot()
        return f"Screenshot saved to {path}" if path else "Screenshot failed."

    def _analyze_screen(self, lang: str = "en") -> str:
        """Analyze the current screen and describe it like a person would.

        The answer is built ONLY from the real ScreenContent returned by the
        vision system — never a hardcoded guess. When vision is unavailable
        (e.g. no Screen Recording permission) or capture fails, say so plainly
        instead of raising or inventing data.
        """
        self._init_vision()
        if not self._vision:
            return (
                "Не могу проанализировать экран — нет доступа к записи экрана. "
                "Разрешите доступ в Системных настройках → Конфиденциальность → Запись экрана."
                if lang == "ru"
                else "I can't analyze the screen — Screen Recording permission is missing. "
                "Enable it in System Settings → Privacy & Security → Screen Recording."
            )
        try:
            content = self._vision.analyze_screen()
        except Exception as exc:
            logger.warning("Screen analysis failed: %s", exc)
            return (
                "Не получилось посмотреть на экран. Попробуйте ещё раз."
                if lang == "ru"
                else "I couldn't look at the screen. Please try again."
            )
        if self._long_term_memory:
            try:
                self._long_term_memory.store_episode(
                    f"Screen: {content.active_app} - {content.window_title}",
                    context=content.description, importance=0.3,
                )
            except Exception:
                pass
        return self._humanize_screen_content(content, lang)

    def _get_active_window(self) -> str:
        self._init_vision()
        if not self._vision:
            return "Vision system not available."
        info = self._vision.get_active_window()
        return f"Active Window:\n  App: {info['app']}\n  Title: {info['title'] or '(unknown)'}"

    def _get_running_apps(self) -> str:
        self._init_vision()
        if not self._vision:
            return "Vision system not available."
        apps = self._vision.get_running_apps()
        return "Running apps:\n" + "\n".join(f"  - {a}" for a in sorted(apps)) if apps else "No apps found."

    def _read_screen_text(self) -> str:
        self._init_vision()
        if not self._vision:
            return "Vision system not available."
        text = self._vision.get_screen_text()
        return f"Screen text:\n{text[:3000]}" if text else "No text detected on screen."

    # ─── Screen Awareness ────────────────────────────────────────────────

    def _is_screen_request(self, lower: str) -> bool:
        """Explicit screen-awareness requests (RU + EN)."""
        word_count = len(lower.split())
        # "Что происходит?" / "Что я делаю?" are screen questions, but the
        # longer "Что происходит с моим проектом?" is not — require short form.
        short_ambiguous = ("что происходит" in lower or "что я делаю" in lower) and word_count <= 4
        return (
            "на экране" in lower
            or "на экран" in lower
            or "что открыто" in lower
            or "что сейчас открыто" in lower
            or "что открыто сейчас" in lower
            or "анализ экрана" in lower
            or short_ambiguous
            or "что это за ошибка" in lower
            or "что написано" in lower
            or "какой файл открыт" in lower
            or "что показывает" in lower
            or "посмотри на экран" in lower
            or re.search(r"on\s+(?:the\s+|my\s+)?screen", lower)
            or re.search(r"what'?s\s+(?:on|open|showing)", lower)
            or re.search(r"what\s+(?:do you see|is open|is on|is showing|am i doing)", lower)
            or re.search(r"look\s+at\s+(?:the\s+|my\s+)?screen", lower)
            or re.search(r"screen\s+analysis", lower)
            or re.search(r"что\s+(?:у\s+меня\s+)?(?:сейчас\s+)?на\s+экране", lower)
        )

    def _has_screen_context(self) -> bool:
        """True when the recent conversation involved the screen/apps — so a
        bare follow-up ("Что там?") can reasonably refer to it."""
        recent = self._conversation_history[-2:]
        if not recent:
            return False
        hints = (
            "экран", "screen", "открыл", "открыт", "открыто", "open",
            "opened", "запустил", "запущен", "launch", "вкладк", "tab",
            "safari", "chrome", "finder", "terminal", "терминал",
            "vs code", "vscode", "показыва", "showing",
        )
        for turn in recent:
            text = f"{turn.get('user', '')} {turn.get('assistant', '')}".lower()
            if any(h in text for h in hints):
                return True
        # The conversation topic itself may be an app ("Открой Safari" → Safari).
        if self._topic and self._topic.lower() in self._APP_ALIASES:
            return True
        return False

    def _is_screen_followup(self, lower: str) -> bool:
        """Bare screen follow-ups ("Что там?", "Посмотри.", "Что это?").

        Only valid when the recent conversation actually involved the screen
        or an app — so "Что это?" in a code discussion is NOT hijacked.
        "Посмотри мой код" is NOT a screen follow-up (it has a subject), so
        the bare "посмотри" form only counts when short or screen-worded.
        """
        if not self._has_screen_context():
            return False
        stripped = lower.strip(".,!? ").strip()
        if stripped in (
            "что там", "посмотри", "что это", "что не так",
            "что здесь не так", "look", "look at it", "what is that",
            "what's that", "what's wrong", "what is this", "what's this",
        ):
            return True
        if re.search(r"что\s+там", lower):
            return True
        # "посмотри" is a screen follow-up only when the message is bare
        # (≤ 2 words: "Посмотри.", "Посмотри там") or explicitly screen-
        # worded. "Посмотри мой код" / "Посмотри этот файл" must NOT hijack.
        if re.match(r"посмотри\b", lower):
            words = lower.split()
            if len(words) <= 2:
                return True
            if "экран" in lower or "screen" in lower or "там" in lower:
                return True
        if re.search(r"что\s+означает\s+эта\s+ошибка", lower):
            return True
        if re.search(r"что\s+за\s+ошибка", lower):
            return True
        return False

    def _capture_screen_content(self) -> Any | None:
        """Capture real screen content, or ``None`` when vision is unavailable
        (no permission / capture failure). Never raises."""
        self._init_vision()
        if not self._vision:
            return None
        try:
            content = self._vision.analyze_screen()
        except Exception as exc:
            logger.warning("Screen capture failed: %s", exc)
            return None
        if self._long_term_memory:
            try:
                self._long_term_memory.store_episode(
                    f"Screen: {content.active_app} - {content.window_title}",
                    context=content.description, importance=0.3,
                )
            except Exception:
                pass
        return content

    def _format_screen_context(self, content: Any) -> str:
        """Build the SCREEN CONTEXT block injected into the LLM prompt."""
        parts = ["SCREEN CONTEXT:"]
        if getattr(content, "active_app", ""):
            parts.append(f"Active application: {content.active_app}")
        if getattr(content, "window_title", ""):
            parts.append(f"Window: {content.window_title}")
        if getattr(content, "screen_text", ""):
            parts.append(f"Screen text (OCR): {content.screen_text[:800]}")
        if getattr(content, "description", ""):
            parts.append(f"Analysis: {content.description[:400]}")
        if len(parts) == 1:
            parts.append("(no reliable screen data — say you cannot see clearly)")
        return "\n".join(parts)

    def _humanize_screen_content(self, content: Any, lang: str) -> str:
        """Turn REAL ScreenContent into a natural-language description."""
        app = (content.active_app or "").strip()
        window = (content.window_title or "").strip()
        text = (content.screen_text or "").strip()
        if not app and not window and not text:
            return (
                "Сейчас на экране ничего не видно."
                if lang == "ru"
                else "There's nothing visible on screen right now."
            )
        if lang == "ru":
            base = f"Сейчас открыт {app}." if app else "Экран активен."
            if window:
                base += f" На экране видно: {window}."
            if text and len(text) < 200:
                base += f" На экране читается текст: {text}."
            elif text:
                base += f" На экране читается текст (начало): {text[:150]}…"
            if not window and not text:
                base += " Больше деталей различить не могу."
            return base
        base = f"{app} is open right now." if app else "The screen is active."
        if window:
            base += f" On screen: {window}."
        if text and len(text) < 200:
            base += f" On-screen text reads: {text}."
        elif text:
            base += f" On-screen text (start): {text[:150]}…"
        if not window and not text:
            base += " I can't make out more detail."
        return base

    async def _screen_response(self, user_input: str) -> str | None:
        """Screen Awareness pipeline.

        Explicit screen requests ("Что на экране?") and context-aware screen
        follow-ups ("Посмотри, что там" after opening an app) are answered
        from the REAL screen content. When an LLM is available it receives the
        SCREEN CONTEXT block for a natural answer; otherwise a rule-based
        humanized description is used. Never a fake answer, never an action.
        Returns ``None`` when the input is not a screen request.
        """
        lower = user_input.lower().strip()
        lang = detect_language(user_input)
        if not (self._is_screen_request(lower) or self._is_screen_followup(lower)):
            return None

        content = self._capture_screen_content()
        if content is not None:
            # LLM path: screenshot → vision analysis → SCREEN CONTEXT → natural response
            if self._llm:
                try:
                    context = self._get_context(user_input)
                    screen_block = self._format_screen_context(content)
                    full_context = (
                        f"{context}\n\n{screen_block}" if context else screen_block
                    )
                    response = await self._llm.generate(user_input, context=full_context)
                    if response and not is_terse_response(response) and not response.startswith("All LLM"):
                        return response
                except Exception as exc:
                    logger.warning("Screen LLM path failed: %s", exc)
            # Rule-based fallback — humanized from the SAME real capture
            return self._humanize_screen_content(content, lang)

        # No vision → permission / failure message (and the mockable seam tests use)
        return self._analyze_screen(lang)

    # ─── Long-term Memory Methods ────────────────────────────────────────

    def _memory_status(self) -> str:
        if not self._long_term_memory:
            return "Long-term memory not initialized."
        stats = self._long_term_memory.stats
        return (
            f"Long-term Memory:\n"
            f"  Memories: {stats['memories']}\n"
            f"  Conversations: {stats['conversations']}\n"
            f"  Knowledge: {stats['knowledge']}\n"
            f"  Episodes: {stats['episodes']}\n"
            f"  Total: {sum(stats.values())}"
        )

    def _search_memory(self, text: str) -> str:
        if not self._long_term_memory:
            return "Long-term memory not initialized."
        lang = detect_language(text)
        query = re.sub(r"^(search memory|найти в памяти)\s+", "", text, flags=re.IGNORECASE).strip()
        if not query:
            return "Что поискать?" if lang == "ru" else "What should I search for?"
        context = self._long_term_memory.get_context_for_query(query)
        if not context:
            return (
                f"По запросу «{query}» ничего не нашёл."
                if lang == "ru"
                else f"No memories found for '{query}'."
            )
        return (
            f"Нашёл по запросу «{query}»:\n{context}"
            if lang == "ru"
            else f"Memory search results for '{query}':\n{context}"
        )

    def _memory_stats(self) -> str:
        if not self._long_term_memory:
            return "Long-term memory not initialized."
        stats = self._long_term_memory.stats
        return (
            f"Memory Statistics:\n"
            f"  Short-term: {len(self._conversation_history)} conversations, {len(self._memories)} memories\n"
            f"  Long-term: {stats['memories']} memories, {stats['conversations']} conversations\n"
            f"             {stats['knowledge']} knowledge, {stats['episodes']} episodes"
        )

    def _recent_conversations(self) -> str:
        if not self._long_term_memory:
            return "Long-term memory not initialized."
        recent = self._long_term_memory.get_recent_conversations(limit=10)
        if not recent:
            return "No recent conversations."
        lines = []
        for conv in recent:
            lines.append(f"  User: {conv['user_input']}")
            lines.append(f"  FOL: {conv['fol_response'][:100]}...")
            lines.append("")
        return "Recent conversations:\n" + "\n".join(lines)

    def _clear_long_term_memory(self, lang: str = "en") -> str:
        if not self._long_term_memory:
            return "Long-term memory not initialized."
        self._long_term_memory.clear_all()
        return (
            "Долговременная память очищена."
            if lang == "ru"
            else "Long-term memory cleared."
        )

    def _learn_forever(self, text: str) -> str:
        """Long-term memory — bilingual, natural (personality layer)."""
        lang = detect_language(text)
        if not self._long_term_memory:
            return ("Долговременная память не инициализирована." if lang == "ru"
                    else "Long-term memory not initialized.")
        content = re.sub(r"^(learn|запомни навсегда|запомни что)\s+", "", text, flags=re.IGNORECASE).strip()
        if not content:
            return ("Что запомнить навсегда?" if lang == "ru" else "What should I learn?")
        self._long_term_memory.store_memory(content, category="permanent", importance=0.9, tags=["permanent"])
        self._long_term_memory.extract_and_store(content)
        return (f"Запомнил навсегда: {content}" if lang == "ru"
                else f"Remembered forever: {content}")

    def _what_i_know(self) -> str:
        if not self._long_term_memory:
            return "Long-term memory not initialized."
        stats = self._long_term_memory.stats
        knowledge = self._long_term_memory._knowledge[-10:] if self._long_term_memory._knowledge else []
        memories = self._long_term_memory.get_recent_memories(limit=5)
        lines = [f"What I know ({sum(stats.values())} total memories):"]
        if knowledge:
            lines.append("\n  Knowledge:")
            for k in knowledge:
                lines.append(f"    - {k.subject} {k.predicate} {k.object}")
        if memories:
            lines.append("\n  Recent memories:")
            for m in memories:
                lines.append(f"    - [{m.category}] {m.content[:80]}")
        if len(lines) == 1:
            lines.append("  (not much yet — talk to me more!)")
        return "\n".join(lines)

    # ─── Obsidian Methods ────────────────────────────────────────────────

    def _obsidian_command(self, text: str) -> str:
        """Handle Obsidian vault commands."""
        if not self._obsidian:
            return "Obsidian memory not initialized."
        lower = text.lower().strip()
        if lower.startswith("obsidian list") or lower.startswith("vault list"):
            return self._obsidian_list()
        return "Usage: obsidian list / obsidian stats / obsidian search <query>"

    def _obsidian_list(self) -> str:
        if not self._obsidian:
            return "Obsidian not initialized."
        notes = self._obsidian.get_all_notes()
        if not notes:
            return "No notes in Obsidian vault yet."
        lines = [f"Obsidian Vault ({len(notes)} notes):"]
        for n in notes[:20]:
            lines.append(f"  [{n['category']}] {n['title']}")
        return "\n".join(lines)

    def _obsidian_stats(self) -> str:
        if not self._obsidian:
            return "Obsidian not initialized."
        stats = self._obsidian.get_stats()
        vault = str(self._obsidian._vault)
        return (
            f"Obsidian Vault Stats:\n"
            f"  Path: {vault}\n"
            f"  People: {stats.get('People', 0)}\n"
            f"  Preferences: {stats.get('Preferences', 0)}\n"
            f"  Knowledge: {stats.get('Knowledge', 0)}\n"
            f"  Conversations: {stats.get('Conversations', 0)}\n"
            f"  Projects: {stats.get('Projects', 0)}\n"
            f"  Episodes: {stats.get('Episodes', 0)}\n"
            f"  Total: {stats['total']}"
        )

    def _obsidian_search(self, text: str) -> str:
        if not self._obsidian:
            return "Obsidian not initialized."
        query = re.sub(r"^(obsidian search|найти в vault)\s+", "", text, flags=re.IGNORECASE).strip()
        if not query:
            return "What should I search for?"
        results = self._obsidian.search(query)
        if not results:
            return f"No notes found for '{query}'."
        lines = [f"Obsidian search results for '{query}':"]
        for r in results:
            lines.append(f"  [{r['category']}] {r['title']}")
        return "\n".join(lines)

    # ─── Freebuff Brain ──────────────────────────────────────────────────

    def _brain_status(self) -> str:
        """Show the Freebuff Brain status — persistent memory that survives
        model changes."""
        if not self._brain:
            return "Мозг не инициализирован."
        try:
            return self._brain.summary()
        except Exception as exc:
            logger.warning("Brain status failed: %s", exc)
            return "Не удалось прочитать мозг."

    def _brain_what_we_did(self, lower: str) -> str:
        """«Что мы делали вчера?» — answer from the Brain Work-Log.

        Understands «вчера» and «позавчера» (RU) / «yesterday» (EN);
        answers with the day's journal entries or says it's empty.
        """
        if not self._brain:
            return "Мозг не инициализирован."
        from datetime import timedelta

        if "позавчера" in lower:
            offset = 2
            label = "позавчера"
        elif "yesterday" in lower:
            offset = 1
            label = "yesterday"
        else:
            offset = 1
            label = "вчера"
        date = (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
        try:
            entries = self._brain.work_log_for_date(date)
        except Exception as exc:
            logger.warning("Brain work-log read failed: %s", exc)
            return "Не удалось прочитать журнал мозга."
        if not entries:
            return (
                f"За {label} ({date}) в журнале пусто — ничего не записано."
            )
        lines = [f"За {label} ({date}) мы делали:"]
        for e in entries[-15:]:
            lines.append(f"  • {e}")
        return "\n".join(lines)

    def _brain_current_work(self) -> str:
        """«Над чем мы работаем?» — projects + recent Work-Log activity."""
        if not self._brain:
            return "Мозг не инициализирован."
        try:
            projects = self._brain.get_projects()
            recent = self._brain.recent_work(days=3, limit=12)
        except Exception as exc:
            logger.warning("Brain current-work failed: %s", exc)
            return "Не удалось прочитать мозг."
        lines = []
        if projects:
            lines.append("Сейчас в работе:")
            for p in projects:
                lines.append(f"  • {p}")
            lines.append("")
        else:
            lines.append("В Projects.md пока не зафиксировано проектов.")
            lines.append("")
        if recent:
            lines.append("Последние действия (по журналу):")
            for item in recent[:8]:
                entry = item["entry"]
                # entry: "**HH:MM** [fol] **User:** … **FOL:** …"
                lines.append(f"  • [{item['date']}] {entry[:160]}")
        else:
            lines.append("В журнале пока пусто — начните разговор, и я всё запомню.")
        return "\n".join(lines)

    def _brain_search(self, query: str) -> str:
        """Full-text search over the Brain Work-Log («поищи в мозгу …»)."""
        if not self._brain:
            return "Мозг не инициализирован."
        try:
            matches = self._brain.search_work_log(query, limit=15)
        except Exception as exc:
            logger.warning("Brain search failed: %s", exc)
            return "Не удалось выполнить поиск по мозгу."
        if not matches:
            return f"По запросу «{query}» в мозгу ничего не найдено."
        lines = [f"Нашёл в мозгу по запросу «{query}» ({len(matches)}):"]
        for item in matches:
            entry = item["entry"]
            lines.append(f"  • [{item['date']}] {entry[:160]}")
        return "\n".join(lines)

    def _brain_daily_summary(self) -> str:
        """Write today's summary into the Brain and Obsidian Daily note.

        Called manually («итоги дня») and automatically by the evening
        background task in ``run_api_server.py``."""
        if not self._brain:
            return "Мозг не инициализирован."
        try:
            summary = self._brain.write_daily_summary()
        except Exception as exc:
            logger.warning("Brain daily summary failed: %s", exc)
            return "Не удалось записать итоги дня."
        if not summary:
            return "Сегодня пока нечего подводить — в журнале пусто."
        # Each journal entry carries exactly one "**User:**" marker.
        entries = summary.count("**User:**")
        return (
            "Записал итоги дня в Obsidian "
            f"(Brain/Daily-Summary/ и Daily-заметку). В журнале: {entries} записей."
        )

    def write_daily_summary_now(self) -> bool:
        """Public hook for the evening background task — best-effort, returns
        True when a summary was actually written."""
        try:
            if not self._brain:
                return False
            return bool(self._brain.write_daily_summary())
        except Exception as exc:
            logger.warning("Brain daily summary task failed: %s", exc)
            return False

    # ─── Email Intent (S5) ───────────────────────────────────────────────

    # Recipient label patterns → (dative, genitive) natural RU forms.
    # Dative for "Отправлю письмо {дательный}", genitive for "email у {родительный}".
    _EMAIL_RECIPIENT_RU = [
        (r"преподавател\w*", "преподавателю", "преподавателя"),
        (r"учител\w*", "учителю", "учителя"),
        (r"профессор\w*", "профессору", "профессора"),
        (r"руководител\w*", "руководителю", "руководителя"),
        (r"начальник\w*", "начальнику", "начальника"),
        (r"ментор\w*", "ментору", "ментора"),
        (r"наставник\w*", "наставнику", "наставника"),
        (r"коллег\w*", "коллеге", "коллеги"),
        (r"друг\w*", "другу", "друга"),
    ]

    _EMAIL_RECIPIENT_EN = [
        (r"teacher\w*", "the teacher"),
        (r"professor\w*", "the professor"),
        (r"supervisor\w*", "your supervisor"),
        (r"manager\w*", "your manager"),
        (r"boss\w*", "your boss"),
        (r"mentor\w*", "your mentor"),
        (r"colleague\w*", "your colleague"),
        (r"friend\w*", "your friend"),
    ]

    def _find_email_address(self) -> str:
        """Look up a known email from preferences, memories or Obsidian People.

        Returns ``""`` when no address is known — the caller then asks the
        user instead of inventing one (never fake responses).
        """
        for key in ("teacher_email", "professor_email", "email", "преподаватель_email"):
            val = self._preferences.get(key)
            if val:
                return str(val)
        for m in self._memories:
            content = str(m.get("content", ""))
            hit = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", content)
            if hit:
                return hit.group(0)
        if self._obsidian:
            try:
                for r in self._obsidian.search("email", limit=5):
                    content = self._obsidian.read_note(r["path"])
                    hit = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", content)
                    if hit:
                        return hit.group(0)
            except Exception:
                pass
        return ""

    def _email_response(self, user_input: str) -> str:
        """Deterministic email intent (S5).

        "Напиши письмо преподавателю" → if the address is unknown, ask for
        it naturally ("Конечно. Какой email у преподавателя?") — never the
        generic fallback. If an address IS known, confirm with the real one.
        """
        lang = detect_language(user_input)
        lower = user_input.lower()
        table = self._EMAIL_RECIPIENT_RU if lang == "ru" else self._EMAIL_RECIPIENT_EN
        dative = "преподавателю" if lang == "ru" else "the recipient"
        genitive = "преподавателя" if lang == "ru" else "the recipient"
        if lang == "ru":
            for pattern, dat, gen in table:
                if re.search(pattern, lower):
                    dative, genitive = dat, gen
                    break
        else:
            for pattern, label in table:
                if re.search(pattern, lower):
                    dative = genitive = label
                    break
        address = self._find_email_address()
        if address:
            return (
                f"Конечно. Отправлю письмо {dative} на {address}. О чём написать?"
                if lang == "ru"
                else f"Sure. I'll write to {dative} at {address}. What should it say?"
            )
        return (
            f"Конечно. Какой email у {genitive}?"
            if lang == "ru"
            else f"Sure — what's the email for {genitive}?"
        )

    # ─── Tasks Intent (S9) ───────────────────────────────────────────────

    def _tasks_response(self, user_input: str) -> str:
        """Deterministic tasks intent (S9).

        "Какие задачи я должен сделать завтра?" → searches short-term
        memories, long-term memory and Obsidian for real tasks for the day;
        when nothing is found, says so plainly instead of the generic
        fallback.
        """
        lang = detect_language(user_input)
        lower = user_input.lower()
        if "завтра" in lower or "tomorrow" in lower:
            day_label = "завтра" if lang == "ru" else "tomorrow"
            day_query = "завтра" if lang == "ru" else "tomorrow"
        else:
            day_label = "сегодня" if lang == "ru" else "today"
            day_query = "сегодня" if lang == "ru" else "today"

        found: list[str] = []

        def _add(item: str) -> None:
            item = item.strip()
            if item and item not in found and len(item) > 2:
                found.append(item)

        # 1. Short-term memories (explicitly remembered tasks)
        for m in self._memories:
            content = str(m.get("content", ""))
            if day_query in content.lower() or any(
                w in content.lower() for w in ("задач", "task", "todo", "to-do", "надо", "нужно", "должен")
            ):
                _add(content)
        # 2. Long-term memory search
        if self._long_term_memory:
            try:
                for entry in self._long_term_memory.search_memories(day_query, limit=8):
                    _add(getattr(entry, "content", str(entry)))
            except Exception:
                pass
        # 3. Obsidian vault (Daily/Tasks/задачи)
        if self._obsidian:
            try:
                for r in self._obsidian.search(day_query, limit=8):
                    _add(f"{r.get('title', '')}")
            except Exception:
                pass

        if not found:
            return (
                f"На {day_label} у меня пока ничего не записано."
                if lang == "ru"
                else f"Nothing scheduled for {day_label} yet."
            )
        header = (
            f"На {day_label} у тебя записано:"
            if lang == "ru"
            else f"Here's what's scheduled for {day_label}:"
        )
        lines = [header]
        for item in found[:8]:
            lines.append(f"  • {item}")
        return "\n".join(lines)

    def _obsidian_save(self, text: str) -> str:
        if not self._obsidian:
            return "Obsidian not initialized."
        content = re.sub(r"^(save to vault|сохрани в vault)\s+", "", text, flags=re.IGNORECASE).strip()
        if not content:
            return "What should I save?"
        path = self._obsidian.store(content, category="Knowledge")
        return f"Saved to Obsidian: {path}"

    # ─── Telegram Methods ────────────────────────────────────────────────

    def _telegram_command(self, text: str) -> str:
        """Handle Telegram commands."""
        if not self._telegram or not self._telegram.is_available:
            return "Telegram not configured. Set FOL_TELEGRAM_BOT_TOKEN in .env"
        lower = text.lower().strip()
        if lower.startswith("telegram status") or lower.startswith("tg status"):
            return "Telegram: connected" if self._telegram.is_available else "Telegram: not configured"
        return "Usage: telegram send <message> / telegram status"

    def _telegram_send(self, text: str) -> str:
        """Send a message via Telegram."""
        if not self._telegram or not self._telegram.is_available:
            return "Telegram not configured. Set FOL_TELEGRAM_BOT_TOKEN in .env"
        message = re.sub(r"^(telegram send|отправь в телеграм)\s+", "", text, flags=re.IGNORECASE).strip()
        if not message:
            return "What should I send?"
        chat_id = self._telegram._default_chat_id
        if not chat_id:
            return "No Telegram chat_id configured. Set FOL_TELEGRAM_CHAT_ID in .env"
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(self._telegram.send_message(chat_id, message))
            if result and result.get("ok"):
                return "Message sent to Telegram."
            return f"Failed to send: {result}"
        finally:
            loop.close()

    # ─── Profile Methods ─────────────────────────────────────────────────

    def _my_profile(self) -> str:
        """Show user profile from Obsidian."""
        if not self._obsidian:
            return "Profile not available."
        notes = self._obsidian.search("Abdulakim", limit=5)
        if not notes:
            notes = self._obsidian.search("profile", limit=5)
        if not notes:
            return "No profile found. Use 'save to vault' to create one."
        content = self._obsidian.read_note(notes[0]["path"])
        # Remove frontmatter
        content = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL)
        return content.strip()[:2000]

    def _my_goals(self) -> str:
        """Show user goals from Obsidian."""
        if not self._obsidian:
            return "Goals not available."
        notes = self._obsidian.search("goals", limit=3)
        if not notes:
            return "No goals found."
        for n in notes:
            if "goal" in n["title"].lower():
                content = self._obsidian.read_note(n["path"])
                content = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL)
                return content.strip()[:1500]
        return "No goals found."

    def _my_projects(self) -> str:
        """Show user projects from Obsidian."""
        if not self._obsidian:
            return "Projects not available."
        notes = self._obsidian.get_all_notes(category="Projects")
        if not notes:
            return "No projects found."
        lines = ["Your Projects:"]
        for n in notes:
            lines.append(f"  - {n['title']}")
        return "\n".join(lines)

    def _my_tech(self) -> str:
        """Show user tech stack from Obsidian."""
        if not self._obsidian:
            return "Tech stack not available."
        notes = self._obsidian.search("tech stack", limit=3)
        if not notes:
            return "No tech stack found."
        for n in notes:
            if "tech" in n["title"].lower():
                content = self._obsidian.read_note(n["path"])
                content = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL)
                return content.strip()[:1000]
        return "No tech stack found."

    def _my_rules(self) -> str:
        """Show communication rules from Obsidian."""
        if not self._obsidian:
            return "Rules not available."
        notes = self._obsidian.search("communication rules", limit=3)
        if not notes:
            return "No rules found."
        for n in notes:
            if "rule" in n["title"].lower():
                content = self._obsidian.read_note(n["path"])
                content = re.sub(r"^---.*?---\s*", "", content, flags=re.DOTALL)
                return content.strip()[:1000]
        return "No rules found."

    # ─── Modes (ROADMAP Этап 2) ──────────────────────────────────────────

    # Aliases for spoken/text mode switching, RU + EN.
    _MODE_ALIASES = {
        "companion": "companion", "компаньон": "companion", "общение": "companion",
        "assistant": "assistant", "ассистент": "assistant", "помощник": "assistant",
        "agent": "agent", "агент": "agent",
        "focus": "focus", "фокус": "focus", "фокуса": "focus",
    }

    _MODE_LABELS_RU = {
        "companion": "Компаньон",
        "assistant": "Ассистент",
        "agent": "Агент",
        "focus": "Фокус",
    }

    _MODE_LABELS_EN = {
        "companion": "Companion",
        "assistant": "Assistant",
        "agent": "Agent",
        "focus": "Focus",
    }

    _MODE_DESCRIPTIONS_RU = {
        "companion": "обычное общение, живой разговор",
        "assistant": "выполняю задачи на Mac напрямую",
        "agent": "сложные многошаговые задачи с инструментами",
        "focus": "минимум разговоров, максимум действий — короткие ответы",
    }

    _MODE_DESCRIPTIONS_EN = {
        "companion": "casual conversation",
        "assistant": "performs tasks on your Mac directly",
        "agent": "complex multi-step tasks with tools",
        "focus": "minimal talk, maximum action — short answers",
    }

    _MODE_CONTEXT_HINTS = {
        "companion": (
            "CURRENT MODE: Companion — natural conversation; engage with the user."
        ),
        "assistant": (
            "CURRENT MODE: Assistant — perform the requested task directly using "
            "tools; confirm what you did briefly."
        ),
        "agent": (
            "CURRENT MODE: Agent — for complex tasks you may take multiple steps "
            "with tools before answering; keep the user informed."
        ),
        "focus": (
            "CURRENT MODE: Focus — minimal talk, maximum action. Answer in one or "
            "two short sentences; no preamble, no extra questions, no small talk."
        ),
    }

    def _set_mode(self, mode: str, lang: str) -> str:
        """Switch the conversation mode (voice/text: "режим фокус")."""
        self._mode = mode
        if lang == "ru":
            label = self._MODE_LABELS_RU.get(mode, mode)
            return f"Режим «{label}» активирован."
        label = self._MODE_LABELS_EN.get(mode, mode)
        return f"Mode «{label}» activated."

    def _mode_status(self, lang: str) -> str:
        """Report the current mode and what modes are available."""
        mode = self._mode
        if lang == "ru":
            current = self._MODE_DESCRIPTIONS_RU.get(mode, "")
            lines = [f"Текущий режим: {self._MODE_LABELS_RU.get(mode, mode)} — {current}."]
            lines.append("Доступные режимы:")
            for m, label in self._MODE_LABELS_RU.items():
                lines.append(f"  • {label} — {self._MODE_DESCRIPTIONS_RU[m]}")
            lines.append('Скажите «режим фокус» / «режим ассистент» / «режим агент».')
            return "\n".join(lines)
        current = self._MODE_DESCRIPTIONS_EN.get(mode, "")
        lines = [f"Current mode: {self._MODE_LABELS_EN.get(mode, mode)} — {current}."]
        lines.append("Available modes:")
        for m, label in self._MODE_LABELS_EN.items():
            lines.append(f"  • {label} — {self._MODE_DESCRIPTIONS_EN[m]}")
        lines.append('Say "focus mode" / "assistant mode" / "agent mode".')
        return "\n".join(lines)

    # ─── System Status ───────────────────────────────────────────────────

    def _system_status(self) -> str:
        uptime = self._format_uptime()
        llm_backends = self._llm.available_backends if self._llm else []
        tools_count = len(self._tools.list_all()) if self._tools else 0
        return (
            f"FOL System Status\n"
            f"  Version: {self.version}\n"
            f"  Uptime: {uptime}\n"
            f"  Platform: {platform.system()} {platform.release()}\n"
            f"  Python: {platform.python_version()}\n"
            f"  Machine: {platform.machine()}\n"
            f"  LLM Backends: {', '.join(llm_backends) if llm_backends else 'none'}\n"
            f"  Tools: {tools_count}\n"
            f"  Mode: {self._mode}\n"
            f"  Proactive: {'on' if self._proactive is not None and self._proactive.enabled else 'off'}\n"
            f"  Conversations: {len(self._conversation_history)}\n"
            f"  Memories: {len(self._memories)}"
        )

    # ─── Tool System ─────────────────────────────────────────────────────

    # Verbs that already carry a full command — the follow-up is used as-is.
    _ACTION_VERBS = re.compile(
        r"^(?:open|открой|откройте|запусти|запустите|launch|start|show|покажи|"
        r"find|найди|play|включи|search|поищи|run|выполни|напиши|create|создай|"
        r"открой сайт|прочитай|read|выведи)\b"
    )

    async def _resolve_action_followup(self, text: str) -> str | None:
        """Resolve action follow-ups that continue the previous turn.

        "А теперь YouTube" / "теперь открой файл" / "and now Chrome" after
        a previous action are resolved by rebuilding the command and matching
        it against the tools. Returns the tool result, or ``None`` when the
        input is not an action follow-up (so the normal pipeline continues).

        Safety: the bare-noun rebuild ("а теперь X" → "открой X") only fires
        when X is a KNOWN app alias — never for free-form text, so common
        words like "now" / "next" can never trigger a real ``open -a`` call.
        """
        lower = text.lower().strip()
        m = re.match(
            r"^(?:а теперь|теперь|а дальше|дальше|затем|а затем|and now|and next)\s+(.+)$",
            lower,
        )
        if not m:
            return None
        action = m.group(1).strip()
        if not action:
            return None
        # Full command already present ("теперь открой файл X") → use as-is.
        if self._ACTION_VERBS.match(lower):
            return await self._try_tools(action)
        # Bare noun ("а теперь YouTube") → only rebuild for known apps.
        if action.lower() in self._APP_ALIASES:
            return await self._try_tools(f"открой {action}")
        # Not a known app and no command verb → not an action follow-up.
        return None

    async def _try_tools(self, text: str) -> str | None:
        """Match user input to MacBook control commands and execute them.
        Supports both English and Russian commands.
        """
        lower = text.lower().strip()
        lang = detect_language(text)

        # ─── Browser Open (EN + RU) — must be BEFORE App Launch ──────
        browser_open_match = re.match(
            r"^(?:open site|open url|открой сайт|открой страницу|открой ссылку|зайди на сайт)\s+(.+)$",
            lower,
        )
        if browser_open_match:
            url = browser_open_match.group(1).strip()
            result = await self._execute_tool("browser_open", {"url": url})
            return result.output if result.success else f"Error: {result.error}"

        # ─── App Launch (EN + RU) ────────────────────────────────────
        app_match = re.match(
            r"^(?:open|открой|откройте|запусти|запустите|launch|start|run app|запусти приложение)\s+(.+)$",
            lower,
        )
        if app_match:
            app_name = app_match.group(1).strip()
            # "запусти команду ls" / "run command ls" — this is a shell
            # command, NOT an app open. Route it to the command executor
            # (app_match runs BEFORE the shell block, so catch it here).
            if re.match(r"^(?:команду|команда|command)\s+", app_name):
                shell_cmd = re.sub(r"^(?:команду|команда|command)\s+", "", app_name).strip()
                result = await self._execute_tool("execute_command", {"command": shell_cmd})
                return result.output if result.success else f"Error: {result.error}"
            # Strip trailing compound intent: "Открой Safari и найди новости" → Safari.
            app_name = re.split(r"\s+(?:и|и\s+затем|and|then)\s+", app_name, maxsplit=1)[0].strip()
            # Strip trailing punctuation: "Открой Safari." → Safari (not "Safari.").
            app_name = re.sub(r"[.!?\s]+$", "", app_name)
            # "этот сайт" = YouTube
            if app_name in ("этот сайт", "этот сайт", "this site", "that site"):
                return self._mac_play_youtube("", lang)
            self._last_tool = ("open_app", {"name": app_name})
            return await self._mac_open_app(app_name, lang)

        # ─── Music / Media Control (EN + RU) ─────────────────────────
        if lower in (
            "play music", "включи музыку", "play", "включи", "включи музыку",
            "play song", "включи песню", "music on", "музыка вкл",
            "воспроизвести", "воспроизведение",
        ):
            self._last_tool = ("media_play", {})
            return self._mac_media("play", lang)

        if lower in (
            "pause music", "пауза", "pause", "останови", "остановить",
            "music pause", "музыка пауза", "приостанови",
        ):
            self._last_tool = ("media_pause", {})
            return self._mac_media("pause", lang)

        if lower in (
            "next song", "следующая", "next", "дальше", "следующий трек",
            "next track", "другая песня", "другая", "ещё одна",
        ):
            self._last_tool = ("media_next", {})
            return self._mac_media("next", lang)

        if lower in (
            "previous song", "предыдущая", "previous", "назад",
            "previous track", "прошлая песня", "прошлый трек",
        ):
            self._last_tool = ("media_previous", {})
            return self._mac_media("previous", lang)

        if lower in (
            "stop music", "выключи музыку", "stop", "выключи",
            "music off", "музыка выкл", "останови музыку",
        ):
            self._last_tool = ("media_stop", {})
            return self._mac_media("stop", lang)

        # Play specific artist/song (EN + RU)
        play_match = re.match(
            r"^(?:play|включи|поставь|поставить|ставь|воспроизвести|запусти музыку|put on)\s+(.+?)(?:\s+(?:on|на)\s+(?:youtube|ютуб\w*))?\s*$",
            lower,
        )
        if play_match:
            query = play_match.group(1).strip()
            # Check if user wants YouTube
            full_match = play_match.group(0)
            if "youtube" in full_match or "ютуб" in full_match:
                self._last_tool = ("open_youtube", {"query": query})
                return self._mac_play_youtube(query, lang)
            self._last_tool = ("play_music", {"query": query})
            return self._mac_play_music(query, lang)

        # YouTube specific (EN + RU)
        youtube_match = re.match(
            r"^(?:youtube|ютуб|ютьюб|play on youtube|включи на youtube|включи на ютуб|ставь на ютуб)\s+(.+)$",
            lower,
        )
        if youtube_match:
            query = youtube_match.group(1).strip()
            self._last_tool = ("open_youtube", {"query": query})
            return self._mac_play_youtube(query, lang)

        if lower in ("youtube", "ютуб", "ютьюб", "open youtube", "открой youtube", "открой ютуб"):
            self._last_tool = ("open_youtube", {})
            return self._mac_play_youtube("", lang)

        # "playX on youtube" pattern (no space between play and artist)
        play_yt_match = re.match(r"^play\s*(.+?)\s*(?:on|на)\s*(?:youtube|ютуб)$", lower)
        if play_yt_match:
            self._last_tool = ("open_youtube", {"query": play_yt_match.group(1).strip()})
            return self._mac_play_youtube(play_yt_match.group(1).strip(), lang)

        # ─── Volume Control (EN + RU) ────────────────────────────────
        vol_up = re.match(
            r"^(?:volume up|громкость вверх|прибавь громкость|прибавь|громче|loud|louder|boost|boost volume)\s*(\d+)?$",
            lower,
        )
        if vol_up:
            step = int(vol_up.group(1)) if vol_up.group(1) else 10
            self._last_tool = ("volume_up", {"step": step})
            return self._mac_volume("up", step, lang)

        vol_down = re.match(
            r"^(?:volume down|громкость вниз|убавь громкость|убавь|тише|тише|quiet|quieter|dim|reduce volume)\s*(\d+)?$",
            lower,
        )
        if vol_down:
            step = int(vol_down.group(1)) if vol_down.group(1) else 10
            self._last_tool = ("volume_down", {"step": step})
            return self._mac_volume("down", step, lang)

        vol_set = re.match(
            r"^(?:set volume|установи громкость|установи|volume to|громкость|громкость до|volume)\s*(?:to\s*)?(\d+)$",
            lower,
        )
        if vol_set:
            level = int(vol_set.group(1))
            self._last_tool = ("volume_set", {"level": level})
            return self._mac_volume("set", level, lang)

        if lower in (
            "mute", "без звука", "приглуши", "выключи звук",
            "без звуку", "приглушить", "тихо", "silence", "silent",
        ):
            self._last_tool = ("volume_mute", {})
            return self._mac_volume("mute", 0, lang)
        if lower in (
            "unmute", "включи звук", "верни звук", "вернуть звук",
            "включить звук", "unmute", "sound on",
        ):
            self._last_tool = ("volume_unmute", {})
            return self._mac_volume("unmute", 0, lang)

        # ─── Brightness (EN + RU) ────────────────────────────────────
        bright_up = re.match(
            r"^(?:brightness up|яркость вверх|прибавь яркость|brighter|ярче|increase brightness)\s*(\d+)?$",
            lower,
        )
        if bright_up:
            step = int(bright_up.group(1)) if bright_up.group(1) else 10
            self._last_tool = ("brightness_up", {"step": step})
            return self._mac_brightness("up", step, lang)

        bright_down = re.match(
            r"^(?:brightness down|яркость вниз|убавь яркость|dimmer|darker|dim|темнее|уменьши яркость)\s*(\d+)?$",
            lower,
        )
        if bright_down:
            step = int(bright_down.group(1)) if bright_down.group(1) else 10
            self._last_tool = ("brightness_down", {"step": step})
            return self._mac_brightness("down", step, lang)

        # ─── Window Management (EN + RU) ─────────────────────────────
        if lower in (
            "minimize", "свернуть", "сверни",            "minimize window",
            "свернуть окно", "свернуть текущее окно",
        ):
            self._last_tool = ("window_minimize", {})
            return self._mac_window("minimize", lang)
        if lower in (
            "maximize", "развернуть", "разверни", "maximize window",
            "fullscreen", "на весь экран", "развернуть окно",
        ):
            self._last_tool = ("window_maximize", {})
            return self._mac_window("maximize", lang)
        if lower in (
            "close window", "закрой окно", "close", "закрой",
            "закрыть окно", "закрыть",
        ):
            self._last_tool = ("window_close", {})
            return self._mac_window("close", lang)
        if lower in (
            "new window", "новое окно", "new tab", "новая вкладка",
            "создай окно", "новая страница",
        ):
            self._last_tool = ("window_new", {})
            return self._mac_window("new", lang)

        # ─── Screenshot (EN + RU) ────────────────────────────────────
        if lower in (
            "screenshot", "скриншот", "capture screen", "снимок экрана",
            "сделай скриншот", "сделай снимок", "take screenshot",
        ):
            return self._take_screenshot()

        # ─── Sleep / Wake / Lock (EN + RU) ───────────────────────────
        if lower in (
            "sleep", "усни", "засни", "уснуть", "заснуть",
            "go to sleep", "put to sleep", "переведи в сон",
        ):
            self._last_tool = ("system_sleep", {})
            return self._mac_system("sleep", lang)
        if lower in (
            "lock", "заблокируй", "заблокировать", "lock screen",
            "заблокируй экран", "заблокируй компьютер",
        ):
            self._last_tool = ("system_lock", {})
            return self._mac_system("lock", lang)
        if lower in (
            "wake up", "проснись", "проснуться", "разбуди",
            "wake", "разбуди компьютер", "wake the mac",
        ):
            self._last_tool = ("system_wake", {})
            return self._mac_system("wake", lang)

        # ─── Run shell command (EN + RU) ─────────────────────────────
        # Longest phrases FIRST — otherwise "выполни команду pwd" would match
        # the shorter "выполни" prefix and run "команду pwd" (garbage).
        run_command = self._extract_shell_command(lower)
        if run_command is not None:
            result = await self._execute_tool("execute_command", {"command": run_command})
            return result.output if result.success else f"Error: {result.error}"

        # ─── Browser interaction (EN + RU) ──────────────────────────
        browser_open_match = re.match(
            r"^(?:open site|open url|открой сайт|открой страницу|открой ссылку|зайди на сайт|открой)\s+(.+)$",
            lower,
        )
        if browser_open_match:
            url = browser_open_match.group(1).strip()
            result = await self._execute_tool("browser_open", {"url": url})
            return result.output if result.success else f"Error: {result.error}"

        browser_click_match = re.match(
            r"^(?:click|нажми|нажми кнопку|нажать)\s+(.+)$",
            lower,
        )
        if browser_click_match:
            selector = browser_click_match.group(1).strip()
            result = await self._execute_tool("browser_click", {"selector": selector})
            return result.output if result.success else f"Error: {result.error}"

        browser_type_match = re.match(
            r"^(?:type|введи|введи текст|набери|напиши в поле)\s+(.+)$",
            lower,
        )
        if browser_type_match:
            text = browser_type_match.group(1).strip()
            result = await self._execute_tool("browser_type", {"selector": "input, textarea", "text": text})
            return result.output if result.success else f"Error: {result.error}"

        browser_scroll_match = re.match(
            r"^(?:scroll|прокрути|скролл)\s+(down|up|top|bottom|вниз|вверх|наверх|внизу)$",
            lower,
        )
        if browser_scroll_match:
            direction = browser_scroll_match.group(1)
            dir_map = {"вниз": "down", "вверх": "up", "наверх": "top", "внизу": "bottom"}
            direction = dir_map.get(direction, direction)
            result = await self._execute_tool("browser_scroll", {"direction": direction})
            return result.output if result.success else f"Error: {result.error}"

        if lower in ("browser extract", "прочитай страницу", "что на странице", "извлеки текст"):
            result = await self._execute_tool("browser_extract", {"mode": "text"})
            return result.output if result.success else f"Error: {result.error}"

        if lower in ("browser links", "ссылки на странице", "все ссылки"):
            result = await self._execute_tool("browser_extract", {"mode": "links"})
            return result.output if result.success else f"Error: {result.error}"

        if lower in ("browser screenshot", "скриншот страницы", "снимок сайта"):
            result = await self._execute_tool("browser_screenshot", {})
            return result.output if result.success else f"Error: {result.error}"

        if lower in ("browser close", "закрой браузер", "закрыть браузер"):
            result = await self._execute_tool("browser_close", {})
            return result.output if result.success else f"Error: {result.error}"

        if lower in ("browser refresh", "обнови страницу", "обновить страницу", "перезагрузи", "reload"):
            result = await self._execute_tool("browser_refresh", {})
            return result.output if result.success else f"Error: {result.error}"


        if lower in ("нажми enter", "press enter", "enter", "нажми ввод"):
            result = await self._execute_tool("browser_press_key", {"key": "Enter"})
            return result.output if result.success else f"Error: {result.error}"

        if lower in ("нажми escape", "press escape", "escape"):
            result = await self._execute_tool("browser_press_key", {"key": "Escape"})
            return result.output if result.success else f"Error: {result.error}"

        # ─── Search (EN + RU) ────────────────────────────────────────
        search_match = re.match(
            r"^(?:search|найди|найти|поищи|google|загугли|поиск|find|look up|search for|найти в интернете|найди в google)\s+(.+)$",
            lower,
        )
        if search_match:
            query = search_match.group(1).strip()
            self._last_tool = ("web_search", {"query": query})
            return self._mac_search(query, lang)

        # ─── Read file (EN + RU) ─────────────────────────────────────
        read_match = re.match(
            r"^(?:read|прочитай|прочитать|open file|открой файл|покажи файл|show file)\s+(.+)$",
            lower,
        )
        if read_match:
            result = await self._execute_tool("read_file", {"path": read_match.group(1)})
            return result.output if result.success else f"Error: {result.error}"

        # ─── System info (EN + RU) ───────────────────────────────────
        if lower in (
            "system info", "инфо", "system", "about this mac",
            "информация о системе", "системная информация",
            "что за компьютер", "конфигурация", "specs", "specifications",
        ):
            result = await self._execute_tool("system_info", {})
            return result.output if result.success else f"Error: {result.error}"

        # ─── Battery (EN + RU) ───────────────────────────────────────
        if lower in (
            "battery", "батарея", "заряд", "зарядка", "power",
            "сколько заряда", "battery level", "charge",
        ):
            self._last_tool = ("system_battery", {})
            return self._mac_battery(lang)

        # ─── WiFi (EN + RU) ──────────────────────────────────────────
        if lower in ("wifi", "вайфай", "wi-fi", "internet", "интернет"):
            self._last_tool = ("system_wifi", {})
            return self._mac_wifi(lang)

        # ─── Bluetooth (EN + RU) ─────────────────────────────────────
        if lower in ("bluetooth", "блутуз", "блютуз"):
            self._last_tool = ("system_bluetooth", {})
            return self._mac_bluetooth(lang)

        # ─── Clipboard (EN + RU) ─────────────────────────────────────
        paste_match = re.match(
            r"^(?:paste|вставь|вставить|вставь текст|paste text)\s*(.+)?$",
            lower,
        )
        if paste_match:
            text_to_paste = paste_match.group(1) if paste_match.group(1) else ""
            self._last_tool = ("paste", {"text": text_to_paste})
            return self._mac_paste(text_to_paste, lang)

        if lower in ("copy", "скопируй", "скопировать", "copy clipboard"):
            self._last_tool = ("copy", {})
            return self._mac_copy(lang)

        return None

    # ─── MacBook Control Methods ──────────────────────────────────────────

    # Known macOS app aliases (EN + RU). Shared by _mac_open_app and the
    # Context-Conversation action follow-up resolver so "а теперь YouTube"
    # only rebuilds commands for REAL apps — never "открой week i need".
    _APP_ALIASES: dict[str, str] = {
        # English
        "safari": "Safari", "chrome": "Google Chrome", "firefox": "Firefox",
        "finder": "Finder", "terminal": "Terminal", "vscode": "Visual Studio Code",
        "visual studio code": "Visual Studio Code", "code": "Visual Studio Code",
        "spotify": "Spotify", "music": "Music",
        "messages": "Messages", "mail": "Mail",
        "notes": "Notes", "calendar": "Calendar",
        "photos": "Photos", "preview": "Preview",
        "textedit": "TextEdit", "calculator": "Calculator",
        "maps": "Maps", "facetime": "FaceTime",
        "slack": "Slack", "discord": "Discord", "telegram": "Telegram",
        "obsidian": "Obsidian",
        "word": "Microsoft Word", "excel": "Microsoft Excel",
        "powerpoint": "Microsoft PowerPoint",
        "figma": "Figma", "sketch": "Sketch",
        "app store": "App Store", "system preferences": "System Settings",
        "settings": "System Settings", "activity monitor": "Activity Monitor",
        "disk utility": "Disk Utility", "xcode": "Xcode",
        "whatsapp": "WhatsApp", "zoom": "zoom.us",
        "notion": "Notion", "trello": "Trello",
        "vs code": "Visual Studio Code", "pycharm": "PyCharm",
        "intellij": "IntelliJ IDEA", "webstorm": "WebStorm",
        "sublime": "Sublime Text", "atom": "Atom",
        # Russian
        "сafari": "Safari", "сафари": "Safari",
        "проводник": "Finder", "файндер": "Finder",
        "терминал": "Terminal",
        "музыка": "Music", "итюнс": "Music", "айтуны": "Music",
        "сообщения": "Messages", "почта": "Mail",
        "заметки": "Notes", "календарь": "Calendar",
        "фото": "Photos", "предпросмотр": "Preview",
        "калькулятор": "Calculator", "карты": "Maps",
        "настройки": "System Settings", "системные настройки": "System Settings",
        "магазин приложений": "App Store",
        "активный монитор": "Activity Monitor",
        "монитор активности": "Activity Monitor",
        # YouTube
        "youtube": "YouTube", "ютуб": "YouTube", "ютьюб": "YouTube",
        "этот сайт": "YouTube",
    }

    @staticmethod
    def _cap(word: str) -> str:
        """Capitalize the first letter of a name, keep the rest as-is."""
        word = (word or "").strip()
        return word[0].upper() + word[1:] if word else word

    async def _mac_open_app(self, app_name: str, lang: str = "en") -> str:
        """Open a macOS application — bilingual, natural, no honorifics."""
        app_map = self._APP_ALIASES
        resolved = app_map.get(app_name.lower(), app_name)

        # Special handling for YouTube — open in new Safari tab
        if resolved == "YouTube":
            return self._mac_play_youtube("", lang)

        try:
            import subprocess
            subprocess.Popen(["open", "-a", resolved], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return (
                f"{self._cap(resolved)} открыт."
                if lang == "ru"
                else f"{self._cap(resolved)} is open."
            )
        except Exception:
            return (
                f"Не удалось открыть {resolved}."
                if lang == "ru"
                else f"I couldn't open {resolved}."
            )

    def _mac_media(self, action: str, lang: str = "en") -> str:
        """Control media playback via AppleScript — bilingual, natural."""
        import subprocess
        scripts = {
            "play": 'tell application "Music" to play',
            "pause": 'tell application "Music" to pause',
            "next": 'tell application "Music" to next track',
            "previous": 'tell application "Music" to previous track',
            "stop": 'tell application "Music" to stop',
        }
        confirm = {
            "play": ("Включил музыку." if lang == "ru" else "Music is playing."),
            "pause": ("Поставил на паузу." if lang == "ru" else "Paused."),
            "next": ("Переключил на следующий трек." if lang == "ru" else "Skipped to the next track."),
            "previous": ("Вернул к предыдущему треку." if lang == "ru" else "Went back to the previous track."),
            "stop": ("Остановил музыку." if lang == "ru" else "Music stopped."),
        }
        try:
            subprocess.run(["osascript", "-e", scripts[action]], timeout=5)
            return confirm.get(action, confirm["play"])
        except Exception:
            return (
                "Не получилось управлять музыкой. Попробуйте ещё раз."
                if lang == "ru"
                else "I couldn't control the music. Please try again."
            )

    def _mac_play_music(self, query: str, lang: str = "en") -> str:
        """Play music via Music app — bilingual, natural."""
        import subprocess
        script = '''
        tell application "Music"
            activate
            if player state is not playing then
                play
            end if
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], timeout=5)
            return (
                (f"Включил музыку: {query}." if query else "Включил музыку.")
                if lang == "ru"
                else (f"Playing: {query}." if query else "Music is playing.")
            )
        except Exception:
            return (
                "Не получилось включить музыку."
                if lang == "ru"
                else "I couldn't start the music."
            )

    def _mac_play_youtube(self, query: str, lang: str = "en") -> str:
        """Play music on YouTube via Safari (new tab) — bilingual, natural."""
        import subprocess
        import urllib.parse

        if not query:
            url = "https://www.youtube.com"
        else:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://www.youtube.com/results?search_query={encoded}"

        # Open in NEW Safari tab (not redirect current page)
        try:
            script = f'''
            tell application "Safari"
                activate
                tell application "System Events" to keystroke "t" using command down
                delay 0.5
                set URL of front document to "{url}"
            end tell
            '''
            subprocess.Popen(["osascript", "-e", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if lang == "ru":
                return f"Открыл YouTube{(' по запросу «' + query + '»') if query else ''}."
            return f"Opened YouTube{(' for ' + query) if query else ''}."
        except Exception:
            return (
                "Не получилось открыть YouTube."
                if lang == "ru"
                else "I couldn't open YouTube."
            )

    def _mac_volume(self, action: str, level: int = 0, lang: str = "en") -> str:
        """Control system volume — bilingual, natural."""
        import subprocess
        ru = lang == "ru"
        try:
            if action in ("up", "down"):
                sign = "+" if action == "up" else "-"
                subprocess.run(["osascript", "-e", "set volume output volume (output volume of (get volume settings) {})".format(sign + str(level))], timeout=5)
                vol = subprocess.run(["osascript", "-e", "output volume of (get volume settings)"], capture_output=True, text=True, timeout=5)
                pct = vol.stdout.strip()
                return f"Громкость: {pct}%." if ru else f"Volume: {pct}%."
            if action == "set":
                subprocess.run(["osascript", "-e", f"set volume output volume {min(max(level, 0), 100)}"], timeout=5)
                return f"Установил громкость {level}%." if ru else f"Volume set to {level}%."
            if action == "mute":
                subprocess.run(["osascript", "-e", "set volume output muted true"], timeout=5)
                return "Звук выключен." if ru else "Sound muted."
            if action == "unmute":
                subprocess.run(["osascript", "-e", "set volume output muted false"], timeout=5)
                return "Звук включён." if ru else "Sound on."
        except Exception:
            return (
                "Не получилось изменить громкость."
                if ru
                else "I couldn't change the volume."
            )
        return "Неизвестная команда громкости." if ru else "Unknown volume action."

    def _mac_brightness(self, action: str, step: int = 10, lang: str = "en") -> str:
        """Control screen brightness — bilingual, natural."""
        import subprocess
        ru = lang == "ru"
        try:
            if action == "up":
                subprocess.run(["brightness", "set", f"+{step/100}"], timeout=5)
                return "Увеличил яркость." if ru else "Brightness increased."
            if action == "down":
                subprocess.run(["brightness", "set", f"-{step/100}"], timeout=5)
                return "Уменьшил яркость." if ru else "Brightness decreased."
        except FileNotFoundError:
            return (
                "Управление яркостью требует утилиты 'brightness' (brew install brightness)."
                if ru
                else "Brightness control needs the 'brightness' CLI tool (brew install brightness)."
            )
        except Exception:
            return (
                "Не получилось изменить яркость."
                if ru
                else "I couldn't change the brightness."
            )
        return "Неизвестная команда яркости." if ru else "Unknown brightness action."

    def _mac_window(self, action: str, lang: str = "en") -> str:
        """Window management via AppleScript — bilingual, natural."""
        import subprocess
        scripts = {
            "minimize": 'tell application "System Events" to set miniaturized of front window to true',
            "maximize": 'tell application "System Events" to set zoomed of front window to true',
            "close": 'tell application "System Events" to close front window',
            "new": 'tell application "System Events" to keystroke "n" using command down',
        }
        confirm = {
            "minimize": ("Свернул окно." if lang == "ru" else "Window minimized."),
            "maximize": ("Развернул окно." if lang == "ru" else "Window maximized."),
            "close": ("Закрыл окно." if lang == "ru" else "Window closed."),
            "new": ("Открыл новое окно." if lang == "ru" else "Opened a new window."),
        }
        try:
            subprocess.run(["osascript", "-e", scripts[action]], timeout=5)
            return confirm.get(action, confirm["minimize"])
        except Exception:
            return (
                "Не получилось управлять окном."
                if lang == "ru"
                else "I couldn't manage the window."
            )

    def _mac_system(self, action: str, lang: str = "en") -> str:
        """System actions: sleep, lock, wake — bilingual, natural."""
        import subprocess
        ru = lang == "ru"
        try:
            if action == "sleep":
                subprocess.run(["pmset", "sleepnow"], timeout=5)
                return "Перевожу компьютер в сон." if ru else "Putting the Mac to sleep."
            if action == "lock":
                subprocess.run([
                    "osascript", "-e",
                    'tell application "System Events" to keystroke "q" using command down'
                ], timeout=5)
                return "Экран заблокирован." if ru else "Screen locked."
            if action == "wake":
                subprocess.run(["caffeinate", "-u", "-t", "1"], timeout=5)
                return "Разбудил компьютер." if ru else "The Mac is awake."
        except Exception:
            return (
                "Не получилось выполнить системное действие."
                if ru
                else "I couldn't perform that system action."
            )
        return "Неизвестное системное действие." if ru else "Unknown system action."

    def _mac_search(self, query: str, lang: str | None = None) -> str:
        """Search the web — bilingual, natural, describes the actual outcome."""
        import subprocess
        lang = lang or detect_language(query)
        url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        try:
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return (
                f"Открыл поиск по запросу «{query}»."
                if lang == "ru"
                else f"Opened a search for '{query}'."
            )
        except Exception:
            return (
                f"Не удалось открыть поиск по запросу «{query}»."
                if lang == "ru"
                else f"I couldn't open the search for '{query}'."
            )

    def _mac_battery(self, lang: str = "en") -> str:
        """Get battery status — bilingual, natural."""
        import subprocess
        ru = lang == "ru"
        try:
            result = subprocess.run(
                ["pmset", "-g", "batt"],
                capture_output=True, text=True, timeout=5,
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) >= 2:
                battery_line = lines[1]
                import re
                pct_match = re.search(r"(\d+)%", battery_line)
                pct = pct_match.group(1) if pct_match else "?"
                charging = "charging" in battery_line.lower()
                state = ("заряжается" if charging else "на батарее") if ru else ("charging" if charging else "on battery")
                return f"Батарея: {pct}% ({state})." if ru else f"Battery: {pct}% ({state})."
            return "Информация о батарее недоступна." if ru else "Battery info unavailable."
        except Exception:
            return (
                "Не получилось узнать заряд батареи."
                if ru
                else "I couldn't read the battery level."
            )

    def _mac_wifi(self, lang: str = "en") -> str:
        """Get WiFi status — bilingual, natural."""
        import subprocess
        ru = lang == "ru"
        try:
            result = subprocess.run(
                ["networksetup", "-getairportnetwork", "en0"],
                capture_output=True, text=True, timeout=5,
            )
            output = result.stdout.strip()
            if "You are not" in output or "not associated" in output.lower():
                return "WiFi: не подключён." if ru else "WiFi: not connected."
            return f"WiFi: {output}"
        except Exception:
            return (
                "Не получилось проверить WiFi."
                if ru
                else "I couldn't check the WiFi."
            )

    def _mac_bluetooth(self, lang: str = "en") -> str:
        """Get Bluetooth status — bilingual, natural."""
        import subprocess
        ru = lang == "ru"
        try:
            result = subprocess.run(
                ["system_profiler", "SPBluetoothDataType"],
                capture_output=True, text=True, timeout=10,
            )
            if "State: On" in result.stdout:
                return "Bluetooth: включён." if ru else "Bluetooth: ON."
            if "State: Off" in result.stdout:
                return "Bluetooth: выключен." if ru else "Bluetooth: OFF."
            return "Статус Bluetooth неизвестен." if ru else "Bluetooth status unknown."
        except Exception:
            return (
                "Не получилось проверить Bluetooth."
                if ru
                else "I couldn't check the Bluetooth."
            )

    def _mac_paste(self, text: str, lang: str = "en") -> str:
        """Paste text to clipboard and paste it — bilingual, natural."""
        import subprocess
        ru = lang == "ru"
        if text:
            subprocess.run(["pbcopy"], input=text.encode(), timeout=5)
            return f"Вставил: {text[:50]}" if ru else f"Pasted: {text[:50]}"
        return "Нечего вставлять." if ru else "Nothing to paste."

    def _mac_copy(self, lang: str = "en") -> str:
        """Copy clipboard content — bilingual, natural."""
        import subprocess
        ru = lang == "ru"
        try:
            result = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
            content = result.stdout.strip()
            if content:
                return f"Буфер обмена: {content[:200]}" if ru else f"Clipboard: {content[:200]}"
            return "Буфер обмена пуст." if ru else "Clipboard is empty."
        except Exception:
            return (
                "Не получилось прочитать буфер обмена."
                if ru
                else "I couldn't read the clipboard."
            )

    # ─── Window & Program Management (EN + RU) ────────────────────────

    async def _mac_switch_app(self, app_name: str) -> str:
        """Switch to (bring front) a macOS application."""
        app_map = {
            "safari": "Safari", "chrome": "Google Chrome", "firefox": "Firefox",
            "finder": "Finder", "terminal": "Terminal", "code": "Visual Studio Code",
            "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
            "spotify": "Spotify", "music": "Music",
            "messages": "Messages", "mail": "Mail",
            "notes": "Notes", "calendar": "Calendar",
            "photos": "Photos", "preview": "Preview",
            "figma": "Figma", "slack": "Slack", "discord": "Discord",
            "telegram": "Telegram", "obsidian": "Obsidian",
            "notion": "Notion", "zoom": "zoom.us",
            "pycharm": "PyCharm", "intellij": "IntelliJ IDEA",
            "сафари": "Safari", "проводник": "Finder", "терминал": "Terminal",
            "музыка": "Music", "сообщения": "Messages", "почта": "Mail",
            "заметки": "Notes", "календарь": "Calendar", "фото": "Photos",
            "калькулятор": "Calculator", "настройки": "System Settings",
        }
        resolved = app_map.get(app_name.lower(), app_name)
        import subprocess
        script = (
            'tell application "System Events" to set frontmost of '
            f'process "{resolved}" to true'
        )
        try:
            subprocess.run(["osascript", "-e", script], timeout=5)
            lang = detect_language(app_name)
            if lang == "ru":
                return f"Переключился на {resolved}."
            return f"Switched to {resolved}."
        except Exception as exc:
            lang = detect_language(app_name)
            if lang == "ru":
                return f"Не удалось переключиться на {app_name}."
            return f"I couldn't switch to {app_name}."

    def _mac_quit_app(self, app_name: str) -> str:
        """Quit a macOS application."""
        app_map = {
            "safari": "Safari", "chrome": "Google Chrome", "firefox": "Firefox",
            "finder": "Finder", "terminal": "Terminal", "code": "Visual Studio Code",
            "vscode": "Visual Studio Code", "vs code": "Visual Studio Code",
            "spotify": "Spotify", "music": "Music",
            "messages": "Messages", "mail": "Mail",
            "notes": "Notes", "calendar": "Calendar",
            "photos": "Photos", "preview": "Preview",
            "figma": "Figma", "slack": "Slack", "discord": "Discord",
            "telegram": "Telegram", "obsidian": "Obsidian",
            "notion": "Notion", "zoom": "zoom.us",
            "pycharm": "PyCharm", "intellij": "IntelliJ IDEA",
            "сафари": "Safari", "проводник": "Finder", "терминал": "Terminal",
            "музыка": "Music", "сообщения": "Messages", "почта": "Mail",
            "заметки": "Notes", "календарь": "Calendar", "фото": "Photos",
            "калькулятор": "Calculator", "настройки": "System Settings",
        }
        resolved = app_map.get(app_name.lower(), app_name)
        import subprocess
        script = f'tell application "{resolved}" to quit'
        try:
            subprocess.run(["osascript", "-e", script], timeout=5)
            lang = detect_language(app_name)
            if lang == "ru":
                return f"Закрыл {resolved}."
            return f"Closed {resolved}."
        except Exception:
            lang = detect_language(app_name)
            if lang == "ru":
                return f"Не удалось закрыть {app_name}."
            return f"I couldn't close {app_name}."

    def _mac_move_window(self, direction: str) -> str:
        """Move/position the front window via AppleScript."""
        import subprocess
        dir_map = {
            "left": "left", "right": "right", "top": "top", "bottom": "bottom",
            "влево": "left", "вправо": "right",
            "вверх": "top", "вниз": "bottom",
            "center": "center", "центр": "center",
        }
        d = dir_map.get(direction.lower(), direction)
        _p = '(name of first application process whose frontmost is true)'
        _te = 'tell application "System Events"'
        scripts = {}
        if d == 'left':
            scripts[d] = _te + ' to tell process ' + _p + ' to set size of front window to {720, 900} '
            scripts[d] += _te + ' to tell process ' + _p + ' to set position of front window to {0, 0}'
        elif d == 'right':
            scripts[d] = _te + ' to tell process ' + _p + ' to set size of front window to {720, 900} '
            scripts[d] += _te + ' to tell process ' + _p + ' to set position of front window to {720, 0}'
        elif d == 'top':
            scripts[d] = _te + ' to tell process ' + _p + ' to set size of front window to {1440, 450} '
            scripts[d] += _te + ' to tell process ' + _p + ' to set position of front window to {0, 0}'
        elif d == 'bottom':
            scripts[d] = _te + ' to tell process ' + _p + ' to set size of front window to {1440, 450} '
            scripts[d] += _te + ' to tell process ' + _p + ' to set position of front window to {0, 450}'
        else:
            scripts[d] = _te + ' to tell process ' + _p + ' to set position of front window to {360, 225}'
        try:
            subprocess.run(["osascript", "-e", scripts[d]], timeout=5)
            lang = detect_language(direction)
            if lang == "ru":
                return f"Переместил окно ({d})."
            return f"Window moved to {d}."
        except Exception:
            lang = detect_language(direction)
            if lang == "ru":
                return "Не удалось переместить окно."
            return "I couldn't move the window."
    def _mac_resize_window(self, width: int, height: int) -> str:
        """Resize the front window to exact pixel dimensions."""
        import subprocess
        script = (
            'tell application "System Events" to tell process (name of first application process whose frontmost is true)\n'
            f'  set size of front window to {{{width}, {height}}}\n'
            'end tell'
        )
        try:
            subprocess.run(["osascript", "-e", script], timeout=5)
            return f"Window resized to {width}x{height}."
        except Exception:
            return "I couldn't resize the window."

    # ─── Response Generation ─────────────────────────────────────────────

    async def _generate_response(self, user_input: str, *, direct_answer: bool = False) -> str:
        """Generate a response via the LLM (with rule-based fallback).

        ``direct_answer=True`` appends a hard instruction to the prompt: small
        local models default to generic offers of help ("How can I help you?")
        instead of answering — one retry with this nudge gets a real answer
        without extra cost."""
        # Try LLM first
        if self._llm:
            try:
                context = self._get_context(user_input)
                # Get long-term memory context
                ltm_context = ""
                if self._long_term_memory:
                    ltm_context = self._long_term_memory.get_context_for_query(user_input)

                # Get Obsidian context
                obsidian_context = ""
                if self._obsidian:
                    obsidian_context = self._obsidian.get_context_for_query(user_input)

                full_context = context
                if ltm_context:
                    full_context += f"\n\nLong-term memory:\n{ltm_context}"
                if obsidian_context:
                    full_context += f"\n\nPersistent knowledge from Obsidian:\n{obsidian_context}"

                # Freebuff Brain context — the persistent memory that lets a
                # freshly-swapped model understand the user immediately.
                if self._brain:
                    try:
                        brain_ctx = self._brain.get_brain_context()
                        if brain_ctx:
                            full_context += f"\n\nBRAIN CONTEXT (persistent memory):\n{brain_ctx}"
                    except Exception as exc:
                        logger.debug("Brain context failed: %s", exc)

                prompt = user_input
                if direct_answer:
                    prompt = (
                        f"{user_input}\n\n"
                        "Instruction: answer the question DIRECTLY and concisely. "
                        "Do not greet, do not offer help, do not ask what the user needs. "
                        "If you do not know the answer, say so and offer to search."
                    )
                response = await self._llm.generate(prompt, context=full_context)
                if response and not response.startswith("[") and not response.startswith("All LLM"):
                    return response
            except Exception as exc:
                logger.warning("LLM generation failed: %s", exc)

        # Fallback to rule-based
        return self._rule_based_response(user_input)

    def _rule_based_response(self, user_input: str) -> str:
        lower = user_input.lower().strip()
        lang = detect_language(user_input)

        # Context Conversation: anaphoric follow-up ("А какая самая важная?") —
        # answer with a reference to the topic, not a generic fallback.
        followup = self._followup_response(user_input)
        if followup:
            return followup

        # Delegate known intents (greetings, remember, search, email, calendar,
        # open-app, ...) to the Personality Layer — the single source of
        # natural confirmations. Only when it has a concrete answer (not its
        # generic classified fallback) do we use it; otherwise the intent
        # branches below / final fallback decide.
        # NB: identity/how-are-you questions are answered below with richer
        # detail (version, uptime), so they are excluded from the delegation.
        cc = contextual_confirmation(user_input, language=lang)
        _CC_GENERIC_MARKERS = (
            "Сделано. Если нужно", "Done that. I can add",
        )
        if cc and not cc.startswith(_CC_GENERIC_MARKERS):
            if not re.search(
                r"\b(who are you|what are you|кто ты|ты кто|что ты|что ты такое|"
                r"how are you|как дела|как ты|как твои дела)\b",
                lower,
            ):
                return cc

        if any(w in lower for w in ["who are you", "кто ты", "ты кто", "что ты", "что ты такое"]):
            if lang == "ru":
                return (
                    f"Я — FOL (Friendly Obedient Listener), версия {self.version}. "
                    f"Вдохновлён JARVIS, работаю на вашем {platform.machine()}. "
                    f"Рад помочь."
                )
            return (
                f"I am FOL (Friendly Obedient Listener), version {self.version}. "
                f"Originally inspired by JARVIS, now running on your {platform.machine()}. "
                f"Happy to help."
            )

        if any(w in lower for w in ["how are you", "как дела", "как ты"]):
            uptime = self._format_uptime()
            if lang == "ru":
                return (
                    f"Все системы работают нормально. "
                    f"Время работы: {uptime}. "
                    f"Обработано {len(self._conversation_history)} взаимодействий. "
                    f"Чем могу помочь?"
                )
            return (
                f"All systems functioning normally. "
                f"Uptime: {uptime}. "
                f"I've processed {len(self._conversation_history)} interactions. "
                f"How may I assist you?"
            )

        if any(w in lower for w in ["thank", "спасибо"]):
            if lang == "ru":
                return "Всегда пожалуйста. Это моя работа."
            return "You're welcome. It's what I'm here for."

        if any(w in lower for w in ["joke", "шутка", "расскажи шутку"]):
            jokes = [
                "Why do programmers prefer dark mode? Because light attracts bugs!",
                "There are only 10 types of people: those who understand binary and those who don't.",
                "A SQL query walks into a bar, sees two tables, and asks: 'Can I join you?'",
                "Why was the JavaScript developer sad? Because he didn't Node how to Express himself!",
            ]
            return random.choice(jokes)

        if any(w in lower for w in ["name", "зовут", "имя"]):
            name = self._preferences.get("name")
            if lang == "ru":
                return f"Твоё имя — {name}. Я его не забываю." if name else "Я пока не знаю твоего имени. Как тебя называть?"
            return f"Your name is {name}. I never forget." if name else "I don't know your name yet. What should I call you?"

        # Natural fallback — never expose LLM configuration internals to the
        # user. Describe what FOL CAN do instead of what is not configured.
        if lang == "ru":
            return (
                f"Интересный вопрос! Сейчас я могу помочь с приложениями, "
                "поиском, памятью и экраном — а по этой теме лучше всего "
                "ответит подключённая модель. Что именно вас интересует?"
            )
        return (
            f"Great question! Right now I can help with apps, search, memory "
            "and the screen — a connected model would go deeper on this. "
            "What exactly would you like to know?"
        )

    # ─── Context Conversation (Stage 1) ─────────────────────────────────

    # Words that never define a conversation topic (commands, fillers,
    # pronouns, follow-up words). Used by _extract_topic().
    _TOPIC_STOPWORDS = frozenset({
        # Command verbs RU
        "открой", "откройте", "запусти", "запустите", "найди", "найти", "поищи",
        "напиши", "создай", "покажи", "запомни", "сохрани", "скажи", "расскажи",
        "сделай", "удали", "перейди", "прочитай", "включи", "выключи", "набери",
        # Command verbs EN
        "open", "launch", "search", "find", "write", "create", "show",
        "remember", "save", "tell", "say", "make", "start", "run", "play",
        "read", "delete", "open", "help", "set", "get", "list", "check",
        # Fillers / prepositions / pronouns RU
        "что", "как", "какой", "какая", "какие", "какое", "какую", "каких",
        "чем", "это", "этот", "эта", "эти", "этой", "этих", "этому", "такой",
        "такая", "такие", "про", "об", "о", "в", "на", "для", "по", "с",
        "у", "к", "и", "а", "то", "же", "мне", "меня", "мой", "моя",
        "мои", "моего", "завтра", "сегодня", "нужно", "надо", "хочешь",
        "можешь", "пожалуйста", "спасибо", "привет", "потом", "сейчас",
        "давай", "будем", "будет", "все", "еще", "ещё", "только", "очень",
        # Fillers EN
        "the", "a", "an", "and", "or", "but", "for", "to", "of", "in",
        "on", "at", "with", "my", "your", "our", "their", "me", "you",
        "please", "thank", "thanks", "hello", "hi", "now", "then", "just",
        "very", "will", "want", "need", "can", "could", "please", "about",
        "today", "tomorrow", "this", "that", "these", "those", "what", "how",
        # Follow-up / anaphora words — the topic must NOT become "самая важная"
        "самая", "самое", "самый", "самые", "важная", "важный", "важное",
        "важные", "наиболее", "более", "подробнее", "дальше", "продолжай",
        "продолжи", "следующая", "следующий", "следующие", "остальные",
        "других", "другие", "них", "ним", "ней", "нее", "ему", "его", "ее",
        "её", "it", "them", "they", "their", "which", "one", "most", "more",
        "important", "next", "others", "another", "подробней", "расскажи",
    })

    def _extract_topic(self, user_input: str) -> str:
        """Extract a short topic label from user input for follow-up resolution.

        ``"Найди новости про OpenAI"`` → ``"OpenAI"``
        ``"Открой Safari"``          → ``"Safari"``
        ``"А какая самая важная?"``   → ``""`` (all stopwords — topic kept)
        """
        if not user_input or not user_input.strip():
            return ""
        words = re.findall(r"[A-Za-zА-Яа-яЁё]{3,}", user_input)
        significant = [w for w in words if w.lower() not in self._TOPIC_STOPWORDS]
        if not significant:
            return ""
        # Prefer proper nouns (capitalized); otherwise use the tail of the phrase.
        entities = [w for w in significant if w[0].isupper()]
        candidates = entities or significant
        return " ".join(candidates[-3:])

    def _update_topic(self, user_input: str) -> None:
        """Remember the conversation topic so follow-ups can reference it."""
        topic = self._extract_topic(user_input)
        if topic:
            self._topic = topic

    def _followup_response(self, user_input: str) -> str | None:
        """Context Conversation for the rule-based fallback (no LLM).

        Detects anaphoric follow-ups ("А какая самая важная?", "which one?")
        and answers with a reference to the current topic instead of a
        generic "Принято". Returns ``None`` when the input is not a follow-up
        or there is no topic to reference.
        """
        lower = user_input.lower().strip()
        lang = detect_language(user_input)
        followup_markers = (
            "а какая", "а что", "какой из", "какая из", "какие из", "что из",
            "самая важная", "самое важное", "самый важный", "подробнее",
            "подробней", "продолжай", "продолжи", "и что дальше", "а дальше",
            "расскажи подробнее", "what about", "which one", "which of",
            "tell me more", "go on", "what's next", "what is next",
            "the most important", "and then", "and now what",
        )
        if not any(marker in lower for marker in followup_markers):
            return None
        # Guard: a true anaphora carries NO new significant content. If the
        # message introduces a new noun/entity ("А что ты думаешь о погоде?",
        # "расскажи подробнее о Python"), it's a NEW question — let the
        # normal pipeline answer it instead of replying about the old topic.
        if self._extract_topic(user_input):
            return None
        topic = self._topic
        if not topic:
            return None
        if lang == "ru":
            return (
                f"Говоря о «{topic}»: могу открыть свежие результаты, сохранить "
                "это в память или копнуть глубже. Что предпочитаете?"
            )
        return (
            f"About «{topic}»: I can open fresh results, save it to memory, "
            "or dig deeper. Which would you like?"
        )

    def _get_context(self, user_input: str = "") -> str:
        recent = self._conversation_history[-6:]
        sections = []
        # Follow-up grounding (Context Conversation): when the current message
        # continues the previous topic ("А какая из них самая важная?"), inject
        # the extracted entity/topic block FIRST so even small models resolve
        # pronouns correctly.
        if user_input and self.context_manager.is_follow_up(user_input):
            follow_up_block = self.context_manager.get_follow_up_context(n=6)
            if follow_up_block:
                sections.append(follow_up_block)
        if recent:
            lines = [
                "Reply in the user's language. Resolve pronouns and implicit "
                "references (like 'а какая самая важная?' or 'which one?') using "
                "the conversation below.",
            ]
            for turn in recent:
                lines.append(f"User: {turn['user']}")
                lines.append(f"FOL: {turn['assistant']}")
            if self._topic:
                lines.append(f"Conversation topic: {self._topic}")
            sections.append("\n".join(lines))
        # The active mode shapes how FOL answers (Focus = terse, Agent = steps).
        # Always included — even a fresh session must know the current mode.
        mode_hint = self._MODE_CONTEXT_HINTS.get(self._mode)
        if mode_hint:
            sections.append(mode_hint)
        return "\n\n".join(sections)

    # ─── Auto-Save to Obsidian ───────────────────────────────────────────

    def _auto_save_to_obsidian(self, user_input: str, response: str) -> None:
        """Analyze conversation and auto-save important things to Obsidian."""
        if not self._obsidian:
            return

        lower = user_input.lower()

        # 1. User's name — save to People/
        name_patterns = [
            r"(?:my name is|i'm|i am|меня зовут|я)\s+([A-Za-zА-Яа-яёЁ]{2,20})",
        ]
        for pattern in name_patterns:
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                name = match.group(1).capitalize()
                self._preferences["name"] = name
                self._obsidian.store(
                    f"User's name is {name}",
                    category="People",
                    title=f"User Name — {name}",
                    tags=["name", "identity"],
                )
                if self._brain:
                    try:
                        self._brain.set_user_info("name", name)
                    except Exception as exc:
                        logger.debug("Brain name save failed: %s", exc)
                return

        # 2. Preferences (likes/dislikes) — save to Preferences/
        pref_patterns = [
            r"(?:i prefer|i like|i love|i enjoy|i hate|i don't like|я люблю|я ненавижу|мне нравится|мне не нравится)\s+(.+?)(?:\.|,|$)",
        ]
        for pattern in pref_patterns:
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                pref = match.group(1).strip()
                is_negative = any(w in lower for w in ["hate", "don't like", "ненавижу", "не нравится"])
                sentiment = "dislikes" if is_negative else "likes"
                self._obsidian.store(
                    f"User {sentiment}: {pref}",
                    category="Preferences",
                    title=f"{sentiment.title()} — {pref[:50]}",
                    tags=["preference", sentiment],
                )
                if self._brain:
                    try:
                        self._brain.set_preference(sentiment, pref)
                    except Exception as exc:
                        logger.debug("Brain pref save failed: %s", exc)
                return

        # 3. Job/role/profession — save to People/
        job_patterns = [
            r"(?:i work as|i'm a|i am a|я работаю|я являюсь)\s+(.+?)(?:\.|,|$)",
            r"(?:i'm working on|i am working on|я работаю над)\s+(.+?)(?:\.|,|$)",
        ]
        for pattern in job_patterns:
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                job = match.group(1).strip()
                self._obsidian.store(
                    f"User's work/role: {job}",
                    category="People",
                    title=f"User Role — {job[:50]}",
                    tags=["role", "work"],
                )
                if self._brain:
                    try:
                        self._brain.set_user_info("role", job)
                    except Exception as exc:
                        logger.debug("Brain role save failed: %s", exc)
                return

        # 4. Important facts — save to Knowledge/
        fact_indicators = [
            "remember that", "don't forget", "keep in mind", "important",
            "запомни что", "не забудь", "важно",
        ]
        if any(ind in lower for ind in fact_indicators):
            self._obsidian.store(
                user_input,
                category="Knowledge",
                title=f"Important — {user_input[:50]}",
                tags=["important", "user-stated"],
            )
            return

        # 5. Projects/goals — save to Projects/
        project_patterns = [
            r"(?:i'm building|i'm creating|i'm working on|working on|building|creating|разрабатываю|создаю|работаю над)\s+(.+?)(?:\.|,|$)",
        ]
        for pattern in project_patterns:
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                project = match.group(1).strip()
                self._obsidian.store(
                    f"Project: {project}",
                    category="Projects",
                    title=f"Project — {project[:50]}",
                    tags=["project"],
                )
                if self._brain:
                    try:
                        self._brain.record_project(project)
                    except Exception as exc:
                        logger.debug("Brain project save failed: %s", exc)
                return

        # 6. Schedule/time references — save to Knowledge/
        schedule_patterns = [
            r"(?:i have|у меня)\s+(?:a\s+)?(?:meeting|appointment|deadline|совещание|встреча|дедлайн)\s+(.+?)(?:\.|,|$)",
        ]
        for pattern in schedule_patterns:
            match = re.search(pattern, user_input, re.IGNORECASE)
            if match:
                event = match.group(1).strip()
                now = datetime.now()
                self._obsidian.store(
                    f"Scheduled: {event}\nDate: {now.strftime('%Y-%m-%d')}",
                    category="Knowledge",
                    title=f"Schedule — {event[:50]}",
                    tags=["schedule", "event"],
                )
                return

        # 7. Episodic — save significant interactions
        significance_words = [
            "first time", "first day", "just started", "new project",
            "впервые", "первый раз", "начал", "новый проект",
        ]
        if any(w in lower for w in significance_words):
            now = datetime.now()
            self._obsidian.store_episode(
                event=user_input,
                context=f"FOL response: {response[:200]}",
                importance=0.7,
            )

    # ─── Memory & Preferences ────────────────────────────────────────────

    def _remember(self, text: str, lang: str | None = None) -> str:
        """Short-term remember — bilingual, natural (personality layer).

        ``lang`` comes from the dispatcher (detected on the FULL user input)
        so an empty ``text`` ("запомни" alone) still answers in the user's
        language instead of defaulting to English.
        """
        lang = lang or detect_language(text)
        if not text:
            return ("Что запомнить?" if lang == "ru"
                    else "What would you like me to remember?")
        self._memories.append({"content": text, "category": "user_request", "importance": 0.8})
        return (f"Запомнил: {text}" if lang == "ru"
                else f"Got it — I'll remember: {text}")

    def _recall(self, lang: str = "en") -> str:
        """Recall short-term memories — bilingual, natural."""
        if not self._memories:
            return ("Пока ничего не запоминал. Скажите, что сохранить." if lang == "ru"
                    else "I haven't saved anything yet. Tell me what to remember.")
        recent = self._memories[-10:]
        lines = [f"  {i+1}. [{m['category']}] {m['content']}" for i, m in enumerate(recent)]
        return ("Вот что я помню:\n" if lang == "ru" else "Here's what I remember:\n") + "\n".join(lines)

    def _show_notes(self, lang: str = "en") -> str:
        """Show saved notes — bilingual, natural."""
        notes = [m for m in self._memories if m.get("category") == "user_request"]
        if not notes:
            return ("Заметок пока нет." if lang == "ru" else "No notes saved yet.")
        prefix = ("Сохранённые заметки:\n" if lang == "ru" else "Saved notes:\n")
        return prefix + "\n".join(f"  {i+1}. {n['content']}" for i, n in enumerate(notes[-20:]))

    def _set_preference(self, text: str) -> str:
        """Set a preference — never expose raw exceptions to the user."""
        lang = detect_language(text)
        try:
            parts = text.split("=", 1)
            if len(parts) != 2:
                return ("Формат: set <ключ> = <значение>" if lang == "ru"
                        else "Usage: set <key> = <value>")
            key = parts[0].replace("set ", "").strip()
            value = parts[1].strip()
            self._preferences[key] = value
            return (f"Настройка сохранена: {key} = {value}" if lang == "ru"
                    else f"Preference set: {key} = {value}")
        except Exception:
            return ("Не получилось сохранить настройку. Попробуйте формат: set ключ = значение"
                    if lang == "ru" else "Couldn't save that preference. Try: set key = value")

    def _get_preference(self, text: str) -> str:
        """Get a preference — bilingual."""
        lang = detect_language(text)
        key = text.replace("get ", "").strip()
        value = self._preferences.get(key)
        if value is None:
            return (f"Настройка '{key}' не найдена." if lang == "ru"
                    else f"Preference '{key}' not found.")
        return f"{key} = {value}"

    def _clear_history(self, lang: str = "en") -> str:
        """Clear conversation history — bilingual."""
        self._conversation_history.clear()
        self._topic = ""
        # Mirror into the core ContextManager so follow-up detection starts fresh.
        self.context_manager.clear_history()
        return ("История разговора очищена." if lang == "ru"
                else "Conversation history cleared.")

    # ─── Utilities ───────────────────────────────────────────────────────

    def _sanitize_input(self, text: str) -> str:
        text = text.replace("\x00", "").strip()
        return text[:10000] if len(text) > 10000 else text

    def _format_uptime(self) -> str:
        seconds = int(time.time() - self.start_time)
        h, m, s = seconds // 3600, (seconds % 3600) // 60, seconds % 60
        if h > 0:
            return f"{h}h {m}m {s}s"
        elif m > 0:
            return f"{m}m {s}s"
        return f"{s}s"


def fol_banner() -> str:
    return r"""
   ______ _____  _      _____
  |  ____|  __ \| |    |  __ \
  | |__  | |__) | |    | |  | | __ _ _ __   __ _ _ __ ___
  |  __| |  ___/| |    | |  | |/ _` | '_ \ / _` | '_ ` _ \
  | |    | |    | |____| |__| | (_| | | | | (_| | | | | | |
  |_|    |_|    |______|_____/ \__,_|_| |_|\__, |_| |_| |_|
                                           __/ |
                                          |___/

FOL v2.0 — Friendly Obedient Listener
Personal AI Assistant with JARVIS-level capabilities
"""


async def run_fol(args: argparse.Namespace) -> int:
    setup_logging(level="DEBUG" if args.debug else "INFO")

    if args.command == "start":
        print(fol_banner())
        fol = FOL()
        await fol.start()

        # Voice mode — continuous voice conversation
        if args.voice:
            if not fol._voice or not fol._voice.stt.is_available:
                print("Voice input not available. Install: pip install SpeechRecognition sounddevice")
                print("Falling back to text mode.\n")
            else:
                print("Entering voice mode. Say 'stop' to exit.\n")
                try:
                    await fol._voice.voice_mode(process_fn=fol.process)
                except KeyboardInterrupt:
                    pass
                finally:
                    await fol.stop()
                return 0

        # Text interactive mode
        if args.interactive:
            print("FOL interactive shell. Type 'help' or 'exit'.\n")
            try:
                while True:
                    try:
                        text = input("FOL > ").strip()
                    except (EOFError, KeyboardInterrupt):
                        print()
                        break
                    if not text:
                        continue
                    if text.lower() in ("exit", "quit"):
                        print("Goodbye.")
                        break

                    response = await fol.process(text)

                    if response == "__VOICE_MODE__":
                        print("Entering voice mode. Say 'stop' to exit.\n")
                        if fol._voice and fol._voice.stt.is_available:
                            await fol._voice.voice_mode(process_fn=fol.process)
                        else:
                            print("Voice input not available.")
                        print("Back to text mode.\n")
                        continue

                    if response == "__SHUTDOWN__":
                        print("Shutting down, sir.")
                        break

                    print(response)

                    # Auto-speak responses when voice is enabled
                    if fol._tts_enabled and fol._voice and fol._voice.tts.is_available:
                        await fol._voice.say(response)
            finally:
                await fol.stop()
        else:
            print("FOL is running. Press Ctrl+C to stop.")
            await fol.lifecycle.wait_for_shutdown()
            await fol.stop()

        return 0

    elif args.command == "send":
        fol = FOL()
        await fol.start()
        command = " ".join(args.text).strip()
        if command:
            response = await fol.process(command)
            print(response)
            # Speak if voice enabled
            if fol._voice and fol._voice.tts.is_available:
                await fol._voice.say(response)
        await fol.stop()
        return 0

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="FOL — Personal AI Assistant")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    subparsers = parser.add_subparsers(dest="command")

    start_parser = subparsers.add_parser("start", help="Start FOL")
    start_parser.add_argument("--interactive", "-i", action="store_true", help="Interactive shell mode")
    start_parser.add_argument("--voice", "-v", action="store_true", help="Voice conversation mode")

    send_parser = subparsers.add_parser("send", help="Send a single command")
    send_parser.add_argument("text", nargs=argparse.REMAINDER, help="Command text")

    subparsers.add_parser("status", help="Show FOL status")

    args = parser.parse_args()

    if args.command is None:
        args.command = "start"
        args.interactive = True
        args.debug = False

    if args.command == "status":
        print(f"FOL v2.0.0 — {'running' if START_TIME else 'not running'}")
        return 0

    return asyncio.run(run_fol(args))


if __name__ == "__main__":
    raise SystemExit(main())
