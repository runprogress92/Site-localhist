/**
 * État partagé de l'application.
 *
 * Volontairement minimal : un objet observable, sans réactivité implicite.
 * Les vues se redessinent explicitement — plus prévisible qu'un système
 * de liaison automatique pour une application de cette taille.
 */
const listeners = new Set();

export const store = {
  athletes: [],
  config: {},
  currentAthlete: null,
  theme: localStorage.getItem('athlytics.theme') || 'dark',
  sidebarCollapsed: localStorage.getItem('athlytics.sidebar') === 'collapsed',
  period: Number(localStorage.getItem('athlytics.period') || 120),
};

export function setState(patch) {
  Object.assign(store, patch);
  listeners.forEach(fn => fn(store));
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('athlytics.theme', theme);
  setState({ theme });
}

export function toggleTheme() {
  setTheme(store.theme === 'dark' ? 'light' : 'dark');
}

export function setPeriod(days) {
  localStorage.setItem('athlytics.period', String(days));
  setState({ period: days });
}

export function athleteById(id) {
  return store.athletes.find(a => a.id === Number(id)) || null;
}
