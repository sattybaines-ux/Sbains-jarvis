// Jarvis service worker: works offline for the app shell, shows morning notifications.
const SHELL = "jarvis-v3";
const FILES = ["/", "/index.html", "/styles.css", "/app.js", "/manifest.webmanifest", "/icons/icon-192.png"];

self.addEventListener("install", (e) => { e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES))); self.skipWaiting(); });
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/") || url.origin !== location.origin) return;
  // Network first so updates land straight away; cached copy when offline.
  e.respondWith(fetch(e.request).then((r) => {
    const copy = r.clone();
    caches.open(SHELL).then((c) => c.put(e.request, copy));
    return r;
  }).catch(() => caches.match(e.request)));
});

self.addEventListener("push", (e) => {
  let msg = { title: "Jarvis", body: "Your brief is ready." };
  try { msg = { ...msg, ...e.data.json() }; } catch (_) {}
  e.waitUntil(self.registration.showNotification(msg.title, { body: msg.body, icon: "/icons/icon-192.png", tag: "brief" }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: "window" }).then((list) => list.length ? list[0].focus() : clients.openWindow("/")));
});
