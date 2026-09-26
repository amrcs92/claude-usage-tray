import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import credentials
from app.model import Limit, pacing
from app.notifier import Notifier
from app.settings import Settings
from app.tray import pick_metric, render_icon, tooltip
from app.usage_api import parse

FIXTURE = Path(__file__).parent / "fixtures" / "usage_sample.json"
NOW = datetime(2030, 1, 1, 14, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- parsing ------------------------------------------------------------------

def test_parses_session_and_weekly(sample):
    snap = parse(sample, now=NOW)
    assert snap.session.percent == 42
    assert snap.session.resets_at == datetime(2030, 1, 1, 17, 40, tzinfo=timezone.utc)
    assert snap.weekly.key == "weekly_all"
    assert snap.weekly.percent == 61
    assert [l.key for l in snap.limits] == ["session", "weekly_all"]


def test_ignores_null_and_codename_keys(sample):
    keys = {l.key for l in parse(sample).limits}
    assert "weekly_opus" not in keys           # null
    assert "some_codename_quota" not in keys   # not a seven_day_* key


def test_breakdown(sample):
    rows = parse(sample).breakdown
    assert [(r.label, r.percent) for r in rows] == [("Claude Code", 70), ("Chats", 25), ("Other", 5)]


def test_legacy_only_response_and_unknown_weekly_key():
    data = {
        "five_hour": {"utilization": 10, "resets_at": "2030-01-01T12:00:00Z"},
        "seven_day": {"utilization": 20, "resets_at": None},
        "seven_day_opus": {"utilization": 30, "resets_at": "2030-01-05T00:00:00+00:00"},
        "seven_day_new_thing": {"utilization": 5},
    }
    snap = parse(data)
    assert [l.key for l in snap.limits] == ["session", "weekly_all", "weekly_new_thing", "weekly_opus"]
    assert snap.get("weekly_opus").label == "Weekly · Opus"
    assert snap.get("weekly_new_thing").label == "Weekly · New Thing"
    assert snap.weekly.resets_at is None


def test_limits_array_wins_and_adds_new_kinds():
    data = {
        "five_hour": {"utilization": 10},
        "limits": [
            {"kind": "session", "group": "session", "percent": 12},
            {"kind": "weekly_design", "group": "weekly", "percent": 3},
        ],
    }
    snap = parse(data)
    assert snap.session.percent == 12
    assert snap.get("weekly_design").group == "weekly"


@pytest.mark.parametrize("data", [
    {}, {"five_hour": None}, {"five_hour": {"utilization": "x"}}, {"limits": "nope"},
    {"limits": [None, {"kind": 5}]}, {"seven_day_breakdown": {"rows": [None]}},
])
def test_tolerates_garbage(data):
    snap = parse(data)
    assert snap.limits == [] or all(isinstance(l, Limit) for l in snap.limits)


def test_percent_is_clamped():
    assert parse({"five_hour": {"utilization": 140}}).session.percent == 100


# --- pacing -------------------------------------------------------------------

def _session(pct, minutes_left):
    return Limit("session", "Session", "session", pct, NOW + timedelta(minutes=minutes_left))


def test_on_pace_when_usage_below_elapsed():
    # 3h40m left of 5h => 26.7% elapsed, 20% used
    assert pacing(_session(20, 220), NOW).ahead is False


def test_ahead_of_pace_projects_time_before_reset():
    # 1h elapsed (4h left) with 50% used => hits 100% 1h from now, 3h before reset
    pace = pacing(_session(50, 240), NOW)
    assert pace.ahead is True
    assert "~3h 0m before reset" in pace.text


def test_no_pace_without_reset():
    assert pacing(Limit("session", "Session", "session", 50, None), NOW) is None


# --- tray -----------------------------------------------------------------------

def test_pick_metric(sample):
    snap = parse(sample)
    assert pick_metric(snap, "session").percent == 42
    assert pick_metric(snap, "weekly").percent == 61
    assert pick_metric(snap, "highest").percent == 61


def test_tooltip_fits_windows_limit(sample):
    text = tooltip(parse(sample), "x" * 200)
    assert len(text) <= 127


@pytest.mark.parametrize("pct,state", [(5, "ok"), (65, "ok"), (100, "ok"), (None, "offline"), (None, "expired")])
def test_render_icon(pct, state):
    assert render_icon(pct, state).size == (64, 64)


# --- notifier -------------------------------------------------------------------

def test_notifier_dedupes_per_window():
    sent = []
    n = Notifier(send=lambda t, b: sent.append(t))
    s = Settings()
    snap = parse({"limits": [{"kind": "session", "percent": 85, "resets_at": "2030-01-01T17:00:00Z"}]})
    assert n.check(snap, s) == ["Session at 85%"]
    assert n.check(snap, s) == []
    snap96 = parse({"limits": [{"kind": "session", "percent": 96, "resets_at": "2030-01-01T17:00:00Z"}]})
    assert n.check(snap96, s) == ["Session at 96%"]
    # New window => alerts again
    later = parse({"limits": [{"kind": "session", "percent": 81, "resets_at": "2030-01-01T22:00:00Z"}]})
    assert n.check(later, s) == ["Session at 81%"]


def test_notifier_jumping_past_both_thresholds_toasts_once():
    n = Notifier(send=lambda t, b: None)
    snap = parse({"limits": [{"kind": "session", "percent": 97, "resets_at": "2030-01-01T17:00:00Z"}]})
    assert n.check(snap, Settings()) == ["Session at 97%"]
    assert n.check(snap, Settings()) == []


def test_notifier_reset_toast():
    n = Notifier(send=lambda t, b: None)
    s = Settings(notify_reset=True)
    n.check(parse({"limits": [{"kind": "session", "percent": 40, "resets_at": "2030-01-01T17:00:00Z"}]}), s)
    out = n.check(parse({"limits": [{"kind": "session", "percent": 0, "resets_at": "2030-01-01T22:00:00Z"}]}), s)
    assert out == ["Session reset"]


def test_notifier_persists(tmp_path):
    path = tmp_path / "notified.json"
    snap = parse({"limits": [{"kind": "session", "percent": 85, "resets_at": "2030-01-01T17:00:00Z"}]})
    Notifier(send=lambda t, b: None, state_path=path).check(snap, Settings())
    assert Notifier(send=lambda t, b: None, state_path=path).check(snap, Settings()) == []


# --- settings & credentials -----------------------------------------------------

def test_settings_migration_safe():
    s = Settings.from_dict({"poll_seconds": 7, "tray_metric": "weekly", "notify_80": "yes", "future": 1})
    assert s.poll_seconds == 60          # invalid choice -> default
    assert s.tray_metric == "weekly"
    assert s.notify_80 is True           # wrong type -> default


def _write_creds(tmp_path, oauth):
    p = tmp_path / ".credentials.json"
    p.write_text(json.dumps({"claudeAiOauth": oauth}), encoding="utf-8")
    return p


def test_credentials_ok(tmp_path):
    p = _write_creds(tmp_path, {"accessToken": "secret", "expiresAt": 2000, "subscriptionType": "pro"})
    c = credentials.load(p, now_ms=1000)
    assert c.subscription_type == "pro"
    assert "secret" not in repr(c)


def test_credentials_expired(tmp_path):
    p = _write_creds(tmp_path, {"accessToken": "secret", "expiresAt": 1000})
    with pytest.raises(credentials.CredentialsExpired):
        credentials.load(p, now_ms=2000)


def test_credentials_missing(tmp_path):
    with pytest.raises(credentials.CredentialsMissing):
        credentials.load(tmp_path / "nope.json")
    with pytest.raises(credentials.CredentialsMissing):
        credentials.load(_write_creds(tmp_path, {}))


def test_config_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    assert credentials.credentials_path() == tmp_path / ".credentials.json"


# --- demo ------------------------------------------------------------------------

@pytest.mark.parametrize("scenario", ["normal", "high", "expired", "offline"])
def test_demo_scenarios(scenario):
    from app import demo
    snap = demo.snapshot(scenario)
    assert snap.session and snap.weekly and snap.breakdown
    assert demo.status(scenario)[0] in ("ok", "expired", "offline")
