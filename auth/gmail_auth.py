"""Wraps an OAuth access token into a google.oauth2.credentials.Credentials object for Gmail API use."""

import logging
from pathlib import Path
from typing import Any

from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)


def get_gmail_credentials_from_token(access_token: str) -> Credentials:
    """Build Gmail API Credentials from a raw Google access token.

    Used with the Auth0 web auth flow, where the browser provides
    a standalone access token (no refresh token or client secrets needed).
    """
    return Credentials(token=access_token)


def get_gmail_credentials() -> Credentials:
    """Legacy OAuth flow: load credentials from the cached token file.

    Reads the token saved by run_auth_server() from
    ~/.secondself/google_token.json and returns Credentials.
    Falls back to raising a RuntimeError if no cached token is found.
    """
    token_path = Path.home() / ".secondself" / "google_token.json"
    if token_path.exists():
        import json
        try:
            data = json.loads(token_path.read_text(encoding="utf-8"))
            access_token = data.get("access_token", "")
            if access_token:
                logger.info("Loaded cached token from %s", token_path)
                return Credentials(token=access_token)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read cached token: %s", exc)

    raise RuntimeError(
        "No Google OAuth token found. Run the web auth flow first "
        "via auth.web_oauth.run_auth_server() or pass an access_token."
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("gmail_auth: use get_gmail_credentials_from_token(token) with an Auth0-provided token")
