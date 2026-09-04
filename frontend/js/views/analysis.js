/** Comparaison de plusieurs athlètes sur une même métrique. */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { store } from '../lib/store.js';
import {
  avatar, card, chips, dataTable, emptyState, notifyError, pageTitle,
  segmented, setTopbar,
} from '../lib/ui.js';
import { timeSeries, scatter } from '../charts/plots.js';

const METRICS = [
  { value: 'ctl', label: 'Condition (CTL)', decimals: 1,
    help: 'Charge chronique : le niveau de condition construit sur six semaines.' },
  { value: 'atl', label: 'Fatigue (ATL)', decimals: 1,
    help: 'Charge aiguë : la fatigue accumulée sur la semaine écoulée.' },
  { value: 'tsb', label: 'Forme (TSB)', decimals: 1,
    help: 'Différence condition − fatigue de la veille : la fraîcheur disponible.' },
  { value: 'load', label: 'Charge quotidienne', decimals: 0,
    help: 'Charge d’entraînement du jour, toutes séances confondues.' },
  { value: 'acwr_ewma', label: 'Ratio charge A:C', decimals: 2,
    help: 'Rapport charge aiguë / charge chronique. Fenêtre d’équilibre : 0,80 à 1,30.' },
  { value: 'monotony', label: 'Monotonie', decimals: 2,
    help: 'Uniformité des charges quotidiennes sur 7 jours (Foster). Au-delà de 2, alerte.' },
  { value: 'readiness', label: 'Disponibilité', decimals: 0,
    help: 'Score composite quotidien de 0 à 100.' },
  { value: 'hrv_ln_rmssd', label: 'VFC — ln(RMSSD)', decimals: 2,
    help: 'Variabilité cardiaque en échelle logarithmique.' },
  { value: 'resting_hr', label: 'FC de repos', decimals: 0,
    help: 'Fréquence cardiaque au réveil.' },
  { value: 'sleep_total_min', label: 'Sommeil (min)', decimals: 0,
    help: 'Durée totale de sommeil par nuit.' },
];

export async function render(root, context) {
  if (store.athletes.length < 1) {
    setTopbar(pageTitle('Comparaison'));
    mount(root, emptyState('Aucun athlète', 'Ajoutez des athlètes pour les comparer.'));
    return;
  }
  const selected = new Set(store.athletes.slice(0, 4).map(a => a.id));
  let metric = 'ctl';
  let days = 120;

  setTopbar(pageTitle('Comparaison',
    'même métrique, plusieurs athlètes, période commune',
    segmented([{ value: 60, label: '60 j' }, { value: 120, label: '120 j' },
               { value: 365, label: '1 an' }], days, (v) => { days = v; load(); })));

  const board = el('div');
  mount(root, [
    el('div.section', [
      el('div.label', { style: { marginBottom: 'var(--sp-2)' } }, 'Athlètes comparés'),
      el('div.compare-legend', store.athletes.map(athlete =>
        el(`div.compare-item.${selected.has(athlete.id) ? 'on' : 'off'}`, {
          onclick: (e) => {
            if (selected.has(athlete.id)) selected.delete(athlete.id);
            else selected.add(athlete.id);
            e.currentTarget.classList.toggle('on');
            e.currentTarget.classList.toggle('off');
            load();
          },
        }, [
          el('span.dot', { style: { width: '9px', height: '9px', borderRadius: '2px',
                                    background: athlete.accent } }),
          `${athlete.first_name} ${athlete.last_name}`,
        ]))),
    ]),
    el('div.section', [
      el('div.label', { style: { marginBottom: 'var(--sp-2)' } }, 'Métrique'),
      chips(METRICS.map(m => ({ value: m.value, label: m.label })), metric,
            (v) => { metric = v; load(); }),
    ]),
    board,
  ]);

  async function load() {
    if (!selected.size) {
      mount(board, emptyState('Aucune sélection', 'Choisissez au moins un athlète.'));
      return;
    }
    mount(board, el('div.loading-screen', [el('span.spinner')]));
    try {
      const spec = METRICS.find(m => m.value === metric);
      const data = await api.compare({
        athletes: [...selected].join(','), metric, days });

      // fusion des séries sur un axe de dates commun
      const dates = [...new Set(data.series.flatMap(s => s.points.map(p => p.date)))].sort();
      const merged = dates.map(date => {
        const row = { date };
        for (const serie of data.series) {
          const point = serie.points.find(p => p.date === date);
          row[`a${serie.athlete.id}`] = point ? point.value : null;
        }
        return row;
      });

      mount(board, [
        card(spec.label, el('div.chart-box', { id: 'compare-chart' }),
          { subtitle: spec.help, className: 'section' }),
        card('Statistiques sur la période', dataTable({
          columns: [
            { label: 'Athlète', render: (row) => el('div.row-tight', {
                style: { cursor: 'pointer' },
                onclick: () => navigate(`/athlete/${row.athlete.id}`) }, [
                avatar(row.athlete, 'sm'),
                `${row.athlete.first_name} ${row.athlete.last_name}`]) },
            { label: 'Actuel', numeric: true, render: (row) =>
                el('span.mono', { style: { fontWeight: 600 } },
                   F.num(row.stats.last, spec.decimals)) },
            { label: 'Moyenne', numeric: true, render: (row) =>
                el('span.mono', F.num(row.stats.mean, spec.decimals)) },
            { label: 'Minimum', numeric: true, render: (row) =>
                el('span.mono.muted', F.num(row.stats.min, spec.decimals)) },
            { label: 'Maximum', numeric: true, render: (row) =>
                el('span.mono.muted', F.num(row.stats.max, spec.decimals)) },
            { label: 'Amplitude', numeric: true, render: (row) =>
                el('span.mono.muted', row.stats.max != null && row.stats.min != null
                  ? F.num(row.stats.max - row.stats.min, spec.decimals) : '—') },
          ],
          rows: data.series,
        }), { flush: true }),
      ]);

      timeSeries(document.getElementById('compare-chart'), {
        data: merged, height: 320,
        series: data.series.map(serie => ({
          key: `a${serie.athlete.id}`,
          label: `${serie.athlete.first_name} ${serie.athlete.last_name}`,
          color: serie.athlete.accent, type: 'line', width: 1.8,
          decimals: spec.decimals, smooth: metric === 'hrv_ln_rmssd',
        })),
        formatY: (v) => F.num(v, spec.decimals),
        bands: metric === 'acwr_ewma'
          ? [{ from: 0.8, to: 1.3, color: 'var(--positive-dim)', label: 'zone d’équilibre' }] : [],
        refs: metric === 'acwr_ewma'
          ? [{ value: 1.5, label: 'seuil de risque', color: 'var(--danger)' }]
          : metric === 'monotony'
            ? [{ value: 2.0, label: 'seuil d’alerte', color: 'var(--warning)' }] : [],
        zeroLine: metric === 'tsb',
      });
    } catch (error) { notifyError(error); }
  }
  await load();
}
