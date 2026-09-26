"""Threshold and reset toasts, one per threshold per reset window.

The dedupe key is `limit + resets_at + threshold`. Sent keys are persisted so
a restart (for example at login) does not repeat a toast.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from app.model import UsageSnapshot
from app.settings import Settings

SendFn = Callable[[str, str], None]


def send_toast(title: str, body: str) -> None:
    def run() -> None:
        try:
            from win11toast import notify
            notify(title, body, app_id="Claude Usage Tray")
        except Exception:
            pass  # notifications are best-effort
    threading.Thread(target=run, daemon=True).start()


class Notifier:
    def __init__(self, send: SendFn = send_toast, state_path: Path | None = None):
        self._send = send
        self._path = state_path
        self._sent: set[str] = self._load()
        self._last_session: tuple[float, str] | None = None

    def _load(self) -> set[str]:
        if not self._path:
            return set()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return set(data) if isinstance(data, list) else set()
        except (OSError, ValueError):
            return set()

    def _save(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Only the newest keys matter; old windows have already reset.
            self._path.write_text(json.dumps(sorted(self._sent)[-200:]), encoding="utf-8")
        except OSError:
            pass

    def check(self, snap: UsageSnapshot, settings: Settings) -> list[str]:
        """Sends any due toasts; returns their titles (handy for tests)."""
        sent: list[str] = []
        thresholds = [t for t, on in ((95, settings.notify_95), (80, settings.notify_80)) if on]

        for limit in snap.limits:
            reset_key = limit.resets_at.isoformat() if limit.resets_at else "none"
            for t in thresholds:  # highest first, so crossing both only toasts 95
                if limit.percent < t:
                    continue
                key = f"{limit.key}|{reset_key}|{t}"
                if key in self._sent:
                    break
                self._sent.add(key)
                # Mark lower thresholds as done too, so they don't fire afterwards.
                for lower in thresholds:
                    if lower < t:
                        self._sent.add(f"{limit.key}|{reset_key}|{lower}")
                title = f"{limit.label} at {limit.percent:.0f}%"
                self._send(title, _reset_hint(limit))
                sent.append(title)
                break

        session = snap.session
        if session is not None:
            current = (session.percent, session.resets_at.isoformat() if session.resets_at else "")
            prev = self._last_session
            if (settings.notify_reset and prev is not None and prev[0] > 0
                    and current[1] != prev[1] and current[0] < prev[0]):
                title = "Session reset"
                self._send(title, f"You're back to {session.percent:.0f}%.")
                sent.append(title)
            self._last_session = current

        if sent:
            self._save()
        return sent


def _reset_hint(limit) -> str:
    if limit.resets_at is None:
        return "Check claude.ai for details."
    local = limit.resets_at.astimezone()
    fmt = "%I:%M %p" if limit.group == "session" else "%a %I:%M %p"
    return "Resets " + local.strftime(fmt).replace(" 0", " ").lstrip("0") + "."
