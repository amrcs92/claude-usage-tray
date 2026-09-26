"""Calls the (undocumented) usage endpoint and parses it into a UsageSnapshot.

All knowledge of the response shape lives in this module, so an API change
only needs fixing here. Parsing is defensive: null or unknown keys are skipped.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from app.model import BreakdownRow, Limit, UsageSnapshot

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
USAGE_PAGE_URL = "https://claude.ai/settings/usage"
USER_AGENT = "claude-usage-tray/0.1"


class UsageError(Exception):
    """Base class; str(e) is safe to show in the UI."""


class AuthError(UsageError):
    """401/403: the token is expired or revoked."""


class TransientError(UsageError):
    """429/5xx or network failure: retry with backoff."""

    def __init__(self, message: str, offline: bool = False):
        super().__init__(message)
        self.offline = offline


def fetch(access_token: str, timeout: float = 15.0) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "anthropic-beta": "oauth-2025-04-20",
        "User-Agent": USER_AGENT,
    }
    try:
        r = httpx.get(USAGE_URL, headers=headers, timeout=timeout)
    except httpx.TransportError:
        raise TransientError("Offline — can't reach Anthropic.", offline=True) from None

    if r.status_code in (401, 403):
        raise AuthError("Login expired. Run any `claude` command to refresh your login.")
    if r.status_code == 429:
        raise TransientError("Rate limited — backing off.")
    if r.status_code >= 500:
        raise TransientError(f"Anthropic API error ({r.status_code}).")
    if r.status_code != 200:
        raise UsageError(f"Unexpected response ({r.status_code}).")
    try:
        data = r.json()
    except ValueError:
        raise UsageError("Unexpected response from the usage endpoint.") from None
    if not isinstance(data, dict):
        raise UsageError("Unexpected response from the usage endpoint.")
    return data


# --- parsing -----------------------------------------------------------------

_LABELS = {
    "session": "Session",
    "weekly_all": "Weekly · all models",
    "weekly_opus": "Weekly · Opus",
    "weekly_sonnet": "Weekly · Sonnet",
    "weekly_oauth_apps": "Weekly · OAuth apps",
    "weekly_cowork": "Weekly · Cowork",
}


def _label(key: str) -> str:
    if key in _LABELS:
        return _LABELS[key]
    if key.startswith("weekly_"):
        return "Weekly · " + key[len("weekly_"):].replace("_", " ").title()
    return key.replace("_", " ").title()


def _dt(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value)))


def _from_legacy_keys(data: dict[str, Any]) -> dict[str, Limit]:
    """`five_hour`, `seven_day` and any `seven_day_*` object."""
    out: dict[str, Limit] = {}
    for raw_key, value in data.items():
        if raw_key == "five_hour":
            key, group = "session", "session"
        elif raw_key == "seven_day":
            key, group = "weekly_all", "weekly"
        elif raw_key.startswith("seven_day_") and raw_key != "seven_day_breakdown":
            key, group = "weekly_" + raw_key[len("seven_day_"):], "weekly"
        else:
            continue
        if not isinstance(value, dict):
            continue
        pct = _num(value.get("utilization"))
        if pct is None:
            continue
        out[key] = Limit(key, _label(key), group, pct, _dt(value.get("resets_at")))
    return out


def _from_limits_array(data: dict[str, Any]) -> dict[str, Limit]:
    """The newer `limits: [{kind, group, percent, resets_at}]` list."""
    out: dict[str, Limit] = {}
    items = data.get("limits")
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        key = item.get("kind")
        pct = _num(item.get("percent"))
        if not isinstance(key, str) or pct is None:
            continue
        group = item.get("group")
        if group not in ("session", "weekly"):
            group = "session" if key == "session" else "weekly"
        out[key] = Limit(key, _label(key), group, pct, _dt(item.get("resets_at")))
    return out


def _breakdown(data: dict[str, Any]) -> list[BreakdownRow]:
    block = data.get("seven_day_breakdown")
    rows = block.get("rows") if isinstance(block, dict) else None
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        pct = _num(row.get("percent"))
        name = row.get("display_name") or row.get("key")
        if pct is not None and isinstance(name, str):
            out.append(BreakdownRow(name, pct))
    return out


def parse(data: dict[str, Any], now: datetime | None = None) -> UsageSnapshot:
    merged = _from_legacy_keys(data)
    merged.update(_from_limits_array(data))  # the newer list wins on overlap

    def order(l: Limit) -> tuple[int, str]:
        return (0 if l.key == "session" else 1 if l.key == "weekly_all" else 2, l.key)

    return UsageSnapshot(
        limits=sorted(merged.values(), key=order),
        fetched_at=now or datetime.now(timezone.utc),
        breakdown=_breakdown(data),
    )
