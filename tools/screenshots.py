"""Regenerates docs/screenshots/*.png using --demo data (no real account shown).

Run from the repo root:  .venv\\Scripts\\python tools\\screenshots.py
It opens the popup for each scenario, captures just the popup window and
closes it again. Leave the bottom-right of the primary screen uncovered.
"""
import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont, ImageGrab  # noqa: E402

from app.tray import render_icon  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
SHOTS = [
    ("dashboard", ["--demo", "normal", "--show", "dashboard"]),
    ("dashboard-high", ["--demo", "high", "--show", "dashboard"]),
    ("settings", ["--demo", "normal", "--show", "settings"]),
    ("login-expired", ["--demo", "expired", "--show", "dashboard"]),
]

ctypes.windll.shcore.SetProcessDpiAwareness(2)  # capture in physical pixels


def popup_rect() -> tuple[int, int, int, int]:
    """The popup's on-screen rectangle, found by its window title."""
    hwnd = ctypes.windll.user32.FindWindowW(None, "Claude Usage")
    if not hwnd:
        raise RuntimeError("popup window not found")
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def capture_popup(name: str, args: list[str]) -> None:
    proc = subprocess.Popen([sys.executable, str(ROOT / "app" / "main.py"), "--pin", *args])
    try:
        time.sleep(7)
        ImageGrab.grab(popup_rect(), all_screens=True).save(OUT / f"{name}.png")
        print(f"wrote docs/screenshots/{name}.png")
    finally:
        proc.kill()
        proc.wait()
        time.sleep(1)


def tray_states() -> None:
    """One strip with every tray icon state, on a dark and a light taskbar."""
    states = [("Under 50%", 23, "ok"), ("50–79%", 64, "ok"), ("80% +", 91, "ok"),
              ("Offline", None, "offline"), ("Login expired", None, "expired")]
    cell, icon, pad = 150, 48, 20
    try:
        font = ImageFont.truetype("segoeui.ttf", 16)
    except OSError:
        font = ImageFont.load_default(16)
    img = Image.new("RGB", (cell * len(states), 2 * (icon + pad * 2) + 30), "#202020")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, icon + pad * 2, img.width, img.height), fill="#F3F3F3")
    for i, (label, pct, state) in enumerate(states):
        ic = render_icon(pct, state).resize((icon, icon), Image.LANCZOS)
        x = i * cell + (cell - icon) // 2
        img.paste(ic, (x, pad), ic)
        img.paste(ic, (x, icon + pad * 3), ic)
        w = draw.textlength(label, font=font)
        draw.text((i * cell + (cell - w) / 2, img.height - 26), label, font=font, fill="#333333")
    img.save(OUT / "tray-states.png")
    print("wrote docs/screenshots/tray-states.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    tray_states()
    for name, args in SHOTS:
        capture_popup(name, args)
