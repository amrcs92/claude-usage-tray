"""Synthetic data for `--demo`: screenshots and UI work without a real account."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.model import UsageSnapshot
from app.usage_api import parse

SCENARIOS = ("normal", "high", "expired", "offline")


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def snapshot(scenario: str) -> UsageSnapshot:
    now = datetime.now(timezone.utc)
    session_pct, weekly_pct, opus_pct = (86, 72, 91) if scenario == "high" else (42, 61, 28)
    session_reset = now + timedelta(hours=2, minutes=15 if scenario == "high" else 10)
    weekly_reset = now + timedelta(days=2, hours=9)
    return parse({
        "limits": [
            {"kind": "session", "group": "session", "percent": session_pct, "resets_at": _iso(session_reset)},
            {"kind": "weekly_all", "group": "weekly", "percent": weekly_pct, "resets_at": _iso(weekly_reset)},
            {"kind": "weekly_opus", "group": "weekly", "percent": opus_pct, "resets_at": _iso(weekly_reset)},
        ],
        "seven_day_breakdown": {"rows": [
            {"display_name": "Claude Code", "percent": 68},
            {"display_name": "Chats", "percent": 22},
            {"display_name": "Cowork", "percent": 10},
        ]},
    }, now=now - timedelta(minutes=4 if scenario in ("expired", "offline") else 0))


def status(scenario: str) -> tuple[str, str | None]:
    if scenario == "expired":
        return "expired", "Login expired. Run any `claude` command to refresh your login."
    if scenario == "offline":
        return "offline", "Offline — can't reach Anthropic."
    return "ok", None
