// Drives the reactive sphere. Subscribes to /events/ws and maps events to:
//   - data-state on .sphere-wrap   (idle/listening/thinking/speaking/...)
//   - --live-hue CSS var           (per tone)
//   - latest utterance strip       (fades in for each turn)
//   - collapsible conversation log (bottom-right history panel)

const sphereWrap = document.getElementById("sphere-wrap");
const stateText = document.getElementById("state-text");
const toneText = document.getElementById("tone-text");
const modeText = document.getElementById("mode-text");
const wakeText = document.getElementById("wake-text");
const latest = document.getElementById("latest");
const log = document.getElementById("log");

// Panel + composer
const panel = document.getElementById("panel");
const panelToggle = document.getElementById("panel-toggle");
const moodBar = document.getElementById("mood-bar");
const energyBar = document.getElementById("energy-bar");
const pMode = document.getElementById("p-mode");
const pWake = document.getElementById("p-wake");
const cards = document.getElementById("cards");
const activity = document.getElementById("activity");
const composer = document.getElementById("composer");
const composerInput = document.getElementById("composer-input");

const HUE = {
  soft: 320,
  playful: 48,
  neutral: 160,
  focused: 200,
  sad: 220,
  angry: 8,
};

let currentTone = "neutral";
let currentMode = "casual";
let latestTimer = null;

function setState(state) {
  sphereWrap.dataset.state = state;
  stateText.textContent = state;
}

function setTone(tone) {
  if (!tone) return;
  currentTone = tone;
  toneText.textContent = tone;
  const hue = HUE[tone] ?? HUE.neutral;
  // Smoothly recolor the sphere by updating the CSS custom property
  document.documentElement.style.setProperty("--live-hue", hue);
  sphereWrap.dataset.tone = tone;
}

function setMode(mode) {
  if (!mode) return;
  currentMode = mode;
  modeText.textContent = mode;
  pMode.textContent = mode;
  sphereWrap.dataset.mode = mode;
}

function setAwake(state) {
  const label = state ? "awake" : "asleep";
  wakeText.textContent = label;
  pWake.textContent = label;
}

function showLatest(who, text, tone) {
  if (!text) return;
  latest.innerHTML = `<span class="who">${who}</span>${escapeHtml(text)}`;
  latest.classList.add("visible");
  if (latestTimer) clearTimeout(latestTimer);
  // Keep visible for a while; long sentences need more time to absorb
  const dwellMs = Math.min(12000, Math.max(4000, text.length * 70));
  latestTimer = setTimeout(() => latest.classList.remove("visible"), dwellMs);
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function appendTurn(who, ev) {
  const node = document.createElement("div");
  node.className = "turn " + (who === "you" ? "user" : "jade");
  node.innerHTML = `
    <div class="who">${who}${ev.tone ? " · " + ev.tone : ""}</div>
    <div class="text"></div>
  `;
  node.querySelector(".text").textContent = ev.text;
  log.appendChild(node);
  while (log.childElementCount > 60) log.removeChild(log.firstElementChild);
  // Only auto-scroll if the panel is already at (or near) the bottom — don't
  // yank the user back if they're reading older history.
  const nearBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 80;
  if (nearBottom) {
    requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
  }
}

function handle(ev) {
  if (!ev || !ev.type) return;
  switch (ev.type) {
    case "status":
      setState(ev.state);
      break;
    case "heard":
      if (ev.tone) setTone(ev.tone);
      if (ev.mode) setMode(ev.mode);
      showLatest("you", ev.text, ev.tone);
      appendTurn("you", ev);
      break;
    case "said":
      if (ev.tone) setTone(ev.tone);
      if (ev.mode) setMode(ev.mode);
      showLatest("jade", ev.text, ev.tone);
      appendTurn("jade", ev);
      break;
    case "wake":
      setAwake(ev.active === true);
      break;
    case "tool":
      flashTool();
      if (ev.tool) {
        addActivity(ev.tool, ev.result);
        appendTurn("jade", { text: `[${ev.tool}] ${(ev.result ?? "").toString().slice(0, 120)}`, tone: currentTone });
      }
      break;
    default:
      // ignore unknown types
  }
}

let toolFlashTimer = null;
function flashTool() {
  sphereWrap.classList.remove("tool-flash");
  void sphereWrap.offsetWidth; // restart the animation
  sphereWrap.classList.add("tool-flash");
  if (toolFlashTimer) clearTimeout(toolFlashTimer);
  toolFlashTimer = setTimeout(() => sphereWrap.classList.remove("tool-flash"), 800);
}

function addActivity(tool, result) {
  const node = document.createElement("div");
  node.className = "act";
  const r = result == null ? "" : ` — ${result.toString().slice(0, 70)}`;
  node.innerHTML = `<b></b><span></span>`;
  node.querySelector("b").textContent = tool;
  node.querySelector("span").textContent = r;
  activity.prepend(node);
  while (activity.childElementCount > 8) activity.removeChild(activity.lastElementChild);
  scheduleOverview(1500); // a tool likely changed timers/cards/spend
}

// ---- /overview panel (mood/energy + feature cards) ----
function renderOverview(d) {
  if (!d) return;
  const e = d.emotion || {};
  if (typeof e.mood === "number") moodBar.style.width = `${Math.round((e.mood + 1) / 2 * 100)}%`;
  if (typeof e.energy === "number") energyBar.style.width = `${Math.round(e.energy * 100)}%`;

  const out = [];
  const card = (h, b) => out.push(`<div class="card"><div class="card-h">${h}</div><div class="card-b">${escapeHtml(b)}</div></div>`);

  (d.timers || []).forEach((t) => {
    const s = t.seconds_left || 0;
    const left = s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
    card("timer", `${t.label} · ${left} left`);
  });
  if ((d.reminders || []).length) {
    card("reminders", d.reminders.map((r) => `${r.message} (${r.in})`).join("\n"));
  }
  if (d.flashcards_due > 0) card("flashcards", `${d.flashcards_due} card${d.flashcards_due === 1 ? "" : "s"} due`);
  if (d.spending && d.spending.total > 0) card("this week", `${d.spending.total.toFixed(2)} ${d.spending.currency} spent`);
  if (d.calendar) card("today", d.calendar);

  cards.innerHTML = out.join("");
}

let overviewTimer = null;
function pollOverview() {
  fetch("/overview").then((r) => r.json()).then(renderOverview).catch(() => {});
}
function scheduleOverview(delay) {
  if (overviewTimer) clearTimeout(overviewTimer);
  overviewTimer = setTimeout(() => { pollOverview(); loopOverview(); }, delay);
}
function loopOverview() {
  if (overviewTimer) clearTimeout(overviewTimer);
  overviewTimer = setTimeout(() => { pollOverview(); loopOverview(); }, 8000);
}

// ---- drawer toggle ----
panelToggle.addEventListener("click", () => {
  const open = document.body.classList.toggle("panel-open");
  panelToggle.setAttribute("aria-expanded", open ? "true" : "false");
  panel.setAttribute("aria-hidden", open ? "false" : "true");
  if (open) pollOverview();
});

// ---- type-to-chat ----
composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = composerInput.value.trim();
  if (!text) return;
  composerInput.value = "";
  composer.classList.add("busy");
  // Rendering happens via the heard/said events the server publishes for /chat,
  // so we don't echo here (avoids duplicate turns).
  fetch("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  })
    .catch((err) => console.error("chat failed", err))
    .finally(() => { composer.classList.remove("busy"); composerInput.focus(); });
});

function connect() {
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${proto}//${window.location.host}/events/ws`;
  const ws = new WebSocket(url);

  ws.onopen = () => setState("idle");
  ws.onmessage = (msg) => {
    try { handle(JSON.parse(msg.data)); }
    catch (e) { console.error("bad event", e, msg.data); }
  };
  ws.onclose = () => {
    setState("disconnected");
    setTimeout(connect, 2000);
  };
  ws.onerror = (e) => console.error("ws error", e);
}

// Hydrate via REST first for instant first paint, then take over with WS.
fetch("/events/recent?limit=50")
  .then((r) => r.json())
  .then((data) => (data.events || []).forEach(handle))
  .catch(() => {})
  .finally(connect);

// Prime the status panel and keep it fresh.
pollOverview();
loopOverview();
