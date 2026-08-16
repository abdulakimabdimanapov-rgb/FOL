"""Output channels — canonical boundaries for everything FOL speaks through."""

from modules.output.base import AbstractOutputModule, OutputChannel
from modules.output.clipboard_out import ClipboardOutput
from modules.output.display import DisplayModule
from modules.output.notifications import NotificationModule
from modules.output.tts import TTSModule
from modules.output.telegram import TelegramBot, get_telegram_bot

__all__ = [
    "AbstractOutputModule",
    "OutputChannel",
    "ClipboardOutput",
    "DisplayModule",
    "NotificationModule",
    "TTSModule",
    "TelegramBot",
    "get_telegram_bot",
]
