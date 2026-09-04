/**
 * Bibliothèque de graphiques.
 *
 * Chaque fonction reçoit un conteneur et une configuration, et renvoie un
 * objet doté de `redraw()` / `dispose()`. Les couleurs viennent des jetons
 * CSS, donc les graphiques suivent automatiquement le thème.
 */
import { el, clear } from '../lib/dom.js';
import * as F from '../lib/format.js';
import {
  areaPath, axisX, axisY, createChart, crosshair, extent, gradient, hideTooltip,
  legend, linePath, nextId, niceTicks, padDomain, refBand, refLine, scaleLinear,
  scaleLog, showTooltip, smoothPath, tooltipRows,
} from './core.js';

const dayIndex = (dates) => dates.map((_, i) => i);

/* ============================================================ séries temporelles */
/**
 * Séries temporelles multiples.
 * series : [{key, label, color, type: 'line'|'area'|'bar', width, dashed,
 *            axis: 'left'|'right', smooth}]
 */
export function timeSeries(container, {
  data, x = 'date', series, height = 240, margin, yDomain, y2Domain,
  formatY = (v) => F.num(v, 0), formatY2 = (v) => F.num(v, 0),
  formatX = (v) => F.date(v, 'short'), bands = [], refs = [],
  legendItems = null, zeroLine = false, xTicks = 6,
}) {
  const dates = data.map(d => d[x]);
  const indices = dayIndex(dates);

  return createChart(container, { height, margin, label: 'série temporelle' }, (ctx) => {
    const { g, svg, inner } = ctx;
    const xScale = scaleLinear([0, Math.max(1, indices.length - 1)], [0, inner.width]);

    const leftSeries = series.filter(s => s.axis !== 'right');
    const rightSeries = series.filter(s => s.axis === 'right');
    const collect = (list) => list.flatMap(s => data.map(d => d[s.key]))
      .filter(v => v !== null && v !== undefined && !Number.isNaN(v));

    const leftValues = collect(leftSeries);
    const domain = yDomain || padDomain(extent(leftValues.length ? leftValues : [0, 1]),
                                        0.10, !zeroLine);
    if (zeroLine) { domain[0] = Math.min(domain[0], 0); domain[1] = Math.max(domain[1], 0); }
    const yScale = scaleLinear(domain, [inner.height, 0]);

    let y2Scale = null;
    if (rightSeries.length) {
      const rightValues = collect(rightSeries);
      y2Scale = scaleLinear(y2Domain || padDomain(extent(rightValues), 0.12),
                            [inner.height, 0]);
    }

    for (const band of bands) {
      refBand(g, yScale(band.from), yScale(band.to), inner,
              { color: band.color, label: band.label });
    }
    axisY(g, yScale, inner, { ticks: 5, format: formatY });
    if (y2Scale) axisY(g, y2Scale, inner, { ticks: 4, format: formatY2, side: 'right', grid: false });
    axisX(g, xScale, inner, {
      values: niceTicks(0, indices.length - 1, xTicks).map(Math.round)
        .filter(i => i >= 0 && i < dates.length),
      format: (i) => formatX(dates[Math.round(i)]),
    });
    if (zeroLine) refLine(g, yScale(0), inner, { color: 'var(--border-strong)', dash: '0' });
    for (const ref of refs) {
      refLine(g, yScale(ref.value), inner,
              { label: ref.label, color: ref.color, dash: ref.dash });
    }

    const barSeries = series.filter(s => s.type === 'bar');
    for (const s of barSeries) {
      const barWidth = Math.max(1, (inner.width / Math.max(1, data.length)) * 0.72);
      const base = yScale(Math.max(domain[0], 0));
      data.forEach((row, i) => {
        const value = row[s.key];
        if (value === null || value === undefined || !value) return;
        const y = yScale(value);
        g.appendChild(el('rect', {
          x: (xScale(i) - barWidth / 2).toFixed(1),
          y: Math.min(y, base).toFixed(1),
          width: barWidth.toFixed(1),
          height: Math.max(0.8, Math.abs(base - y)).toFixed(1),
          fill: typeof s.color === 'function' ? s.color(row) : s.color,
          opacity: s.opacity ?? 0.8, rx: 1,
        }));
      });
    }

    for (const s of series.filter(s => s.type !== 'bar')) {
      const scale = s.axis === 'right' ? y2Scale : yScale;
      const points = data.map((row, i) => [xScale(i), row[s.key] === null ||
        row[s.key] === undefined ? null : scale(row[s.key])]);
      if (s.type === 'area') {
        const id = nextId('area');
        const fill = gradient(svg, id, s.color, s.fillFrom ?? 0.28, 0);
        g.appendChild(el('path', {
          d: areaPath(points, inner.height), fill, stroke: 'none',
        }));
      }
      g.appendChild(el('path', {
        d: s.smooth ? smoothPath(points) : linePath(points),
        fill: 'none', stroke: s.color, 'stroke-width': s.width || 1.75,
        'stroke-linejoin': 'round', 'stroke-linecap': 'round',
        'stroke-dasharray': s.dashed ? '4 3' : null,
        opacity: s.opacity ?? 1,
      }));
    }

    // marqueurs interactifs
    const markers = series.filter(s => s.type !== 'bar').map(s =>
      el('circle', {
        r: 3.4, fill: 'var(--surface)', stroke: s.color, 'stroke-width': 2,
        style: { opacity: 0 },
      }));
    markers.forEach(m => g.appendChild(m));

    crosshair(g, inner, indices, xScale, (index, event) => {
      const row = data[index];
      const lines = series.map((s, si) => {
        const value = row[s.key];
        const marker = markers[series.filter(x => x.type !== 'bar').indexOf(s)];
        if (marker) {
          if (value === null || value === undefined) { marker.style.opacity = 0; }
          else {
            const scale = s.axis === 'right' ? y2Scale : yScale;
            marker.setAttribute('cx', xScale(index).toFixed(1));
            marker.setAttribute('cy', scale(value).toFixed(1));
            marker.style.opacity = 1;
          }
        }
        if (value === null || value === undefined) return null;
        return [s.label, s.format ? s.format(value) : F.num(value, s.decimals ?? 1), s.color];
      });
      showTooltip(tooltipRows(F.date(row[x], 'weekday'), lines), event);
    }, () => markers.forEach(m => { m.style.opacity = 0; }));

    if (legendItems !== false) {
      const items = legendItems || series.map(s => ({ label: s.label, color: s.color,
                                                      dashed: s.dashed }));
      const existing = container.parentElement?.querySelector('.chart-legend');
      if (existing) existing.remove();
      container.parentElement?.insertBefore(legend(items), container);
    }
  });
}

/* ==================================================================== PMC */
/**
 * Graphique de forme, en deux panneaux partageant l'axe des temps.
 *
 * Condition (CTL) et fatigue (ATL) en haut, forme (TSB) en bas. Superposer
 * les trois sur un seul panneau donne trois courbes bruitées dont deux sont
 * quasi symétriques (TSB = CTL − ATL) : illisible. Séparer la forme lui rend
 * sa lecture propre — au-dessus de zéro on est frais, en dessous on encaisse.
 */
export function pmcChart(container, { pmc, projection = [], height = 280, events = [] }) {
  const data = [...pmc.map(p => ({ ...p, projected: false })),
                ...projection.map(p => ({ ...p, projected: true }))];
  if (!data.length) return emptyChart(container, 'Aucune donnée de charge.');

  const gap = 14;
  const formHeight = Math.round(height * 0.30);
  const fitnessHeight = height - formHeight - gap;

  return createChart(container, { height: height + 26,
                                  margin: { top: 14, right: 46, bottom: 24, left: 46 } },
    (ctx) => {
      const { g, svg, inner } = ctx;
      const indices = data.map((_, i) => i);
      const xScale = scaleLinear([0, data.length - 1], [0, inner.width]);
      const fitness = data.flatMap(d => [d.ctl, d.atl]).filter(v => v != null);
      const yScale = scaleLinear([0, Math.max(10, Math.max(...fitness) * 1.10)],
                                 [fitnessHeight, 0]);
      const tsbValues = data.map(d => d.tsb).filter(v => v != null);
      const tsbAbs = Math.max(12, ...tsbValues.map(Math.abs)) * 1.12;
      const formTop = fitnessHeight + gap;
      const y2Scale = scaleLinear([-tsbAbs, tsbAbs], [formTop + formHeight, formTop]);

      const upper = el('g');
      const lower = el('g');
      g.appendChild(upper); g.appendChild(lower);

      /* ------------------------------------------- panneau haut : CTL / ATL */
      axisY(upper, yScale, { ...inner, height: fitnessHeight }, {
        ticks: 4, format: (v) => F.num(v, 0) });

      // charge quotidienne, en fond du panneau haut
      const maxLoad = Math.max(...data.map(d => d.load || 0), 1);
      const loadScale = scaleLinear([0, maxLoad],
                                    [fitnessHeight, fitnessHeight * 0.55]);
      const barWidth = Math.max(0.8, (inner.width / data.length) * 0.62);
      data.forEach((d, i) => {
        if (!d.load) return;
        const y = loadScale(d.load);
        upper.appendChild(el('rect', {
          x: (xScale(i) - barWidth / 2).toFixed(1), y: y.toFixed(1),
          width: barWidth.toFixed(1), height: (fitnessHeight - y).toFixed(1),
          fill: d.projected ? 'var(--accent)' : 'var(--border-strong)',
          opacity: d.projected ? 0.30 : 0.45, rx: 0.5,
        }));
      });

      const ctlPoints = data.map((d, i) => [xScale(i), d.ctl == null ? null : yScale(d.ctl)]);
      upper.appendChild(el('path', {
        d: areaPath(ctlPoints, fitnessHeight),
        fill: gradient(svg, nextId('ctl'), 'var(--ctl)', 0.26, 0), stroke: 'none',
      }));
      upper.appendChild(el('path', {
        d: linePath(data.map((d, i) => [xScale(i), d.atl == null ? null : yScale(d.atl)])),
        fill: 'none', stroke: 'var(--atl)', 'stroke-width': 1.2, opacity: 0.8,
      }));
      upper.appendChild(el('path', {
        d: linePath(ctlPoints), fill: 'none', stroke: 'var(--ctl)', 'stroke-width': 2.2,
      }));

      /* --------------------------------------------- panneau bas : forme */
      const zero = y2Scale(0);
      const tsbPoints = data.map((d, i) => [xScale(i), d.tsb == null ? null : y2Scale(d.tsb)]);
      const clipPositive = nextId('clip-pos');
      const clipNegative = nextId('clip-neg');
      const defs = el('defs', [
        el('clipPath', { id: clipPositive },
          [el('rect', { x: 0, y: formTop, width: inner.width,
                        height: Math.max(0, zero - formTop) })]),
        el('clipPath', { id: clipNegative },
          [el('rect', { x: 0, y: zero, width: inner.width,
                        height: Math.max(0, formTop + formHeight - zero) })]),
      ]);
      svg.insertBefore(defs, svg.firstChild);
      const area = areaPath(tsbPoints, zero);
      lower.appendChild(el('path', { d: area, fill: 'var(--tsb)', opacity: 0.30,
                                     'clip-path': `url(#${clipPositive})` }));
      lower.appendChild(el('path', { d: area, fill: 'var(--atl)', opacity: 0.22,
                                     'clip-path': `url(#${clipNegative})` }));
      lower.appendChild(el('path', { d: linePath(tsbPoints), fill: 'none',
                                     stroke: 'var(--text-muted)', 'stroke-width': 1 }));
      lower.appendChild(el('line', {
        x1: 0, x2: inner.width, y1: zero.toFixed(1), y2: zero.toFixed(1),
        stroke: 'var(--border-strong)', 'stroke-width': 1,
      }));
      for (const value of [tsbAbs * 0.6, -tsbAbs * 0.6]) {
        lower.appendChild(el('text.axis-label', {
          x: -8, y: (y2Scale(value) + 3.5).toFixed(1), 'text-anchor': 'end',
        }, F.signed(Math.round(value / 5) * 5, 0)));
      }
      lower.appendChild(el('text.ref-label', {
        x: 3, y: (formTop + 11).toFixed(1), 'text-anchor': 'start',
      }, 'Forme (TSB)'));

      /* ------------------------------------------------------ repères communs */
      const style = data.length > 200 ? 'monthShort' : 'short';
      axisX(g, xScale, { ...inner, height: formTop + formHeight }, {
        values: niceTicks(0, data.length - 1, 7).map(Math.round)
          .filter(i => i >= 0 && i < data.length),
        format: (i) => F.date(data[Math.round(i)].date, style),
      });

      if (projection.length) {
        const boundary = xScale(pmc.length - 1);
        g.insertBefore(el('rect', {
          x: boundary.toFixed(1), y: 0, width: (inner.width - boundary).toFixed(1),
          height: formTop + formHeight, fill: 'var(--grid)',
        }), g.firstChild);
        g.appendChild(el('line', {
          x1: boundary.toFixed(1), x2: boundary.toFixed(1), y1: 0,
          y2: formTop + formHeight, stroke: 'var(--border-strong)',
          'stroke-width': 1, 'stroke-dasharray': '3 3',
        }));
        g.appendChild(el('text.ref-label', {
          x: (boundary + 5).toFixed(1), y: 11, 'text-anchor': 'start',
        }, 'projection'));
      }

      for (const event of events) {
        const index = data.findIndex(d => d.date === event.date);
        if (index < 0) continue;
        const x = xScale(index);
        g.appendChild(el('line', {
          x1: x.toFixed(1), x2: x.toFixed(1), y1: 0, y2: formTop + formHeight,
          stroke: 'var(--danger)', 'stroke-width': 1, 'stroke-dasharray': '2 3',
          opacity: 0.75,
        }));
        g.appendChild(el('text.ref-label', {
          x: (x + 4).toFixed(1), y: 22, fill: 'var(--danger)',
        }, event.name.slice(0, 20)));
      }

      const marks = [
        el('circle', { r: 3.6, fill: 'var(--surface)', stroke: 'var(--ctl)',
                       'stroke-width': 2, style: { opacity: 0 } }),
        el('circle', { r: 3.2, fill: 'var(--surface)', stroke: 'var(--atl)',
                       'stroke-width': 2, style: { opacity: 0 } }),
        el('circle', { r: 3, fill: 'var(--surface)', stroke: 'var(--text-muted)',
                       'stroke-width': 2, style: { opacity: 0 } }),
      ];
      marks.forEach(m => g.appendChild(m));

      crosshair(g, { ...inner, height: formTop + formHeight }, indices, xScale,
        (index, event) => {
          const d = data[index];
          [[d.ctl, yScale], [d.atl, yScale], [d.tsb, y2Scale]].forEach(([value, scale], i) => {
            if (value == null) { marks[i].style.opacity = 0; return; }
            marks[i].setAttribute('cx', xScale(index).toFixed(1));
            marks[i].setAttribute('cy', scale(value).toFixed(1));
            marks[i].style.opacity = 1;
          });
          showTooltip(tooltipRows(
            F.date(d.date, 'weekday'),
            [
              ['Condition (CTL)', F.num(d.ctl, 1), 'var(--ctl)'],
              ['Fatigue (ATL)', F.num(d.atl, 1), 'var(--atl)'],
              ['Forme (TSB)', F.signed(d.tsb, 1), 'var(--tsb)'],
              d.load ? ['Charge du jour', F.num(d.load, 0), 'var(--text-faint)'] : null,
              d.acwr_ewma ? ['Ratio A:C', F.num(d.acwr_ewma, 2), F.acwrColor(d.acwr_ewma)] : null,
            ],
            d.projected ? 'projection' : (d.form || null)), event);
        }, () => marks.forEach(m => { m.style.opacity = 0; }));
    });
}

/* ============================================================ barres empilées */
export function stackedBars(container, {
  data, x = 'period', keys, colors, height = 220, formatX = (v) => v,
  formatY = (v) => F.num(v, 0), overlay = null, overlayColor = 'var(--warning)',
  onBarClick = null, tooltipTitle = (row) => String(row[x]),
}) {
  if (!data.length) return emptyChart(container, 'Aucune donnée sur la période.');
  return createChart(container, { height }, (ctx) => {
    const { g, inner } = ctx;
    const totals = data.map(row => keys.reduce((sum, k) => sum + (row[k] || 0), 0));
    const yScale = scaleLinear([0, Math.max(1, Math.max(...totals) * 1.10)],
                               [inner.height, 0]);
    const step = inner.width / data.length;
    const barWidth = Math.min(46, step * 0.68);

    axisY(g, yScale, inner, { ticks: 4, format: formatY });
    const every = Math.max(1, Math.round(data.length / 10));
    data.forEach((row, i) => {
      if (i % every !== 0) return;
      g.appendChild(el('text.axis-label', {
        x: (step * (i + 0.5)).toFixed(1), y: inner.height + 16, 'text-anchor': 'middle',
      }, formatX(row[x])));
    });

    data.forEach((row, i) => {
      const cx = step * (i + 0.5);
      let cursor = inner.height;
      const group = el('g', { style: { cursor: onBarClick ? 'pointer' : 'default' } });
      keys.forEach((key, ki) => {
        const value = row[key] || 0;
        if (!value) return;
        const h = inner.height - yScale(value);
        cursor -= h;
        group.appendChild(el('rect', {
          x: (cx - barWidth / 2).toFixed(1), y: cursor.toFixed(1),
          width: barWidth.toFixed(1), height: Math.max(0.7, h).toFixed(1),
          fill: colors[ki % colors.length], rx: 1.5,
        }));
      });
      group.addEventListener('mousemove', (event) => showTooltip(tooltipRows(
        tooltipTitle(row),
        keys.map((key, ki) => row[key] ? [key, formatY(row[key]), colors[ki % colors.length]] : null)
          .concat([['Total', formatY(totals[i]), null]])), event));
      group.addEventListener('mouseleave', hideTooltip);
      if (onBarClick) group.addEventListener('click', () => onBarClick(row));
      g.appendChild(group);
    });

    if (overlay) {
      const points = data.map((row, i) => [step * (i + 0.5),
        row[overlay] == null ? null : yScale(row[overlay])]);
      g.appendChild(el('path', {
        d: smoothPath(points), fill: 'none', stroke: overlayColor,
        'stroke-width': 1.8, 'stroke-dasharray': '4 3',
      }));
    }
  });
}

/* ========================================================== courbe record */
export function powerCurve(container, {
  curves, height = 280, unit = 'W', model = null, perKg = false, weight = null,
  formatValue = null,
}) {
  const names = Object.keys(curves);
  if (!names.length) return emptyChart(container, 'Aucune donnée de performance.');
  const palette = ['var(--accent)', 'var(--positive)', 'var(--warning)', 'var(--text-faint)'];
  const format = formatValue || ((v) => `${F.num(v, unit === 'W' ? 0 : 2)} ${unit}`);

  return createChart(container, { height, margin: { top: 14, right: 18, bottom: 30, left: 52 } },
    (ctx) => {
      const { g, inner } = ctx;
      const allDurations = [...new Set(names.flatMap(n => curves[n].map(p => p.duration_s)))]
        .sort((a, b) => a - b);
      const scaleValue = (p) => (perKg && weight ? p.value / weight : p.value);
      const allValues = names.flatMap(n => curves[n].map(scaleValue));
      const xScale = scaleLog([Math.max(1, allDurations[0]),
                               allDurations[allDurations.length - 1]], [0, inner.width]);
      const yScale = scaleLinear(padDomain(extent(allValues), 0.10, true), [inner.height, 0]);

      axisY(g, yScale, inner, { ticks: 5,
        format: (v) => F.num(v, perKg ? 1 : 0) });
      const labels = { 1: '1 s', 5: '5 s', 15: '15 s', 60: '1 min', 300: '5 min',
                       600: '10 min', 1200: '20 min', 3600: '1 h', 10800: '3 h', 18000: '5 h' };
      for (const [seconds, label] of Object.entries(labels)) {
        const value = Number(seconds);
        if (value < xScale.domain[0] || value > xScale.domain[1]) continue;
        const x = xScale(value);
        g.appendChild(el('line.grid-line', { x1: x.toFixed(1), x2: x.toFixed(1),
                                             y1: 0, y2: inner.height }));
        g.appendChild(el('text.axis-label', { x: x.toFixed(1), y: inner.height + 17,
                                              'text-anchor': 'middle' }, label));
      }

      if (model && model.cp_w) {
        const modelPoints = allDurations.map(d => {
          const k = model.w_prime_j / Math.max(1, (model.pmax_w || 1500) - model.cp_w);
          const value = model.cp_w + model.w_prime_j / (d + k);
          return [xScale(d), yScale(perKg && weight ? value / weight : value)];
        });
        g.appendChild(el('path', {
          d: linePath(modelPoints), fill: 'none', stroke: 'var(--text-faint)',
          'stroke-width': 1.2, 'stroke-dasharray': '3 4', opacity: 0.7,
        }));
      }

      names.forEach((name, ni) => {
        const points = curves[name]
          .filter(p => p.duration_s >= xScale.domain[0])
          .map(p => [xScale(p.duration_s), yScale(scaleValue(p))]);
        g.appendChild(el('path', {
          d: linePath(points), fill: 'none', stroke: palette[ni % palette.length],
          'stroke-width': ni === 0 ? 2.2 : 1.6, opacity: ni === 0 ? 1 : 0.72,
        }));
      });

      const primary = curves[names[0]];
      const overlay = el('rect', { x: 0, y: 0, width: inner.width, height: inner.height,
                                   fill: 'transparent', style: { cursor: 'crosshair' } });
      const marker = el('circle', { r: 4, fill: 'var(--surface)', stroke: 'var(--accent)',
                                    'stroke-width': 2, style: { opacity: 0 } });
      g.appendChild(marker); g.appendChild(overlay);
      overlay.addEventListener('mousemove', (event) => {
        const box = overlay.getBoundingClientRect();
        const duration = xScale.invert(((event.clientX - box.left) / box.width) * inner.width);
        let best = primary[0], bestDistance = Infinity;
        for (const p of primary) {
          const d = Math.abs(Math.log10(p.duration_s) - Math.log10(duration));
          if (d < bestDistance) { bestDistance = d; best = p; }
        }
        marker.setAttribute('cx', xScale(best.duration_s).toFixed(1));
        marker.setAttribute('cy', yScale(scaleValue(best)).toFixed(1));
        marker.style.opacity = 1;
        const rows = names.map((name, ni) => {
          const point = curves[name].find(p => p.duration_s === best.duration_s);
          return point ? [name, format(scaleValue(point)), palette[ni % palette.length]] : null;
        });
        showTooltip(tooltipRows(F.duration(best.duration_s, 'long'), rows), event);
      });
      overlay.addEventListener('mouseleave', () => { marker.style.opacity = 0; hideTooltip(); });

      const existing = container.parentElement?.querySelector('.chart-legend');
      if (existing) existing.remove();
      container.parentElement?.insertBefore(legend([
        ...names.map((n, i) => ({ label: n, color: palette[i % palette.length] })),
        model ? { label: 'modèle CP/W′', color: 'var(--text-faint)', dashed: true } : null,
      ]), container);
    });
}

/* ====================================================== répartition en zones */
export function zoneBars(container, { zones, distribution, showLabels = true }) {
  clear(container);
  const total = distribution.reduce((s, d) => s + d.seconds, 0) || 1;
  const bar = el('div.zone-bar');
  distribution.forEach((d, i) => {
    const share = (d.seconds / total) * 100;
    if (share < 0.15) return;
    const zone = zones[i] || {};
    const segment = el('div.zone-seg', {
      style: { width: `${share}%`, background: F.ZONE_COLORS[i % 7] },
      title: `${zone.name || `Zone ${i + 1}`} — ${F.duration(d.seconds)} (${share.toFixed(1)} %)`,
    }, share > 6 ? `${Math.round(share)} %` : '');
    segment.addEventListener('mousemove', (event) => showTooltip(tooltipRows(
      zone.name || `Zone ${i + 1}`,
      [['Temps', F.duration(d.seconds)], ['Part', `${share.toFixed(1)} %`],
       zone.low ? ['Plage', `${F.num(zone.low, 0)}–${zone.high ? F.num(zone.high, 0) : '∞'}`] : null],
      zone.purpose), event));
    segment.addEventListener('mouseleave', hideTooltip);
    bar.appendChild(segment);
  });
  container.appendChild(bar);

  if (showLabels) {
    container.appendChild(el('div.zone-legend', distribution.map((d, i) => {
      const zone = zones[i] || {};
      const share = (d.seconds / total) * 100;
      return el('div.zone-legend-item', [
        el('span.zone-dot', { style: { background: F.ZONE_COLORS[i % 7] } }),
        el('span.zone-name', zone.short_name || `Z${i + 1}`),
        el('span.zone-time.mono', F.duration(d.seconds, 'hm')),
        el('span.zone-pct.mono', `${share.toFixed(0)} %`),
      ]);
    })));
  }
  return { redraw: () => {}, dispose: () => {} };
}

/* ============================================================ jauge circulaire */
export function gauge(container, {
  value, max = 100, label = '', sublabel = '', color = 'var(--accent)',
  size = 132, thickness = 9, segments = null,
}) {
  clear(container);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const ratio = value == null ? 0 : Math.max(0, Math.min(1, value / max));
  const svg = el('svg', { viewBox: `0 0 ${size} ${size}`, width: size, height: size,
                          class: 'gauge' });
  const center = size / 2;

  if (segments) {
    let offset = 0;
    for (const segment of segments) {
      const arc = (segment.to - segment.from) / max;
      svg.appendChild(el('circle', {
        cx: center, cy: center, r: radius, fill: 'none', stroke: segment.color,
        'stroke-width': 2.5, opacity: 0.35,
        'stroke-dasharray': `${(arc * circumference * 0.75).toFixed(1)} ${circumference}`,
        'stroke-dashoffset': -(offset * circumference * 0.75).toFixed(1),
        transform: `rotate(135 ${center} ${center})`,
      }));
      offset += arc;
    }
  }
  svg.appendChild(el('circle', {
    cx: center, cy: center, r: radius, fill: 'none', stroke: 'var(--surface-3)',
    'stroke-width': thickness, 'stroke-linecap': 'round',
    'stroke-dasharray': `${(circumference * 0.75).toFixed(1)} ${circumference}`,
    transform: `rotate(135 ${center} ${center})`,
  }));
  svg.appendChild(el('circle', {
    cx: center, cy: center, r: radius, fill: 'none', stroke: color,
    'stroke-width': thickness, 'stroke-linecap': 'round',
    'stroke-dasharray': `${(ratio * circumference * 0.75).toFixed(1)} ${circumference}`,
    transform: `rotate(135 ${center} ${center})`,
    style: { transition: 'stroke-dasharray 600ms cubic-bezier(0.4,0,0.2,1)' },
  }));
  container.appendChild(el('div.gauge-wrap', [
    svg,
    el('div.gauge-center', [
      el('div.gauge-value', { style: { color } }, value == null ? '—' : F.num(value, 0)),
      label ? el('div.gauge-label', label) : null,
    ]),
    sublabel ? el('div.gauge-sub', sublabel) : null,
  ]));
  return { redraw: () => {}, dispose: () => {} };
}

/* ================================================================ nuage */
export function scatter(container, {
  points, height = 260, xLabel = '', yLabel = '', formatX = (v) => F.num(v, 1),
  formatY = (v) => F.num(v, 1), color = 'var(--accent)', trend = false,
  onPointClick = null, tooltipFor = null,
}) {
  if (!points.length) return emptyChart(container, 'Pas assez de données.');
  return createChart(container, { height, margin: { top: 14, right: 18, bottom: 38, left: 52 } },
    (ctx) => {
      const { g, inner } = ctx;
      const xScale = scaleLinear(padDomain(extent(points.map(p => p.x)), 0.08),
                                 [0, inner.width]);
      const yScale = scaleLinear(padDomain(extent(points.map(p => p.y)), 0.10),
                                 [inner.height, 0]);
      axisY(g, yScale, inner, { ticks: 5, format: formatY });
      axisX(g, xScale, inner, { ticks: 6, format: formatX, grid: true });
      if (yLabel) {
        g.appendChild(el('text.axis-title', {
          transform: `rotate(-90) translate(${-inner.height / 2},-36)`,
          'text-anchor': 'middle',
        }, yLabel));
      }
      if (xLabel) {
        g.appendChild(el('text.axis-title', {
          x: inner.width / 2, y: inner.height + 33, 'text-anchor': 'middle',
        }, xLabel));
      }

      if (trend && points.length > 3) {
        const n = points.length;
        const mx = points.reduce((s, p) => s + p.x, 0) / n;
        const my = points.reduce((s, p) => s + p.y, 0) / n;
        const sxx = points.reduce((s, p) => s + (p.x - mx) ** 2, 0);
        if (sxx > 0) {
          const slope = points.reduce((s, p) => s + (p.x - mx) * (p.y - my), 0) / sxx;
          const intercept = my - slope * mx;
          const [x0, x1] = xScale.domain;
          g.appendChild(el('line', {
            x1: xScale(x0), y1: yScale(intercept + slope * x0),
            x2: xScale(x1), y2: yScale(intercept + slope * x1),
            stroke: 'var(--text-faint)', 'stroke-width': 1.3, 'stroke-dasharray': '4 4',
          }));
        }
      }

      for (const point of points) {
        const dot = el('circle', {
          cx: xScale(point.x).toFixed(1), cy: yScale(point.y).toFixed(1),
          r: point.r || 3.6, fill: point.color || color, opacity: 0.72,
          style: { cursor: onPointClick ? 'pointer' : 'default' },
        });
        dot.addEventListener('mousemove', (event) => showTooltip(
          tooltipFor ? tooltipFor(point)
            : tooltipRows(point.label || '', [[xLabel || 'x', formatX(point.x)],
                                              [yLabel || 'y', formatY(point.y)]]), event));
        dot.addEventListener('mouseleave', hideTooltip);
        if (onPointClick) dot.addEventListener('click', () => onPointClick(point));
        g.appendChild(dot);
      }
    });
}

/* =========================================================== courbe minuscule */
export function sparkline(container, { values, color = 'var(--accent)', height = 34,
                                       fill = true, baseline = null }) {
  const clean = values.filter(v => v != null);
  if (clean.length < 2) { clear(container); return { redraw() {}, dispose() {} }; }
  return createChart(container, { height, margin: { top: 3, right: 1, bottom: 3, left: 1 },
                                  label: 'tendance' }, (ctx) => {
    const { g, svg, inner } = ctx;
    const xScale = scaleLinear([0, values.length - 1], [0, inner.width]);
    const yScale = scaleLinear(padDomain(extent(clean), 0.12), [inner.height, 0]);
    const points = values.map((v, i) => [xScale(i), v == null ? null : yScale(v)]);
    if (fill) {
      const id = nextId('spark');
      g.appendChild(el('path', {
        d: areaPath(points, inner.height),
        fill: gradient(svg, id, color, 0.24, 0), stroke: 'none',
      }));
    }
    if (baseline != null) {
      g.appendChild(el('line', {
        x1: 0, x2: inner.width, y1: yScale(baseline).toFixed(1),
        y2: yScale(baseline).toFixed(1), stroke: 'var(--border-strong)',
        'stroke-width': 1, 'stroke-dasharray': '2 2',
      }));
    }
    g.appendChild(el('path', { d: linePath(points), fill: 'none', stroke: color,
                               'stroke-width': 1.6, 'stroke-linejoin': 'round' }));
  });
}

export function emptyChart(container, message) {
  clear(container);
  container.appendChild(el('div.chart-empty', message));
  return { redraw: () => {}, dispose: () => {} };
}
