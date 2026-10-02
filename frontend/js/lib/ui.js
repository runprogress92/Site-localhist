/**
 * Éléments d'interface partagés : notifications, fenêtres modales,
 * en-tête, états vides, tuiles de mesure.
 */
import { el, clear, icon, mount } from './dom.js';
import * as F from './format.js';
import { currentRoute } from './router.js';
import { viewport } from './viewport.js';

/* ---------------------------------------------------------- notifications */
export function toast(message, kind = 'info', duration = 4200) {
  const container = document.getElementById('toasts');
  const node = el(`div.toast.${kind}`, message);
  container.appendChild(node);
  setTimeout(() => {
    node.style.transition = 'opacity 180ms, transform 180ms';
    node.style.opacity = '0';
    node.style.transform = 'translateX(16px)';
    setTimeout(() => node.remove(), 200);
  }, duration);
  return node;
}

export const notifyError = (error) => toast(
  error?.message || String(error), 'error', 6500);

/* ----------------------------------------------------------------- modale */
export function modal({ title, body, actions = [], wide = false, onClose = null }) {
  const backdrop = el('div.modal-backdrop');
  const close = () => { backdrop.remove(); document.removeEventListener('keydown', onKey);
                        if (onClose) onClose(); };
  const onKey = (event) => { if (event.key === 'Escape') close(); };
  document.addEventListener('keydown', onKey);

  const dialog = el(`div.modal${wide ? '.wide' : ''}`, [
    el('div.modal-head', [
      el('h2', title),
      el('button.btn.ghost.icon', { onclick: close, 'aria-label': 'Fermer' },
         [icon('close')]),
    ]),
    el('div.modal-body', typeof body === 'function' ? body(close) : body),
    actions.length ? el('div.modal-foot', actions.map(action =>
      el(`button.btn${action.primary ? '.primary' : ''}${action.danger ? '.danger' : ''}`, {
        onclick: async () => {
          if (action.keepOpen) { await action.onClick(close); return; }
          const result = await action.onClick(close);
          if (result !== false) close();
        },
      }, action.label))) : null,
  ]);
  backdrop.appendChild(dialog);
  backdrop.addEventListener('click', (event) => {
    if (event.target === backdrop) close();
  });
  document.body.appendChild(backdrop);
  const firstInput = dialog.querySelector('input, select, textarea');
  if (firstInput) setTimeout(() => firstInput.focus(), 60);
  return { close, dialog };
}

export function confirmDialog(message, { title = 'Confirmer', danger = true,
                                         confirmLabel = 'Confirmer' } = {}) {
  return new Promise((resolve) => {
    modal({
      title,
      body: el('p.muted', message),
      onClose: () => resolve(false),
      actions: [
        { label: 'Annuler', onClick: () => resolve(false) },
        { label: confirmLabel, primary: !danger, danger, onClick: () => resolve(true) },
      ],
    });
  });
}

/* --------------------------------------------------------------- en-têtes */
export function setTopbar(children) {
  mount(document.getElementById('topbar'), children);
}

/**
 * En-tête de page.
 *
 * Sur téléphone, un chevron de retour précède le titre dès qu'on n'est plus
 * sur une destination de la barre d'onglets : sans lui, revenir d'une fiche
 * athlète à la liste suppose de deviner quel onglet la contient.
 */
export function pageTitle(title, subtitle = null, actions = null) {
  const ROOTS = ['/', '/bien-etre', '/calendrier', '/seances', '/analyse',
                 '/charge', '/connexions', '/reglages'];
  const showBack = viewport.isMobile && !ROOTS.includes(currentRoute());
  return [
    showBack ? el('button.btn.ghost.icon.back-btn', {
      onclick: () => window.history.back(),
      'aria-label': 'Retour',
    }, [icon('chevronLeft')]) : null,
    el('div.col', { style: { gap: '1px' } }, [
      el('h1', title),
      subtitle ? el('div.breadcrumb', subtitle) : null,
    ]),
    el('div.spacer'),
    // Sur téléphone, cette rangée passe sous le titre et défile
    // horizontalement : des boutons qui sortent de l'écran sont des
    // boutons qui n'existent pas.
    actions ? el('div.topbar-actions', actions) : null,
  ];
}

/* ------------------------------------------------------------ états vides */
export function emptyState(title, message, action = null, iconName = 'info') {
  return el('div.empty', [
    icon(iconName),
    el('div.empty-title', title),
    el('div', { style: { maxWidth: '380px', margin: '0 auto', lineHeight: '1.6' } }, message),
    action ? el('div', { style: { marginTop: '18px' } }, action) : null,
  ]);
}

export function loading(message = 'Chargement…') {
  return el('div.loading-screen', [el('span.spinner'), el('span', message)]);
}

export function skeletonCard(height = 180) {
  return el('div.card', [el('div.skeleton', { style: { height: `${height}px` } })]);
}

/* ------------------------------------------------------------- indicateurs */
export function metric(label, value, { unit = null, sub = null, delta = null,
                                       color = null, size = '' } = {}) {
  return el('div.metric', [
    el('div.metric-label', label),
    el(`div.metric-value${size ? `.${size}` : ''}`, { style: color ? { color } : null },
      [value, unit ? el('span.metric-unit', unit) : null]),
    sub ? el('div.metric-sub', sub) : null,
    delta ? el(`div.metric-delta.${delta.direction}`, delta.text) : null,
  ]);
}

export function statTile(label, value, options = {}) {
  const { unit, sub, tone = '', spark = null, onClick = null, hint = null } = options;
  const tile = el(`div.stat-tile${tone ? `.${tone}` : ''}`, {
    style: onClick ? { cursor: 'pointer' } : null,
    onclick: onClick, title: hint,
  }, [
    el('div.metric-label', label),
    el('div.metric-value', { style: options.color ? { color: options.color } : null },
      [value, unit ? el('span.metric-unit', unit) : null]),
    sub ? el('div.metric-sub', sub) : null,
    spark ? el('div.spark.chart-box', { dataset: { spark: '1' } }) : null,
  ]);
  return tile;
}

/* ------------------------------------------------------------- avatar */
export function avatar(athlete, size = '') {
  return el(`div.avatar${size ? `.${size}` : ''}`, {
    style: { background: athlete.accent || 'var(--accent)' },
    title: `${athlete.first_name} ${athlete.last_name}`,
  }, F.initials(athlete.first_name, athlete.last_name));
}

export function athleteChip(athlete, onClick = null) {
  return el('div.athlete-chip', {
    style: onClick ? { cursor: 'pointer' } : null, onclick: onClick,
  }, [
    avatar(athlete, 'sm'),
    el('span.truncate', `${athlete.first_name} ${athlete.last_name}`),
  ]);
}

/* --------------------------------------------------------------- formulaire */
export function field(label, input, hint = null) {
  return el('div.field', [
    el('label.field-label', label),
    input,
    hint ? el('div.field-hint', hint) : null,
  ]);
}

export function input(props = {}) { return el('input.input', props); }
export function textarea(props = {}) { return el('textarea.textarea', props); }

export function select(options, props = {}) {
  return el('select.select', props, options.map(option =>
    el('option', { value: option.value, selected: option.selected }, option.label)));
}

/** Échelle 1–7 de Hooper-Mackinnon (1 = très bon, 7 = très mauvais). */
export function scaleField(label, name, value, onChange, hint = null) {
  const buttons = [];
  const wrap = el('div.scale-input', Array.from({ length: 7 }, (_, i) => {
    const n = i + 1;
    const button = el('button', {
      type: 'button', class: value === n ? 'on' : '',
      onclick: () => {
        buttons.forEach(b => b.classList.remove('on'));
        button.classList.add('on');
        onChange(n);
      },
    }, String(n));
    buttons.push(button);
    return button;
  }));
  return field(label, wrap, hint);
}

/* ------------------------------------------------------------- tableaux */
/**
 * Tableau sur grand écran, liste de cartes sur téléphone.
 *
 * Un tableau de dix colonnes sur 390 px impose un défilement horizontal que
 * personne n'utilise : les colonnes de droite deviennent invisibles. Fournir
 * un descripteur `card` fait basculer le même jeu de données vers des
 * cartes empilées, où chaque ligne se lit d'un coup d'œil.
 *
 * `card` : { title, subtitle, accent, badge, metrics } — `metrics` renvoie
 * une liste de paires [libellé, valeur] à afficher en grille.
 */
export function dataTable({ columns, rows, onRowClick = null, empty = 'Aucune donnée',
                            sortable = false, initialSort = null, card = null }) {
  if (!rows.length) return el('div.empty', empty);
  if (card && viewport.isMobile) return cardList({ rows, onRowClick, card });
  let sortKey = initialSort?.key || null;
  let sortDir = initialSort?.dir || 'desc';

  const table = el('table.data');
  const thead = el('thead');
  const tbody = el('tbody');

  function renderHead() {
    clear(thead);
    thead.appendChild(el('tr', columns.map(column =>
      el(`th${column.numeric ? '.num' : ''}${sortable && column.key ? '.sortable' : ''}`, {
        style: column.width ? { width: column.width } : null,
        onclick: sortable && column.key ? () => {
          if (sortKey === column.key) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
          else { sortKey = column.key; sortDir = 'desc'; }
          renderHead(); renderBody();
        } : null,
      }, [column.label,
          sortable && sortKey === column.key
            ? el('span.faint', sortDir === 'asc' ? ' ↑' : ' ↓') : null]))));
  }

  function renderBody() {
    let list = [...rows];
    if (sortKey) {
      list.sort((a, b) => {
        const va = a[sortKey], vb = b[sortKey];
        if (va == null) return 1;
        if (vb == null) return -1;
        const cmp = typeof va === 'string' ? va.localeCompare(vb, 'fr') : va - vb;
        return sortDir === 'asc' ? cmp : -cmp;
      });
    }
    clear(tbody);
    for (const row of list) {
      tbody.appendChild(el(`tr${onRowClick ? '.clickable' : ''}`, {
        onclick: onRowClick ? () => onRowClick(row) : null,
      }, columns.map(column =>
        el(`td${column.numeric ? '.num' : ''}`, column.render(row)))));
    }
  }

  renderHead(); renderBody();
  table.appendChild(thead); table.appendChild(tbody);
  return el('div.table-wrap', [table]);
}

function cardList({ rows, onRowClick, card }) {
  return el('div.row-cards', rows.map(row => {
    const metrics = (card.metrics ? card.metrics(row) : []).filter(Boolean);
    return el('div.row-card', {
      style: { borderLeftColor: card.accent ? card.accent(row) : 'var(--border)',
               cursor: onRowClick ? 'pointer' : 'default' },
      onclick: onRowClick ? () => onRowClick(row) : null,
    }, [
      el('div.row-card-head', [
        card.avatar ? card.avatar(row) : null,
        el('div', { style: { minWidth: 0, flex: 1 } }, [
          el('div.row-card-title.truncate', card.title(row)),
          card.subtitle ? el('div.row-card-sub.truncate', card.subtitle(row)) : null,
        ]),
        card.badge ? card.badge(row) : null,
      ]),
      metrics.length
        ? el('dl.row-card-metrics', metrics.flatMap(([label, value]) =>
            el('div.row-card-metric', [el('dt', label), el('dd', value)])))
        : null,
    ]);
  }));
}

/* -------------------------------------------------------------- badges */
export function formBadge(tsb, form) {
  if (tsb === null || tsb === undefined) return el('span.badge', '—');
  const tone = tsb > 5 ? 'pos' : tsb > -12 ? '' : tsb > -28 ? 'warn' : 'neg';
  return el(`span.badge${tone ? `.${tone}` : ''}`, [
    el('span.dot'), `${F.signed(tsb, 0)} · ${form || ''}`,
  ]);
}

export function readinessBadge(score, flag) {
  if (score === null || score === undefined) return el('span.badge', 'non renseigné');
  const tone = flag === 'vert' ? 'pos' : flag === 'ambre' ? 'warn' : 'neg';
  return el(`span.badge.${tone}`, [el('span.dot'), `${F.num(score, 0)}/100`]);
}

export function segmented(options, active, onChange) {
  return el('div.btn-group', options.map(option =>
    el(`button.btn.sm${option.value === active ? '.active' : ''}`, {
      onclick: () => onChange(option.value),
    }, option.label)));
}

export function chips(options, active, onChange) {
  return el('div.row-tight.wrap', options.map(option =>
    el(`div.chip${option.value === active ? '.active' : ''}`, {
      onclick: () => onChange(option.value),
    }, option.label)));
}

/** Petite carte à en-tête, corps et action. */
export function card(title, body, { subtitle = null, action = null, flush = false,
                                    className = '' } = {}) {
  return el(`div.card${flush ? '.flush' : ''}${className ? `.${className}` : ''}`, [
    title ? el('div.card-head', {
      style: flush ? { padding: 'var(--sp-4) var(--sp-5) 0', marginBottom: 'var(--sp-3)' } : null,
    }, [
      el('div', [el('div.card-title', title),
                 subtitle ? el('div.card-sub', subtitle) : null]),
      action,
    ]) : null,
    el('div.card-body', body),
  ]);
}

/** Conteneur pour un graphique, avec sa hauteur réservée. */
export function chartBox(height = 240) {
  return el('div.chart-box', { style: { minHeight: `${height}px` } });
}
