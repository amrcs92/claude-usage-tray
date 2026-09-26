/* Popup UI. Python pushes state with render(state); buttons call pywebview.api.* */
"use strict";

const RING_LEN = 2 * Math.PI * 52;
const BREAKDOWN_COLORS = ["#D97757", "#8FC7B8", "#E0A84F", "#9C8FD6", "#A29E97"];
let state = null;

const $ = (id) => document.getElementById(id);
const api = () => (window.pywebview && window.pywebview.api) || null;

function colorFor(pct) {
  if (pct >= 80) return "var(--red)";
  if (pct >= 50) return "var(--amber)";
  return "var(--teal)";
}

function fmtDuration(ms) {
  const mins = Math.max(0, Math.floor(ms / 60000));
  const d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60), m = mins % 60;
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtReset(iso, withDay) {
  if (!iso) return "No reset time";
  const at = new Date(iso);
  const left = at - Date.now();
  if (left <= 0) return "Resetting…";
  const time = at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const day = withDay ? at.toLocaleDateString([], { weekday: "short" }) + " " : "";
  return `Resets in ${fmtDuration(left)} · ${day}${time}`;
}

function fmtAgo(iso) {
  if (!iso) return "Not updated yet";
  const s = Math.floor((Date.now() - new Date(iso)) / 1000);
  if (s < 60) return "Updated just now";
  return `Updated ${fmtDuration(s * 1000)} ago`;
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function render(next) {
  state = next;
  $("btn-refresh").classList.remove("spin");

  // Plan badge
  $("plan").hidden = !state.plan;
  $("plan").textContent = state.plan || "";

  // Status banner
  const banner = $("banner");
  banner.className = "banner";
  if (state.status !== "ok" && state.status !== "loading" && state.message) {
    banner.hidden = false;
    if (state.status === "expired") banner.classList.add("expired");
    // Show `claude` as code; the message itself is trusted text from Python.
    banner.textContent = "";
    state.message.split(/`([^`]+)`/).forEach((part, i) => {
      banner.appendChild(i % 2 ? el("code", null, part) : document.createTextNode(part));
    });
    if (state.updated_at) banner.appendChild(document.createTextNode(" Showing last known data."));
  } else {
    banner.hidden = true;
  }

  const limits = state.limits || [];
  const session = limits.find((l) => l.group === "session");
  const weekly = limits.filter((l) => l.group === "weekly");

  // Session ring
  const fill = $("ring-fill");
  if (session) {
    const pct = Math.round(session.percent);
    $("session-pct").textContent = `${pct}%`;
    fill.style.strokeDashoffset = RING_LEN * (1 - Math.min(100, session.percent) / 100);
    fill.style.stroke = colorFor(session.percent);
    const pace = $("session-pace");
    pace.hidden = !session.pace;
    if (session.pace) {
      pace.textContent = session.pace.text;
      pace.classList.toggle("ahead", session.pace.ahead);
    }
  } else {
    $("session-pct").textContent = "–";
    fill.style.strokeDashoffset = RING_LEN;
    $("session-pace").hidden = true;
  }

  // Weekly bars
  const list = $("weekly-list");
  list.textContent = "";
  if (!weekly.length) list.appendChild(el("div", "muted small", "No weekly data yet."));
  for (const l of weekly) {
    const row = el("div", "row");
    const head = el("div", "row-head");
    head.append(el("span", null, l.label), el("b", null, `${Math.round(l.percent)}%`));
    const meter = el("div", "meter");
    const bar = el("span");
    bar.style.width = `${Math.min(100, l.percent)}%`;
    bar.style.background = colorFor(l.percent);
    meter.appendChild(bar);
    const sub = el("div", "row-sub muted small");
    sub.dataset.reset = l.resets_at || "";
    row.append(head, meter, sub);
    if (l.pace && l.pace.ahead) row.appendChild(el("div", "row-sub small", l.pace.text));
    list.appendChild(row);
  }

  // Breakdown
  const rows = (state.breakdown || []).filter((b) => b.percent > 0);
  $("breakdown-card").hidden = !rows.length;
  const stack = $("breakdown-bar"), legend = $("breakdown-legend");
  stack.textContent = ""; legend.textContent = "";
  rows.forEach((b, i) => {
    const color = BREAKDOWN_COLORS[i % BREAKDOWN_COLORS.length];
    const seg = el("span");
    seg.style.width = `${b.percent}%`;
    seg.style.background = color;
    stack.appendChild(seg);
    const item = el("span");
    const sw = el("i"); sw.style.background = color;
    item.append(sw, document.createTextNode(`${b.label} ${Math.round(b.percent)}%`));
    legend.appendChild(item);
  });

  renderSettings();
  tick();
}

// Countdown text updates every 30s without waiting for a poll.
function tick() {
  if (!state) return;
  const session = (state.limits || []).find((l) => l.group === "session");
  $("session-reset").textContent = session ? fmtReset(session.resets_at, false)
    : state.status === "loading" ? "Waiting for data…" : "No session data";
  document.querySelectorAll("#weekly-list .row-sub[data-reset]").forEach((e) => {
    e.textContent = fmtReset(e.dataset.reset || null, true);
  });
  $("updated").textContent = fmtAgo(state.updated_at);
}
setInterval(tick, 30000);

// --- Settings ---------------------------------------------------------------

function renderSettings() {
  const s = state && state.settings;
  if (!s) return;
  document.querySelectorAll(".seg[data-setting]").forEach((seg) => {
    const current = String(s[seg.dataset.setting]);
    seg.querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset.value === current));
  });
  document.querySelectorAll("input[data-setting]").forEach((input) => {
    input.checked = !!s[input.dataset.setting];
  });
}

async function saveSetting(name, value) {
  if (!api()) return;
  const next = await api().save_settings({ [name]: value });
  if (next) render(next);
}

document.querySelectorAll(".seg[data-setting]").forEach((seg) => {
  seg.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const raw = b.dataset.value;
    saveSetting(seg.dataset.setting, /^\d+$/.test(raw) ? Number(raw) : raw);
  });
});
document.querySelectorAll("input[data-setting]").forEach((input) => {
  input.addEventListener("change", () => saveSetting(input.dataset.setting, input.checked));
});

// --- Navigation and buttons -------------------------------------------------

function showView(name) {
  $("view-dashboard").hidden = name !== "dashboard";
  $("view-settings").hidden = name !== "settings";
  tick();
}

$("btn-settings").addEventListener("click", () => showView("settings"));
$("btn-back").addEventListener("click", () => showView("dashboard"));
$("btn-refresh").addEventListener("click", () => {
  $("btn-refresh").classList.add("spin");
  setTimeout(() => $("btn-refresh").classList.remove("spin"), 3000);
  api() && api().refresh();
});
$("btn-usage-page").addEventListener("click", () => api() && api().open_usage_page());

window.addEventListener("blur", () => api() && api().hide());
document.addEventListener("keydown", (e) => { if (e.key === "Escape") api() && api().hide(); });

window.addEventListener("pywebviewready", async () => {
  const initial = await api().get_state();
  if (initial) render(initial);
});
