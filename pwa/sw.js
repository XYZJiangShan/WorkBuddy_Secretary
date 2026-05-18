/* DeskSecretary PWA Service Worker
   策略：
   - 静态资源 (HTML/CSS/JS/图标) → cache-first（首次安装后离线可用）
   - GitHub API 请求 → 不缓存（始终网络优先），失败时由 app.js 用 localStorage 回退
*/

const VERSION = "v1.0.0";
const CACHE_NAME = `desksec-pwa-${VERSION}`;
const PRECACHE_URLS = [
  "./",
  "index.html",
  "style.css",
  "app.js",
  "manifest.json",
  "icon-192.png",
  "icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      cache.addAll(PRECACHE_URLS).catch((err) => {
        console.warn("[SW] precache partial failed", err);
      })
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => k.startsWith("desksec-pwa-") && k !== CACHE_NAME)
          .map((k) => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  // GitHub API 不缓存（每次都拉最新数据）
  if (url.hostname === "api.github.com" || url.hostname === "raw.githubusercontent.com") {
    return;
  }

  // 同源静态资源：cache-first
  if (event.request.method === "GET" && url.origin === self.location.origin) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request).then((res) => {
          // 200 才缓存
          if (res && res.status === 200 && res.type === "basic") {
            const clone = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return res;
        }).catch(() => caches.match("./index.html"));
      })
    );
  }
});
