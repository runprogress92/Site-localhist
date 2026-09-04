/**
 * Fiche athlète — sept onglets couvrant l'ensemble du suivi.
 *
 * Chaque onglet est chargé à la demande et garde son propre état ; changer
 * d'onglet ne recharge pas la synthèse déjà obtenue.
 */
import { api } from '../lib/api.js';
import { $, clear, el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { store } from '../lib/store.js';
import {
  avatar, card, chartBox, confirmDialog, dataTable, emptyState, field, formBadge,
  input, metric, modal, notifyError, pageTitle, readinessBadge, scaleField, select,
  segmented, setTopbar, statTile, textarea, toast,
} from '../lib/ui.js';
import { gauge, pmcChart, powerCurve, sparkline, stackedBars, timeSeries, zoneBars,
         scatter } from '../charts/plots.js';
import { lactateCurve } from '../charts/streams.js';

const TABS = [
  { key: 'synthese', label: 'Synthèse' },
  { key: 'charge', label: 'Charge & forme' },
  { key: 'seances', label: 'Séances' },
  { key: 'bien-etre', label: 'Bien-être & VFC' },
  { key: 'physiologie', label: 'Physiologie' },
  { key: 'planning', label: 'Planification' },
  { key: 'suivi', label: 'Notes & santé' },
];

export async function render(root, context) {
  const athleteId = Number(context.params.id);
  const tab = context.params.tab || 'synthese';
  const [athlete, summary] = await Promise.all([
    api.athlete(athleteId),
    api.summary(athleteId, store.period),
  ]);
  if (context.token.stale) return;

  setTopbar(pageTitle(
    `${athlete.first_name} ${athlete.last_name}`,
    [el('a', { href: '#/', onclick: () => navigate('/') }, 'Athlètes'),
     el('span', '/'), el('span', athlete.discipline || F.sportLabel(athlete.primary_sport))],
    el('div.row-tight', [
      segmented([
        { value: 60, label: '60 j' }, { value: 120, label: '120 j' },
        { value: 365, label: '1 an' },
      ], store.period, (days) => {
        localStorage.setItem('athlytics.period', String(days));
        store.period = days;
        render(root, context);
      }),
      el('button.btn.sm', {
        onclick: () => openEditAthlete(athlete, () => render(root, context)),
      }, [icon('edit'), 'Modifier']),
    ])));

  const body = el('div');
  mount(root, [
    header(athlete, summary),
    el('div.tabs', TABS.map(t => el(`button.tab${t.key === tab ? '.active' : ''}`, {
      onclick: () => navigate(`/athlete/${athleteId}/${t.key}`),
    }, t.label))),
    body,
  ]);

  const renderers = {
    synthese: tabSummary, charge: tabLoad, seances: tabSessions,
    'bien-etre': tabWellness, physiologie: tabPhysiology,
    planning: tabPlanning, suivi: tabFollowUp,
  };
  const renderer = renderers[tab] || tabSummary;
  await renderer(body, { athlete, summary, athleteId, reload: () => render(root, context) });
}

/* ------------------------------------------------------------------ en-tête */
function header(athlete, summary) {
  const state = athlete.state;
  const physio = athlete.physiology || {};
  return el('div', [
    el('div.athlete-header', [
      avatar(athlete, 'xl'),
      el('div.athlete-id', { style: { flex: 1, minWidth: 0 } }, [
        el('div.athlete-name', `${athlete.first_name} ${athlete.last_name}`),
        el('div.athlete-meta', [
          el('span', [icon('activity', 'nav-icon'),
                      athlete.discipline || F.sportLabel(athlete.primary_sport)]),
          athlete.age ? el('span', `${Math.floor(athlete.age)} ans`) : null,
          athlete.height_cm ? el('span', `${F.num(athlete.height_cm)} cm`) : null,
          physio.weight_kg ? el('span', `${F.num(physio.weight_kg, 1)} kg`) : null,
          athlete.level ? el('span.badge', athlete.level) : null,
          athlete.team_name ? el('span.badge', athlete.team_name) : null,
          athlete.status === 'injured' ? el('span.badge.neg', 'blessé') : null,
        ]),
        el('div.athlete-meta', { style: { marginTop: '6px' } }, [
          athlete.totals?.sessions
            ? el('span.faint',
                 `${F.num(athlete.totals.sessions)} séances enregistrées · `
                 + `${F.duration(athlete.totals.duration_s, 'hm')} · `
                 + `${F.distance(athlete.totals.distance_m, 0)} · `
                 + `${F.num(athlete.totals.elevation_m, 0)} m D+`)
            : null,
        ]),
      ]),
      el('div', { style: { textAlign: 'right' } }, [
        readinessBadge(state.readiness, state.readiness_flag),
        el('div.faint', { style: { fontSize: '11px', marginTop: '5px' } },
           state.wellness_date ? `relevé du ${F.date(state.wellness_date, 'medium')}`
                               : 'aucun relevé'),
      ]),
    ]),
    el('div.kpi-strip', [
      kpi('Condition', F.num(state.ctl, 1), 'CTL — charge chronique', 'var(--ctl)'),
      kpi('Fatigue', F.num(state.atl, 1), 'ATL — charge aiguë', 'var(--atl)'),
      kpi('Forme', F.signed(state.tsb, 0), state.form || '', F.formColor(state.tsb)),
      kpi('Ratio A:C', F.num(state.acwr, 2), 'aigu / chronique', F.acwrColor(state.acwr)),
      kpi('Monotonie', F.num(state.monotony, 2), 'Foster (seuil 2,0)',
          state.monotony > 2 ? 'var(--warning)' : null),
      kpi('VFC', state.hrv_rmssd ? `${F.num(state.hrv_rmssd, 0)}` : '—', 'RMSSD (ms)'),
      kpi('FC repos', state.resting_hr ? `${F.num(state.resting_hr, 0)}` : '—', 'bpm'),
      kpi('Sommeil', state.sleep_total_min
        ? F.duration(state.sleep_total_min * 60, 'hm') : '—', 'dernière nuit'),
    ]),
  ]);
}

function kpi(label, value, sub, color = null) {
  return el('div.kpi', { style: color ? { borderLeftColor: color } : null }, [
    el('div.kpi-label', label),
    el('div.kpi-value', { style: color ? { color } : null }, value),
    el('div.kpi-sub', sub),
  ]);
}

/* ============================================================== 1. Synthèse */
async function tabSummary(root, ctx) {
  const { summary, athlete, athleteId } = ctx;
  const zoneHr = summary.zone_summary?.hr || [];
  const totalWeek = summary.pmc.slice(-7).reduce((s, p) => s + (p.load || 0), 0);
  const prevWeek = summary.pmc.slice(-14, -7).reduce((s, p) => s + (p.load || 0), 0);
  const delta = prevWeek ? ((totalWeek - prevWeek) / prevWeek) * 100 : null;

  mount(root, [
    el('div.grid.grid-main.section', [
      card('Condition, fatigue et forme',
        [el('div.chart-box', { id: 'pmc-mini' })],
        { subtitle: `${summary.period.days} derniers jours — condition (aire bleue), fatigue `
                  + `(ligne rouge) et forme dans le panneau du bas` }),
      el('div.col', [
        card('Disponibilité du jour', el('div', { id: 'readiness-gauge' }),
             { subtitle: 'score composite VFC · FC de repos · sommeil · ressenti · charge' }),
        card('Semaine en cours', el('div.kv', [
          el('dt', 'Charge'), el('dd', F.num(totalWeek, 0)),
          el('dt', 'Évolution'), el('dd', {
            style: { color: delta > 15 ? 'var(--warning)' : delta < -20
                       ? 'var(--info)' : 'var(--text)' },
          }, delta === null ? '—' : `${F.signed(delta, 0)} %`),
          el('dt', 'Séances'), el('dd', String(athlete.state.week?.sessions || 0)),
          el('dt', 'Durée'), el('dd', F.duration(athlete.state.week?.duration_s, 'hm')),
          el('dt', 'Distance'), el('dd', F.distance(athlete.state.week?.distance_m)),
        ])),
      ]),
    ]),

    el('div.grid.grid-3.section', [
      card('Répartition en zones de fréquence cardiaque',
        el('div', { id: 'zone-bars' }),
        { subtitle: `${summary.period.days} jours — modèle Friel sur la FC au seuil`,
          className: 'span-2' }),
      card('Répartition par sport',
        summary.sports.length
          ? el('div.hbars', summary.sports.map((sport, i) => {
              const max = Math.max(...summary.sports.map(s => s.duration_s));
              return el('div.hbar-row', [
                el('span.truncate', F.sportLabel(sport.sport)),
                el('div.hbar-track', [el('div.hbar-fill', {
                  style: { width: `${(sport.duration_s / max) * 100}%`,
                           background: F.ZONE_COLORS[i % 7] },
                })]),
                el('span.hbar-value', F.duration(sport.duration_s, 'hm')),
              ]);
            }))
          : el('div.muted', 'Aucune séance sur la période.')),
    ]),

    summary.alerts.length ? el('section.section', [
      el('div.section-head', [el('div.section-title', 'Signaux à surveiller')]),
      el('div.col', summary.alerts.slice(0, 4).map(a => el(`div.alert.${a.severity}`, [
        el('div.alert-icon', { style: { color: F.severityColor(a.severity) } },
           [icon(a.severity === 'critical' ? 'alert' : 'info')]),
        el('div', [
          el('div.alert-title', a.title),
          el('div.alert-msg', a.message),
        ]),
      ]))),
    ]) : null,

    el('div.grid.grid-2.section', [
      card('Dernières séances', recentActivities(summary.activities.slice(0, 8)),
           { flush: true, action: el('button.btn.sm.ghost', {
               onclick: () => navigate(`/athlete/${athleteId}/seances`) }, 'Tout voir') }),
      card('Prochaines échéances',
        summary.events.length
          ? el('div.col', { style: { gap: 'var(--sp-3)' } }, summary.events.map(event =>
              el('div.between', [
                el('div', [
                  el('div', { style: { fontWeight: 570 } }, [
                    el('span.badge', { style: { marginRight: '6px' } }, event.priority),
                    event.name]),
                  el('div.faint', { style: { fontSize: '11px' } },
                     `${F.date(event.date, 'long')}${event.location ? ` · ${event.location}` : ''}`),
                ]),
                el('div', { style: { textAlign: 'right' } }, [
                  el('div.mono', { style: { fontWeight: 600 } }, `J−${event.days_out}`),
                  event.target_time_s
                    ? el('div.faint', { style: { fontSize: '11px' } },
                         `objectif ${F.duration(event.target_time_s, 'clock')}`) : null,
                ]),
              ])))
          : el('div.muted', 'Aucun objectif planifié pour l’instant.')),
    ]),
  ]);

  pmcChart(document.getElementById('pmc-mini'), {
    pmc: summary.pmc, height: 250,
    events: summary.events.map(e => ({ date: e.date, name: e.name })),
  });
  const readinessAdvice = {
    vert: 'Organisme disponible : la séance prévue peut être réalisée telle quelle.',
    ambre: 'Disponibilité moyenne : réduire le volume ou l’intensité de 10 à 20 %, '
         + 'et réévaluer à l’échauffement.',
    rouge: 'Disponibilité faible : privilégier la récupération active. Une séance '
         + 'intense coûterait aujourd’hui plus qu’elle n’apporterait.',
  }[athlete.state.readiness_flag] || 'Aucun relevé récent : score non calculable.';
  gauge(document.getElementById('readiness-gauge'), {
    value: athlete.state.readiness, max: 100,
    label: 'disponibilité',
    color: F.readinessColor(athlete.state.readiness_flag),
    sublabel: readinessAdvice,
  });
  if (zoneHr.length) {
    zoneBars(document.getElementById('zone-bars'), {
      zones: summary.zones.hr || [],
      distribution: (summary.zones.hr || []).map((_, i) =>
        zoneHr.find(z => z.zone === i + 1) || { seconds: 0 }),
    });
  } else {
    mount(document.getElementById('zone-bars'),
          el('div.chart-empty', 'Aucune donnée de fréquence cardiaque sur la période.'));
  }
}

function recentActivities(activities) {
  if (!activities.length) return el('div.empty', 'Aucune séance sur la période.');
  return dataTable({
    onRowClick: (row) => navigate(`/seance/${row.id}`),
    columns: [
      { label: 'Date', render: (row) => el('div', [
          el('div.mono', F.date(row.local_date, 'short')),
          el('div.faint', { style: { fontSize: '10.5px' } }, F.time(row.start_time))]) },
      { label: 'Séance', render: (row) => el('div', [
          el('div.truncate', row.name),
          el('div.faint', { style: { fontSize: '11px' } }, F.sportLabel(row.sport))]) },
      { label: 'Durée', numeric: true,
        render: (row) => el('span.mono', F.duration(row.duration_s, 'hm')) },
      { label: 'Charge', numeric: true, render: (row) => el('span.mono', F.num(row.load, 0)) },
    ],
    rows: activities,
  });
}

/* =========================================================== 2. Charge & forme */
async function tabLoad(root, ctx) {
  const { athleteId, summary } = ctx;
  const [pmc, breakdown, zoneDist, curve] = await Promise.all([
    api.pmc(athleteId, { days: Math.max(180, store.period), project: 21 }),
    api.loadBreakdown(athleteId, { group: 'week', periods: 26 }),
    api.zoneDist(athleteId, { days: 90, kind: 'hr' }),
    api.powerCurve(athleteId, { kind: curveKind(ctx.athlete) }),
  ]);

  const current = pmc.current || {};
  mount(root, [
    el('div.grid.grid-4.section', [
      statTile('Condition (CTL)', F.num(current.ctl, 1), {
        sub: `rampe ${F.signed(current.ctl_ramp_7d, 1)} / semaine`,
        tone: (current.ctl_ramp_7d || 0) > 8 ? 'warn' : 'pos' }),
      statTile('Forme (TSB)', F.signed(current.tsb, 0), {
        sub: current.form_advice?.slice(0, 60), color: F.formColor(current.tsb),
        tone: 'plain' }),
      statTile('Ratio charge A:C', F.num(current.acwr_ewma, 2), {
        sub: current.acwr_state, color: F.acwrColor(current.acwr_ewma), tone: 'plain' }),
      statTile('Monotonie / contrainte',
        `${F.num(current.monotony, 2)}`, {
        sub: `strain ${F.num(current.strain, 0)}`,
        tone: current.monotony > 2 ? 'warn' : 'plain' }),
    ]),

    card('Graphique de forme (PMC)', el('div.chart-box', { id: 'pmc-full' }), {
      subtitle: 'En haut : condition construite (aire bleue), fatigue récente (ligne rouge) '
              + 'et charge quotidienne (barres). En bas : la forme — vert au-dessus de zéro '
              + '(fraîcheur), rouge en dessous (fatigue assumée). La zone grisée projette le plan.',
      className: 'section' }),

    el('div.grid.grid-2.section', [
      card('Charge hebdomadaire par sport', el('div.chart-box', { id: 'weekly' }),
        { subtitle: '26 dernières semaines' }),
      card('Ratio charge aiguë / chronique', el('div.chart-box', { id: 'acwr' }),
        { subtitle: 'la bande verte est la fenêtre d’équilibre 0,80–1,30 ; '
                  + 'au-delà de 1,50 le risque de blessure de surcharge augmente' }),
    ]),

    el('div.grid.grid-2.section', [
      card('Distribution d’intensité sur 90 jours', el('div', [
        el('div', { id: 'dist-bars' }),
        el('div.note-box', { style: { marginTop: 'var(--sp-4)' } }, [
          el('div.row-tight', { style: { marginBottom: '6px' } }, [
            el('span.badge.accent', `Indice de polarisation ${F.num(zoneDist.polarization_index, 2)}`),
            el('span.badge', `${F.num(zoneDist.three_zone.low, 0)} % / `
              + `${F.num(zoneDist.three_zone.threshold, 0)} % / `
              + `${F.num(zoneDist.three_zone.high, 0)} %`),
          ]),
          zoneDist.verdict,
        ]),
      ])),
      card(curveKind(ctx.athlete) === 'power' ? 'Courbe record de puissance'
                                              : 'Courbe record de vitesse',
        el('div', [el('div.chart-box', { id: 'power-curve' })]),
        { subtitle: curve.model
            ? modelCaption(curve, curveKind(ctx.athlete))
            : 'meilleures moyennes par durée' }),
    ]),
  ]);

  pmcChart(document.getElementById('pmc-full'), {
    pmc: pmc.pmc, projection: pmc.projection, height: 320,
    events: summary.events.map(e => ({ date: e.date, name: e.name })),
  });
  stackedBars(document.getElementById('weekly'), {
    data: breakdown.periods.map(p => ({ ...p, ...p.by_sport })),
    keys: [...new Set(breakdown.periods.flatMap(p => Object.keys(p.by_sport)))],
    colors: F.ZONE_COLORS, height: 230,
    formatX: (v) => F.date(v, 'short'),
    tooltipTitle: (row) => `Semaine du ${F.date(row.period, 'medium')}`,
  });
  timeSeries(document.getElementById('acwr'), {
    data: pmc.pmc.filter(p => p.acwr_ewma != null),
    series: [
      { key: 'acwr_ewma', label: 'Ratio A:C (EWMA)', color: 'var(--accent)',
        type: 'line', decimals: 2 },
      { key: 'acwr_rolling', label: 'Ratio A:C (glissant)', color: 'var(--text-faint)',
        type: 'line', dashed: true, decimals: 2 },
    ],
    height: 230, formatY: (v) => F.num(v, 2),
    bands: [{ from: 0.8, to: 1.3, color: 'var(--positive-dim)', label: 'fenêtre optimale' }],
    refs: [{ value: 1.5, label: 'seuil de risque', color: 'var(--danger)' }],
  });
  zoneBars(document.getElementById('dist-bars'), {
    zones: zoneDist.distribution,
    distribution: zoneDist.distribution.map(z => ({ seconds: z.seconds })),
  });
  renderCurve(document.getElementById('power-curve'), curve, ctx.athlete);
}

function curveKind(athlete) {
  return ['cycling', 'rowing'].includes(athlete.primary_sport) ? 'power' : 'speed';
}

function modelCaption(curve, kind) {
  if (kind === 'power') {
    return `Modèle ajusté : puissance critique ${F.num(curve.model.cp_w, 0)} W, `
         + `réserve W′ ${F.num(curve.model.w_prime_j / 1000, 1)} kJ (r² = ${F.num(curve.model.r2, 3)})`
         + (curve.phenotype ? ` — profil : ${curve.phenotype}` : '');
  }
  return `Vitesse critique ${F.num(curve.model.cs_ms, 2)} m/s `
       + `(${F.pace(curve.model.cs_pace_s_km)}), D′ ${F.num(curve.model.d_prime_m, 0)} m`;
}

function renderCurve(node, curve, athlete) {
  if (!node) return;
  const kind = curveKind(athlete);
  const curves = curve.curves || {};
  if (!Object.keys(curves).length) {
    mount(node, el('div.chart-empty', 'Pas encore de données de performance.'));
    return;
  }
  powerCurve(node, {
    curves, height: 260, unit: kind === 'power' ? 'W' : 'm/s',
    model: curve.model && kind === 'power'
      ? { ...curve.model, pmax_w: (curve.curves['Historique'] || [])[0]?.value } : null,
    formatValue: kind === 'power'
      ? (v) => `${F.num(v, 0)} W` : (v) => F.pace(F.speedToPace(v)),
  });
}

/* =============================================================== 3. Séances */
async function tabSessions(root, ctx) {
  const { athleteId } = ctx;
  const state = { sport: '', from: '', page: 0 };
  const container = el('div');
  mount(root, [
    el('div.between.section', [
      el('div.row-tight.wrap', [
        el('select.select', {
          style: { width: '180px' },
          onchange: (e) => { state.sport = e.target.value; state.page = 0; load(); },
        }, [el('option', { value: '' }, 'Tous les sports'),
            ...Object.entries(store.sports || F.SPORT_LABELS).map(([k, v]) =>
              el('option', { value: k }, v))]),
        el('input.input', {
          type: 'date', style: { width: '160px' },
          onchange: (e) => { state.from = e.target.value; state.page = 0; load(); },
        }),
      ]),
      el('div.row-tight', [
        el('button.btn.sm', {
          onclick: () => window.location.href =
            `/api/activities/export.csv?athlete_id=${athleteId}`,
        }, [icon('download'), 'Exporter en CSV']),
        el('button.btn.sm.primary', {
          onclick: () => openUpload(athleteId, load),
        }, [icon('upload'), 'Importer']),
      ]),
    ]),
    container,
  ]);

  async function load() {
    mount(container, el('div.loading-screen', [el('span.spinner')]));
    const data = await api.activities({
      athlete_id: athleteId, sport: state.sport || undefined,
      from: state.from || undefined, limit: 60, offset: state.page * 60,
    });
    mount(container, [
      card(null, activityTable(data.activities), { flush: true }),
      data.total > 60 ? el('div.between', { style: { marginTop: 'var(--sp-4)' } }, [
        el('span.muted', `${data.offset + 1}–${Math.min(data.offset + 60, data.total)} `
                       + `sur ${data.total}`),
        el('div.row-tight', [
          el('button.btn.sm', { disabled: state.page === 0,
            onclick: () => { state.page -= 1; load(); } }, 'Précédent'),
          el('button.btn.sm', { disabled: data.offset + 60 >= data.total,
            onclick: () => { state.page += 1; load(); } }, 'Suivant'),
        ]),
      ]) : null,
    ]);
  }
  await load();
}

function activityTable(activities) {
  if (!activities.length) {
    return emptyState('Aucune séance', 'Aucune séance ne correspond à ces filtres.');
  }
  return dataTable({
    sortable: true,
    onRowClick: (row) => navigate(`/seance/${row.id}`),
    columns: [
      { label: 'Date', key: 'local_date', render: (row) => el('div', [
          el('div.mono', F.date(row.local_date, 'medium')),
          el('div.faint', { style: { fontSize: '10.5px' } }, F.time(row.start_time))]) },
      { label: 'Séance', key: 'name', render: (row) => el('div', [
          el('div.truncate', { style: { fontWeight: 550 } }, row.name),
          el('div.faint', { style: { fontSize: '11px' } },
             `${F.sportLabel(row.sport)}${row.device_name ? ` · ${row.device_name}` : ''}`)]) },
      { label: 'Durée', key: 'duration_s', numeric: true,
        render: (row) => el('span.mono', F.duration(row.duration_s, 'hm')) },
      { label: 'Distance', key: 'distance_m', numeric: true,
        render: (row) => el('span.mono', F.distance(row.distance_m)) },
      { label: 'D+', key: 'elevation_gain_m', numeric: true,
        render: (row) => el('span.mono.muted', row.elevation_gain_m
          ? `${F.num(row.elevation_gain_m, 0)} m` : '—') },
      { label: 'Allure / vitesse', numeric: true, render: (row) =>
          el('span.mono', F.paceForSport(row.sport, row.avg_speed_ms)) },
      { label: 'FC moy', key: 'avg_hr', numeric: true,
        render: (row) => el('span.mono', row.avg_hr ? F.num(row.avg_hr, 0) : '—') },
      { label: 'NP', key: 'np_w', numeric: true,
        render: (row) => el('span.mono', row.np_w ? `${F.num(row.np_w, 0)} W` : '—') },
      { label: 'IF', key: 'intensity_factor', numeric: true,
        render: (row) => el('span.mono', F.num(row.intensity_factor, 2)) },
      { label: 'Charge', key: 'load', numeric: true, render: (row) =>
          el('span.mono', { style: { fontWeight: 600 } }, F.num(row.load, 0)) },
      { label: 'RPE', key: 'rpe', numeric: true,
        render: (row) => row.rpe ? el('span.badge', String(row.rpe)) : '' },
    ],
    rows: activities,
  });
}

/* ========================================================== 4. Bien-être & VFC */
async function tabWellness(root, ctx) {
  const { athleteId, summary } = ctx;
  const [hrv, readiness] = await Promise.all([
    api.hrv(athleteId, 180), api.readiness(athleteId),
  ]);
  const wellness = summary.wellness;

  mount(root, [
    el('div.between.section', [
      el('div', [
        el('div.section-title', 'Suivi de la variabilité cardiaque'),
        el('div.section-sub', hrv.method),
      ]),
      el('button.btn.sm.primary', {
        onclick: () => openWellnessForm(athleteId, ctx.reload),
      }, [icon('plus'), 'Saisir un relevé']),
    ]),

    el('div.grid.grid-4.section', [
      statTile('VFC (ligne de base 7 j)',
        hrv.points.length ? F.num(Math.exp(lastValue(hrv.points, 'baseline_7d') || 0), 0) : '—',
        { unit: 'ms', sub: hrv.status.label,
          tone: hrv.status.level >= 3 ? 'neg' : hrv.status.level >= 2 ? 'warn' : 'pos' }),
      statTile('Coefficient de variation', F.num(hrv.cv, 1), {
        unit: '%', sub: hrv.cv_baseline ? `référence ${F.num(hrv.cv_baseline, 1)} %`
                                        : 'dispersion jour à jour',
        tone: hrv.cv && hrv.cv_baseline && hrv.cv > hrv.cv_baseline * 1.3 ? 'warn' : 'plain' }),
      statTile('FC de repos',
        F.num(lastValue(hrv.points, 'resting_hr'), 0), {
        unit: 'bpm', sub: hrv.rhr_deviation
          ? `${F.signed(hrv.rhr_deviation.delta_bpm, 1)} vs référence` : 'aucune référence',
        tone: (hrv.rhr_deviation?.level || 0) >= 2 ? 'warn' : 'plain' }),
      statTile('Disponibilité', F.num(readiness.readiness.score, 0), {
        unit: '/100', sub: `couverture des données ${F.pct(readiness.readiness.coverage * 100, 0)}`,
        color: F.readinessColor(readiness.readiness.flag), tone: 'plain' }),
    ]),

    card('ln(RMSSD) — valeur du jour, moyenne 7 jours et plage normale',
      el('div.chart-box', { id: 'hrv-chart' }), {
      subtitle: 'La bande grise est la plage normale (moyenne 60 j ± 0,5 écart-type). '
              + 'Une sortie durable par le bas signale une fatigue non absorbée.',
      className: 'section' }),

    el('div.grid.grid-2.section', [
      card('Décomposition de la disponibilité', readinessDrivers(readiness.readiness),
        { subtitle: readiness.readiness.advice }),
      card('Sommeil et FC de repos', el('div.chart-box', { id: 'sleep-chart' }),
        { subtitle: 'durée de sommeil (barres) et FC de repos (ligne)' }),
    ]),

    card('Ressenti déclaré', el('div.chart-box', { id: 'subjective-chart' }), {
      subtitle: 'échelles de Hooper-Mackinnon, 1 = très bon, 7 = très mauvais',
      className: 'section' }),

    card('Charge et VFC', el('div.chart-box', { id: 'load-hrv' }), {
      subtitle: 'chaque point est un jour : fatigue aiguë en abscisse, ln(RMSSD) en ordonnée. '
              + 'Une pente descendante confirme que la charge pèse sur le système nerveux autonome.',
      className: 'section' }),
  ]);

  timeSeries(document.getElementById('hrv-chart'), {
    data: hrv.points, height: 280,
    series: [
      { key: 'ln_rmssd', label: 'ln(RMSSD) du jour', color: 'var(--text-faint)',
        type: 'line', width: 1, decimals: 2 },
      { key: 'baseline_7d', label: 'Moyenne 7 jours', color: 'var(--accent)',
        type: 'line', width: 2.2, decimals: 2 },
      { key: 'baseline_30d', label: 'Moyenne 30 jours', color: 'var(--positive)',
        type: 'line', dashed: true, width: 1.4, decimals: 2 },
    ],
    formatY: (v) => F.num(v, 2),
    bands: hrv.normal_range.low ? [{
      from: hrv.normal_range.low, to: hrv.normal_range.high,
      color: 'var(--grid-strong)', label: 'plage normale' }] : [],
  });

  timeSeries(document.getElementById('sleep-chart'), {
    data: wellness.map(w => ({ ...w, sleep_h: w.sleep_total_min ? w.sleep_total_min / 60 : null })),
    height: 220,
    series: [
      { key: 'sleep_h', label: 'Sommeil (h)', color: 'var(--z1)', type: 'bar',
        decimals: 1, format: (v) => F.duration(v * 3600, 'hm') },
      { key: 'resting_hr', label: 'FC de repos', color: 'var(--atl)', type: 'line',
        axis: 'right', width: 1.6, decimals: 0, smooth: true },
    ],
    formatY: (v) => F.num(v, 0), formatY2: (v) => F.num(v, 0),
    refs: [{ value: 8, label: 'besoin de référence', color: 'var(--border-strong)' }],
  });

  timeSeries(document.getElementById('subjective-chart'), {
    data: wellness, height: 200,
    series: [
      { key: 'fatigue', label: 'Fatigue', color: 'var(--atl)', type: 'line', smooth: true },
      { key: 'soreness', label: 'Douleurs musculaires', color: 'var(--z4)', type: 'line', smooth: true },
      { key: 'sleep_quality', label: 'Qualité du sommeil', color: 'var(--z1)', type: 'line', smooth: true },
      { key: 'stress_subj', label: 'Stress', color: 'var(--z6)', type: 'line', smooth: true },
      { key: 'motivation', label: 'Motivation', color: 'var(--positive)', type: 'line', smooth: true },
    ],
    yDomain: [1, 7], formatY: (v) => F.num(v, 0),
  });

  const points = [];
  const loadByDate = Object.fromEntries(summary.pmc.map(p => [p.date, p]));
  for (const w of wellness) {
    const day = loadByDate[w.date];
    if (!day || w.hrv_ln_rmssd == null || day.atl == null || day.ctl == null) continue;
    points.push({ x: day.atl - day.ctl, y: w.hrv_ln_rmssd, label: F.date(w.date, 'medium'),
                  color: F.readinessColor(w.readiness_flag) });
  }
  scatter(document.getElementById('load-hrv'), {
    points, height: 260, trend: true,
    xLabel: 'Fatigue aiguë (ATL − CTL)', yLabel: 'ln(RMSSD)',
    formatX: (v) => F.signed(v, 0), formatY: (v) => F.num(v, 2),
  });
}

function lastValue(points, key) {
  for (let i = points.length - 1; i >= 0; i -= 1) {
    if (points[i][key] != null) return points[i][key];
  }
  return null;
}

function readinessDrivers(readiness) {
  const labels = { hrv: 'Variabilité cardiaque', rhr: 'FC de repos', sleep: 'Sommeil',
                   subjective: 'Ressenti déclaré', load: 'Bilan de charge' };
  const entries = Object.entries(readiness.components).filter(([, v]) => v != null);
  if (!entries.length) return el('div.muted', 'Aucune donnée pour ce jour.');
  return el('div', [
    el('div.readiness-drivers', entries.map(([key, value]) => {
      const above = value >= 50;
      const width = Math.abs(value - 50);
      return el('div.driver-row', [
        el('span.muted', labels[key] || key),
        el('div.driver-track', [
          el('div.driver-mid'),
          el('div.driver-fill', {
            style: {
              left: above ? '50%' : `${50 - width}%`, width: `${width}%`,
              background: above ? 'var(--positive)' : 'var(--danger)',
            },
          }),
        ]),
        el('span.mono.right', F.num(value, 0)),
      ]);
    })),
    el('div.note-box', { style: { marginTop: 'var(--sp-4)' } },
      'Chaque composante est ramenée sur 100, 50 correspondant à la référence '
      + 'personnelle de l’athlète. La barre indique l’écart à cette référence ; '
      + 'le score global est la moyenne pondérée des composantes disponibles.'),
  ]);
}

/* ========================================================== 5. Physiologie */
async function tabPhysiology(root, ctx) {
  const { athlete, athleteId } = ctx;
  const [tests, estimates, predictions, progression] = await Promise.all([
    api.tests(athleteId), api.estimates(athleteId),
    api.predictions(athleteId).catch(() => null),
    api.progression(athleteId, 18),
  ]);
  const physio = athlete.physiology || {};
  const zones = athlete.zones || {};

  mount(root, [
    el('div.grid.grid-4.section', [
      statTile('VO2max', F.num(physio.vo2max, 1), {
        unit: 'ml/kg/min', sub: athlete.vo2max_rating || 'valeur du profil', tone: 'plain' }),
      physio.ftp_w ? statTile('FTP', F.num(physio.ftp_w, 0), {
        unit: 'W', sub: physio.weight_kg
          ? `${F.num(physio.ftp_w / physio.weight_kg, 2)} W/kg` : null, tone: 'plain' })
        : statTile('Allure au seuil', F.pace(physio.threshold_pace_s_km), {
            sub: `vitesse ${F.num(physio.critical_speed_ms, 2)} m/s`, tone: 'plain' }),
      statTile('FC maximale', F.num(physio.hr_max, 0), {
        unit: 'bpm', sub: `seuil ${F.num(physio.hr_lt2, 0)} · repos ${F.num(physio.hr_rest, 0)}`,
        tone: 'plain' }),
      statTile('Poids', F.num(physio.weight_kg, 1), {
        unit: 'kg', sub: physio.body_fat_pct ? `${F.num(physio.body_fat_pct, 1)} % de masse grasse`
                                             : 'dernière pesée', tone: 'plain' }),
    ]),

    el('div.grid.grid-3.section', [
      card('Zones de fréquence cardiaque', zoneTable(zones.hr, 'bpm'),
        { subtitle: `modèle Friel — base : FC au seuil ${F.num(physio.hr_lt2, 0)} bpm` }),
      zones.power?.length
        ? card('Zones de puissance', zoneTable(zones.power, 'W'),
            { subtitle: `modèle Coggan — base : FTP ${F.num(physio.ftp_w, 0)} W` })
        : card('Zones d’allure', zoneTable(zones.pace, 'm/s', true),
            { subtitle: `base : allure seuil ${F.pace(physio.threshold_pace_s_km)}` }),
      card('Estimations de terrain', estimatesPanel(estimates),
        { subtitle: 'valeurs déduites du profil, à confronter à un test' }),
    ]),

    predictions ? card('Prédictions de performance en course',
      el('div', [
        el('div.row-tight.wrap', { style: { marginBottom: 'var(--sp-4)' } },
          predictions.predictions.map(p => el('div.chip', [
            el('strong', p.label), el('span.mono', F.duration(p.time_s, 'clock')),
            el('span.faint', F.pace(p.pace_s_km)),
          ]))),
        el('div.note-box', predictions.caveat),
      ]), { subtitle: `${predictions.source}${predictions.vdot
              ? ` — VDOT ${F.num(predictions.vdot, 1)}` : ''}`,
            className: 'section' }) : null,

    card('Évolution des indicateurs', el('div.chart-box', { id: 'physio-trend' }),
      { subtitle: '18 derniers mois — les points correspondent aux mises à jour de profil',
        className: 'section' }),

    el('section.section', [
      el('div.between', { style: { marginBottom: 'var(--sp-4)' } }, [
        el('div.section-title', 'Tests et évaluations'),
        el('button.btn.sm', { onclick: () => openPhysiologyForm(athleteId, ctx.reload) },
           [icon('plus'), 'Mettre à jour le profil']),
      ]),
      tests.tests.length
        ? el('div.col', tests.tests.slice(0, 4).map(test => testCard(test)))
        : el('div.card', emptyState('Aucun test enregistré',
            'Les tests de laboratoire et de terrain apparaîtront ici.')),
    ]),
  ]);

  const trend = progression.physiology.filter(p => p.vo2max || p.ftp_w || p.threshold_pace_s_km);
  if (trend.length > 1) {
    timeSeries(document.getElementById('physio-trend'), {
      data: trend.map(p => ({
        date: p.effective_date, vo2max: p.vo2max, ftp: p.ftp_w, weight: p.weight_kg,
        pace: p.threshold_pace_s_km ? 1000 / p.threshold_pace_s_km : null,
      })),
      height: 240,
      series: [
        { key: 'vo2max', label: 'VO2max', color: 'var(--accent)', type: 'line', decimals: 1 },
        physio.ftp_w
          ? { key: 'ftp', label: 'FTP (W)', color: 'var(--z4)', type: 'line',
              axis: 'right', decimals: 0 }
          : { key: 'pace', label: 'Vitesse seuil (m/s)', color: 'var(--z4)', type: 'line',
              axis: 'right', decimals: 2 },
        { key: 'weight', label: 'Poids (kg)', color: 'var(--text-faint)', type: 'line',
          axis: 'right', dashed: true, decimals: 1 },
      ],
      formatX: (v) => F.date(v, 'monthShort'),
    });
  } else {
    mount(document.getElementById('physio-trend'),
          el('div.chart-empty', 'Historique insuffisant pour tracer une évolution.'));
  }

  for (const test of tests.tests.slice(0, 4)) {
    const node = document.getElementById(`lactate-${test.id}`);
    if (node && test.points?.length) {
      const analysis = await api.testAnalysis(test.id);
      lactateCurve(node, {
        points: analysis.thresholds?.curve || test.points.map(p => ({
          intensity: p.intensity, lactate: p.lactate, hr: p.hr })),
        thresholds: analysis.thresholds || {}, height: 260,
      });
      const caption = document.getElementById(`lactate-caption-${test.id}`);
      if (caption && analysis.thresholds?.interpretation) {
        mount(caption, el('div.note-box', analysis.thresholds.interpretation));
      }
    }
  }
}

function zoneTable(zones, unit, isPace = false) {
  if (!zones || !zones.length) return el('div.muted', 'Zones non calculables : profil incomplet.');
  return el('table.zone-table', zones.map((zone, i) => el('tr', [
    el('td', { style: { width: '6px' } },
       el('span.zone-swatch', { style: { background: F.ZONE_COLORS[i % 7] } })),
    el('td', [
      el('div', { style: { fontWeight: 550 } }, `${zone.short_name} · ${zone.name}`),
      el('div.faint', { style: { fontSize: '10.5px' } }, zone.purpose),
    ]),
    el('td.mono.right', { style: { whiteSpace: 'nowrap' } },
      isPace
        ? `${zone.low ? F.pace(1000 / zone.high || 0) : ''}`
          .replace('—', '') || boundsPace(zone)
        : bounds(zone, unit)),
  ])));
}

function bounds(zone, unit) {
  const low = zone.low != null ? F.num(zone.low, 0) : '<';
  const high = zone.high != null ? F.num(zone.high, 0) : '+';
  if (zone.low == null) return `< ${high} ${unit}`;
  if (zone.high == null) return `> ${low} ${unit}`;
  return `${low}–${high} ${unit}`;
}

function boundsPace(zone) {
  const fast = zone.high != null ? F.pace(1000 / zone.high) : null;
  const slow = zone.low != null ? F.pace(1000 / zone.low) : null;
  if (!slow) return `plus lent que ${fast}`;
  if (!fast) return `plus vite que ${slow}`;
  return `${slow} → ${fast}`;
}

function estimatesPanel(estimates) {
  const rows = [];
  const available = estimates.available || {};
  if (available.vo2max_uth) rows.push(['VO2max (FCmax/FCrepos)', `${F.num(available.vo2max_uth, 1)} ml/kg/min`]);
  if (available.vo2max_from_ftp) rows.push(['VO2max (depuis la FTP)', `${F.num(available.vo2max_from_ftp, 1)} ml/kg/min`]);
  if (available.vo2max_from_vma) rows.push(['VO2max (depuis la VMA)', `${F.num(available.vo2max_from_vma, 1)} ml/kg/min`]);
  if (available.ftp_w_per_kg) rows.push(['Rapport poids/puissance', `${F.num(available.ftp_w_per_kg, 2)} W/kg`]);
  if (available.percentile) rows.push(['Situation dans les normes', available.percentile]);
  if (available.bmr_kcal) rows.push(['Métabolisme de base', `${F.num(available.bmr_kcal, 0)} kcal/j`]);
  if (available.tdee_kcal) rows.push(['Dépense totale estimée', `${F.num(available.tdee_kcal, 0)} kcal/j`]);
  const formulas = estimates.hr_max_formulas || {};
  if (formulas.tanaka) {
    rows.push(['FC max estimée (Tanaka)', `${formulas.tanaka.hr_max} bpm ± ${formulas.tanaka.sem_bpm}`]);
  }
  if (!rows.length) return el('div.muted', 'Profil trop incomplet pour produire des estimations.');
  return el('div', [
    el('dl.kv', rows.flatMap(([k, v]) => [el('dt', k), el('dd', v)])),
    (estimates.notes || []).length
      ? el('div.note-box', { style: { marginTop: 'var(--sp-3)' } }, estimates.notes[0]) : null,
  ]);
}

function testCard(test) {
  return card(`${test.type_label} — ${F.date(test.date, 'long')}`,
    el('div', [
      test.protocol ? el('div.definition', test.protocol) : null,
      test.points?.length ? el('div.chart-box', { id: `lactate-${test.id}`,
                                                  style: { marginTop: 'var(--sp-4)' } }) : null,
      el('div', { id: `lactate-caption-${test.id}`, style: { marginTop: 'var(--sp-3)' } }),
      test.results && typeof test.results === 'object'
        ? el('dl.kv', { style: { marginTop: 'var(--sp-3)' } },
            Object.entries(test.results).flatMap(([k, v]) =>
              [el('dt', k), el('dd', String(v))])) : null,
      test.conclusion ? el('div.muted', { style: { marginTop: 'var(--sp-3)' } },
                           test.conclusion) : null,
    ]),
    { subtitle: test.lab });
}

/* ========================================================== 6. Planification */
async function tabPlanning(root, ctx) {
  const { athleteId } = ctx;
  const [planned, events, blocks, compliance] = await Promise.all([
    api.planned(athleteId, { from: F.isoDate(F.addDays(new Date(), -7)),
                             to: F.isoDate(F.addDays(new Date(), 28)) }),
    api.events(athleteId), api.blocks(athleteId), api.compliance(athleteId, 12),
  ]);
  let taper = null;
  try { taper = await api.taper(athleteId, { tsb: 15 }); } catch { /* aucun objectif A */ }

  mount(root, [
    el('div.between.section', [
      el('div', [
        el('div.section-title', 'Trois prochaines semaines'),
        el('div.section-sub',
           `Taux de réalisation sur 12 semaines : ${F.pct(compliance.overall_rate, 0)} `
           + `(${compliance.completed}/${compliance.planned} séances)`),
      ]),
      el('div.row-tight', [
        el('button.btn.sm', { onclick: async () => {
          const result = await api.matchPlanned(athleteId);
          toast(`${result.matched} séance(s) rapprochée(s) du plan.`, 'success');
          ctx.reload();
        } }, [icon('refresh'), 'Rapprocher du réalisé']),
        el('button.btn.sm', { onclick: () => openGenerateWeek(athleteId, ctx.reload) },
           [icon('plus'), 'Générer une semaine']),
      ]),
    ]),
    weeksStrip(planned.planned),

    taper ? card('Simulation d’affûtage', taperPanel(taper),
      { subtitle: `Objectif du ${F.date(taper.target_date, 'long')} — recherche de la `
                + `charge qui amène la forme à +${F.num(taper.target_tsb, 0)} le jour J`,
        className: 'section' }) : null,

    el('div.grid.grid-2.section', [
      card('Objectifs', events.events.length
        ? el('div.col', { style: { gap: 'var(--sp-3)' } },
            events.events.slice(0, 8).map(event => el('div.between', [
              el('div', [
                el('div', [el('span.badge', { style: { marginRight: '6px' } }, event.priority),
                           el('span', { style: { fontWeight: 550 } }, event.name)]),
                el('div.faint', { style: { fontSize: '11px' } },
                   `${F.date(event.date, 'long')}${event.location ? ` · ${event.location}` : ''}`),
              ]),
              el('div.right', [
                el('div.mono', event.days_out >= 0 ? `J−${event.days_out}` : F.relative(event.date)),
                event.result_time_s
                  ? el('div.faint', { style: { fontSize: '11px' } },
                       `réalisé ${F.duration(event.result_time_s, 'clock')}`)
                  : event.target_time_s
                    ? el('div.faint', { style: { fontSize: '11px' } },
                         `cible ${F.duration(event.target_time_s, 'clock')}`) : null,
              ]),
            ])))
        : el('div.muted', 'Aucun objectif enregistré.'),
        { action: el('button.btn.sm.ghost', {
            onclick: () => openEventForm(athleteId, ctx.reload) }, [icon('plus'), 'Ajouter']) }),

      card('Blocs de préparation', blocks.blocks.length
        ? el('div.col', { style: { gap: 'var(--sp-2)' } }, blocks.blocks.slice(0, 8).map(block =>
            el('div', [
              el('div.between', [
                el('span', { style: { fontWeight: 550 } }, block.name),
                el('span.badge', block.phase || ''),
              ]),
              el('div.faint', { style: { fontSize: '11px' } },
                 `${F.date(block.start_date, 'medium')} → ${F.date(block.end_date, 'medium')}`
                 + `${block.focus ? ` · ${block.focus}` : ''}`),
            ])))
        : el('div.muted', 'Aucun bloc défini.')),
    ]),

    card('Réalisation du plan', el('div.chart-box', { id: 'compliance-chart' }),
      { subtitle: 'charge planifiée contre charge réalisée, par semaine',
        className: 'section' }),
  ]);

  if (compliance.weeks.length) {
    timeSeries(document.getElementById('compliance-chart'), {
      data: compliance.weeks.map(w => ({ date: w.week, ...w })), height: 220,
      series: [
        { key: 'target_load', label: 'Charge planifiée', color: 'var(--text-faint)',
          type: 'bar', decimals: 0 },
        { key: 'actual_load', label: 'Charge réalisée', color: 'var(--accent)',
          type: 'line', width: 2, decimals: 0 },
        { key: 'rate', label: 'Séances réalisées (%)', color: 'var(--positive)',
          type: 'line', axis: 'right', dashed: true, decimals: 0 },
      ],
      formatX: (v) => F.date(v, 'short'), formatY2: (v) => `${F.num(v, 0)} %`,
    });
  }
}

function weeksStrip(planned) {
  const start = F.addDays(new Date(), -((new Date().getDay() + 6) % 7));
  const weeks = [];
  for (let w = 0; w < 3; w += 1) {
    const days = [];
    for (let d = 0; d < 7; d += 1) {
      const day = F.addDays(start, w * 7 + d);
      const key = F.isoDate(day);
      const items = planned.filter(p => p.date === key);
      days.push(el(`div.week-day${key === F.isoDate(new Date()) ? '.today' : ''}`, [
        el('div.week-dayname', `${F.DAYS_SHORT[d]} ${day.getDate()}`),
        ...items.map(item => el(
          `div.workout-pill${item.status === 'completed' ? '.done'
            : item.status === 'missed' ? '.missed' : ''}`,
          { title: item.description || '' },
          [
            el('span.w-name', item.name),
            el('span.w-meta',
               `${F.duration(item.target_duration_s, 'hm')} · ${F.num(item.target_load, 0)} pts`
               + (item.compliance_pct ? ` · ${F.num(item.compliance_pct, 0)} %` : '')),
          ])),
      ]));
    }
    weeks.push(el('div', { style: { marginBottom: 'var(--sp-4)' } }, [
      el('div.label', { style: { marginBottom: 'var(--sp-2)' } },
         `Semaine du ${F.date(F.addDays(start, w * 7), 'medium')}`),
      el('div.week-strip', days),
    ]));
  }
  return el('div.section', weeks);
}

function taperPanel(taper) {
  return el('div', [
    el('div.grid.grid-4', { style: { marginBottom: 'var(--sp-4)' } }, [
      metric('Jours restants', String(taper.days), { sub: `dont ${taper.taper_days} d’affûtage` }),
      metric('Charge hebdomadaire visée', F.num(taper.weekly_load, 0), {
        sub: `contre ${F.num(taper.baseline_weekly_load, 0)} actuellement` }),
      metric('Réduction', `${F.num(taper.reduction_pct, 0)} %`, {
        sub: 'volume, à intensité maintenue',
        color: taper.reduction_pct > 65 ? 'var(--warning)' : 'var(--positive)' }),
      metric('Forme le jour J', F.signed(taper.final?.tsb, 0), {
        sub: `condition ${F.num(taper.final?.ctl, 0)} (${F.signed(taper.ctl_cost, 1)})`,
        color: F.formColor(taper.final?.tsb) }),
    ]),
    el('div.note-box', taper.guidance),
  ]);
}

/* ========================================================== 7. Notes & santé */
async function tabFollowUp(root, ctx) {
  const { athleteId } = ctx;
  const [notes, injuries] = await Promise.all([api.notes(athleteId), api.injuries(athleteId)]);
  mount(root, [
    el('div.grid.grid-2.section', [
      card('Notes d’entraînement',
        notes.notes.length
          ? el('div.col', notes.notes.slice(0, 20).map(note => el('div', {
              style: { paddingBottom: 'var(--sp-3)',
                       borderBottom: '1px solid var(--border-subtle)' },
            }, [
              el('div.between', [
                el('div.row-tight', [
                  note.category ? el('span.badge', note.category) : null,
                  el('span.faint', { style: { fontSize: '11px' } },
                     F.date(note.date, 'long')),
                ]),
                el('button.btn.ghost.icon', {
                  onclick: async () => { await api.deleteNote(note.id); ctx.reload(); },
                  title: 'Supprimer',
                }, [icon('trash')]),
              ]),
              el('div', { style: { marginTop: '5px', lineHeight: '1.6' } }, note.text),
            ])))
          : el('div.muted', 'Aucune note.'),
        { action: el('button.btn.sm.ghost', {
            onclick: () => openNoteForm(athleteId, ctx.reload) }, [icon('plus'), 'Ajouter']) }),

      card('Historique des blessures',
        injuries.injuries.length
          ? el('div.col', injuries.injuries.map(injury => el('div', {
              style: { paddingBottom: 'var(--sp-3)',
                       borderBottom: '1px solid var(--border-subtle)' },
            }, [
              el('div.between', [
                el('div', { style: { fontWeight: 570 } },
                   `${injury.body_part}${injury.side ? ` (${injury.side})` : ''}`),
                el(`span.badge${injury.status === 'résolue' ? '.pos' : '.neg'}`, injury.status),
              ]),
              el('div.faint', { style: { fontSize: '11px', marginTop: '2px' } },
                 `${injury.type || ''} · ${F.date(injury.date, 'long')}`
                 + (injury.days_lost ? ` · ${injury.days_lost} jours d’arrêt` : '')),
              injury.diagnosis ? el('div.muted', { style: { marginTop: '5px' } },
                                    injury.diagnosis) : null,
              injury.treatment ? el('div.definition', { style: { marginTop: '6px' } },
                                    injury.treatment) : null,
            ])))
          : el('div.muted', 'Aucune blessure enregistrée.'),
        { action: el('button.btn.sm.ghost', {
            onclick: () => openInjuryForm(athleteId, ctx.reload) }, [icon('plus'), 'Déclarer']) }),
    ]),
  ]);
}

/* ------------------------------------------------------------ formulaires */
function openWellnessForm(athleteId, reload) {
  const values = { date: F.isoDate(new Date()) };
  modal({
    title: 'Relevé quotidien',
    body: el('div.col', { style: { gap: 'var(--sp-4)' } }, [
      el('div.grid.grid-2', [
        field('Date', input({ type: 'date', value: values.date,
          onchange: (e) => { values.date = e.target.value; } })),
        field('VFC — RMSSD (ms)', input({ type: 'number', step: '0.1', placeholder: 'ex. 62',
          onchange: (e) => { values.hrv_rmssd = Number(e.target.value) || null; } })),
        field('FC de repos (bpm)', input({ type: 'number',
          onchange: (e) => { values.resting_hr = Number(e.target.value) || null; } })),
        field('Sommeil (heures)', input({ type: 'number', step: '0.25',
          onchange: (e) => { values.sleep_total_min = e.target.value
            ? Number(e.target.value) * 60 : null; } })),
        field('Poids (kg)', input({ type: 'number', step: '0.1',
          onchange: (e) => { values.weight_kg = Number(e.target.value) || null; } })),
      ]),
      el('div.label', 'Ressenti — échelles de 1 (très bon) à 7 (très mauvais)'),
      scaleField('Fatigue', 'fatigue', null, (v) => { values.fatigue = v; }),
      scaleField('Douleurs musculaires', 'soreness', null, (v) => { values.soreness = v; }),
      scaleField('Qualité du sommeil', 'sleep_quality', null, (v) => { values.sleep_quality = v; }),
      scaleField('Stress perçu', 'stress_subj', null, (v) => { values.stress_subj = v; }),
      scaleField('Humeur', 'mood', null, (v) => { values.mood = v; }),
      scaleField('Motivation', 'motivation', null, (v) => { values.motivation = v; }),
      field('Remarque', textarea({ placeholder: 'facultatif',
        onchange: (e) => { values.notes = e.target.value || null; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          try {
            const result = await api.saveWellness(athleteId, values);
            toast(`Relevé enregistré — disponibilité ${F.num(result.readiness.score, 0)}/100 `
                  + `(${result.readiness.flag}).`, 'success');
            reload();
          } catch (error) { notifyError(error); return false; }
        } },
    ],
  });
}

function openPhysiologyForm(athleteId, reload) {
  const values = { effective_date: F.isoDate(new Date()), reanalyze: false };
  modal({
    title: 'Mise à jour du profil physiologique',
    body: el('div.col', { style: { gap: 'var(--sp-4)' } }, [
      el('div.note-box', 'Les valeurs saisies s’appliquent à partir de la date d’effet. '
        + 'Les séances antérieures conservent les seuils qui étaient les leurs — c’est ce '
        + 'qui garantit la comparabilité de la charge dans le temps.'),
      el('div.grid.grid-2', [
        field('Date d’effet', input({ type: 'date', value: values.effective_date,
          onchange: (e) => { values.effective_date = e.target.value; } })),
        field('Poids (kg)', input({ type: 'number', step: '0.1',
          onchange: (e) => { values.weight_kg = Number(e.target.value) || null; } })),
        field('FC maximale', input({ type: 'number',
          onchange: (e) => { values.hr_max = Number(e.target.value) || null; } })),
        field('FC de repos', input({ type: 'number',
          onchange: (e) => { values.hr_rest = Number(e.target.value) || null; } })),
        field('FC au premier seuil (LT1)', input({ type: 'number',
          onchange: (e) => { values.hr_lt1 = Number(e.target.value) || null; } })),
        field('FC au second seuil (LT2)', input({ type: 'number',
          onchange: (e) => { values.hr_lt2 = Number(e.target.value) || null; } }),
          'Base des zones de fréquence cardiaque.'),
        field('FTP (W)', input({ type: 'number',
          onchange: (e) => { values.ftp_w = Number(e.target.value) || null; } })),
        field('Puissance critique (W)', input({ type: 'number',
          onchange: (e) => { values.cp_w = Number(e.target.value) || null; } })),
        field('W′ (joules)', input({ type: 'number',
          onchange: (e) => { values.w_prime_j = Number(e.target.value) || null; } })),
        field('Allure au seuil (s/km)', input({ type: 'number', placeholder: 'ex. 210 pour 3:30',
          onchange: (e) => { values.threshold_pace_s_km = Number(e.target.value) || null; } })),
        field('VO2max (ml/kg/min)', input({ type: 'number', step: '0.1',
          onchange: (e) => { values.vo2max = Number(e.target.value) || null; } })),
        field('VDOT', input({ type: 'number', step: '0.1',
          onchange: (e) => { values.vdot = Number(e.target.value) || null; } })),
      ]),
      el('label.row-tight', [
        el('input', { type: 'checkbox',
          onchange: (e) => { values.reanalyze = e.target.checked; } }),
        el('span.muted', 'Réanalyser les séances postérieures à la date d’effet '
          + '(recalcule TSS, IF et temps en zones avec les nouveaux seuils)'),
      ]),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          try {
            const result = await api.addPhysiology(athleteId, values);
            toast(result.reanalyzed
              ? `Profil mis à jour, ${result.reanalyzed} séances réanalysées.`
              : 'Profil mis à jour.', 'success');
            reload();
          } catch (error) { notifyError(error); return false; }
        } },
    ],
  });
}

function openNoteForm(athleteId, reload) {
  const values = { date: F.isoDate(new Date()), category: 'technique' };
  modal({
    title: 'Nouvelle note',
    body: el('div.col', [
      el('div.grid.grid-2', [
        field('Date', input({ type: 'date', value: values.date,
          onchange: (e) => { values.date = e.target.value; } })),
        field('Catégorie', select(
          ['technique', 'mental', 'nutrition', 'médical', 'logistique']
            .map(c => ({ value: c, label: c })),
          { onchange: (e) => { values.category = e.target.value; } })),
      ]),
      field('Note', textarea({ rows: 5,
        onchange: (e) => { values.text = e.target.value; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          if (!values.text) { toast('La note est vide.', 'error'); return false; }
          await api.addNote(athleteId, values); reload();
        } },
    ],
  });
}

function openInjuryForm(athleteId, reload) {
  const values = { date: F.isoDate(new Date()), status: 'ouverte', severity: 2 };
  modal({
    title: 'Déclarer une blessure',
    body: el('div.grid.grid-2', [
      field('Date', input({ type: 'date', value: values.date,
        onchange: (e) => { values.date = e.target.value; } })),
      field('Zone corporelle', input({ placeholder: 'ex. tendon d’Achille',
        onchange: (e) => { values.body_part = e.target.value; } })),
      field('Côté', select([{ value: '', label: '—' }, { value: 'gauche', label: 'gauche' },
        { value: 'droite', label: 'droite' }, { value: 'bilatéral', label: 'bilatéral' }],
        { onchange: (e) => { values.side = e.target.value || null; } })),
      field('Type', input({ placeholder: 'ex. tendinopathie',
        onchange: (e) => { values.type = e.target.value; } })),
      field('Mécanisme', select([{ value: 'surcharge', label: 'surcharge' },
        { value: 'traumatique', label: 'traumatique' }, { value: 'récidive', label: 'récidive' }],
        { onchange: (e) => { values.mechanism = e.target.value; } })),
      field('Gravité (1–5)', input({ type: 'number', min: 1, max: 5, value: 2,
        onchange: (e) => { values.severity = Number(e.target.value); } })),
      field('Diagnostic', textarea({ onchange: (e) => { values.diagnosis = e.target.value; } })),
      field('Traitement', textarea({ onchange: (e) => { values.treatment = e.target.value; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          if (!values.body_part) { toast('La zone corporelle est obligatoire.', 'error'); return false; }
          await api.addInjury(athleteId, values); reload();
        } },
    ],
  });
}

function openEventForm(athleteId, reload) {
  const values = { priority: 'A', date: F.isoDate(F.addDays(new Date(), 60)) };
  modal({
    title: 'Nouvel objectif',
    body: el('div.grid.grid-2', [
      field('Nom', input({ onchange: (e) => { values.name = e.target.value; } })),
      field('Date', input({ type: 'date', value: values.date,
        onchange: (e) => { values.date = e.target.value; } })),
      field('Priorité', select([{ value: 'A', label: 'A — objectif majeur' },
        { value: 'B', label: 'B — objectif secondaire' },
        { value: 'C', label: 'C — course de préparation' }],
        { onchange: (e) => { values.priority = e.target.value; } })),
      field('Lieu', input({ onchange: (e) => { values.location = e.target.value; } })),
      field('Distance (m)', input({ type: 'number',
        onchange: (e) => { values.distance_m = Number(e.target.value) || null; } })),
      field('Temps visé (s)', input({ type: 'number',
        onchange: (e) => { values.target_time_s = Number(e.target.value) || null; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          if (!values.name) { toast('Le nom est obligatoire.', 'error'); return false; }
          await api.createEvent(athleteId, values); reload();
        } },
    ],
  });
}

function openGenerateWeek(athleteId, reload) {
  const values = { replace: true, start: F.isoDate(new Date()) };
  modal({
    title: 'Générer une semaine type',
    body: el('div.col', [
      el('div.note-box', 'La semaine générée suit une répartition polarisée : deux séances '
        + 'de qualité, une sortie longue, le reste en aisance, et un jour de repos. '
        + 'La charge est répartie proportionnellement à la cible hebdomadaire.'),
      el('div.grid.grid-2', [
        field('Semaine du', input({ type: 'date', value: values.start,
          onchange: (e) => { values.start = e.target.value; } })),
        field('Charge hebdomadaire visée', input({ type: 'number',
          placeholder: 'laisser vide pour +5 % sur la CTL',
          onchange: (e) => { values.weekly_load = Number(e.target.value) || null; } })),
      ]),
      el('label.row-tight', [
        el('input', { type: 'checkbox', checked: true,
          onchange: (e) => { values.replace = e.target.checked; } }),
        el('span.muted', 'Remplacer les séances déjà planifiées cette semaine'),
      ]),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Générer', primary: true, onClick: async () => {
          const result = await api.generateWeek(athleteId, values);
          toast(`${result.created.length} séances planifiées.`, 'success');
          reload();
        } },
    ],
  });
}

function openEditAthlete(athlete, reload) {
  const values = {};
  modal({
    title: 'Modifier la fiche',
    body: el('div.grid.grid-2', [
      field('Prénom', input({ value: athlete.first_name,
        onchange: (e) => { values.first_name = e.target.value; } })),
      field('Nom', input({ value: athlete.last_name,
        onchange: (e) => { values.last_name = e.target.value; } })),
      field('Date de naissance', input({ type: 'date', value: athlete.birth_date || '',
        onchange: (e) => { values.birth_date = e.target.value; } })),
      field('Sexe', select([{ value: 'F', label: 'Féminin', selected: athlete.sex === 'F' },
        { value: 'M', label: 'Masculin', selected: athlete.sex === 'M' },
        { value: 'X', label: 'Non précisé', selected: athlete.sex === 'X' }],
        { onchange: (e) => { values.sex = e.target.value; } }),
        'Utilisé par les coefficients du TRIMP de Banister et les normes de VO2max.'),
      field('Taille (cm)', input({ type: 'number', value: athlete.height_cm || '',
        onchange: (e) => { values.height_cm = Number(e.target.value) || null; } })),
      field('Discipline', input({ value: athlete.discipline || '',
        onchange: (e) => { values.discipline = e.target.value; } })),
      field('Niveau', select(['loisir', 'compétiteur', 'national', 'élite', 'pro']
        .map(l => ({ value: l, label: l, selected: athlete.level === l })),
        { onchange: (e) => { values.level = e.target.value; } })),
      field('Statut', select([{ value: 'active', label: 'actif', selected: athlete.status === 'active' },
        { value: 'injured', label: 'blessé', selected: athlete.status === 'injured' },
        { value: 'paused', label: 'en pause', selected: athlete.status === 'paused' }],
        { onchange: (e) => { values.status = e.target.value; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          await api.updateAthlete(athlete.id, values);
          const { refreshRoster } = await import('../main.js');
          await refreshRoster();
          reload();
        } },
    ],
  });
}

export function openUpload(athleteId, onDone) {
  const fileInput = el('input', {
    type: 'file', multiple: true, accept: '.fit,.tcx,.gpx',
    style: { display: 'none' },
  });
  const results = el('div.file-list');
  const zone = el('div.dropzone', [
    icon('upload'),
    el('div', { style: { fontWeight: 600, marginBottom: '4px' } },
       'Déposez vos fichiers ici'),
    el('div.faint', { style: { fontSize: 'var(--fs-sm)' } },
       'Formats .fit, .tcx et .gpx — exportables depuis Garmin Connect, '
       + 'Polar Flow et l’application COROS'),
  ]);
  zone.addEventListener('click', () => fileInput.click());
  ['dragenter', 'dragover'].forEach(type => zone.addEventListener(type, (e) => {
    e.preventDefault(); zone.classList.add('over');
  }));
  ['dragleave', 'drop'].forEach(type => zone.addEventListener(type, (e) => {
    e.preventDefault(); zone.classList.remove('over');
  }));
  zone.addEventListener('drop', (e) => handle([...e.dataTransfer.files]));
  fileInput.addEventListener('change', () => handle([...fileInput.files]));

  async function handle(files) {
    if (!files.length) return;
    clear(results);
    results.appendChild(el('div.row-tight', [el('span.spinner'),
      el('span.muted', `Analyse de ${files.length} fichier(s)…`)]));
    try {
      const result = await api.uploadFiles(athleteId, files);
      clear(results);
      for (const item of result.results) {
        results.appendChild(el('div.file-item.ok', [
          icon('check'), el('span.truncate', item.filename),
          el('span.spacer'),
          el('span.mono.muted',
             `${F.duration(item.metrics?.duration_s, 'hm')} · charge ${F.num(item.metrics?.load, 0)}`),
        ]));
      }
      for (const item of result.errors) {
        results.appendChild(el('div.file-item.fail', [
          icon('alert'), el('span.truncate', item.filename),
          el('span.spacer'), el('span.muted', item.error),
        ]));
      }
      if (result.imported) {
        toast(`${result.imported} séance(s) importée(s).`, 'success');
        if (onDone) onDone();
      }
    } catch (error) {
      clear(results);
      notifyError(error);
    }
  }

  modal({
    title: 'Importer des séances',
    body: el('div.col', [
      zone, fileInput, results,
      el('div.note-box', 'Les fichiers sont décodés localement, par le serveur qui tourne '
        + 'sur votre machine. Aucune donnée n’est transmise à un service tiers.'),
    ]),
    actions: [{ label: 'Fermer', onClick: () => {} }],
  });
}
