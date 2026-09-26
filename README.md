# Claude Usage Tray

A small Windows tray app that shows your Claude plan usage (the 5-hour session and weekly limits) without opening claude.ai. It reuses the login that [Claude Code](https://claude.com/claude-code) already saved on your PC, so there is nothing to configure.

- **Tray icon** shows the current % in color: teal under 50%, amber from 50% to 79%, red from 80%. A dashed grey icon means you're offline or your login has expired.
- **Left-click** opens a popup with the session ring, weekly bars, reset countdowns, a pacing hint and a per-surface breakdown.
- **Hover** shows a tooltip, for example `Session 42% · resets 6:41 PM`.
- **Right-click** menu: Open dashboard · Refresh now · Start with Windows · Settings… · Open claude.ai usage page · Quit.
- **Notifications** at 80% and 95%, one per reset window, plus an optional "session reset" toast.

## Requirements

- Windows 10 or 11 (the Edge WebView2 runtime is preinstalled on both)
- Claude Code installed and logged in with a Claude account (Pro or Max)

## Run from source

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\python app\main.py          # add --show to open the popup at launch
.\.venv\Scripts\python -m pytest -q
```

## Build the .exe

```powershell
.\build.ps1           # dist\ClaudeUsageTray.exe (single portable file)
.\build.ps1 -OneDir   # folder build, if antivirus flags the one-file exe
```

The `.exe` is unsigned, so Windows SmartScreen may show "Windows protected your PC". Click **More info → Run anyway**.

## How it works

On every poll (default 1 min, with ±5 s jitter) the app:

1. Reads `%USERPROFILE%\.claude\.credentials.json`, or `%CLAUDE_CONFIG_DIR%\.credentials.json` if that variable is set. The file is read fresh each time, because Claude Code rewrites it when it refreshes the token.
2. Calls `GET https://api.anthropic.com/api/oauth/usage`, the same source Claude Code's `/usage` command uses.
3. Parses the response defensively. Unknown weekly quota types appear as extra bars automatically.

On 429, 5xx or network errors it backs off (1 → 2 → 4 … up to 15 min) and keeps showing the last good data.

### Privacy and token handling

- The OAuth token is only read. It is kept in memory, never logged, never written anywhere, and **never refreshed**. Refreshing could rotate the token and log Claude Code out. When the login expires, the app asks you to run any `claude` command, which refreshes it.
- The only network call is the usage endpoint above.
- Settings live in `%APPDATA%\ClaudeUsageTray\settings.json`.

> The usage endpoint is undocumented and may change. All parsing lives in [`app/usage_api.py`](app/usage_api.py), and the fixture tests catch shape changes.

## Project layout

```
app/
  main.py         entry point: tray + poller + popup
  credentials.py  reads the Claude Code login (read-only)
  usage_api.py    fetches and parses the usage endpoint
  model.py        UsageSnapshot / Limit dataclasses, pacing
  tray.py         icon rendering, tooltip, menu
  popup.py        pywebview window + JS bridge
  notifier.py     threshold / reset toasts with dedupe
  settings.py     settings.json load/save
  autostart.py    HKCU Run key toggle
  ui/             popup HTML/CSS/JS
tests/            pytest suite + synthetic fixture
docs/PLAN.md      the implementation plan
```
