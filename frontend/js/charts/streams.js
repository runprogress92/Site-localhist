/**
 * Graphiques d'analyse d'une séance.
 *
 * `streamPanels` empile plusieurs pistes (FC, puissance, allure, altitude,
 * W'bal) partageant le même axe temporel et un curseur synchronisé — c'est
 * la lecture qu'attend un entraîneur : voir d'un coup ce que faisaient la
 * puissance et la fréquence cardiaque au même instant.
 */
import { el, clear } from '../lib/dom.js';
import * as F from '../lib/format.js';
import {
  areaPath, axisX, axisY, createChart, extent, gradient, hideTooltip, linePath,
  nextId, niceTicks, padDomain, refLine, scaleLinear, showTooltip, tooltipRows,
} from './core.js';

const PANEL_SPECS = {
  heart_rate: { label: 'Fréquence cardiaque', unit: 'bpm', color: 'var(--atl)',
                format: (v) => `${Math.round(v)} bpm`, zeroFloor: false },
  power:      { label: 'Puissance', unit: 'W', color: 'var(--accent)',
                format: (v) => `${Math.round(v)} W`, zeroFloor: true, fill: true },
  speed:      { label: 'Vitesse', unit: 'm/s', color: 'var(--positive)',
                format: (v) => F.speed(v), zeroFloor: true },
  cadence:    { label: 'Cadence', unit: '', color: 'var(--z7)',
                format: (v) => `${Math.round(v)}`, zeroFloor: true },
  altitude:   { label: 'Altitude', unit: 'm', color: 'var(--text-faint)',
                format: (v) => `${Math.round(v)} m`, fill: true, area: true },
  temperature:{ label: 'Température', unit: '°C', color: 'var(--z3)',
                format: (v) => `${Math.round(v)} °C` },
  w_bal:      { label: "Réserve W′", unit: 'J', color: 'var(--z6)',
                format: (v) => `${F.num(v / 1000, 1)} kJ`, fill: true, zeroFloor: true },
  gap_speed:  { label: 'Allure ajustée', unit: '', color: 'var(--z4)',
                format: (v) => F.pace(F.speedToPace(v)) },
  stance_time:{ label: 'Temps de contact', unit: 'ms', color: 'var(--z2)',
                format: (v) => `${Math.round(v)} ms` },
  vertical_oscillation: { label: 'Oscillation verticale', unit: 'mm',
                color: 'var(--z1)', format: (v) => `${Math.round(v)} mm` },
};

export function panelSpec(key) {
  return PANEL_SPECS[key] || { label: key, unit: '', color: 'var(--accent)',
                               format: (v) => F.num(v, 1) };
}

/** Lissage par moyenne glissante — indispensable au-delà de ~1 500 points. */
function smoothValues(values, window) {
  if (window <= 1) return values;
  const out = new Array(values.length);
  let sum = 0, count = 0;
  const queue = [];
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    queue.push(v);
    if (v != null) { sum += v; count += 1; }
    if (queue.length > window) {
      const old = queue.shift();
      if (old != null) { sum -= old; count -= 1; }
    }
    out[i] = count ? sum / count : null;
  }
  return out;
}

export function streamPanels(container, {
  streams, keys, sport = 'running', height = 110, smoothing = 1,
  sampleStep = 1, zones = null, laps = [], onRange = null,
}) {
  clear(container);
  const available = keys.filter(k => streams[k] && streams[k].some(v => v != null));
  if (!available.length) {
    container.appendChild(el('div.chart-empty', 'Aucun flux détaillé enregistré.'));
    return { dispose() {} };
  }
  const length = Math.max(...available.map(k => streams[k].length));
  // `streams.time` porte déjà des secondes réelles (le sous-échantillonnage a
  // moyenné l'indice temporel) : le remultiplier par le pas gonflerait l'axe.
  const seconds = streams.time
    || Array.from({ length }, (_, i) => i * sampleStep);

  const charts = [];
  const cursors = [];

  available.forEach((key, index) => {
    const spec = panelSpec(key);
    const raw = streams[key];
    const values = smoothing > 1 ? smoothValues(raw, smoothing) : raw;
    const isLast = index === available.length - 1;

    const panel = el('div.stream-panel');
    const header = el('div.stream-head', [
      el('span.stream-label', [
        el('span.stream-dot', { style: { background: spec.color } }), spec.label,
      ]),
      el('span.stream-readout.mono', { id: `readout-${key}` }, ''),
    ]);
    const plot = el('div.stream-plot');
    panel.appendChild(header);
    panel.appendChild(plot);
    container.appendChild(panel);

    const chart = createChart(plot, {
      height, margin: { top: 6, right: 12, bottom: isLast ? 22 : 6, left: 48 },
    }, (ctx) => {
      const { g, svg, inner } = ctx;
      const clean = values.filter(v => v != null);
      const domain = padDomain(extent(clean), 0.06, spec.zeroFloor);
      if (spec.zeroFloor) domain[0] = 0;
      const xScale = scaleLinear([0, values.length - 1], [0, inner.width]);
      const yScale = scaleLinear(domain, [inner.height, 0]);

      // bandes de zones en fond
      if (zones && zones.length && (key === 'heart_rate' || key === 'power')) {
        zones.forEach((zone, zi) => {
          const low = zone.low ?? domain[0];
          const high = zone.high ?? domain[1];
          if (high < domain[0] || low > domain[1]) return;
          const y1 = yScale(Math.min(high, domain[1]));
          const y2 = yScale(Math.max(low, domain[0]));
          g.appendChild(el('rect', {
            x: 0, y: y1.toFixed(1), width: inner.width,
            height: Math.max(0, y2 - y1).toFixed(1),
            fill: F.ZONE_COLORS[zi % 7], opacity: 0.075,
          }));
        });
      }

      axisY(g, yScale, inner, { ticks: 3, format: (v) => F.num(v, spec.unit === 'm/s' ? 1 : 0) });
      if (isLast) {
        axisX(g, xScale, inner, {
          values: niceTicks(0, values.length - 1, 7).map(Math.round),
          format: (i) => F.duration(seconds[Math.round(i)] ?? i * sampleStep, 'clock'),
        });
      }

      for (const lap of laps) {
        const index = Math.round((lap.start_offset_s || 0) / sampleStep);
        if (index <= 0 || index >= values.length) continue;
        g.appendChild(el('line', {
          x1: xScale(index).toFixed(1), x2: xScale(index).toFixed(1),
          y1: 0, y2: inner.height, stroke: 'var(--border-strong)',
          'stroke-width': 1, 'stroke-dasharray': '2 3', opacity: 0.7,
        }));
      }

      const points = values.map((v, i) => [xScale(i), v == null ? null : yScale(v)]);
      if (spec.fill || spec.area) {
        const id = nextId('stream');
        g.appendChild(el('path', {
          d: areaPath(points, inner.height),
          fill: gradient(svg, id, spec.color, spec.area ? 0.32 : 0.20, 0), stroke: 'none',
        }));
      }
      g.appendChild(el('path', {
        d: linePath(points), fill: 'none', stroke: spec.color,
        'stroke-width': 1.4, 'stroke-linejoin': 'round',
      }));

      const cursor = el('line.crosshair', { y1: 0, y2: inner.height, x1: 0, x2: 0,
                                            style: { opacity: 0 } });
      g.appendChild(cursor);
      const overlay = el('rect', { x: 0, y: 0, width: inner.width, height: inner.height,
                                   fill: 'transparent', style: { cursor: 'crosshair' } });
      g.appendChild(overlay);
      cursors.push({ cursor, xScale, inner, key, values, spec, overlay });

      overlay.addEventListener('mousemove', (event) => {
        const box = overlay.getBoundingClientRect();
        const ratio = (event.clientX - box.left) / box.width;
        const i = Math.max(0, Math.min(values.length - 1, Math.round(ratio * (values.length - 1))));
        syncCursors(i);
        showTooltip(tooltipRows(
          F.duration(seconds[i] ?? i * sampleStep, 'clock'),
          available.map(k => {
            const s = panelSpec(k);
            const v = streams[k]?.[i];
            return v == null ? null : [s.label, s.format(v), s.color];
          }),
          streams.distance?.[i] != null ? F.distance(streams.distance[i]) : null), event);
      });
      overlay.addEventListener('mouseleave', () => { clearCursors(); hideTooltip(); });
    });
    charts.push(chart);
  });

  function syncCursors(index) {
    for (const c of cursors) {
      const x = c.xScale(Math.min(index, c.values.length - 1));
      c.cursor.setAttribute('x1', x.toFixed(1));
      c.cursor.setAttribute('x2', x.toFixed(1));
      c.cursor.style.opacity = 1;
      const readout = document.getElementById(`readout-${c.key}`);
      const value = c.values[index];
      if (readout) readout.textContent = value == null ? '—' : c.spec.format(value);
    }
  }
  function clearCursors() {
    for (const c of cursors) {
      c.cursor.style.opacity = 0;
      const readout = document.getElementById(`readout-${c.key}`);
      if (readout) readout.textContent = '';
    }
  }
  return { dispose: () => charts.forEach(c => c.dispose && c.dispose()) };
}

/* ================================================================== trace GPS */
/** Trace projetée en Mercator local, colorée par une métrique. */
export function routeMap(container, { lat, lon, values = null, colorBy = null,
                                      height = 300, zones = null }) {
  clear(container);
  const points = [];
  for (let i = 0; i < lat.length; i += 1) {
    if (lat[i] == null || lon[i] == null) continue;
    points.push([lon[i], lat[i], values ? values[i] : null, i]);
  }
  if (points.length < 2) {
    container.appendChild(el('div.chart-empty', 'Aucune trace GPS pour cette séance.'));
    return { dispose() {} };
  }

  return createChart(container, { height, margin: { top: 8, right: 8, bottom: 8, left: 8 } },
    (ctx) => {
      const { g, inner } = ctx;
      const lons = points.map(p => p[0]);
      const lats = points.map(p => p[1]);
      const [lon0, lon1] = extent(lons);
      const [lat0, lat1] = extent(lats);
      // correction de la convergence des méridiens à la latitude moyenne
      const latMid = (lat0 + lat1) / 2;
      const kx = Math.cos((latMid * Math.PI) / 180);
      const spanX = Math.max(1e-9, (lon1 - lon0) * kx);
      const spanY = Math.max(1e-9, lat1 - lat0);
      const scale = Math.min(inner.width / spanX, inner.height / spanY) * 0.94;
      const offsetX = (inner.width - spanX * scale) / 2;
      const offsetY = (inner.height - spanY * scale) / 2;
      const project = ([lonV, latV]) => [
        offsetX + (lonV - lon0) * kx * scale,
        inner.height - offsetY - (latV - lat0) * scale,
      ];

      const projected = points.map(project);
      g.appendChild(el('path', {
        d: linePath(projected), fill: 'none', stroke: 'var(--border-strong)',
        'stroke-width': 4.5, 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
        opacity: 0.45,
      }));

      if (colorBy && values) {
        const clean = points.map(p => p[2]).filter(v => v != null);
        const [vmin, vmax] = extent(clean);
        const step = Math.max(1, Math.floor(points.length / 900));
        for (let i = step; i < points.length; i += step) {
          const value = points[i][2];
          if (value == null) continue;
          const ratio = (value - vmin) / Math.max(1e-6, vmax - vmin);
          g.appendChild(el('line', {
            x1: projected[i - step][0].toFixed(1), y1: projected[i - step][1].toFixed(1),
            x2: projected[i][0].toFixed(1), y2: projected[i][1].toFixed(1),
            stroke: rampColor(ratio), 'stroke-width': 2.6, 'stroke-linecap': 'round',
          }));
        }
      } else {
        g.appendChild(el('path', {
          d: linePath(projected), fill: 'none', stroke: 'var(--accent)',
          'stroke-width': 2.2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round',
        }));
      }

      const [sx, sy] = projected[0];
      const [ex, ey] = projected[projected.length - 1];
      g.appendChild(el('circle', { cx: sx.toFixed(1), cy: sy.toFixed(1), r: 5,
                                   fill: 'var(--positive)', stroke: 'var(--surface)',
                                   'stroke-width': 2 }));
      g.appendChild(el('circle', { cx: ex.toFixed(1), cy: ey.toFixed(1), r: 5,
                                   fill: 'var(--danger)', stroke: 'var(--surface)',
                                   'stroke-width': 2 }));
    });
}

/** Rampe bleu → vert → jaune → rouge, lisible en thème clair comme sombre. */
export function rampColor(ratio) {
  const stops = [[0, [91, 143, 214]], [0.35, [63, 185, 140]], [0.65, [201, 192, 74]],
                 [0.85, [224, 141, 60]], [1, [216, 84, 63]]];
  const t = Math.max(0, Math.min(1, ratio));
  for (let i = 1; i < stops.length; i += 1) {
    if (t <= stops[i][0]) {
      const [t0, c0] = stops[i - 1];
      const [t1, c1] = stops[i];
      const k = (t - t0) / (t1 - t0 || 1);
      const rgb = c0.map((c, j) => Math.round(c + (c1[j] - c) * k));
      return `rgb(${rgb.join(',')})`;
    }
  }
  return 'rgb(216,84,63)';
}

/* ============================================================ carte de chaleur */
/** Matrice charge × jour, une ligne par athlète. */
export function loadMatrix(container, { dates, matrix, onCellClick = null }) {
  clear(container);
  const maxLoad = Math.max(1, ...matrix.flatMap(r => r.cells.map(c => c.load || 0)));
  const table = el('div.matrix');
  const header = el('div.matrix-row.head', [el('div.matrix-name', '')]);
  dates.forEach((d, i) => {
    const date = F.parseDate(d);
    const showLabel = date.getDate() === 1 || i === 0 || i === dates.length - 1;
    header.appendChild(el('div.matrix-cell.head', { title: F.date(d, 'medium') },
      showLabel ? el('span.matrix-tick', F.date(d, 'short')) : ''));
  });
  table.appendChild(header);

  for (const row of matrix) {
    const line = el('div.matrix-row', [
      el('div.matrix-name', [
        el('span.dot', { style: { background: row.athlete.accent } }),
        el('span.truncate', `${row.athlete.first_name} ${row.athlete.last_name[0]}.`),
      ]),
    ]);
    for (const cell of row.cells) {
      const ratio = (cell.load || 0) / maxLoad;
      const node = el('div.matrix-cell', {
        style: {
          background: cell.load ? `color-mix(in srgb, var(--accent) ${Math.round(12 + ratio * 88)}%, transparent)`
                                : 'var(--surface-3)',
          cursor: onCellClick ? 'pointer' : 'default',
        },
      });
      const cellTip = (event) => showTooltip(tooltipRows(
        `${row.athlete.first_name} ${row.athlete.last_name}`,
        [['Date', F.date(cell.date, 'weekday')],
         ['Charge', cell.load ? F.num(cell.load, 0) : 'repos'],
         cell.tsb != null ? ['Forme', F.signed(cell.tsb, 0)] : null]), event);
      node.addEventListener('mousemove', cellTip);
      node.addEventListener('touchstart', (e) => cellTip(e.touches[0]), { passive: true });
      node.addEventListener('mouseleave', hideTooltip);
      if (onCellClick) node.addEventListener('click', () => onCellClick(row.athlete, cell));
      line.appendChild(node);
    }
    table.appendChild(line);
  }
  container.appendChild(table);
  return { dispose() {} };
}

/** Courbe lactate avec seuils annotés. */
export function lactateCurve(container, { points, thresholds = {}, height = 280,
                                          unit = 'W' }) {
  if (!points.length) return { dispose() {} };
  return createChart(container, { height, margin: { top: 16, right: 46, bottom: 38, left: 48 } },
    (ctx) => {
      const { g, inner } = ctx;
      const xValues = points.map(p => p.intensity);
      const xScale = scaleLinear(padDomain(extent(xValues), 0.06), [0, inner.width]);
      const yScale = scaleLinear([0, Math.max(6, Math.max(...points.map(p => p.lactate)) * 1.15)],
                                 [inner.height, 0]);
      const hrValues = points.map(p => p.hr).filter(v => v != null);
      const hrScale = hrValues.length
        ? scaleLinear(padDomain(extent(hrValues), 0.10), [inner.height, 0]) : null;

      axisY(g, yScale, inner, { ticks: 5, format: (v) => F.num(v, 1) });
      axisX(g, xScale, inner, { ticks: 6, format: (v) => F.num(v, 0), grid: true });
      if (hrScale) axisY(g, hrScale, inner, { ticks: 4, format: (v) => F.num(v, 0),
                                              side: 'right', grid: false });
      g.appendChild(el('text.axis-title', { x: inner.width / 2, y: inner.height + 33,
                                            'text-anchor': 'middle' },
        unit === 'W' ? 'Puissance (W)' : 'Vitesse (m/s)'));

      refLine(g, yScale(4), inner, { label: 'OBLA 4 mmol/L', color: 'var(--warning)' });
      refLine(g, yScale(2), inner, { label: '2 mmol/L', color: 'var(--border-strong)' });

      if (hrScale) {
        g.appendChild(el('path', {
          d: linePath(points.filter(p => p.hr != null)
            .map(p => [xScale(p.intensity), hrScale(p.hr)])),
          fill: 'none', stroke: 'var(--atl)', 'stroke-width': 1.4,
          'stroke-dasharray': '4 3', opacity: 0.75,
        }));
      }
      const curve = points.map(p => [xScale(p.intensity), yScale(p.lactate)]);
      g.appendChild(el('path', { d: linePath(curve), fill: 'none', stroke: 'var(--accent)',
                                 'stroke-width': 2.2 }));
      points.forEach((p, i) => {
        const dot = el('circle', { cx: curve[i][0].toFixed(1), cy: curve[i][1].toFixed(1),
                                   r: 4, fill: 'var(--accent)' });
        dot.addEventListener('mousemove', (event) => showTooltip(tooltipRows(
          `Palier ${i + 1}`,
          [['Intensité', `${F.num(p.intensity, 0)} ${unit}`],
           ['Lactate', `${F.num(p.lactate, 2)} mmol/L`],
           p.hr ? ['FC', `${F.num(p.hr, 0)} bpm`] : null]), event));
        dot.addEventListener('mouseleave', hideTooltip);
        g.appendChild(dot);
      });

      for (const [key, config] of Object.entries({
        lt1: { color: 'var(--positive)', label: 'LT1' },
        lt2_obla: { color: 'var(--warning)', label: 'LT2 (OBLA)' },
        lt2_dmax: { color: 'var(--danger)', label: 'LT2 (Dmax)' },
      })) {
        const threshold = thresholds[key];
        if (!threshold) continue;
        const x = xScale(threshold.intensity);
        g.appendChild(el('line', { x1: x.toFixed(1), x2: x.toFixed(1), y1: 0, y2: inner.height,
                                   stroke: config.color, 'stroke-width': 1.4,
                                   'stroke-dasharray': '3 3' }));
        g.appendChild(el('text.ref-label', { x: (x + 4).toFixed(1), y: 12,
                                             fill: config.color },
          `${config.label} ${F.num(threshold.intensity, 0)}`));
      }
    });
}
