"""FOL system constants."""

from __future__ import annotations

from pathlib import Path
from typing import Final

# Paths
FOL_DIR: Final[Path] = Path.home() / ".fol"
DATA_DIR: Final[Path] = FOL_DIR / "data"
LOGS_DIR: Final[Path] = DATA_DIR / "logs"
MODELS_DIR: Final[Path] = DATA_DIR / "models"
VECTOR_DB_DIR: Final[Path] = DATA_DIR / "vector_db"

# Defaults
DEFAULT_MODEL: Final[str] = "mlx-community/Llama-3.2-3B-Instruct-4bit"
DEFAULT_STT_MODEL: Final[str] = "medium"
DEFAULT_MAX_TOKENS: Final[int] = 4096
DEFAULT_TEMPERATURE: Final[float] = 0.7
DEFAULT_API_HOST: Final[str] = "127.0.0.1"
DEFAULT_API_PORT: Final[int] = 8754

# Limits
MAX_CONVERSATION_HISTORY: Final[int] = 32
MAX_AGENT_ITERATIONS: Final[int] = 10
DEFAULT_TIMEOUT_SECONDS: Final[float] = 30.0
MAX_RETRY_COUNT: Final[int] = 3

# Version
VERSION: Final[str] = "0.1.0"
APP_NAME: Final[str] = "FOL"
