/**
 * Fabrique d'éléments DOM minimaliste.
 *
 * `el('div.card', {onclick: fn}, [enfants])` — le sélecteur accepte
 * `tag#id.classe1.classe2`. Les enfants peuvent être des chaînes, des nœuds,
 * des tableaux, ou `null` (ignoré). Aucune dépendance, aucun moteur de
 * gabarit : le rendu reste explicite et déboguable.
 */
const SVG_NS = 'http://www.w3.org/2000/svg';
const SVG_TAGS = new Set(['svg', 'g', 'path', 'rect', 'circle', 'line', 'text',
  'polyline', 'polygon', 'defs', 'linearGradient', 'stop', 'clipPath', 'ellipse',
  'tspan', 'use', 'pattern', 'mask', 'filter', 'feGaussianBlur', 'animate']);

export function el(selector, props = null, children = null) {
  if (Array.isArray(props) || typeof props === 'string' ||
      props instanceof Node) { children = props; props = null; }

  const match = /^([a-zA-Z][a-zA-Z0-9]*)?(#[\w-]+)?((?:\.[\w-]+)*)$/.exec(selector);
  if (!match) throw new Error(`Sélecteur invalide : ${selector}`);
  const tag = match[1] || 'div';
  const node = SVG_TAGS.has(tag)
    ? document.createElementNS(SVG_NS, tag)
    : document.createElement(tag);
  if (match[2]) node.id = match[2].slice(1);
  if (match[3]) {
    const classes = match[3].split('.').filter(Boolean);
    if (node instanceof SVGElement) node.setAttribute('class', classes.join(' '));
    else node.classList.add(...classes);
  }

  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class' || key === 'className') {
      if (node instanceof SVGElement) {
        node.setAttribute('class', `${node.getAttribute('class') || ''} ${value}`.trim());
      } else node.classList.add(...String(value).split(/\s+/).filter(Boolean));
    } else if (key === 'style' && typeof value === 'object') {
      Object.assign(node.style, value);
    } else if (key === 'dataset') {
      Object.assign(node.dataset, value);
    } else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'html') {
      node.innerHTML = value;
    } else if (key === 'text') {
      node.textContent = value;
    } else if (node instanceof SVGElement || key.includes('-') ||
               key.startsWith('aria') || key === 'role' || key === 'for') {
      node.setAttribute(key === 'for' ? 'for' : key, value);
    } else if (key in node) {
      node[key] = value;
    } else {
      node.setAttribute(key, value);
    }
  }
  append(node, children);
  return node;
}

export function append(parent, children) {
  if (children === null || children === undefined || children === false) return parent;
  if (Array.isArray(children)) { children.forEach(c => append(parent, c)); return parent; }
  parent.appendChild(children instanceof Node
    ? children : document.createTextNode(String(children)));
  return parent;
}

export function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); return node; }

export function mount(node, children) { clear(node); append(node, children); return node; }

export const $  = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

/** Icônes : tracés SVG en trait, ligne de 1,7 px, boîte 24×24. */
const ICONS = {
  dashboard: 'M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z',
  users: 'M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm14 10v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75',
  activity: 'M22 12h-4l-3 9L9 3l-3 9H2',
  calendar: 'M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z',
  chart: 'M3 3v18h18M7 16l4-5 4 3 5-7',
  heart: 'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21.2l7.8-7.7 1-1.1a5.5 5.5 0 0 0 0-7.8z',
  watch: 'M12 8v4l2 2M9 2h6l.5 4M9 22h6l.5-4M12 20a8 8 0 1 0 0-16 8 8 0 0 0 0 16z',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z',
  alert: 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01',
  search: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35',
  upload: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
  plus: 'M12 5v14M5 12h14',
  close: 'M18 6 6 18M6 6l12 12',
  chevronRight: 'M9 18l6-6-6-6',
  chevronLeft: 'M15 18l-6-6 6-6',
  chevronDown: 'M6 9l6 6 6-6',
  check: 'M20 6 9 17l-5-5',
  flask: 'M9 2v6.5L3.5 18A2 2 0 0 0 5.2 21h13.6a2 2 0 0 0 1.7-3L15 8.5V2M8 2h8M7 14h10',
  clipboard: 'M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2M9 2h6a1 1 0 0 1 1 1v2a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z',
  target: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zm0-4a6 6 0 1 0 0-12 6 6 0 0 0 0 12zm0-4a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  refresh: 'M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
  sun: 'M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  menu: 'M3 12h18M3 6h18M3 18h18',
  trash: 'M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6',
  edit: 'M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7M18.5 2.5a2.1 2.1 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z',
  moon2: 'M12 3a9 9 0 1 0 9 9',
  bed: 'M2 20v-8a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v8M2 16h20M6 10V7a2 2 0 0 1 2-2h3v5',
  map: 'M1 6v16l7-4 8 4 7-4V2l-7 4-8-4-7 4zM8 2v16M16 6v16',
  layers: 'M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
  info: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01',
  zap: 'M13 2 3 14h9l-1 8 10-12h-9l1-8z',
  trending: 'M23 6l-9.5 9.5-5-5L1 18M17 6h6v6',
  file: 'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6',
  link: 'M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7',
  play: 'M5 3l14 9-14 9V3z',
  filter: 'M22 3H2l8 9.5V19l4 2v-8.5L22 3z',
};

export function icon(name, cls = '') {
  const path = ICONS[name] || ICONS.info;
  return el('svg', {
    class: cls, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor',
    'stroke-width': '1.7', 'stroke-linecap': 'round', 'stroke-linejoin': 'round',
    'aria-hidden': 'true',
  }, [el('path', { d: path })]);
}

export function delegate(root, selector, event, handler) {
  root.addEventListener(event, (e) => {
    const target = e.target.closest(selector);
    if (target && root.contains(target)) handler(e, target);
  });
}

/** Limite la fréquence d'appel (redimensionnement, saisie). */
export function debounce(fn, wait = 220) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
}

export function onResize(node, callback) {
  const observer = new ResizeObserver(entries => {
    for (const entry of entries) callback(entry.contentRect);
  });
  observer.observe(node);
  return () => observer.disconnect();
}
