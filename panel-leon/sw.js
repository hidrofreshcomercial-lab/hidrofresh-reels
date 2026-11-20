// Service worker mínimo para que el dashboard se pueda instalar como app.
// No guarda datos: siempre trae la versión más nueva desde internet (v14.3: la página nunca sale de la caché del navegador).
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.method !== 'GET' || new URL(e.request.url).origin !== self.location.origin) return;
  e.respondWith(fetch(e.request, e.request.mode === 'navigate' || /\.html?$|\/$/.test(new URL(e.request.url).pathname) ? { cache: 'no-store' } : undefined).catch(() => new Response(
    '<meta charset="utf-8"><body style="font-family:sans-serif;padding:40px;text-align:center"><h2>Sin conexión</h2><p>Revisa tu internet y vuelve a abrir Hidro Fresh.</p></body>',
    { headers: { 'Content-Type': 'text/html; charset=utf-8' } })));
});

// Avisos push (v9): muestra la notificación y al tocarla abre el dashboard en la oportunidad o página.
self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: 'Hidro Fresh', body: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Hidro Fresh · Mercado Público', {
    body: d.body || '', icon: 'icon-192.png', badge: 'icon-192.png', tag: d.tag || undefined, data: { url: d.url || './' },
  }));
});
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const url = new URL((e.notification.data && e.notification.data.url) || './', self.registration.scope).href;
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((ws) => {
    for (const w of ws) if (w.url.startsWith(self.registration.scope) && 'navigate' in w) return w.navigate(url).then((c) => c && c.focus());
    return self.clients.openWindow(url);
  }));
});
