// Jarvis iPhone app: fetch the encrypted brief, decrypt it on-device, render it.
const $ = (id) => document.getElementById(id);
const KEY = "jarvis-passphrase";
const store = {
  get() { try { return localStorage.getItem(KEY); } catch (_) { return null; } },
  set(v) { try { localStorage.setItem(KEY, v); } catch (_) {} },
  clear() { try { localStorage.removeItem(KEY); } catch (_) {} },
};
const fromB64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));

async function decrypt(box, passphrase) {
  const base = await crypto.subtle.importKey("raw", new TextEncoder().encode(passphrase), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name: "PBKDF2", hash: "SHA-256", salt: fromB64(box.salt), iterations: box.iter },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: fromB64(box.iv) }, key, fromB64(box.ct));
  return JSON.parse(new TextDecoder().decode(plain));
}

function el(tag, text, cls) {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (cls) n.className = cls;
  return n;
}

function render(d) {
  $("date").textContent = d.dateLabel;
  $("updated").textContent = "Updated " + new Date(d.generatedAt).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  $("brief").replaceChildren(...d.brief.map((l) => el("p", l)));
  if (d.audio) {
    const blob = new Blob([fromB64(d.audio)], { type: "audio/mpeg" });
    $("audio").src = URL.createObjectURL(blob);
    $("audio").classList.remove("hidden");
  }

  const n = d.numbers, show = (v) => (v === null || v === undefined ? "—" : v);
  const tiles = [["Meetings", n.meetingsToday], ["Need prep", n.needsPrep], ["Conflicts", n.conflicts],
                 ["Need reply", n.needsReply], ["Drafts", n.draftsCreated], ["Due today", n.tasksDueToday]];
  $("tiles").replaceChildren(...tiles.map(([label, v]) => {
    const t = el("div", undefined, "tile"); t.append(el("b", show(v)), el("span", label)); return t;
  }));

  $("top3").replaceChildren(...d.top3.map((t) => { const li = el("li", t.item); li.append(el("small", t.why)); return li; }));
  const one = el("li", d.oneThing); one.style.listStyle = "none"; one.style.marginLeft = "-20px"; one.style.color = "var(--muted)";
  $("top3").append(one);

  const sched = d.schedule.length ? d.schedule.map((e) => {
    const r = el("div", undefined, "row"), t = el("div", e.time, "time"), title = el("div", e.title);
    title.append(el("span", e.source, "tag"));
    if (e.needsPrep) title.append(el("span", "prep", "tag prep"));
    r.append(t, title); return r;
  }) : [el("div", "Nothing on the calendar.", "sub")];
  for (const c of d.conflicts) sched.push(el("div", "⚠︎ Conflict: " + c, "sub"));
  if (d.focusGaps.length) sched.push(el("div", "Focus time: " + d.focusGaps.join(", "), "sub"));
  $("schedule").replaceChildren(...sched);

  $("drafts").replaceChildren(...(d.drafts.length ? d.drafts.map((x) => {
    const li = el("li", x.label); li.append(el("small", x.created ? `Draft saved in ${x.source}` : "Not drafted")); return li;
  }) : [el("li", "None.")]));

  $("suspiciousCard").classList.toggle("hidden", !d.suspicious.length);
  $("suspicious").replaceChildren(...d.suspicious.map((s) => el("li", s)));

  $("sources").replaceChildren(...Object.values(d.connectors).map((c) => {
    const row = el("div", undefined, "src"); row.append(el("span", undefined, "dot " + c.status), c.label + " · " + c.status);
    row.append(el("small", c.log)); return row;
  }));

  $("lock").classList.add("hidden");
  $("content").classList.remove("hidden");
}

async function load() {
  const pass = store.get();
  if (!pass) { $("lock").classList.remove("hidden"); return; }
  try {
    const r = await fetch("data/latest.json?t=" + Date.now());
    if (!r.ok) throw new Error("No brief published yet.");
    render(await decrypt(await r.json(), pass));
  } catch (e) {
    const wrongPass = e.name === "OperationError";
    if (wrongPass) store.clear();
    $("lockErr").textContent = wrongPass ? "That passphrase didn't work." : e.message;
    $("lock").classList.remove("hidden");
  }
}

$("unlock").onclick = () => { store.set($("pass").value); $("lockErr").textContent = ""; load(); };
$("pass").onkeydown = (e) => { if (e.key === "Enter") $("unlock").click(); };
$("forget").onclick = () => { store.clear(); location.reload(); };
$("copy").onclick = () => navigator.clipboard.writeText($("sub").value);

$("notify").onclick = async () => {
  try {
    if (!("PushManager" in window)) throw new Error("Add Jarvis to your Home Screen first (Share → Add to Home Screen), then open it from there.");
    if ((await Notification.requestPermission()) !== "granted") throw new Error("Notifications were not allowed.");
    const reg = await navigator.serviceWorker.ready;
    const key = window.JARVIS_CONFIG.vapidPublicKey;
    if (!key) throw new Error("The VAPID public key isn't configured yet (see README).");
    const raw = fromB64(key.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((key.length + 3) % 4));
    const sub = (await reg.pushManager.getSubscription()) ||
      (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: raw }));
    $("sub").value = JSON.stringify(sub);
    $("subBox").classList.remove("hidden");
  } catch (e) { alert(e.message); }
};

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js");
load();
