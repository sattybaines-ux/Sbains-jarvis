// Service worker: offline shell + push notifications.
const SHELL = "jarvis-shell-v2";
const FILES = ["./", "index.html", "app.js", "config.js", "manifest.webmanifest", "icons/icon-192.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET") return;
  // Network first so new briefs and app updates show up; cached copy when offline.
  e.respondWith(
    fetch(e.request, { cache: "no-store" }).then((r) => {
      const copy = r.clone();
      caches.open(SHELL).then((c) => c.put(e.request.url.split("?")[0], copy));
      return r;
    }).catch(() => caches.match(e.request.url.split("?")[0]))
  );
});

self.addEventListener("push", (e) => {
  let msg = { title: "Jarvis", body: "Your morning brief is ready." };
  try { msg = { ...msg, ...e.data.json() }; } catch (_) {}
  e.waitUntil(self.registration.showNotification(msg.title, {
    body: msg.body, icon: "icons/icon-192.png", badge: "icons/icon-192.png", tag: "brief",
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: "window" }).then((list) => {
    for (const c of list) if ("focus" in c) return c.focus();
    return clients.openWindow("./");
  }));
});
