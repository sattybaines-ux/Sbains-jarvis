// Jarvis — the iPhone app. Talks to the Jarvis server on the same address.
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; };
const pref = {
  get(k, d) { try { const v = localStorage.getItem("jarvis." + k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } },
  set(k, v) { try { localStorage.setItem("jarvis." + k, JSON.stringify(v)); } catch (_) {} },
};

let me = null, brief = null, busy = false;

async function api(path, opts = {}) {
  const r = await fetch(path, { credentials: "same-origin", ...opts,
    headers: opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json", ...(opts.headers || {}) } : opts.headers });
  if (r.status === 401 && path !== "/api/login") { showLock(); throw new Error("signed out"); }
  return r;
}

// ---------- theme ----------
function applyTheme() {
  const t = pref.get("theme", "auto");
  if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = t;
  $("theme").textContent = { auto: "Automatic", light: "Light", dark: "Dark" }[t];
}
$("theme").onclick = () => { const order = ["auto", "dark", "light"]; pref.set("theme", order[(order.indexOf(pref.get("theme", "auto")) + 1) % 3]); applyTheme(); };
applyTheme();

// ---------- views ----------
function show(view) {
  for (const v of ["home", "chat", "settings"]) $(v).classList.toggle("hidden", v !== view);
  for (const t of document.querySelectorAll(".tab")) t.setAttribute("aria-selected", t.dataset.view === view);
  $("composer").classList.toggle("hidden", view !== "chat");
  if (view === "chat") setTimeout(() => window.scrollTo(0, document.body.scrollHeight), 50);
}
for (const t of document.querySelectorAll(".tab")) t.onclick = () => show(t.dataset.view);

function showLock() {
  $("lock").classList.remove("hidden");
  for (const id of ["home", "chat", "settings", "tabs", "composer"]) $(id).classList.add("hidden");
}

// ---------- sign in ----------
$("unlock").onclick = async () => {
  $("lockErr").textContent = "";
  const r = await api("/api/login", { method: "POST", body: JSON.stringify({ passphrase: $("pass").value }) });
  if (!r.ok) { $("lockErr").textContent = (await r.json().catch(() => ({}))).detail || "That didn't work."; return; }
  $("pass").value = "";
  boot();
};
$("pass").onkeydown = (e) => { if (e.key === "Enter") $("unlock").click(); };

// ---------- home ----------
function partOfDay() { const h = new Date().getHours(); return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening"; }

function renderHeader() {
  const now = new Date();
  $("today").textContent = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  $("greet").replaceChildren(document.createTextNode(`Good ${partOfDay()}, `), el("em", null, (me && me.name) || "Satty"));
}

function renderBrief(d) {
  brief = d;
  renderHeader();
  if (!d) {
    $("brief").replaceChildren(el("p", null, "No brief yet. Tap refresh and I'll put one together."));
    return;
  }
  const made = new Date(d.generatedAt), today = made.toDateString() === new Date().toDateString();
  $("stamp").textContent = (today ? "" : made.toLocaleDateString([], { weekday: "short" }) + " ") +
    made.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  $("stamp").classList.toggle("stale", !today);
  $("briefMeta").textContent = d.quick ? "Refreshed" : "Morning";
  $("brief").replaceChildren(...d.brief.map((l) => el("p", null, l)));

  const n = d.numbers || {}, v = (x) => (x === null || x === undefined ? "—" : x);
  const stats = [["Meetings", n.meetingsToday, "--peri"], ["Need reply", n.needsReply, "--apricot"], ["Drafts", n.draftsCreated, "--mint"],
                 ["Need prep", n.needsPrep, "--sky"], ["Conflicts", n.conflicts, "--rose"], ["Due today", n.tasksDueToday, "--gold"]];
  $("stats").replaceChildren(...stats.map(([label, val, c]) => {
    const s = el("div", "stat"); s.style.setProperty("--accent", `var(${c})`); s.append(el("b", null, v(val)), el("span", null, label)); return s;
  }));

  $("top3").replaceChildren(...(d.top3 || []).map((t) => { const li = el("li"); const b = el("div", null, t.item); b.append(el("span", "why", t.why)); li.append(b); return li; }));
  $("know").textContent = d.oneThing || "";
  $("know").classList.toggle("hidden", !d.oneThing);

  const tl = [], nowIso = localIso(new Date());
  let nowShown = false;
  for (const e of d.schedule || []) {
    if (!nowShown && e.start && !e.past && e.start > nowIso) { tl.push(el("div", "now", "Now")); nowShown = true; }
    const row = el("div", "ev" + (e.past ? " past" : ""));
    row.style.setProperty("--dot", e.source === "Google" ? "var(--mint)" : "var(--peri)");
    const title = el("div", "title", e.title);
    if (e.needsPrep) { const t = el("span", "tag", "prep"); t.style.setProperty("--c", "var(--apricot)"); title.append(t); }
    row.append(el("div", "t", `${e.time} · ${e.source}`), title);
    tl.push(row);
  }
  if (!tl.length) tl.push(el("div", "note", "Nothing on the calendar."));
  for (const c of d.conflicts || []) tl.push(el("div", "note", "⚠︎ Overlap: " + c));
  if ((d.focusGaps || []).length) tl.push(el("div", "note", "Focus time: " + d.focusGaps.join(", ")));
  $("timeline").replaceChildren(...tl);
  $("schedMeta").textContent = `${(d.schedule || []).filter((e) => !e.past).length} left`;

  const drafts = d.drafts || [];
  $("drafts").replaceChildren(...(drafts.length ? drafts.map((x) => {
    const li = el("li", null, x.label);
    li.append(el("small", null, x.needsReply ? "Needs a reply. Ask me to draft it" : x.alreadyWaiting ? `Already waiting in ${x.source}` :
      x.created ? `Saved in ${x.source} drafts` : "Handle yourself"));
    return li;
  }) : [el("li", "note", "Nothing waiting.")]));

  $("sources").replaceChildren(...Object.values(d.connectors || {}).map((c) => {
    const s = el("span", "src"); s.title = c.log; s.append(el("i", c.status), c.label); return s;
  }));
}

function localIso(d) {
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

async function loadBrief() {
  const r = await api("/api/brief");
  renderBrief(r.ok ? await r.json() : null);
}

$("refresh").onclick = async () => {
  if ($("refresh").classList.contains("spin")) return;
  $("refresh").classList.add("spin");
  $("stamp").textContent = "Updating…";
  $("hint").textContent = "Writing a fresh brief…";
  try {
    const r = await api("/api/refresh", { method: "POST" });
    if (r.ok) { renderBrief(await r.json()); $("hint").textContent = "Tap to talk"; }
    else {
      $("stamp").textContent = "Couldn't refresh";
      const why = (await r.json().catch(() => ({}))).detail;
      if (why) $("hint").textContent = "Refresh failed: " + why;
    }
  } catch (_) { $("stamp").textContent = "Offline"; }
  $("refresh").classList.remove("spin");
};

$("playBrief").onclick = () => { unlockAudio(); if (brief) say(brief.brief.join(" ")); };

const CHIPS = [["What's next?", "What's my next meeting and do I need to prep for it?"],
               ["Inbox", "Catch me up on email from today. Anything that needs me?"],
               ["Plan", "Help me plan the rest of my day around my top priorities."],
               ["Urgent?", "Is anything urgent or slipping that I should know about?"]];
$("chips").replaceChildren(...CHIPS.map(([label, prompt]) => {
  const c = el("button", "chip", label);
  c.onclick = () => { show("chat"); send(prompt, false); };
  return c;
}));

// ---------- conversation ----------
function bubble(cls, text) { const b = el("div", "msg " + cls, text); $("messages").append(b); scrollChat(); return b; }
function scrollChat() { if (!$("chat").classList.contains("hidden")) window.scrollTo(0, document.body.scrollHeight); }

async function send(text, voice) {
  text = text.trim();
  if (!text || busy) return;
  busy = true;
  bubble("me", text);
  const reply = bubble("jarvis", "");
  const status = el("span", "tool", "Thinking…");
  reply.append(status);
  setOrb("thinking", "Thinking…");
  let full = "", sentences = "";
  try {
    const r = await api("/api/chat", { method: "POST", body: JSON.stringify({ message: text, voice }) });
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const line = buf.slice(0, i).replace(/^data: /, ""); buf = buf.slice(i + 2);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "text") {
          full += ev.delta; status.textContent = "";
          reply.textContent = full; scrollChat();
          if (voice && pref.get("speak", true)) {
            sentences += ev.delta;
            const m = sentences.match(/^([\s\S]*?[.!?])\s/);
            if (m) { say(m[1]); sentences = sentences.slice(m[0].length); }
          }
        } else if (ev.type === "turn" && full && !full.endsWith("\n")) { full += "\n\n"; }
        else if (ev.type === "tool") { status.textContent = ev.label + "…"; if (!reply.contains(status)) reply.prepend(status); setOrb("thinking", ev.label + "…"); }
        else if (ev.type === "confirm") { confirmCard(ev); }
        else if (ev.type === "error") { full += (full ? "\n" : "") + ev.message; reply.textContent = full; }
      }
    }
    if (voice && pref.get("speak", true) && sentences.trim()) say(sentences.trim());
  } catch (e) {
    if (e.message !== "signed out") reply.textContent = "I can't reach the server right now.";
  }
  if (!full.trim() && !reply.textContent.trim()) reply.textContent = "Done.";
  $("hint").textContent = (full.trim().split("\n").pop() || "Tap to talk").slice(0, 160);
  if (!speaking()) setOrb("idle");
  busy = false;
}

function confirmCard(ev) {
  const card = el("div", "confirm");
  card.append(el("div", null, ev.summary));
  const row = el("div", "row"), yes = el("button", "btn primary", "Confirm"), no = el("button", "btn", "Cancel");
  const decide = async (approve) => {
    row.remove();
    const r = await api("/api/confirm", { method: "POST", body: JSON.stringify({ id: ev.id, approve }) });
    card.append(el("div", "note", (await r.json()).message));
  };
  yes.onclick = () => decide(true); no.onclick = () => decide(false);
  row.append(no, yes); card.append(row);
  $("messages").append(card); scrollChat();
}

$("ask").onsubmit = (e) => { e.preventDefault(); const v = $("askInput").value; $("askInput").value = ""; send(v, false); };
$("newChat").onclick = async () => { await api("/api/chat/reset", { method: "POST" }); $("messages").replaceChildren(); greetChat(); };
function greetChat() { if (!$("messages").children.length) bubble("jarvis", `Good ${partOfDay()}. What can I do for you?`); }

// ---------- voice ----------
let recorder = null, chunks = [], stopTimer = null, current = null, speechQueue = Promise.resolve(), pending = 0;

function setOrb(state, hint) { $("orb").dataset.state = state; if (hint) $("hint").textContent = hint;
  $("orb").querySelector("use").setAttribute("href", state === "listening" ? "#i-stop" : "#i-mic"); }
function speaking() { return pending > 0; }

let audioCtx = null;
function unlockAudio() {
  // iPhone only plays sound that starts from a tap: wake both audio paths while the finger is down.
  try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); audioCtx.resume(); } catch (_) {}
  try { speechSynthesis.speak(new SpeechSynthesisUtterance("")); } catch (_) {}
}

function playMp3(buf) {
  return new Promise(async (res) => {
    try {
      const src = audioCtx.createBufferSource();
      src.buffer = await audioCtx.decodeAudioData(buf);
      src.connect(audioCtx.destination); src.onended = res; src.start(); current = src;
    } catch (_) { res(); }
  });
}

function say(text) {
  pending++;
  setOrb("speaking");
  speechQueue = speechQueue.then(async () => {
    try {
      const r = me && me.voice ? await api("/api/speak", { method: "POST", body: JSON.stringify({ text }) }) : null;
      if (r && r.status === 200 && audioCtx) {
        await playMp3(await r.arrayBuffer());
      } else {
        await new Promise((res) => {
          const u = new SpeechSynthesisUtterance(text);
          const v = speechSynthesis.getVoices().find((x) => /Daniel|Arthur|en-GB/.test(x.name + x.lang));
          if (v) u.voice = v;
          u.rate = 1.04; u.onend = res; u.onerror = res;
          speechSynthesis.speak(u);
        });
      }
    } catch (_) {}
    if (--pending === 0 && !busy) setOrb("idle");
  });
}

async function startListening() {
  unlockAudio();
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const type = ["audio/mp4", "audio/webm"].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || "";
    recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      clearTimeout(stopTimer);
      setOrb("thinking", "Listening back…");
      const form = new FormData();
      form.append("audio", new Blob(chunks, { type: recorder.mimeType || "audio/mp4" }), "speech." + ((recorder.mimeType || "").includes("webm") ? "webm" : "m4a"));
      try {
        const r = await api("/api/transcribe", { method: "POST", body: form });
        const { text } = r.ok ? await r.json() : { text: "" };
        if (!text) { setOrb("idle", r.ok ? "I didn't catch that. Tap to try again." : "Voice isn't available; type instead."); return; }
        send(text, true);
      } catch (_) { setOrb("idle", "I can't reach the server."); }
    };
    recorder.start();
    setOrb("listening", "Listening… tap to finish");
    stopTimer = setTimeout(() => recorder && recorder.state === "recording" && recorder.stop(), 30000);
  } catch (_) {
    setOrb("idle", "Allow the microphone for Jarvis in Settings to talk.");
  }
}

function toggleTalk() {
  if (recorder && recorder.state === "recording") { recorder.stop(); return; }
  if (speaking()) { speechSynthesis.cancel(); try { current && current.stop(); } catch (_) {} pending = 0; setOrb("idle", "Tap to talk"); return; }
  if (!busy) startListening();
}
$("orb").onclick = toggleTalk;
$("askMic").onclick = toggleTalk;

// ---------- settings ----------
function renderSettings() {
  $("speakToggle").textContent = pref.get("speak", true) ? "On" : "Off";
  $("connected").textContent = me && me.connected.length ? me.connected.join(" · ") : "Nothing yet";
}
$("speakToggle").onclick = () => { pref.set("speak", !pref.get("speak", true)); renderSettings(); };

$("notify").onclick = async () => {
  try {
    if (!("PushManager" in window)) throw new Error("Open Jarvis from your Home Screen icon first.");
    if ((await Notification.requestPermission()) !== "granted") throw new Error("Notifications weren't allowed.");
    const reg = await navigator.serviceWorker.ready, key = me.vapidPublicKey;
    const raw = Uint8Array.from(atob(key.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((key.length + 3) % 4)), (c) => c.charCodeAt(0));
    const sub = (await reg.pushManager.getSubscription()) || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: raw }));
    await api("/api/push/subscribe", { method: "POST", body: JSON.stringify(sub) });
    $("notifyState").textContent = "On. You'll get a ping each morning.";
    $("notify").textContent = "On";
  } catch (e) { $("notifyState").textContent = e.message; }
};

// ---------- start ----------
async function boot() {
  const r = await fetch("/api/me", { credentials: "same-origin" }).catch(() => null);
  if (!r || r.status === 401) { showLock(); return; }
  me = await r.json();
  $("lock").classList.add("hidden");
  $("tabs").classList.remove("hidden");
  show("home");
  renderHeader(); renderSettings(); greetChat();
  await loadBrief();
}

document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && me) loadBrief().catch(() => {}); });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
boot();
