"""The frameless pywebview popup that sits above the tray."""
from __future__ import annotations

import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

import webview

WIDTH, HEIGHT, MARGIN = 380, 580, 12


def ui_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "ui"


def _work_area_logical() -> tuple[float, float, float, float]:
    rect = wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    try:
        scale = ctypes.windll.user32.GetDpiForSystem() / 96
    except AttributeError:
        scale = 1.0
    return rect.left / scale, rect.top / scale, rect.right / scale, rect.bottom / scale


class Api:
    """Methods callable from JS as `pywebview.api.<name>()`.

    Attributes are underscore-prefixed so pywebview doesn't expose them.
    """

    def __init__(self, handlers: dict[str, Callable[..., Any]]):
        self._h = handlers

    def get_state(self) -> dict:
        return self._h["get_state"]()

    def refresh(self) -> None:
        self._h["refresh"]()

    def save_settings(self, values: dict) -> dict:
        return self._h["save_settings"](values)

    def open_usage_page(self) -> None:
        self._h["usage_page"]()

    def hide(self) -> None:
        self._h["hide"]()


class Popup:
    def __init__(self, api: Api):
        self._visible = False
        self._hidden_at = 0.0
        self._loaded = False
        self.window = webview.create_window(
            "Claude Usage",
            url=str(ui_dir() / "index.html"),
            js_api=api,
            width=WIDTH,
            height=HEIGHT,
            hidden=True,
            frameless=True,
            easy_drag=False,
            resizable=False,
            on_top=True,
            background_color="#1F1E1D",
        )
        self.window.events.loaded += self._on_loaded
        self.window.events.closing += self._on_closing

    def _on_loaded(self) -> None:
        self._loaded = True

    def _on_closing(self) -> bool:
        # Alt+F4 etc. only hides the popup; Quit from the tray exits for real.
        if getattr(self, "_quitting", False):
            return True
        self.hide()
        return False

    def toggle(self, view: str = "dashboard") -> None:
        # Clicking the tray icon blurs the popup first, which hides it; don't
        # immediately reopen it from that same click.
        if self._visible or time.monotonic() - self._hidden_at < 0.4:
            self.hide()
        else:
            self.show(view)

    def show(self, view: str = "dashboard") -> None:
        left, top, right, bottom = _work_area_logical()
        self.window.move(int(right - WIDTH - MARGIN), int(bottom - HEIGHT - MARGIN))
        if self._loaded:
            self.window.evaluate_js(f"showView({json.dumps(view)})")
        self.window.show()
        self._visible = True

    def hide(self) -> None:
        if self._visible:
            self._hidden_at = time.monotonic()
        self._visible = False
        self.window.hide()

    def push(self, state: dict) -> None:
        if self._loaded:
            try:
                self.window.evaluate_js(f"render({json.dumps(state)})")
            except Exception:
                pass

    def destroy(self) -> None:
        self._quitting = True
        self.window.destroy()
