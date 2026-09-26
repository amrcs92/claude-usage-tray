"""Plain data types shared by the API layer, the tray and the popup."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

SESSION_WINDOW = timedelta(hours=5)
WEEKLY_WINDOW = timedelta(days=7)


@dataclass(frozen=True)
class Limit:
    key: str                    # "session", "weekly_all", "weekly_opus", ...
    label: str                  # human label, e.g. "Weekly · Opus"
    group: str                  # "session" or "weekly"
    percent: float              # 0-100
    resets_at: datetime | None  # timezone-aware UTC

    @property
    def window(self) -> timedelta:
        return SESSION_WINDOW if self.group == "session" else WEEKLY_WINDOW


@dataclass(frozen=True)
class BreakdownRow:
    label: str
    percent: float


@dataclass(frozen=True)
class UsageSnapshot:
    limits: list[Limit]
    fetched_at: datetime
    breakdown: list[BreakdownRow] = field(default_factory=list)

    def get(self, key: str) -> Limit | None:
        return next((l for l in self.limits if l.key == key), None)

    @property
    def session(self) -> Limit | None:
        return self.get("session")

    @property
    def weekly(self) -> Limit | None:
        """The all-models weekly limit, or the first weekly limit found."""
        return self.get("weekly_all") or next(
            (l for l in self.limits if l.group == "weekly"), None
        )

    @property
    def highest(self) -> Limit | None:
        return max(self.limits, key=lambda l: l.percent, default=None)


@dataclass(frozen=True)
class Pace:
    ahead: bool
    text: str


def pacing(limit: Limit, now: datetime | None = None) -> Pace | None:
    """Compare usage against the elapsed fraction of the limit's window."""
    if limit.resets_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    remaining = limit.resets_at - now
    if remaining <= timedelta(0):
        return None
    elapsed = limit.window - remaining
    if elapsed <= timedelta(0):
        return None

    elapsed_pct = 100 * elapsed / limit.window
    if limit.percent <= elapsed_pct:
        return Pace(False, "On pace — room to spare")
    if limit.percent >= 100:
        return Pace(True, "Limit reached — waits for reset")

    # Linear projection at the current burn rate.
    rate = limit.percent / elapsed.total_seconds()          # % per second
    time_to_full = timedelta(seconds=(100 - limit.percent) / rate)
    early = remaining - time_to_full
    if early <= timedelta(0):
        return Pace(False, "On pace — room to spare")
    return Pace(True, f"Ahead of pace — at this rate you hit 100% ~{format_duration(early)} before reset")


def format_duration(d: timedelta) -> str:
    minutes = max(0, int(d.total_seconds() // 60))
    days, rem = divmod(minutes, 60 * 24)
    hours, mins = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"
