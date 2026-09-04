/**
 * Routeur à ancre (#/chemin).
 *
 * Les motifs acceptent des segments dynamiques `:nom`. Le routeur gère
 * l'annulation : si l'utilisateur navigue pendant un chargement, le rendu
 * obsolète n'écrase pas le nouveau (jeton de génération).
 */
const routes = [];
let notFound = null;
let generation = 0;
let currentPath = '';

export function route(pattern, handler, meta = {}) {
  const keys = [];
  const regex = new RegExp(`^${pattern.replace(/:([\w]+)/g, (_, key) => {
    keys.push(key);
    return '([^/]+)';
  }).replace(/\//g, '\\/')}$`);
  routes.push({ pattern, regex, keys, handler, meta });
}

export function setNotFound(handler) { notFound = handler; }

export function navigate(path, { replace = false } = {}) {
  const target = path.startsWith('#') ? path : `#${path}`;
  if (replace) window.history.replaceState(null, '', target);
  else window.location.hash = target;
  if (replace) resolve();
}

export function currentRoute() { return currentPath; }

export function params(pattern) {
  for (const entry of routes) {
    if (entry.pattern !== pattern) continue;
    const match = entry.regex.exec(currentPath);
    if (!match) return null;
    return Object.fromEntries(entry.keys.map((k, i) => [k, match[i + 1]]));
  }
  return null;
}

/** Jeton d'annulation : `token.stale` devient vrai si on a navigué depuis. */
export function guard() {
  const mine = generation;
  return { get stale() { return mine !== generation; } };
}

export async function resolve() {
  const hash = window.location.hash.slice(1) || '/';
  currentPath = hash.split('?')[0];
  generation += 1;
  const query = Object.fromEntries(new URLSearchParams(hash.split('?')[1] || ''));

  for (const entry of routes) {
    const match = entry.regex.exec(currentPath);
    if (!match) continue;
    const routeParams = Object.fromEntries(entry.keys.map((k, i) => [k, match[i + 1]]));
    try {
      await entry.handler({ params: routeParams, query, path: currentPath,
                            meta: entry.meta, token: guard() });
    } catch (error) {
      console.error(`Erreur sur la route ${currentPath}`, error);
      const { renderError } = await import('../views/error.js');
      renderError(error);
    }
    return;
  }
  if (notFound) notFound({ path: currentPath });
}

export function start() {
  window.addEventListener('hashchange', resolve);
  resolve();
}
