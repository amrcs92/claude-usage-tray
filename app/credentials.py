"""Read-only access to the login Claude Code saved on this machine.

The token is kept in memory only: never logged, never written, never refreshed.
Refreshing stays Claude Code's job, because rotating the refresh token here
could log Claude Code out.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


class CredentialsError(Exception):
    """Base class; str(e) is safe to show in the UI."""


class CredentialsMissing(CredentialsError):
    pass


class CredentialsExpired(CredentialsError):
    pass


@dataclass(frozen=True)
class Credentials:
    access_token: str
    expires_at_ms: int | None
    subscription_type: str | None

    def __repr__(self) -> str:  # keep the token out of any accidental log
        return f"Credentials(subscription_type={self.subscription_type!r}, expires_at_ms={self.expires_at_ms})"


def config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".claude"


def credentials_path() -> Path:
    return config_dir() / ".credentials.json"


def load(path: Path | None = None, now_ms: int | None = None) -> Credentials:
    """Read the credentials file fresh. Raises CredentialsError subclasses."""
    path = path or credentials_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CredentialsMissing("Claude Code login not found. Run `claude` and log in.") from None
    except (OSError, ValueError):
        raise CredentialsMissing("Could not read the Claude Code login file.") from None

    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    token = oauth.get("accessToken") if isinstance(oauth, dict) else None
    if not token:
        raise CredentialsMissing("Claude Code is not logged in with a Claude account. Run `claude` and log in.")

    expires_at = oauth.get("expiresAt")
    expires_at = int(expires_at) if isinstance(expires_at, (int, float)) else None
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    if expires_at is not None and expires_at <= now_ms:
        raise CredentialsExpired("Login expired. Run any `claude` command to refresh your login.")

    return Credentials(token, expires_at, oauth.get("subscriptionType"))
