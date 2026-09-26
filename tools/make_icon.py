"""Regenerates assets/icon.ico from the same renderer the tray uses."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.tray import render_icon  # noqa: E402

img = render_icon(42, "ok")
img.save(ROOT / "assets" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)])
print("wrote assets/icon.ico")
