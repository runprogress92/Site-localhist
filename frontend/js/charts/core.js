/**
 * Socle des graphiques : échelles, axes, grille, curseur et infobulle.
 *
 * Tout est dessiné en SVG généré à la main. Aucune bibliothèque externe :
 * la page fonctionne hors ligne, sans CDN, et le rendu reste totalement
 * maîtrisé (unités, arrondis, contraste, thème clair et sombre).
 */
import { el, clear, onResize } from '../lib/dom.js';

/* --------------------------------------------------------------- échelles */
export function scaleLinear(domain, range) {
  let [d0, d1] = domain;
  const [r0, r1] = range;
  if (d0 === d1) { d0 -= 0.5; d1 += 0.5; }
  const span = d1 - d0;
  const fn = (value) => r0 + ((value - d0) / span) * (r1 - r0);
  fn.invert = (pixel) => d0 + ((pixel - r0) / (r1 - r0)) * span;
  fn.domain = [d0, d1];
  fn.range = [r0, r1];
  fn.ticks = (count = 6) => niceTicks(d0, d1, count);
  return fn;
}

export function scaleLog(domain, range) {
  const [d0, d1] = domain.map(v => Math.log10(Math.max(v, 1e-6)));
  const [r0, r1] = range;
  const span = d1 - d0 || 1;
  const fn = (value) => r0 + ((Math.log10(Math.max(value, 1e-6)) - d0) / span) * (r1 - r0);
  fn.invert = (pixel) => 10 ** (d0 + ((pixel - r0) / (r1 - r0)) * span);
  fn.domain = domain;
  fn.range = range;
  fn.ticks = () => {
    const out = [];
    for (let exp = Math.floor(d0); exp <= Math.ceil(d1); exp += 1) {
      for (const mantissa of [1, 2, 5]) {
        const value = mantissa * 10 ** exp;
        if (value >= domain[0] && value <= domain[1]) out.push(value);
      }
    }
    return out;
  };
  return fn;
}

/** Bornes « rondes » : 0, 25, 50, 75, 100 plutôt que 0, 23, 46… */
export function niceTicks(min, max, count = 6) {
  if (min === max) return [min];
  const rawStep = (max - min) / Math.max(1, count);
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const step = (normalized >= 7.5 ? 10 : normalized >= 3.5 ? 5
              : normalized >= 1.5 ? 2 : 1) * magnitude;
  const start = Math.ceil(min / step) * step;
  const out = [];
  for (let v = start; v <= max + step * 1e-6; v += step) {
    out.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toFixed(10)));
  }
  return out;
}

export function extent(values) {
  let min = Infinity, max = -Infinity;
  for (const v of values) {
    if (v === null || v === undefined || Number.isNaN(v)) continue;
    if (v < min) min = v;
    if (v > max) max = v;
  }
  return min === Infinity ? [0, 1] : [min, max];
}

/** Étend un domaine d'une marge relative, en respectant un plancher. */
export function padDomain([min, max], pad = 0.08, floorAtZero = false) {
  const span = (max - min) || Math.abs(max) || 1;
  let lo = min - span * pad;
  const hi = max + span * pad;
  if (floorAtZero && min >= 0) lo = Math.max(0, lo);
  return [lo, hi];
}

/* --------------------------------------------------------------- tracés */
/** Chemin en ligne brisée, interrompu sur les valeurs manquantes. */
export function linePath(points) {
  let path = '';
  let pen = false;
  for (const [x, y] of points) {
    if (y === null || y === undefined || Number.isNaN(y)) { pen = false; continue; }
    path += `${pen ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
    pen = true;
  }
  return path;
}

/** Courbe lissée (spline cardinale) — pour les tendances, jamais pour les données brutes. */
export function smoothPath(points, tension = 0.32) {
  const clean = points.filter(p => p[1] !== null && !Number.isNaN(p[1]));
  if (clean.length < 3) return linePath(clean);
  let path = `M${clean[0][0].toFixed(1)} ${clean[0][1].toFixed(1)}`;
  for (let i = 0; i < clean.length - 1; i += 1) {
    const p0 = clean[Math.max(0, i - 1)];
    const p1 = clean[i];
    const p2 = clean[i + 1];
    const p3 = clean[Math.min(clean.length - 1, i + 2)];
    const c1x = p1[0] + (p2[0] - p0[0]) * tension / 3;
    const c1y = p1[1] + (p2[1] - p0[1]) * tension / 3;
    const c2x = p2[0] - (p3[0] - p1[0]) * tension / 3;
    const c2y = p2[1] - (p3[1] - p1[1]) * tension / 3;
    path += `C${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ` +
            `${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return path;
}

export function areaPath(points, baseline) {
  const clean = points.filter(p => p[1] !== null && !Number.isNaN(p[1]));
  if (!clean.length) return '';
  const top = linePath(clean);
  const first = clean[0][0];
  const last = clean[clean.length - 1][0];
  return `${top}L${last.toFixed(1)} ${baseline.toFixed(1)}L${first.toFixed(1)} ${baseline.toFixed(1)}Z`;
}

/* ------------------------------------------------------------- infobulle */
let tooltipNode = null;
let dismissTimer = null;
let dismissBound = false;

/**
 * Durée d'affichage d'une infobulle ouverte au doigt.
 *
 * À la souris, « le pointeur a quitté le graphique » est un évènement ; au
 * doigt, il n'existe pas. Sans effacement explicite, l'infobulle — qui
 * occupe toute la largeur de l'écran sur téléphone — restait en travers de
 * la page, y compris après un changement d'onglet ou de vue.
 */
const TOUCH_LINGER_MS = 2600;

export function tooltip() {
  if (!tooltipNode) {
    tooltipNode = el('div.chart-tooltip', { style: { display: 'none' } });
    document.body.appendChild(tooltipNode);
  }
  return tooltipNode;
}

/** Y a-t-il un survol possible, ou l'interface est-elle pilotée au doigt ? */
function touchDriven() {
  return window.matchMedia('(hover: none)').matches || window.innerWidth <= 820;
}

/**
 * Deux filets pour qu'une infobulle tactile finisse toujours par disparaître :
 * le contact suivant, où qu'il ait lieu, et un délai.
 */
function armAutoDismiss() {
  clearTimeout(dismissTimer);
  dismissTimer = null;
  if (!touchDriven()) return;
  dismissTimer = setTimeout(hideTooltip, TOUCH_LINGER_MS);
  if (dismissBound) return;
  dismissBound = true;
  // En phase de capture : le contact est vu avant le graphique, qui
  // réaffiche aussitôt son infobulle s'il en est la cible. Un contact
  // ailleurs — un onglet, un bouton, la barre du bas — l'efface donc.
  document.addEventListener('touchstart', hideTooltip, true);
}

export function showTooltip(content, event, anchor) {
  const node = tooltip();
  clear(node);
  if (typeof content === 'string') node.innerHTML = content;
  else node.appendChild(content);
  node.style.display = 'block';
  armAutoDismiss();

  // Sur téléphone, l'infobulle est ancrée en bas de l'écran par la feuille
  // mobile : la placer sous le doigt la rendrait invisible, puisque la main
  // couvre précisément l'endroit touché.
  if (window.innerWidth <= 820) {
    node.style.left = '';
    node.style.top = '';
    return;
  }
  const box = node.getBoundingClientRect();
  const margin = 14;
  let x = (event.clientX ?? 0) + margin;
  let y = (event.clientY ?? 0) - box.height / 2;
  if (x + box.width > window.innerWidth - 8) x = event.clientX - box.width - margin;
  y = Math.max(8, Math.min(window.innerHeight - box.height - 8, y));
  node.style.left = `${x}px`;
  node.style.top = `${y}px`;
}

export function hideTooltip() {
  clearTimeout(dismissTimer);
  dismissTimer = null;
  if (tooltipNode) tooltipNode.style.display = 'none';
}

export function tooltipRows(title, rows, subtitle = null) {
  return el('div', [
    el('div.tt-title', title),
    subtitle ? el('div.tt-sub', subtitle) : null,
    el('div.tt-rows', rows.filter(Boolean).map(([label, value, color]) =>
      el('div.tt-row', [
        color ? el('span.tt-swatch', { style: { background: color } }) : null,
        el('span.tt-label', label),
        el('span.tt-value', value),
      ]))),
  ]);
}

/* ------------------------------------------------------------- conteneur */
const DEFAULT_MARGIN = { top: 12, right: 16, bottom: 26, left: 46 };

/**
 * Crée un cadre de graphique réactif.
 *
 * `render(ctx)` reçoit `{svg, g, width, height, inner}` et dessine ; il est
 * rappelé à chaque redimensionnement du conteneur.
 */
export function createChart(container, options, render) {
  const margin = { ...DEFAULT_MARGIN, ...(options.margin || {}) };
  const height = options.height || 220;
  let disposeResize = null;

  function draw() {
    const width = Math.max(160, container.clientWidth || options.width || 600);
    const inner = {
      width: Math.max(20, width - margin.left - margin.right),
      height: Math.max(20, height - margin.top - margin.bottom),
    };
    const svg = el('svg.chart', {
      viewBox: `0 0 ${width} ${height}`, width: '100%', height,
      preserveAspectRatio: 'none', role: 'img',
      'aria-label': options.label || 'graphique',
    });
    const g = el('g', { transform: `translate(${margin.left},${margin.top})` });
    svg.appendChild(g);
    clear(container);
    container.appendChild(svg);
    try {
      render({ svg, g, width, height, inner, margin, container });
    } catch (error) {
      console.error('Erreur de rendu du graphique', error);
      clear(container);
      container.appendChild(el('div.chart-error',
        'Impossible d’afficher ce graphique.'));
    }
  }

  draw();
  if (!options.static) {
    let lastWidth = container.clientWidth;
    disposeResize = onResize(container, (rect) => {
      if (Math.abs(rect.width - lastWidth) > 4) { lastWidth = rect.width; draw(); }
    });
  }
  return { redraw: draw, dispose: () => disposeResize && disposeResize() };
}

/* ------------------------------------------------------------------ axes */
export function axisY(g, scale, inner, {
  ticks = 5, format = (v) => v, grid = true, side = 'left', color = null,
} = {}) {
  const values = typeof ticks === 'number' ? scale.ticks(ticks) : ticks;
  const x = side === 'left' ? -8 : inner.width + 8;
  for (const value of values) {
    const y = scale(value);
    if (y < -2 || y > inner.height + 2) continue;
    if (grid && side === 'left') {
      g.appendChild(el('line.grid-line', {
        x1: 0, x2: inner.width, y1: y.toFixed(1), y2: y.toFixed(1),
      }));
    }
    g.appendChild(el('text.axis-label', {
      x, y: (y + 3.5).toFixed(1),
      'text-anchor': side === 'left' ? 'end' : 'start',
      fill: color || 'currentColor',
    }, format(value)));
  }
}

export function axisX(g, scale, inner, {
  ticks = 6, format = (v) => v, grid = false, values = null,
} = {}) {
  const list = values || (typeof ticks === 'number' ? scale.ticks(ticks) : ticks);
  let previousLabel = null;
  for (const value of list) {
    const x = scale(value);
    if (x < -20 || x > inner.width + 20) continue;
    // Deux graduations voisines produisant le même texte (« mai 26 » deux fois)
    // donnent une lecture fausse : on ne dessine que les libellés distincts.
    const text = String(format(value));
    if (text === previousLabel) continue;
    previousLabel = text;
    if (grid) {
      g.appendChild(el('line.grid-line', {
        x1: x.toFixed(1), x2: x.toFixed(1), y1: 0, y2: inner.height,
      }));
    }
    g.appendChild(el('text.axis-label', {
      x: x.toFixed(1), y: inner.height + 16, 'text-anchor': 'middle',
    }, text));
  }
}

/** Ligne de référence horizontale annotée (seuil, zéro, cible). */
export function refLine(g, y, inner, { label = null, color = 'var(--border-strong)',
  dash = '3 3', anchor = 'end' } = {}) {
  g.appendChild(el('line', {
    x1: 0, x2: inner.width, y1: y.toFixed(1), y2: y.toFixed(1),
    stroke: color, 'stroke-width': 1, 'stroke-dasharray': dash,
  }));
  if (label) {
    g.appendChild(el('text.ref-label', {
      x: anchor === 'end' ? inner.width - 4 : 4, y: (y - 4).toFixed(1),
      'text-anchor': anchor === 'end' ? 'end' : 'start', fill: color,
    }, label));
  }
}

/** Bande horizontale (plage normale, zone optimale). */
export function refBand(g, y1, y2, inner, { color = 'var(--accent-dim)', label = null } = {}) {
  const top = Math.min(y1, y2);
  g.appendChild(el('rect', {
    x: 0, y: top.toFixed(1), width: inner.width,
    height: Math.abs(y2 - y1).toFixed(1), fill: color,
  }));
  if (label) {
    g.appendChild(el('text.ref-label', {
      x: inner.width - 4, y: (top + 11).toFixed(1), 'text-anchor': 'end',
    }, label));
  }
}

/** Dégradé vertical réutilisable (aires). */
export function gradient(svg, id, color, from = 0.30, to = 0.0) {
  const defs = el('defs', [
    el('linearGradient', { id, x1: '0', y1: '0', x2: '0', y2: '1' }, [
      el('stop', { offset: '0%', 'stop-color': color, 'stop-opacity': from }),
      el('stop', { offset: '100%', 'stop-color': color, 'stop-opacity': to }),
    ]),
  ]);
  svg.insertBefore(defs, svg.firstChild);
  return `url(#${id})`;
}

let uid = 0;
export const nextId = (prefix = 'g') => `${prefix}-${(uid += 1)}`;

/**
 * Couche interactive : curseur vertical suivant la souris.
 * `onMove(index, event, x)` reçoit l'indice du point le plus proche.
 */
export function crosshair(g, inner, xValues, xScale, onMove, onLeave) {
  const line = el('line.crosshair', {
    y1: 0, y2: inner.height, x1: 0, x2: 0, style: { opacity: 0 },
  });
  g.appendChild(line);
  const overlay = el('rect', {
    x: 0, y: 0, width: inner.width, height: inner.height,
    fill: 'transparent', style: { cursor: 'crosshair', touchAction: 'pan-y' },
  });
  g.appendChild(overlay);

  function pointAt(clientX) {
    const box = overlay.getBoundingClientRect();
    const px = ((clientX - box.left) / box.width) * inner.width;
    let best = 0, bestDistance = Infinity;
    for (let i = 0; i < xValues.length; i += 1) {
      const distance = Math.abs(xScale(xValues[i]) - px);
      if (distance < bestDistance) { bestDistance = distance; best = i; }
    }
    return best;
  }

  function show(index, event) {
    const x = xScale(xValues[index]);
    line.setAttribute('x1', x.toFixed(1));
    line.setAttribute('x2', x.toFixed(1));
    line.style.opacity = 1;
    onMove(index, event, x);
  }

  function clear() {
    line.style.opacity = 0;
    hideTooltip();
    if (onLeave) onLeave();
  }

  overlay.addEventListener('mousemove', (event) => show(pointAt(event.clientX), event));
  overlay.addEventListener('mouseleave', clear);

  // Lecture au doigt : sans survol, un graphique n'est qu'une image. On
  // suit le déplacement du doigt le long de la courbe, tout en laissant le
  // défilement vertical de la page fonctionner (touch-action: pan-y).
  let touching = false;
  let linger = null;
  overlay.addEventListener('touchstart', (event) => {
    touching = true;
    clearTimeout(linger);
    show(pointAt(event.touches[0].clientX), event.touches[0]);
  }, { passive: true });
  overlay.addEventListener('touchmove', (event) => {
    if (!touching) return;
    show(pointAt(event.touches[0].clientX), event.touches[0]);
  }, { passive: true });
  const release = () => {
    touching = false;
    // Le trait disparaît un instant après le relâchement : l'effacer au
    // doigt levé ne laisserait rien à lire. L'infobulle, elle, est effacée
    // par le minuteur partagé de showTooltip — un graphique ne doit pas
    // pouvoir effacer celle d'un autre.
    clearTimeout(linger);
    linger = setTimeout(() => {
      line.style.opacity = 0;
      if (onLeave) onLeave();
    }, TOUCH_LINGER_MS);
  };
  overlay.addEventListener('touchend', release, { passive: true });
  overlay.addEventListener('touchcancel', release, { passive: true });

  return { line, overlay };
}

/** Légende compacte réutilisable. */
export function legend(items) {
  return el('div.chart-legend', items.filter(Boolean).map(item =>
    el('div.legend-item', [
      el('span.legend-swatch', {
        style: {
          background: item.dashed ? 'transparent' : item.color,
          borderTop: item.dashed ? `2px dashed ${item.color}` : 'none',
          borderRadius: item.dashed ? '0' : '2px',
          height: item.dashed ? '0' : '9px',
        },
      }),
      el('span', item.label),
      item.value ? el('span.legend-value', item.value) : null,
    ])));
}
