"""Telegram output channel — sends assistant messages via the Bot API.

Uses only the standard library (``urllib``) so no new dependencies are
required. When no ``FOL_TELEGRAM_BOT_TOKEN`` / ``FOL_TELEGRAM_CHAT_ID`` are
configured the channel reports ``is_available = False`` and sending is a
no-op.
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from typing import Any

from modules.output.base import OutputChannel

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramBot(OutputChannel):
    """Sends messages to a Telegram chat via the Bot API."""

    name = "telegram"

    def __init__(self) -> None:
        self._token: str = ""
        self._default_chat_id: str = ""
        self._configured = False

    def configure(self, token: str, chat_id: str) -> None:
        """Set credentials. Called by the app from settings."""
        self._token = (token or "").strip()
        self._default_chat_id = (chat_id or "").strip()
        self._configured = bool(self._token and self._default_chat_id)
        if self._configured:
            logger.info("Telegram bot configured")

    @property
    def is_available(self) -> bool:
        return self._configured

    async def initialize(self) -> None:
        return None

    async def send(self, text: str) -> bool:
        return await self.send_message(self._default_chat_id, text)

    async def send_message(self, chat_id: str, text: str) -> bool:
        """Send a text message to ``chat_id``. Returns True on success."""
        if not self._configured or not chat_id or not text:
            return False
        return await asyncio.to_thread(self._post_send_message, chat_id, text)

    def _post_send_message(self, chat_id: str, text: str) -> bool:
        url = f"{API_BASE}/bot{self._token}/sendMessage"
        body = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            try:
                data = json.loads(resp.read().decode("utf-8"))
            finally:
                resp.close()
            return bool(data.get("ok"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            logger.warning("Telegram send failed: %s", exc)
            return False

    async def shutdown(self) -> None:
        return None


_instance: TelegramBot | None = None


def get_telegram_bot() -> TelegramBot:
    """Return the process-wide Telegram bot singleton (app-compatible)."""
    global _instance
    if _instance is None:
        _instance = TelegramBot()
    return _instance
