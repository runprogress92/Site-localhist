/**
 * Analyse détaillée d'une séance.
 *
 * Le cœur de la vue est la pile de pistes synchronisées : fréquence
 * cardiaque, puissance, allure, altitude et réserve W′ partagent un même
 * axe temporel et un curseur commun.
 */
import { api } from '../lib/api.js';
import { clear, el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import {
  avatar, card, confirmDialog, dataTable, field, input, metric, modal,
  notifyError, pageTitle, segmented, select, setTopbar, textarea, toast,
} from '../lib/ui.js';
import { zoneBars, powerCurve } from '../charts/plots.js';
import { routeMap, streamPanels, panelSpec } from '../charts/streams.js';

export async function render(root, context) {
  const activityId = Number(context.params.id);
  const activity = await api.activity(activityId);
  if (context.token.stale) return;
  const streams = activity.has_streams
    ? await api.streams(activityId, { points: 3000, derived: true })
    : { streams: {}, derived: {} };
  if (context.token.stale) return;

  setTopbar(pageTitle(
    activity.name || 'Séance',
    [el('a', { onclick: () => navigate(`/athlete/${activity.athlete_id}`),
               style: { cursor: 'pointer' } },
        `${activity.first_name} ${activity.last_name}`),
     el('span', '/'),
     el('span', `${F.sportLabel(activity.sport)} · ${F.date(activity.local_date, 'long')} `
              + `à ${F.time(activity.start_time)}`)],
    el('div.row-tight', [
      el('button.btn.sm', { onclick: () => openEdit(activity, () => render(root, context)) },
         [icon('edit'), 'Annoter']),
      el('button.btn.sm', {
        onclick: async () => {
          await api.reanalyze(activityId);
          toast('Séance réanalysée avec les seuils en vigueur.', 'success');
          render(root, context);
        },
      }, [icon('refresh'), 'Réanalyser']),
      exportMenu(activity),
      el('button.btn.sm.danger', {
        onclick: async () => {
          if (!await confirmDialog(
            'Cette séance et ses flux détaillés seront définitivement supprimés.',
            { title: 'Supprimer la séance', confirmLabel: 'Supprimer' })) return;
          await api.deleteActivity(activityId);
          toast('Séance supprimée.', 'success');
          navigate(`/athlete/${activity.athlete_id}/seances`);
        },
      }, [icon('trash')]),
    ])));

  const allStreams = { ...streams.streams, ...streams.derived };
  const panelKeys = choosePanels(activity, allStreams);
  const hrZones = activity.zones?.hr || [];
  const zoneTimes = groupZoneTimes(activity.zone_times);

  mount(root, [
    el('div.activity-hero', [
      el('div', [
        el('div.activity-metrics', heroMetrics(activity)),
      ]),
      el('div.col', { style: { minWidth: '190px', alignItems: 'flex-end' } }, [
        el('div.badge.accent', { style: { fontSize: 'var(--fs-sm)' } },
           `Charge ${F.num(activity.load, 0)} (${loadSourceLabel(activity.load_source)})`),
        activity.rpe ? el('div.badge', `RPE ${activity.rpe}/10`) : null,
        activity.device_name ? el('div.faint', { style: { fontSize: '11px' } },
                                  activity.device_name) : null,
      ]),
    ]),

    activity.has_streams ? card('Analyse temporelle',
      el('div', [
        el('div.row-tight', { style: { marginBottom: 'var(--sp-3)' } }, [
          el('span.label', 'Lissage'),
          segmented([
            { value: 1, label: 'brut' }, { value: 10, label: '10 s' },
            { value: 30, label: '30 s' }, { value: 60, label: '1 min' },
          ], 10, (v) => drawPanels(v)),
        ]),
        el('div', { id: 'stream-panels' }),
      ]),
      { subtitle: 'passez la souris sur les courbes : le curseur est commun à toutes '
                + 'les pistes et les valeurs s’affichent en regard de chaque libellé',
        className: 'section' })
      : el('div.card.section', el('div.chart-empty',
          'Cette séance a été importée sans flux détaillé : seules les valeurs '
          + 'agrégées sont disponibles.')),

    el('div.grid.grid-2.section', [
      zoneTimes.hr?.length
        ? card('Temps par zone de fréquence cardiaque', el('div', { id: 'act-zones-hr' }),
            { subtitle: 'zones de Friel calculées sur la FC au seuil de l’athlète' })
        : null,
      zoneTimes.power?.length
        ? card('Temps par zone de puissance', el('div', { id: 'act-zones-power' }),
            { subtitle: `zones de Coggan, FTP ${F.num(activity.context?.ftp_w, 0)} W` })
        : null,
      activity.has_gps
        ? card('Trace', el('div', { id: 'route-map' }),
            { subtitle: 'coloration par intensité — vert au départ, rouge à l’arrivée' })
        : null,
    ].filter(Boolean)),

    activity.best_efforts?.length ? card('Meilleurs efforts de la séance',
      bestEffortsTable(activity), {
        subtitle: 'meilleure moyenne obtenue sur chaque durée au cours de cette séance',
        className: 'section' }) : null,

    activity.laps?.length ? card('Tours', lapsTable(activity),
      { flush: true, className: 'section' }) : null,

    card('Interprétation', interpretation(activity), { className: 'section' }),
  ]);

  function drawPanels(smoothing) {
    const node = document.getElementById('stream-panels');
    if (!node) return;
    streamPanels(node, {
      streams: allStreams, keys: panelKeys, sport: activity.sport,
      smoothing, sampleStep: streams.step || 1, zones: hrZones,
      laps: activity.laps || [],
    });
  }
  if (activity.has_streams) drawPanels(10);

  if (zoneTimes.hr?.length) {
    zoneBars(document.getElementById('act-zones-hr'), {
      zones: hrZones,
      distribution: hrZones.map((_, i) => ({ seconds: zoneTimes.hr[i] || 0 })),
    });
  }
  if (zoneTimes.power?.length) {
    zoneBars(document.getElementById('act-zones-power'), {
      zones: activity.zones.power,
      distribution: activity.zones.power.map((_, i) => ({ seconds: zoneTimes.power[i] || 0 })),
    });
  }
  if (activity.has_gps && allStreams.lat) {
    const colorSource = allStreams.power || allStreams.speed || allStreams.heart_rate;
    routeMap(document.getElementById('route-map'), {
      lat: allStreams.lat, lon: allStreams.lon,
      values: colorSource, colorBy: !!colorSource, height: 300,
    });
  }
}

/* --------------------------------------------------------------- fragments */
function choosePanels(activity, streams) {
  const candidates = ['heart_rate', 'power', 'w_bal', 'speed', 'gap_speed',
                      'cadence', 'altitude', 'stance_time', 'vertical_oscillation',
                      'temperature'];
  const available = candidates.filter(k => streams[k]?.some(v => v != null));
  // on limite à six pistes : au-delà, chacune devient trop écrasée pour être lue
  const priority = activity.sport === 'cycling'
    ? ['power', 'heart_rate', 'w_bal', 'speed', 'cadence', 'altitude']
    : ['heart_rate', 'speed', 'gap_speed', 'cadence', 'altitude', 'stance_time'];
  const ordered = [...priority.filter(k => available.includes(k)),
                   ...available.filter(k => !priority.includes(k))];
  return ordered.slice(0, 6);
}

function groupZoneTimes(rows) {
  const out = {};
  for (const row of rows || []) {
    out[row.kind] = out[row.kind] || [];
    out[row.kind][row.zone_idx - 1] = row.seconds;
  }
  return out;
}

function loadSourceLabel(source) {
  return { tss: 'puissance', rtss: 'allure', hrtss: 'fréquence cardiaque',
           stss: 'natation', rpe: 'ressenti' }[source] || source || '—';
}

function heroMetrics(activity) {
  const items = [
    ['Durée', F.duration(activity.duration_s, 'hm'),
     activity.moving_time_s ? `${F.duration(activity.moving_time_s, 'hm')} en mouvement` : null],
    ['Distance', F.distance(activity.distance_m), null],
    ['Dénivelé positif', activity.elevation_gain_m
      ? `${F.num(activity.elevation_gain_m, 0)} m` : '—', null],
    ['Allure / vitesse', F.paceForSport(activity.sport, activity.avg_speed_ms),
     activity.gap_pace_s_km ? `${F.pace(activity.gap_pace_s_km)} ajustée` : null],
    ['FC moyenne', activity.avg_hr ? `${F.num(activity.avg_hr, 0)} bpm` : '—',
     activity.max_hr ? `max ${F.num(activity.max_hr, 0)}` : null],
  ];
  if (activity.np_w) {
    items.push(['Puissance normalisée', `${F.num(activity.np_w, 0)} W`,
                `moyenne ${F.num(activity.avg_power_w, 0)} W`]);
    items.push(['Facteur d’intensité', F.num(activity.intensity_factor, 2),
                `VI ${F.num(activity.variability_index, 2)}`]);
    items.push(['Travail', `${F.num(activity.work_kj, 0)} kJ`,
                activity.calories ? `${F.num(activity.calories, 0)} kcal` : null]);
  } else {
    items.push(['Charge', F.num(activity.load, 0), loadSourceLabel(activity.load_source)]);
    if (activity.calories) items.push(['Dépense', `${F.num(activity.calories, 0)} kcal`, null]);
  }
  if (activity.decoupling_pct != null) {
    items.push(['Découplage', `${F.num(activity.decoupling_pct, 1)} %`,
                activity.decoupling_pct < 5 ? 'base aérobie solide' : 'dérive cardiaque']);
  }
  if (activity.efficiency_factor) {
    items.push(['Facteur d’efficacité', F.num(activity.efficiency_factor, 3), null]);
  }
  if (activity.avg_cadence) {
    items.push(['Cadence', F.num(activity.avg_cadence, 0),
                activity.avg_stride_len_m ? `foulée ${F.num(activity.avg_stride_len_m, 2)} m` : null]);
  }
  return items.map(([label, value, sub]) => metric(label, value, { sub, size: 'sm' }));
}

function bestEffortsTable(activity) {
  const byKind = {};
  for (const effort of activity.best_efforts) {
    byKind[effort.kind] = byKind[effort.kind] || [];
    byKind[effort.kind].push(effort);
  }
  const kind = byKind.power ? 'power' : byKind.speed ? 'speed' : Object.keys(byKind)[0];
  const durations = [5, 15, 60, 300, 600, 1200, 1800, 3600];
  const rows = (byKind[kind] || []).filter(e => durations.includes(e.duration_s));
  if (!rows.length) return el('div.muted', 'Aucun effort de référence sur cette séance.');
  return el('div.pill-row', rows.map(effort => el('div.chip', [
    el('strong', F.duration(effort.duration_s, 'long')),
    el('span.mono', kind === 'power'
      ? `${F.num(effort.value, 0)} W`
      : F.paceForSport(activity.sport, effort.value)),
    effort.value_per_kg
      ? el('span.faint', `${F.num(effort.value_per_kg, 2)} W/kg`) : null,
  ])));
}

function lapsTable(activity) {
  return dataTable({
    columns: [
      { label: 'Tour', render: (l) => el('span.mono', String(l.idx + 1)) },
      { label: 'Durée', numeric: true,
        render: (l) => el('span.mono', F.duration(l.duration_s, 'clock')) },
      { label: 'Distance', numeric: true,
        render: (l) => el('span.mono', F.distance(l.distance_m)) },
      { label: 'Allure / vitesse', numeric: true,
        render: (l) => el('span.mono', F.paceForSport(activity.sport, l.avg_speed_ms)) },
      { label: 'FC moy', numeric: true,
        render: (l) => el('span.mono', l.avg_hr ? F.num(l.avg_hr, 0) : '—') },
      { label: 'Puissance', numeric: true,
        render: (l) => el('span.mono', l.avg_power_w ? `${F.num(l.avg_power_w, 0)} W` : '—') },
      { label: 'D+', numeric: true,
        render: (l) => el('span.mono.muted', l.elevation_gain_m
          ? `${F.num(l.elevation_gain_m, 0)} m` : '—') },
    ],
    rows: activity.laps,
  });
}

function interpretation(activity) {
  const notes = [];
  const baseline = activity.baseline || {};
  if (activity.intensity_factor) {
    const factor = activity.intensity_factor;
    const label = factor < 0.65 ? 'récupération'
      : factor < 0.80 ? 'endurance'
      : factor < 0.90 ? 'tempo'
      : factor < 1.00 ? 'seuil'
      : factor < 1.05 ? 'proche du seuil maximal' : 'supra-seuil';
    notes.push(`Facteur d’intensité de ${F.num(factor, 2)} : séance de type ${label}. `
      + `Une heure exactement à la FTP vaudrait 100 points de charge ; celle-ci en vaut `
      + `${F.num(activity.load, 0)} pour ${F.duration(activity.duration_s, 'long')}.`);
  }
  if (activity.decoupling_pct != null) {
    notes.push(activity.decoupling_pct < 5
      ? `Découplage de ${F.num(activity.decoupling_pct, 1)} % : le rapport intensité/FC `
        + `est resté stable entre la première et la seconde moitié. C’est le marqueur `
        + `d’une base aérobie solide pour cette durée et cette intensité.`
      : `Découplage de ${F.num(activity.decoupling_pct, 1)} % : au-delà de 5 %, la dérive `
        + `cardiaque indique que l’effort a été soutenu au-dessus du niveau que la base `
        + `aérobie absorbe confortablement — ou que la chaleur, l’hydratation ou la `
        + `fatigue résiduelle ont pesé.`);
  }
  if (activity.variability_index && activity.variability_index > 1.10) {
    notes.push(`Indice de variabilité de ${F.num(activity.variability_index, 2)} : effort très `
      + `haché. La puissance normalisée dépasse nettement la moyenne, ce qui rend le coût `
      + `métabolique supérieur à ce que suggère la puissance moyenne.`);
  }
  if (baseline.n > 3 && baseline.load) {
    const ratio = activity.load / baseline.load;
    notes.push(`Cette séance représente ${F.num(ratio * 100, 0)} % de la charge moyenne des `
      + `${baseline.n} séances de ${F.sportLabel(activity.sport).toLowerCase()} des 90 derniers jours.`);
  }
  if (activity.polarization_index != null) {
    notes.push(`Indice de polarisation de la séance : ${F.num(activity.polarization_index, 2)}.`);
  }
  if (!notes.length) {
    notes.push('Les données disponibles ne permettent pas d’interprétation détaillée : '
      + 'ni puissance ni fréquence cardiaque continue n’ont été enregistrées.');
  }
  return el('div.col', notes.map(text => el('div.definition', text)));
}

function exportMenu(activity) {
  return el('div.btn-group', [
    el('button.btn.sm', {
      onclick: () => { window.location.href = `/api/activities/${activity.id}/export.csv`; },
      title: 'Flux détaillés au format CSV',
    }, 'CSV'),
    el('button.btn.sm', {
      onclick: () => { window.location.href = `/api/activities/${activity.id}/export.fit`; },
      title: 'Réencodage au format FIT',
    }, 'FIT'),
    activity.has_gps ? el('button.btn.sm', {
      onclick: () => { window.location.href = `/api/activities/${activity.id}/gpx`; },
      title: 'Trace GPS au format GPX',
    }, 'GPX') : null,
  ].filter(Boolean));
}

function openEdit(activity, reload) {
  const values = {};
  modal({
    title: 'Annoter la séance',
    body: el('div.col', [
      field('Nom', input({ value: activity.name || '',
        onchange: (e) => { values.name = e.target.value; } })),
      el('div.grid.grid-2', [
        field('Effort perçu (RPE 1–10)', input({ type: 'number', min: 1, max: 10,
          value: activity.rpe || '',
          onchange: (e) => { values.rpe = Number(e.target.value) || null; } }),
          'Sert de charge de repli quand aucune mesure objective n’est disponible.'),
        field('Ressenti (1–5)', input({ type: 'number', min: 1, max: 5,
          value: activity.feel || '',
          onchange: (e) => { values.feel = Number(e.target.value) || null; } })),
      ]),
      field('Étiquettes', input({ value: activity.tags || '', placeholder: 'séparées par des virgules',
        onchange: (e) => { values.tags = e.target.value; } })),
      field('Notes', textarea({ rows: 4, value: activity.notes || '',
        onchange: (e) => { values.notes = e.target.value; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          await api.updateActivity(activity.id, values);
          toast('Séance mise à jour.', 'success');
          reload();
        } },
    ],
  });
}
