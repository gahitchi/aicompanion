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
  sphereWrap.dataset.mode = mode;
}

function setAwake(state) {
  wakeText.textContent = state ? "awake" : "asleep";
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
      // Tools don't get a sphere reaction; just a small log entry under jade's voice.
      if (ev.tool && ev.result) {
        appendTurn("jade", { text: `[${ev.tool}] ${ev.result.toString().slice(0, 120)}`, tone: currentTone });
      }
      break;
    default:
      // ignore unknown types
  }
}

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
