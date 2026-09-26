"""Settings stored as JSON in %APPDATA%\\ClaudeUsageTray\\settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

POLL_CHOICES = (30, 60, 300, 900)
METRIC_CHOICES = ("session", "weekly", "highest")


def data_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "ClaudeUsageTray"


@dataclass
class Settings:
    poll_seconds: int = 60
    tray_metric: str = "session"
    notify_80: bool = True
    notify_95: bool = True
    notify_reset: bool = False
    start_with_windows: bool = False

    def validated(self) -> "Settings":
        if self.poll_seconds not in POLL_CHOICES:
            self.poll_seconds = 60
        if self.tray_metric not in METRIC_CHOICES:
            self.tray_metric = "session"
        return self

    @classmethod
    def from_dict(cls, raw: object) -> "Settings":
        """Keeps known keys of the right type; ignores the rest (migration-safe)."""
        s = cls()
        if isinstance(raw, dict):
            for f in fields(cls):
                value = raw.get(f.name)
                default = getattr(s, f.name)
                if value is not None and type(value) is type(default):
                    setattr(s, f.name, value)
        return s.validated()

    def to_dict(self) -> dict:
        return asdict(self)


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load(path: Path | None = None) -> Settings:
    path = path or settings_path()
    try:
        return Settings.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Settings()


def save(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)
