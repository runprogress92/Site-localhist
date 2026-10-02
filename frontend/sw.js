/**
 * Service worker d'Athlytics.
 *
 * Deux stratégies, parce que les deux types de contenu n'ont pas les mêmes
 * exigences :
 *
 *   • La **coquille** (HTML, CSS, JavaScript, icônes) change seulement quand
 *     l'application est mise à jour : elle est servie depuis le cache, et
 *     rafraîchie en arrière-plan. L'application s'ouvre donc instantanément,
 *     même sans réseau.
 *
 *   • Les **données** (/api/) doivent être fraîches : on interroge toujours
 *     le réseau d'abord. En cas d'échec seulement, on sert la dernière
 *     réponse connue, en la marquant d'un en-tête que l'interface lit pour
 *     avertir l'utilisateur qu'il consulte des données d'hier.
 *
 * Les écritures (POST, PATCH, DELETE) ne sont jamais mises en cache ni
 * rejouées : enregistrer en silence un questionnaire qui n'est jamais
 * parvenu au serveur serait pire que de le refuser franchement.
 *
 * Note : un service worker exige une origine sûre (HTTPS ou localhost).
 * Consulté depuis un téléphone via l'adresse locale du PC en HTTP, il ne
 * s'enregistrera pas — l'application fonctionne alors normalement, mais
 * sans mode hors ligne. C'est prévu et sans conséquence.
 */
const VERSION = 'athlytics-v1';
const SHELL_CACHE = `${VERSION}-shell`;
const DATA_CACHE = `${VERSION}-data`;

const SHELL = [
  '/',
  '/index.html',
  '/css/tokens.css',
  '/css/base.css',
  '/css/layout.css',
  '/css/components.css',
  '/css/charts.css',
  '/css/views.css',
  '/css/mobile.css',
  '/js/main.js',
  '/js/lib/dom.js',
  '/js/lib/format.js',
  '/js/lib/api.js',
  '/js/lib/router.js',
  '/js/lib/store.js',
  '/js/lib/ui.js',
  '/js/lib/viewport.js',
  '/js/lib/mobilenav.js',
  '/js/lib/pwa.js',
  '/js/charts/core.js',
  '/js/charts/plots.js',
  '/js/charts/streams.js',
  '/manifest.webmanifest',
  '/assets/icons/icon-192.png',
  '/assets/icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE);
    // addAll échoue en bloc si une seule ressource manque : on ajoute une à
    // une pour qu'un fichier renommé n'empêche pas toute l'installation.
    await Promise.all(SHELL.map(url =>
      cache.add(url).catch(() => console.warn('[sw] non mis en cache :', url))));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names
      .filter(name => !name.startsWith(VERSION))
      .map(name => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data === 'skip-waiting') self.skipWaiting();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;            // écritures : jamais interceptées

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Exports et téléchargements : toujours le réseau, jamais le cache.
  if (url.pathname.includes('/export') || url.pathname.endsWith('.fit')
      || url.pathname.endsWith('.gpx') || url.pathname.includes('/backup')) {
    return;
  }

  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request));
    return;
  }
  event.respondWith(staleWhileRevalidate(request));
});

/** Données : réseau d'abord, dernière réponse connue en secours. */
async function networkFirst(request) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const response = await fetch(request);
    if (response.ok) {
      // On conserve l'heure de mise en cache pour que l'interface puisse
      // dire « données d'il y a deux heures » plutôt qu'un vague « hors ligne ».
      const copy = response.clone();
      const body = await copy.blob();
      const headers = new Headers(copy.headers);
      headers.set('X-Athlytics-Cached-At', new Date().toISOString());
      cache.put(request, new Response(body, {
        status: copy.status, statusText: copy.statusText, headers,
      }));
    }
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) {
      const headers = new Headers(cached.headers);
      headers.set('X-Athlytics-Offline', '1');
      return new Response(await cached.blob(), {
        status: 200, statusText: 'OK (hors ligne)', headers,
      });
    }
    return new Response(
      JSON.stringify({
        error: 'Hors ligne et aucune donnée en mémoire pour cette page.',
        offline: true,
      }),
      { status: 503, headers: { 'Content-Type': 'application/json' } });
  }
}

/** Coquille : cache d'abord, rafraîchissement en arrière-plan. */
async function staleWhileRevalidate(request) {
  const cache = await caches.open(SHELL_CACHE);
  const cached = await cache.match(request);
  const network = fetch(request).then((response) => {
    if (response.ok) cache.put(request, response.clone());
    return response;
  }).catch(() => null);

  if (cached) return cached;
  const response = await network;
  if (response) return response;

  // Navigation hors ligne vers une page jamais visitée : on sert la coquille,
  // le routeur côté client se chargera du reste.
  if (request.mode === 'navigate') {
    const shell = await cache.match('/index.html');
    if (shell) return shell;
  }
  return new Response('Hors ligne', { status: 503, statusText: 'Hors ligne' });
}
