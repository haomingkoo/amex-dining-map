// Service Worker for Amex Dining Map PWA
const CACHE_NAME = "amex-dining-v1";
const URLS_TO_CACHE = [
  "/",
  "/index.html",
  "/app.js",
  "/i18n.js",
  "/styles.css",
  "/manifest.json",
  "/robots.txt",
  "/sitemap.xml",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css",
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js",
  "https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.css",
  "https://cdn.jsdelivr.net/npm/flatpickr/dist/flatpickr.min.js",
  "https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;0,700;1,300;1,400;1,500;1,600&family=Figtree:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400&display=swap"
];

// Install event - cache app shell
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        return cache.addAll(URLS_TO_CACHE).catch(() => {
          // Partial cache OK - don't fail if external resources unavailable
          return cache.addAll(URLS_TO_CACHE.filter(url => !url.includes("http")));
        });
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event - clean up old caches
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((cacheName) => cacheName !== CACHE_NAME)
            .map((cacheName) => caches.delete(cacheName))
        );
      })
      .then(() => self.clients.claim())
  );
});

// Fetch event - network first, fall back to cache
self.addEventListener("fetch", (event) => {
  // Skip non-GET requests
  if (event.request.method !== "GET") return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Cache successful responses
        if (response.ok) {
          const responseToCache = response.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(event.request, responseToCache);
          });
        }
        return response;
      })
      .catch(() => {
        // Return cached version on network failure
        return caches.match(event.request)
          .then((response) => {
            return response || new Response("Offline - resource not cached", {
              status: 503,
              statusText: "Service Unavailable",
              headers: new Headers({ "Content-Type": "text/plain" })
            });
          });
      })
  );
});

// Background sync for favorites and trips
self.addEventListener("sync", (event) => {
  if (event.tag === "sync-data") {
    event.waitUntil(
      // Sync favorites and trips data
      Promise.resolve()
    );
  }
});
