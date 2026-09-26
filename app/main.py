"""Entry point: starts the tray icon, the poller and the (hidden) popup."""
from __future__ import annotations

import argparse
import ctypes
import random
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

if not getattr(sys, "frozen", False):  # allow `python app/main.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webview

from app import autostart, credentials, demo, settings as settings_mod
from app.model import UsageSnapshot, pacing
from app.notifier import Notifier
from app.popup import Api, Popup
from app.tray import Tray, pick_metric, render_icon, tooltip
from app.usage_api import USAGE_PAGE_URL, AuthError, TransientError, UsageError, fetch, parse

MAX_BACKOFF = 15 * 60
MANUAL_REFRESH_THROTTLE = 10


class App:
    def __init__(self, demo_scenario: str | None = None, show_view: str | None = None,
                 pin: bool = False) -> None:
        self.demo = demo_scenario       # synthetic data, nothing persisted
        self.show_view = show_view
        self.settings = settings_mod.Settings() if self.demo else settings_mod.load()
        self.notifier = Notifier(state_path=settings_mod.data_dir() / "notified.json")
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._last_manual = 0.0
        self._failures = 0

        self.snapshot: UsageSnapshot | None = None
        self.status = "loading"          # loading | ok | offline | error | expired
        self.message: str | None = None
        self.plan: str | None = None

        self.popup = Popup(Api({
            "get_state": self.view_state,
            "refresh": self.refresh,
            "save_settings": self.save_settings,
            "usage_page": self.open_usage_page,
            "hide": lambda: None if pin else self.popup.hide(),
        }))
        self.tray = Tray({
            "toggle": lambda: self.popup.toggle(),
            "refresh": self.refresh,
            "toggle_autostart": self.toggle_autostart,
            "settings": lambda: self.popup.show("settings"),
            "usage_page": self.open_usage_page,
            "quit": self.quit,
        }, autostart_checked=autostart.is_enabled)

    # --- polling -------------------------------------------------------------

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            delay = self._poll_once()
            self._wake.wait(delay + random.uniform(-5, 5))
            self._wake.clear()

    def _poll_once(self) -> float:
        interval = self.settings.poll_seconds
        if self.demo:
            with self._lock:
                self.plan, self.snapshot = "max", demo.snapshot(self.demo)
            self._set(*demo.status(self.demo))
            return interval
        try:
            creds = credentials.load()
            self.plan = creds.subscription_type
            snap = parse(fetch(creds.access_token))
        except (credentials.CredentialsError, AuthError) as e:
            self._set("expired", str(e))
            return interval
        except TransientError as e:
            self._failures += 1
            self._set("offline" if e.offline else "error", str(e))
            return min(60 * 2 ** (self._failures - 1), MAX_BACKOFF)
        except UsageError as e:
            self._set("error", str(e))
            return interval
        except Exception as e:  # never let the poller die
            self._set("error", f"Unexpected error: {type(e).__name__}")
            return interval

        self._failures = 0
        with self._lock:
            self.snapshot = snap
        self._set("ok", None)
        self.notifier.check(snap, self.settings)
        return interval

    def _set(self, status: str, message: str | None) -> None:
        with self._lock:
            self.status, self.message = status, message
        self._publish()

    def _publish(self) -> None:
        with self._lock:
            snap, status, message = self.snapshot, self.status, self.message
        limit = pick_metric(snap, self.settings.tray_metric) if snap else None
        if status == "ok" and limit:
            image = render_icon(limit.percent, "ok")
        else:
            image = render_icon(None, "expired" if status == "expired" else
                                "loading" if status == "loading" else "offline")
        status_text = None if status == "ok" else (message or "Loading…")
        self.tray.update(image, tooltip(snap, status_text))
        self.popup.push(self.view_state())

    # --- actions -------------------------------------------------------------

    def refresh(self) -> None:
        now = time.monotonic()
        if now - self._last_manual < MANUAL_REFRESH_THROTTLE:
            return
        self._last_manual = now
        self._wake.set()

    def save_settings(self, values: dict) -> dict:
        merged = {**self.settings.to_dict(), **(values or {})}
        new = settings_mod.Settings.from_dict(merged)
        poll_changed = new.poll_seconds != self.settings.poll_seconds
        self.settings = new
        if self.demo:
            self._publish()
            return self.view_state()
        settings_mod.save(new)
        try:
            if new.start_with_windows != autostart.is_enabled():
                autostart.set_enabled(new.start_with_windows)
        except OSError:
            pass
        if poll_changed:
            self._wake.set()
        self._publish()
        return self.view_state()

    def toggle_autostart(self) -> None:
        self.save_settings({"start_with_windows": not autostart.is_enabled()})

    def open_usage_page(self) -> None:
        webbrowser.open(USAGE_PAGE_URL)

    def quit(self) -> None:
        self._stop.set()
        self._wake.set()
        self.tray.stop()
        self.popup.destroy()

    # --- view model for the popup -------------------------------------------

    def view_state(self) -> dict:
        with self._lock:
            snap, status, message = self.snapshot, self.status, self.message
        now = datetime.now(timezone.utc)
        limits = []
        if snap:
            for l in snap.limits:
                pace = pacing(l, now)
                limits.append({
                    "key": l.key,
                    "label": l.label,
                    "group": l.group,
                    "percent": l.percent,
                    "resets_at": l.resets_at.isoformat() if l.resets_at else None,
                    "pace": {"ahead": pace.ahead, "text": pace.text} if pace else None,
                })
        s = self.settings.to_dict()
        if not self.demo:
            s["start_with_windows"] = _safe(autostart.is_enabled, s["start_with_windows"])
        return {
            "status": status,
            "message": message,
            "plan": self.plan,
            "updated_at": snap.fetched_at.isoformat() if snap else None,
            "limits": limits,
            "breakdown": [{"label": b.label, "percent": b.percent} for b in snap.breakdown] if snap else [],
            "settings": s,
        }

    # --- lifecycle -----------------------------------------------------------

    def _started(self) -> None:
        threading.Thread(target=self.tray.icon.run, daemon=True).start()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        if self.show_view:
            time.sleep(1)
            self.popup.show(self.show_view)


def _safe(fn, default):
    try:
        return fn()
    except OSError:
        return default


def _single_instance() -> bool:
    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\ClaudeUsageTray.SingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main() -> None:
    parser = argparse.ArgumentParser(description="Claude plan usage in the Windows tray.")
    parser.add_argument("--show", nargs="?", const="dashboard", choices=("dashboard", "settings"),
                        help="open the popup at launch")
    parser.add_argument("--demo", nargs="?", const="normal", choices=demo.SCENARIOS,
                        help="use synthetic data instead of your account (no network)")
    parser.add_argument("--pin", action="store_true",
                        help="keep the popup open when it loses focus (screenshots, UI work)")
    args = parser.parse_args()
    if not _single_instance():
        return
    app = App(demo_scenario=args.demo, show_view=args.show, pin=args.pin)
    webview.start(app._started, gui="edgechromium")


if __name__ == "__main__":
    main()
