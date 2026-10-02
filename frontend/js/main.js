/**
 * Point d'entrée de l'application.
 *
 * Charge la configuration et le roster, construit la barre latérale, puis
 * délègue au routeur. Chaque vue est importée à la demande : le premier
 * affichage ne télécharge que ce qu'il montre.
 */
import { api } from './lib/api.js';
import { $, clear, el, icon, mount } from './lib/dom.js';
import * as F from './lib/format.js';
import { navigate, resolve as resolveCurrent, route, setNotFound, start,
         currentRoute } from './lib/router.js';
import { setState, setTheme, store, subscribe, toggleTheme } from './lib/store.js';
import { onLayoutChange, viewport } from './lib/viewport.js';
import { removeBottomNav, renderBottomNav } from './lib/mobilenav.js';
import { initPwa } from './lib/pwa.js';
import { emptyState, loading, notifyError, setTopbar, toast } from './lib/ui.js';

const content = () => document.getElementById('content');

/* ------------------------------------------------------------ navigation */
const NAV_SECTIONS = [
  {
    title: 'Suivi',
    items: [
      { path: '/', label: "Vue d'ensemble", icon: 'dashboard' },
      { path: '/bien-etre', label: 'Bien-être du jour', icon: 'heart' },
      { path: '/calendrier', label: 'Calendrier', icon: 'calendar' },
      { path: '/seances', label: 'Séances', icon: 'activity' },
    ],
  },
  {
    title: 'Analyse',
    items: [
      { path: '/analyse', label: 'Comparaison', icon: 'chart' },
      { path: '/charge', label: 'Charge du groupe', icon: 'layers' },
    ],
  },
  {
    title: 'Système',
    items: [
      { path: '/connexions', label: 'Montres', icon: 'watch' },
      { path: '/reglages', label: 'Réglages', icon: 'settings' },
    ],
  },
];

function renderSidebar() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('collapsed', store.sidebarCollapsed);
  const path = currentRoute();
  const alertCount = store.athletes.reduce(
    (sum, a) => sum + (a.alerts || []).filter(x => x.severity !== 'info').length, 0);

  mount(sidebar, [
    el('div.brand', [
      el('div.brand-mark', 'A'),
      el('div.brand-text', [
        el('span.brand-name', 'Athlytics'),
        el('span.brand-sub', 'Suivi de performance'),
      ]),
    ]),
    el('nav.nav', [
      ...NAV_SECTIONS.map(section => el('div.nav-section', [
        el('div.nav-section-title', section.title),
        ...section.items.map(item => el(
          `button.nav-item${path === item.path ? '.active' : ''}`,
          { onclick: () => navigate(item.path), title: item.label },
          [
            icon(item.icon, 'nav-icon'),
            el('span.nav-label', item.label),
            item.path === '/' && alertCount
              ? el('span.nav-badge', String(alertCount)) : null,
          ])),
      ])),
      store.athletes.length ? el('div.nav-section', [
        el('div.nav-section-title', `Athlètes · ${store.athletes.length}`),
        ...store.athletes.map(athlete => el(
          `button.nav-athlete${path.startsWith(`/athlete/${athlete.id}`) ? '.active' : ''}`,
          { onclick: () => navigate(`/athlete/${athlete.id}`) },
          [
            el('span.dot', { style: { background: readinessDot(athlete) } }),
            el('span.nav-label.truncate',
               `${athlete.first_name} ${athlete.last_name}`),
          ])),
        el('button.nav-athlete', {
          onclick: async () => {
            const { openAthleteForm } = await import('./views/athlete-form.js');
            openAthleteForm(null, refreshRoster);
          },
        }, [icon('plus', 'nav-icon'), el('span.nav-label', 'Ajouter un athlète')]),
      ]) : null,
    ]),
    el('div.sidebar-foot', [
      el('button.btn.ghost.icon', {
        onclick: () => { toggleTheme(); renderSidebar(); },
        title: store.theme === 'dark' ? 'Passer en thème clair' : 'Passer en thème sombre',
      }, [icon(store.theme === 'dark' ? 'sun' : 'moon')]),
      el('button.btn.ghost.icon', {
        onclick: () => {
          const collapsed = !store.sidebarCollapsed;
          localStorage.setItem('athlytics.sidebar', collapsed ? 'collapsed' : 'open');
          setState({ sidebarCollapsed: collapsed });
          renderSidebar();
        },
        title: store.sidebarCollapsed ? 'Déplier le menu' : 'Replier le menu',
      }, [icon('menu')]),
      el('span.sidebar-foot-text.faint', { style: { fontSize: '11px', marginLeft: 'auto' } },
         'v1.0'),
    ]),
  ]);
}

function readinessDot(athlete) {
  if (athlete.status === 'injured') return 'var(--danger)';
  return F.readinessColor(athlete.readiness_flag);
}

/* ---------------------------------------------------------------- routes */
function view(loader) {
  return async (context) => {
    mount(content(), loading());
    const module = await loader();
    if (context.token.stale) return;
    await module.render(content(), context);
    if (context.token.stale) return;
    renderNav();
    content().scrollTop = 0;
  };
}

/** Dessine la navigation adaptée au format courant. */
export function renderNav() {
  if (viewport.isMobile) {
    removeSidebarContent();
    renderBottomNav();
  } else {
    removeBottomNav();
    renderSidebar();
  }
}

function removeSidebarContent() {
  // La barre latérale est masquée en CSS ; on vide aussi son contenu pour
  // qu'elle ne garde pas en mémoire des gestionnaires inutiles.
  const sidebar = document.getElementById('sidebar');
  if (sidebar && sidebar.childElementCount) clear(sidebar);
}

route('/',            view(() => import('./views/dashboard.js')));
route('/bien-etre',   view(() => import('./views/wellness.js')));
route('/calendrier',  view(() => import('./views/calendar.js')));
route('/seances',     view(() => import('./views/activities.js')));
route('/analyse',     view(() => import('./views/analysis.js')));
route('/charge',      view(() => import('./views/teamload.js')));
route('/connexions',  view(() => import('./views/devices.js')));
route('/reglages',    view(() => import('./views/settings.js')));
route('/athlete/:id', view(() => import('./views/athlete.js')));
route('/athlete/:id/:tab', view(() => import('./views/athlete.js')));
route('/seance/:id',  view(() => import('./views/activity.js')));

setNotFound(({ path }) => {
  setTopbar([el('h1', 'Page introuvable')]);
  mount(content(), emptyState(
    'Cette page n’existe pas',
    `Aucune vue ne correspond à « ${path} ».`,
    el('button.btn.primary', { onclick: () => navigate('/') },
       "Revenir à la vue d'ensemble")));
});

/* ------------------------------------------------------------ démarrage */
async function boot() {
  setTheme(store.theme);
  try {
    const [config, roster] = await Promise.all([api.config(), api.athletes()]);
    setState({ config: config.config, sports: config.sports, athletes: roster.athletes });
  } catch (error) {
    console.error(error);
    mount(content(), emptyState(
      'Serveur injoignable',
      "L'interface n'arrive pas à contacter l'API. Vérifiez que « python3 run.py » "
      + 'tourne toujours dans votre terminal, puis rechargez la page.',
      el('button.btn.primary', { onclick: () => window.location.reload() }, 'Recharger'),
      'alert'));
    return;
  }
  initPwa();
  renderNav();
  // Rotation du téléphone ou redimensionnement de la fenêtre : on repasse
  // d'une navigation à l'autre et on redessine la vue courante.
  onLayoutChange(() => { renderNav(); resolveCurrent(); });
  subscribe(() => { /* la navigation est redessinée explicitement */ });
  start();

  // raccourcis clavier
  document.addEventListener('keydown', (event) => {
    if (event.target.matches('input, textarea, select')) return;
    if (event.key === '/') {
      event.preventDefault();
      const search = document.querySelector('.search-box input');
      if (search) search.focus();
      else navigate('/seances');
    }
    if (event.key === 'g') window.__athlyticsGoto = true;
    else if (window.__athlyticsGoto) {
      const map = { d: '/', c: '/calendrier', s: '/seances', a: '/analyse',
                    b: '/bien-etre', m: '/connexions', r: '/reglages' };
      if (map[event.key]) navigate(map[event.key]);
      window.__athlyticsGoto = false;
    }
  });
}

/** Rafraîchit le roster (après import, saisie de bien-être, etc.). */
export async function refreshRoster() {
  try {
    const roster = await api.athletes();
    setState({ athletes: roster.athletes });
    renderNav();
  } catch (error) { notifyError(error); }
}

window.athlytics = { refreshRoster, navigate, toast, store };
boot();
