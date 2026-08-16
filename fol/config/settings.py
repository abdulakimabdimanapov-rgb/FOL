"""FOL configuration via Pydantic Settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Look for .env relative to the fol/ directory (works from any CWD)
_FOL_DIR = Path(__file__).parent.parent
_DOT_ENV_PATH = _FOL_DIR / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_DOT_ENV_PATH) if _DOT_ENV_PATH.exists() else ".env",
        env_file_encoding="utf-8",
        env_prefix="FOL_",
        case_sensitive=False,
        extra="ignore",
    )

    # General
    app_name: str = "FOL"
    debug: bool = False
    log_level: str = "INFO"
    data_dir: Path = Path.home() / ".fol"

    # STT (Speech-to-Text)
    stt_model: str = "medium"
    stt_device: str = "mps"
    stt_language: str = "ru"

    # LLM
    llm_backend: str = "mlx"
    llm_model: str = "mlx-community/Llama-3.2-3B-Instruct-4bit"
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.7

    # OpenAI (optional)
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # OpenRouter (optional) — OpenAI-compatible, free models like Nemotron
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Memory
    memory_vector_db_path: Path = Path.home() / ".fol" / "vector_db"
    memory_max_results: int = 10

    # Obsidian Integration
    obsidian_vault: str = str(Path.home() / "Documents" / "Obsidian Vault" / "FOL-Memory")
    obsidian_enabled: bool = True

    # Shared Brain vault (~/Obsidian/Brain) — общая память ассистентов и FOL.
    # FOL читает Profile/Goals/Models/Conversations из этого vault и дописывает
    # туда свои диалоги, чтобы любой ассистент видел, что делал FOL.
    brain_vault: str = str(Path.home() / "Obsidian" / "Brain")

    # Telegram Integration
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Proactive Mode (ROADMAP Etap 5) — ambient suggestions. OFF by default:
    # FOL must never become an annoying assistant (the toggle is mandatory).
    # Env: FOL_PROACTIVE_ENABLED, FOL_PROACTIVE_INTERVAL_MINUTES, ...
    proactive_enabled: bool = False
    proactive_interval_minutes: int = 30
    proactive_cooldown_minutes: int = 5
    proactive_max_per_hour: int = 3

    # API
    api_host: str = "127.0.0.1"
    api_port: int = 8754


settings = Settings()
