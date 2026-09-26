# Claude Usage Tray: Implementation Plan

A small Windows tray app that shows your Claude plan usage (5-hour session + weekly limits) without opening claude.ai. It reads the login Claude Code already saved on your machine.

> Status: **v1 implemented (Phases 0–5).** The popup UI follows §5; compare it against the "Claude Usage Tray UI" design canvas before calling it final. Phase 0 found that the endpoint also returns a `limits` array and a `seven_day_breakdown`, and both are parsed. The manual test checklist in Phase 5 is still to do.

---

## 1. Goals and non-goals

**Goals**
- A tray icon that always shows the current usage % with a color (green, amber, red).
- A popup on left-click that shows the session ring, weekly bars, reset countdowns and a pacing hint.
- Hover tooltip, a right-click menu, and a Windows notification at 80% / 95%.
- Start with Windows (optional), and ship as a single portable `.exe`.
- Zero configuration: if Claude Code is logged in, it works.

**Non-goals (v1)**
- No multi-account switching.
- No token/cost accounting from local transcripts (possible v2).
- The app never refreshes or rotates your OAuth token. That stays Claude Code's job (see §4.3).

---

## 2. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Fast to build; easy to package |
| Tray icon + menu | **pystray** + **Pillow** | Native Windows tray; icon drawn at runtime with the % number |
| Popup window | **pywebview** (Edge WebView2, preinstalled on Win 10/11) | Lets the popup be HTML/CSS that matches the approved mockup exactly |
| HTTP | **httpx** | Timeouts, clean errors |
| Notifications | **win11toast** (or `windows-toasts`) | Native toast notifications |
| Autostart | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` registry value via `winreg` | No admin rights needed |
| Settings | JSON in `%APPDATA%\ClaudeUsageTray\settings.json` | Simple, human-editable |
| Packaging | **PyInstaller** `--onefile --noconsole` | One portable `.exe` |

*Alternative considered:* C#/WPF or Tauri. They produce a smaller binary but take longer to build. Python gets v1 working fastest, and the UI (HTML) could be reused later if we port it.

---

## 3. Project structure

```
claude-usage-tray/
├─ app/
│  ├─ main.py            # entry point: starts tray + scheduler
│  ├─ credentials.py     # reads Claude Code login file
│  ├─ usage_api.py       # calls the usage endpoint, parses response
│  ├─ model.py           # dataclasses: UsageSnapshot, Limit
│  ├─ tray.py            # pystray icon, tooltip, menu, icon rendering
│  ├─ popup.py           # pywebview window + JS bridge
│  ├─ notifier.py        # threshold + reset alerts (dedup per window)
│  ├─ settings.py        # load/save settings.json
│  ├─ autostart.py       # registry Run key on/off
│  └─ ui/
│     ├─ index.html      # dashboard + settings views (from approved mockup)
│     ├─ app.css
│     └─ app.js
├─ assets/icon.ico
├─ tests/
│  ├─ test_usage_parse.py
│  └─ fixtures/usage_sample.json
├─ requirements.txt
├─ build.ps1             # PyInstaller build script
└─ README.md
```

---

## 4. Data source

### 4.1 Credentials
Claude Code on Windows stores its login in:
```
%USERPROFILE%\.claude\.credentials.json
```
Expected shape (verify in Phase 0):
```json
{ "claudeAiOauth": { "accessToken": "…", "refreshToken": "…", "expiresAt": 1790000000000, "subscriptionType": "max" } }
```
- Read the file **fresh on every poll**, because Claude Code rewrites it when it refreshes the token.
- Keep the token in memory only. Never log it and never write it anywhere.
- Also check the `CLAUDE_CONFIG_DIR` env var in case the user moved the config folder.

### 4.2 Usage endpoint (undocumented)
This is the same source Claude Code's `/usage` command uses:
```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer <accessToken>
anthropic-beta: oauth-2025-04-20
```
Expected response fields (verify in Phase 0, and parse defensively):
- `five_hour` → `{ utilization: 0–100, resets_at: ISO-8601 }` (session)
- `seven_day` → weekly, all models
- `seven_day_opus`, `seven_day_sonnet`, … → per-model weekly (may be `null`)
- Any unknown `seven_day_*` key is shown automatically as an extra weekly bar, so new quota types still appear.

### 4.3 Token expiry: a deliberate choice
If `expiresAt` has passed or the API returns 401:
- **Do not** call the refresh endpoint ourselves. Rotating the refresh token could log Claude Code out.
- Instead, show the "login expired" tray state and the message *"Run any `claude` command to refresh your login."* Then retry on the next poll.

### 4.4 Polling and errors
- Default poll interval: 1 min (30s / 1m / 5m / 15m in settings). Add ±5s jitter.
- On 429 or 5xx, use exponential backoff (1 → 2 → 4 → max 15 min) and keep showing the last good data with "Updated Xm ago".
- On a network error, show the offline icon state and the same backoff.

---

## 5. UI behaviour (maps to the mockup)

**Tray icon** (rendered with Pillow, 32×32, redrawn each poll)
- The number shows the % for the chosen metric (Session / Weekly / Highest).
- Color: < 50% teal `#8FC7B8`, 50–79% amber `#E0A84F`, ≥ 80% red `#B8433A`, dashed grey = offline/expired.
- Tooltip: `Session 42% · resets 6:41 PM` / `Weekly 61% · resets Thu 10:00 AM`.

**Popup** (pywebview, 380×580, frameless, placed just above the tray near the bottom-right)
- Left-click on the tray toggles it. It hides when it loses focus. Closing only hides it; it is not destroyed.
- Python pushes a snapshot through `window.evaluate_js("render(<json>)")`. JS buttons call Python through the `js_api` bridge (`refresh()`, `saveSettings()`, `openUsagePage()`).
- Pacing hint: compares `utilization` against the elapsed fraction of the window.
  - `used% ≤ elapsed%` → "On pace — room to spare"
  - otherwise → "Ahead of pace — at this rate you hit 100% ~Xm before reset"

**Right-click menu:** Open dashboard · Refresh now · ✓ Start with Windows · Settings… · Open claude.ai usage page · Quit.

**Notifications:** one toast per threshold per reset window (the dedupe key is `limit + resets_at + threshold`). An optional toast "Session reset — you're back to 0%".

---

## 6. Phases and tasks

### Phase 0: Verify assumptions (≈ 1 hour)
- [ ] Confirm the credentials file path and JSON shape on your machine (**never paste the token anywhere**).
- [ ] Call the endpoint once with a tiny script and save a **redacted** response to `tests/fixtures/usage_sample.json`.
- [ ] Adjust §4.1 and §4.2 if the shapes differ.

### Phase 1: Core data layer
- [ ] `credentials.py`: locate and read the file, handle missing/expired.
- [ ] `usage_api.py` + `model.py`: fetch, parse to `UsageSnapshot`, tolerate null/unknown keys.
- [ ] Unit tests against the fixture.

### Phase 2: Tray
- [ ] `tray.py`: icon rendering (4 states), tooltip, menu.
- [ ] Background poll thread + backoff; thread-safe state handed to the UI.

### Phase 3: Popup UI
- [ ] Port the approved mockup to `ui/index.html` (dashboard + settings views).
- [ ] pywebview window: frameless, always-on-top while open, positioned above the tray, hides on blur.
- [ ] JS bridge: render, refresh, settings save, open usage page.

### Phase 4: Settings, notifications, autostart
- [ ] `settings.py` with defaults + migration-safe loading.
- [ ] `notifier.py` with dedupe.
- [ ] `autostart.py` registry toggle (path to the packaged `.exe`).

### Phase 5: Package and test
- [ ] `build.ps1`: `pyinstaller --onefile --noconsole --icon assets/icon.ico --add-data "app/ui;ui" app/main.py`
- [ ] Manual test checklist:
  - Normal usage, then crossing 80%, then crossing 95%, then a session reset
  - Expired login, then running `claude` to refresh
  - Wi-Fi off, then back on
  - Autostart on/off after a reboot
  - DPI scaling at 100%, 150% and 200%
  - Dark and light Windows taskbar
- [ ] SmartScreen note: an unsigned `.exe` shows "Windows protected your PC". Click *More info → Run anyway* (or code-sign later).

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| Undocumented endpoint changes or disappears | All parsing lives in one module; the app degrades to showing the "Open on claude.ai" link; fixture tests catch shape changes quickly |
| Token handling mistakes | Read-only access, in-memory only, no refresh, no logging |
| Rate limiting from polling too often | 1-min default, jitter, backoff, manual refresh throttled to once per 10s |
| Antivirus flags a PyInstaller one-file `.exe` | Offer a `--onedir` build as a fallback; code-sign optionally |

---

## 8. Definition of done (v1)
- The `.exe` runs on a clean Windows 11 PC with Claude Code logged in and shows correct numbers that match claude.ai's usage page within one poll.
- All states in the mockup are reachable and look as approved.
- It uses no more than ~60 MB RAM idle and does no network calls other than the usage endpoint.
