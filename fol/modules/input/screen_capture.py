"""Screen capture module — take screenshots."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from config.constants import FOL_DIR

logger = logging.getLogger(__name__)

SCREENSHOT_PATH = FOL_DIR / "screen.png"


class ScreenCapture:
    """Captures screenshots from macOS screen."""

    name = "screen_capture"

    async def capture(self) -> Path | None:
        """Take a screenshot and save to ~/.fol/screen.png."""
        SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(
                ["screencapture", "-x", str(SCREENSHOT_PATH)],
                check=True,
                timeout=5,
            )
            logger.info("Screenshot captured", path=str(SCREENSHOT_PATH))
            return SCREENSHOT_PATH
        except Exception as exc:
            logger.error("Screen capture failed", error=str(exc))
            return None

    def is_available(self) -> bool:
        """Check if screenshot file exists."""
        return SCREENSHOT_PATH.exists()
