const CACHE_NAME = "lifepilot-shell-v5";
const SHELL = ["/", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/icon-512.png", "/offline.html", "/offline.css", "/offline-capture.mjs", "/offline-store.mjs"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("lifepilot-shell-") && key !== CACHE_NAME).map(key => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || url.origin !== self.location.origin || request.headers.has("Authorization")) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/mcp")) return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).then(async response => response.status >= 500 ? (await caches.match("/offline.html")) || response : response).catch(async () => (await caches.match("/offline.html")) || Response.error()));
    return;
  }
  if (!SHELL.includes(url.pathname) && !url.pathname.startsWith("/_next/static/")) return;
  event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
    if (response.ok && !response.headers.get("Cache-Control")?.includes("no-store")) {
      const copy = response.clone();
      event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.put(request, copy)));
    }
    return response;
  })));
});


self.addEventListener("push", event => {
  // No private user data or provider-supplied destination is rendered.
  event.waitUntil(self.registration.showNotification("LifePilot", {
    body: "Du hast offene Erinnerungen. Öffne LifePilot für Details.",
    icon: "/icon-192.png",
    badge: "/icon-192.png",
    tag: "lifepilot-reminders"
  }));
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({type: "window", includeUncontrolled: true});
    const client = windows.find(item => new URL(item.url).origin === self.location.origin);
    if (client) return client.focus();
    return self.clients.openWindow("/");
  })());
});
