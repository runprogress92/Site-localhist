/**
 * Navigation mobile : barre d'onglets en bas et panneau coulissant.
 *
 * Le menu latéral du bureau ne convient pas au téléphone : il mange un
 * tiers de la largeur et impose un geste d'ouverture que rien ne signale.
 * La barre basse place les quatre destinations les plus fréquentes sous le
 * pouce, et un cinquième onglet ouvre le reste dans une feuille.
 */
import { clear, el, icon, mount } from './dom.js';
import * as F from './format.js';
import { currentRoute, navigate } from './router.js';
import { store, toggleTheme, setState } from './store.js';
import { viewport } from './viewport.js';

const TABS = [
  { path: '/', label: 'Groupe', icon: 'dashboard' },
  { path: '/bien-etre', label: 'Bien-être', icon: 'heart' },
  { path: '/calendrier', label: 'Agenda', icon: 'calendar' },
  { path: '/seances', label: 'Séances', icon: 'activity' },
];

const MORE_ITEMS = [
  { path: '/analyse', label: 'Comparaison', icon: 'chart',
    hint: 'Comparer plusieurs athlètes sur une même métrique' },
  { path: '/charge', label: 'Charge du groupe', icon: 'layers',
    hint: 'Matrice charge × jour de tout le groupe' },
  { path: '/connexions', label: 'Montres', icon: 'watch',
    hint: 'Garmin, Polar, COROS et import de fichiers' },
  { path: '/reglages', label: 'Réglages', icon: 'settings',
    hint: 'Seuils, pondérations, sauvegarde' },
];

let sheet = null;

/** La route courante relève-t-elle de cet onglet ? */
function isActive(path, current) {
  if (path === '/') {
    // la fiche d'un athlète et le détail d'une séance se rattachent au groupe
    return current === '/' || current.startsWith('/athlete/')
           || current.startsWith('/seance/');
  }
  return current === path || current.startsWith(`${path}/`);
}

export function renderBottomNav() {
  let bar = document.getElementById('bottom-nav');
  if (!bar) {
    bar = el('nav#bottom-nav.bottom-nav', { 'aria-label': 'Navigation principale' });
    document.getElementById('app').appendChild(bar);
  }
  const current = currentRoute();
  const inMore = MORE_ITEMS.some(item => isActive(item.path, current));

  mount(bar, [
    ...TABS.map(tab => el(`button.tab-item${isActive(tab.path, current) ? '.active' : ''}`, {
      onclick: () => { closeSheet(); navigate(tab.path); },
      'aria-current': isActive(tab.path, current) ? 'page' : null,
    }, [
      icon(tab.icon, 'tab-icon'),
      el('span.tab-label', tab.label),
    ])),
    el(`button.tab-item${inMore ? '.active' : ''}`, {
      onclick: () => toggleSheet(),
      'aria-label': 'Plus d’options',
    }, [icon('menu', 'tab-icon'), el('span.tab-label', 'Plus')]),
  ]);
  return bar;
}

/* ------------------------------------------------------------- feuille */
export function toggleSheet() {
  if (sheet) { closeSheet(); return; }
  openSheet();
}

export function closeSheet() {
  if (!sheet) return;
  sheet.classList.add('closing');
  const node = sheet;
  sheet = null;
  setTimeout(() => node.remove(), 180);
  document.removeEventListener('keydown', onKey);
}

function onKey(event) {
  if (event.key === 'Escape') closeSheet();
}

function openSheet() {
  const current = currentRoute();
  const backdrop = el('div.sheet-backdrop', {
    onclick: (event) => { if (event.target === backdrop) closeSheet(); },
  });
  const panel = el('div.sheet', [
    el('div.sheet-grip'),

    el('div.sheet-section', [
      el('div.sheet-title', 'Athlètes'),
      store.athletes.length
        ? el('div.sheet-athletes', store.athletes.map(athlete =>
            el('button.sheet-athlete', {
              onclick: () => { closeSheet(); navigate(`/athlete/${athlete.id}`); },
            }, [
              el('span.avatar.sm', { style: { background: athlete.accent } },
                 F.initials(athlete.first_name, athlete.last_name)),
              el('span.sheet-athlete-name',
                 `${athlete.first_name} ${athlete.last_name.charAt(0)}.`),
              el('span.sheet-athlete-dot', {
                style: { background: athlete.status === 'injured'
                  ? 'var(--danger)' : F.readinessColor(athlete.readiness_flag) },
                title: athlete.readiness != null
                  ? `Disponibilité ${Math.round(athlete.readiness)}/100` : 'aucun relevé',
              }),
            ])))
        : el('div.muted', { style: { fontSize: 'var(--fs-sm)' } }, 'Aucun athlète.'),
    ]),

    el('div.sheet-section', [
      el('div.sheet-title', 'Autres pages'),
      ...MORE_ITEMS.map(item => el(
        `button.sheet-item${isActive(item.path, current) ? '.active' : ''}`,
        { onclick: () => { closeSheet(); navigate(item.path); } },
        [
          el('span.sheet-item-icon', [icon(item.icon)]),
          el('span', [
            el('span.sheet-item-label', item.label),
            el('span.sheet-item-hint', item.hint),
          ]),
        ])),
    ]),

    el('div.sheet-section', [
      el('button.sheet-item', {
        onclick: () => { toggleTheme(); closeSheet(); },
      }, [
        el('span.sheet-item-icon', [icon(store.theme === 'dark' ? 'sun' : 'moon')]),
        el('span', [
          el('span.sheet-item-label',
             store.theme === 'dark' ? 'Thème clair' : 'Thème sombre'),
          el('span.sheet-item-hint',
             'Le thème clair se lit mieux en plein soleil'),
        ]),
      ]),
    ]),
  ]);
  backdrop.appendChild(panel);
  document.body.appendChild(backdrop);
  sheet = backdrop;
  document.addEventListener('keydown', onKey);

  // fermeture par glissement vers le bas
  let startY = null;
  panel.addEventListener('touchstart', (e) => { startY = e.touches[0].clientY; },
                         { passive: true });
  panel.addEventListener('touchmove', (e) => {
    if (startY === null) return;
    const delta = e.touches[0].clientY - startY;
    if (delta > 0) panel.style.transform = `translateY(${delta}px)`;
  }, { passive: true });
  panel.addEventListener('touchend', () => {
    const shift = parseFloat((panel.style.transform.match(/([\d.]+)px/) || [0, 0])[1]);
    panel.style.transform = '';
    if (shift > 90) closeSheet();
    startY = null;
  });
}

/** Retire la barre basse (passage en format bureau). */
export function removeBottomNav() {
  closeSheet();
  const bar = document.getElementById('bottom-nav');
  if (bar) bar.remove();
}
