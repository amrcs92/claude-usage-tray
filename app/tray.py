"""Tray icon rendering, tooltip text and menu."""
from __future__ import annotations

import math
from typing import Callable

import pystray
from PIL import Image, ImageDraw, ImageFont

from app.model import Limit, UsageSnapshot

TEAL = "#8FC7B8"
AMBER = "#E0A84F"
RED = "#B8433A"
GREY = "#9A9A9A"

SIZE = 64  # drawn large, Windows downsamples for the tray


def color_for(percent: float) -> str:
    if percent >= 80:
        return RED
    if percent >= 50:
        return AMBER
    return TEAL


def _font(px: int) -> ImageFont.ImageFont:
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(px)


def _centered_text(draw: ImageDraw.ImageDraw, text: str, px: int, fill: str) -> None:
    font = _font(px)
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    x = (SIZE - (right - left)) / 2 - left
    y = (SIZE - (bottom - top)) / 2 - top
    draw.text((x, y), text, font=font, fill=fill)


def render_icon(percent: float | None, state: str = "ok") -> Image.Image:
    """state: "ok", "offline", "expired" or "loading"."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if state != "ok" or percent is None:
        # Dashed grey ring for offline / expired / loading.
        r, w, dashes = SIZE / 2 - 4, 6, 12
        box = (SIZE / 2 - r, SIZE / 2 - r, SIZE / 2 + r, SIZE / 2 + r)
        step = 360 / dashes
        for i in range(dashes):
            draw.arc(box, i * step, i * step + step * 0.6, fill=GREY, width=w)
        glyph = {"expired": "!", "offline": "×"}.get(state, "…")
        _centered_text(draw, glyph, 34, GREY)
        return img

    color = color_for(percent)
    draw.rounded_rectangle((0, 0, SIZE - 1, SIZE - 1), radius=14, fill=color)
    text = f"{min(100, math.floor(percent + 0.5))}"
    px = {1: 48, 2: 44}.get(len(text), 32)
    fg = "#FFFFFF" if color == RED else "#1B1B1B"
    _centered_text(draw, text, px, fg)
    return img


def pick_metric(snap: UsageSnapshot, metric: str) -> Limit | None:
    if metric == "weekly":
        return snap.weekly or snap.session
    if metric == "highest":
        return snap.highest
    return snap.session or snap.weekly


def _time_label(limit: Limit) -> str:
    if limit.resets_at is None:
        return ""
    local = limit.resets_at.astimezone()
    text = local.strftime("%I:%M %p").lstrip("0")
    if limit.group != "session":
        text = local.strftime("%a ") + text
    return f" · resets {text}"


def tooltip(snap: UsageSnapshot | None, status_text: str | None = None) -> str:
    lines = []
    if status_text:
        lines.append(status_text)
    if snap:
        for limit in (snap.session, snap.weekly):
            if limit:
                name = "Session" if limit.group == "session" else "Weekly"
                lines.append(f"{name} {limit.percent:.0f}%{_time_label(limit)}")
    text = "\n".join(lines) or "Claude Usage"
    return text[:127]  # Windows tooltip limit


class Tray:
    def __init__(self, actions: dict[str, Callable[[], None]], autostart_checked: Callable[[], bool]):
        a = actions
        menu = pystray.Menu(
            pystray.MenuItem("Open dashboard", lambda: a["toggle"](), default=True),
            pystray.MenuItem("Refresh now", lambda: a["refresh"]()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Start with Windows", lambda: a["toggle_autostart"](),
                             checked=lambda _: autostart_checked()),
            pystray.MenuItem("Settings…", lambda: a["settings"]()),
            pystray.MenuItem("Open claude.ai usage page", lambda: a["usage_page"]()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: a["quit"]()),
        )
        self.icon = pystray.Icon("ClaudeUsageTray", render_icon(None, "loading"), "Claude Usage", menu)

    def start(self) -> None:
        self.icon.run_detached()

    def update(self, image: Image.Image, title: str) -> None:
        self.icon.icon = image
        self.icon.title = title

    def stop(self) -> None:
        self.icon.stop()
