"""The frameless pywebview popup that sits above the tray."""
from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Callable

import webview

WIDTH, HEIGHT, MARGIN = 380, 580, 12
SHOW_DELAY = 0.15  # let the shell finish handling the tray click before we take focus
BLUR_GRACE = 0.6   # the shell can still grab focus back this long after we show

_user32 = ctypes.windll.user32
_user32.GetForegroundWindow.restype = wintypes.HWND


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


def _force_foreground(hwnd: int | None) -> None:
    """SetForegroundWindow is refused unless we share input state with the
    current foreground window (the taskbar), so attach to it briefly."""
    if not hwnd:
        return
    fg = _user32.GetForegroundWindow()
    if fg == hwnd:
        return
    ours = ctypes.windll.kernel32.GetCurrentThreadId()
    theirs = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(theirs) and theirs != ours and _user32.AttachThreadInput(ours, theirs, True)
    try:
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(ours, theirs, False)


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

    def blurred(self) -> None:
        self._h["blur"]()


class Popup:
    def __init__(self, api: Api):
        self._visible = False
        self._hidden_at = 0.0
        self._shown_at = 0.0
        self._hwnd: int | None = None
        self._loaded = False
        self._pending_view: str | None = None
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
        try:
            self._hwnd = self.window.native.Handle.ToInt64()
        except Exception:
            self._hwnd = _user32.FindWindowW(None, self.window.title)
        if self._pending_view:
            self.window.evaluate_js(f"showView({json.dumps(self._pending_view)})")
            self._pending_view = None

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
            # Clicking an icon in the tray overflow hands focus back to the
            # overflow flyout right after the click; showing straight away
            # loses focus and the blur handler closes the popup again.
            threading.Timer(SHOW_DELAY, self.show, (view,)).start()

    def show(self, view: str = "dashboard") -> None:
        left, top, right, bottom = _work_area_logical()
        # Frameless windows can come out a little smaller than requested,
        # so position by the real size.
        width = self.window.width or WIDTH
        height = self.window.height or HEIGHT
        self.window.move(int(right - width - MARGIN), int(bottom - height - MARGIN))
        if self._loaded:
            self.window.evaluate_js(f"showView({json.dumps(view)})")
        else:
            self._pending_view = view
        self._shown_at = time.monotonic()
        self.window.show()
        self._visible = True
        _force_foreground(self._hwnd)

    def on_blur(self) -> None:
        if not self._visible:
            return
        if time.monotonic() - self._shown_at < BLUR_GRACE:
            # The shell took focus while the popup was opening: take it back.
            threading.Timer(0.05, lambda: self._visible and _force_foreground(self._hwnd)).start()
            return
        self.hide()

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
