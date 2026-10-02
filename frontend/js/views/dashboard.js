/**
 * Vue d'ensemble du groupe.
 *
 * Répond en un écran aux trois questions qu'un entraîneur se pose chaque
 * matin : qui va bien, qui inquiète, et qu'est-ce qui a été fait hier.
 */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { store } from '../lib/store.js';
import {
  avatar, card, dataTable, emptyState, formBadge, notifyError, pageTitle,
  readinessBadge, setTopbar, statTile, toast,
} from '../lib/ui.js';
import { sparkline } from '../charts/plots.js';
import { loadMatrix as matrixChart } from '../charts/streams.js';
import { openAthleteForm } from './athlete-form.js';
import { welcomeScreen } from './onboarding.js';

export async function render(root, context) {
  const [overview, matrix] = await Promise.all([
    api.teamOverview(),
    api.teamMatrix(35),
  ]);
  if (context.token.stale) return;

  // Base vide : un tableau de bord rempli de zéros n'apprend rien et ne dit
  // pas quoi faire. On propose les trois points d'entrée à la place.
  if (!overview.athletes.length) {
    setTopbar(pageTitle('Athlytics', 'aucun athlète enregistré'));
    mount(root, welcomeScreen(() => render(root, context)));
    return;
  }

  setTopbar(pageTitle(
    "Vue d'ensemble",
    `${overview.totals.athletes} athlètes suivis · semaine du ${F.date(weekStart(), 'medium')}`,
    el('div.row-tight', [
      el('button.btn.sm', { onclick: () => navigate('/bien-etre') },
         [icon('heart'), 'Relevés du jour']),
      el('button.btn.sm', { onclick: () => navigate('/seances') },
         [icon('upload'), 'Importer des séances']),
      el('button.btn.sm.primary', {
        onclick: () => openAthleteForm(null, () => render(root, context)),
      }, [icon('plus'), 'Nouvel athlète']),
    ])));

  const flags = overview.totals.flags;
  const criticalAlerts = overview.alerts.filter(a => a.severity === 'critical');
  const warningAlerts = overview.alerts.filter(a => a.severity === 'warning');

  mount(root, [
    /* ---------------------------------------------------- indicateurs clés */
    el('div.grid.grid-4.section', [
      statTile('Athlètes actifs', F.num(overview.totals.active), {
        sub: overview.totals.injured
          ? `${overview.totals.injured} en soins` : 'aucune blessure en cours',
        tone: overview.totals.injured ? 'warn' : 'pos',
      }),
      statTile('Condition moyenne', F.num(overview.totals.mean_ctl, 1), {
        unit: 'CTL', sub: 'charge chronique du groupe',
        hint: 'Moyenne des CTL (charge chronique) — le niveau de condition '
            + 'physique construit sur les six dernières semaines.',
      }),
      statTile('Disponibilité moyenne', F.num(overview.totals.mean_readiness, 0), {
        unit: '/100',
        sub: `${flags.vert} verts · ${flags.ambre} ambres · ${flags.rouge} rouges`,
        tone: flags.rouge > flags.vert ? 'warn' : 'pos',
        color: overview.totals.mean_readiness >= 65 ? 'var(--positive)'
             : overview.totals.mean_readiness >= 50 ? 'var(--warning)' : 'var(--danger)',
      }),
      statTile('Volume de la semaine', F.duration(overview.week.duration_s, 'hm'), {
        sub: `${overview.week.sessions} séances · ${F.distance(overview.week.distance_m, 0)}`,
        tone: 'plain',
      }),
    ]),

    /* --------------------------------------------------------- alertes */
    overview.alerts.length ? el('section.section', [
      el('div.section-head', [
        el('div', [
          el('div.section-title', 'Points de vigilance'),
          el('div.section-sub',
             `${criticalAlerts.length} critique(s), ${warningAlerts.length} avertissement(s) — `
             + 'chaque alerte indique son seuil et la valeur observée'),
        ]),
      ]),
      el('div.grid.grid-2', overview.alerts.slice(0, 6).map(alertCard)),
    ]) : el('section.section', [
      card(null, el('div.row', [
        el('div', { style: { color: 'var(--positive)' } }, [icon('check')]),
        el('div', [
          el('div', { style: { fontWeight: 600 } }, 'Aucun signal d’alerte'),
          el('div.muted', { style: { fontSize: 'var(--fs-sm)' } },
             'Charge, monotonie, VFC et sommeil sont dans les plages attendues '
             + 'pour l’ensemble du groupe.'),
        ]),
      ])),
    ]),

    /* ------------------------------------------------------ tableau roster */
    el('section.section', [
      el('div.section-head', [
        el('div', [
          el('div.section-title', 'État des athlètes'),
          el('div.section-sub',
             'Condition (CTL), fatigue (ATL), forme (TSB), ratio charge aiguë/chronique '
             + 'et disponibilité du jour'),
        ]),
      ]),
      card(null, rosterTable(overview.athletes), { flush: true }),
    ]),

    /* -------------------------------------------- charge du groupe + à venir */
    el('div.split.section', [
      card('Charge quotidienne du groupe',
        el('div', { id: 'team-matrix' }),
        { subtitle: '35 derniers jours — l’intensité de la case reflète la charge du jour',
          action: el('button.btn.sm.ghost', { onclick: () => navigate('/charge') },
                     'Détail') }),
      el('div.col', [
        card('Prochaines échéances',
          overview.events.length
            ? el('div.col', { style: { gap: 'var(--sp-2)' } },
                overview.events.slice(0, 5).map(eventRow))
            : el('div.muted', { style: { fontSize: 'var(--fs-sm)' } },
                 'Aucun objectif planifié.'),
          { subtitle: 'objectifs A et B à venir' }),
      ]),
    ]),

    /* --------------------------------------------------- séances récentes */
    el('section.section', [
      el('div.section-head', [
        el('div.section-title', 'Dernières séances'),
        el('button.btn.sm.ghost', { onclick: () => navigate('/seances') },
           ['Tout voir', icon('chevronRight')]),
      ]),
      card(null, recentTable(overview.recent), { flush: true }),
    ]),
  ]);

  matrixChart(document.getElementById('team-matrix'), {
    dates: matrix.dates, matrix: matrix.matrix,
    onCellClick: (athlete) => navigate(`/athlete/${athlete.id}`),
  });

  // sparklines de charge dans le tableau
  for (const athlete of overview.athletes) {
    const node = document.getElementById(`spark-${athlete.id}`);
    if (!node) continue;
    const row = matrix.matrix.find(m => m.athlete.id === athlete.id);
    if (row) {
      sparkline(node, {
        values: row.cells.map(c => c.load || 0),
        color: athlete.accent, height: 26,
      });
    }
  }
}

/* -------------------------------------------------------------- fragments */
function alertCard(alert) {
  return el(`div.alert.${alert.severity}`, {
    style: { cursor: 'pointer' },
    onclick: () => navigate(`/athlete/${alert.athlete_id}`),
  }, [
    el('div.alert-icon', { style: { color: F.severityColor(alert.severity) } },
       [icon(alert.severity === 'critical' ? 'alert' : 'info')]),
    el('div', { style: { minWidth: 0 } }, [
      el('div.alert-title', [
        el('span', { style: { color: alert.accent } },
           `${alert.first_name} ${alert.last_name}`),
        el('span.faint', ' — '),
        alert.title,
      ]),
      el('div.alert-msg', alert.message),
      alert.value != null ? el('div.row-tight', { style: { marginTop: '6px' } }, [
        el('span.badge', `observé ${F.num(alert.value, 2)}`),
        alert.threshold != null
          ? el('span.badge', `seuil ${F.num(alert.threshold, 2)}`) : null,
      ]) : null,
    ]),
  ]);
}

function rosterTable(athletes) {
  return dataTable({
    sortable: true,
    initialSort: { key: 'ctl', dir: 'desc' },
    onRowClick: (row) => navigate(`/athlete/${row.id}`),
    // Sur téléphone : quatre chiffres suffisent à décider s'il faut ouvrir
    // la fiche. Le reste tient dans la fiche elle-même.
    card: {
      accent: (row) => row.alerts?.length
        ? F.severityColor(row.alert_level) : row.accent,
      avatar: (row) => avatar(row, 'sm'),
      title: (row) => `${row.first_name} ${row.last_name}`,
      subtitle: (row) => row.discipline || F.sportLabel(row.primary_sport),
      badge: (row) => row.status === 'injured'
        ? el('span.badge.neg', 'blessé')
        : readinessBadge(row.readiness, row.readiness_flag),
      metrics: (row) => [
        ['Condition', el('span', F.num(row.ctl, 1))],
        ['Forme', el('span', { style: { color: F.formColor(row.tsb) } },
                     F.signed(row.tsb, 0))],
        ['Ratio A:C', el('span', { style: { color: F.acwrColor(row.acwr) } },
                          F.num(row.acwr, 2))],
        ['Semaine', el('span', F.duration(row.week?.duration_s, 'hm'))],
      ],
    },
    columns: [
      {
        label: 'Athlète', key: 'last_name', width: '24%',
        render: (row) => el('div.row-tight', [
          avatar(row, 'sm'),
          el('div', { style: { minWidth: 0 } }, [
            el('div.truncate', { style: { fontWeight: 570 } },
               `${row.first_name} ${row.last_name}`),
            el('div.faint.truncate', { style: { fontSize: '11px' } },
               row.discipline || F.sportLabel(row.primary_sport)),
          ]),
          row.status === 'injured'
            ? el('span.badge.neg', { style: { marginLeft: '4px' } }, 'blessé') : null,
        ]),
      },
      {
        label: 'Charge 30 j', render: (row) =>
          el('div.chart-box', { id: `spark-${row.id}`, style: { width: '120px', height: '26px' } }),
      },
      { label: 'CTL', key: 'ctl', numeric: true,
        render: (row) => el('span.mono', F.num(row.ctl, 1)) },
      { label: 'ATL', key: 'atl', numeric: true,
        render: (row) => el('span.mono.muted', F.num(row.atl, 1)) },
      { label: 'Forme', key: 'tsb', numeric: true,
        render: (row) => formBadge(row.tsb, row.form) },
      { label: 'Ratio A:C', key: 'acwr', numeric: true,
        render: (row) => el('span.mono', { style: { color: F.acwrColor(row.acwr) } },
                            F.num(row.acwr, 2)) },
      { label: 'Disponibilité', key: 'readiness', numeric: true,
        render: (row) => readinessBadge(row.readiness, row.readiness_flag) },
      { label: 'VFC', key: 'hrv_rmssd', numeric: true,
        render: (row) => el('span.mono', row.hrv_rmssd
          ? `${F.num(row.hrv_rmssd, 0)} ms` : '—') },
      { label: 'Sommeil', key: 'sleep_total_min', numeric: true,
        render: (row) => el('span.mono', row.sleep_total_min
          ? F.duration(row.sleep_total_min * 60, 'hm') : '—') },
      { label: 'Semaine', numeric: true,
        render: (row) => el('div.col', { style: { gap: 0, alignItems: 'flex-end' } }, [
          el('span.mono', F.duration(row.week?.duration_s, 'hm')),
          el('span.faint.mono', { style: { fontSize: '11px' } },
             `${F.num(row.week?.load, 0)} pts`),
        ]) },
      { label: '', render: (row) => row.alerts?.length
          ? el('span.badge', {
              style: { color: F.severityColor(row.alert_level),
                       borderColor: 'transparent' },
            }, [icon('alert', 'nav-icon'), String(row.alerts.length)])
          : '' },
    ],
    rows: athletes,
  });
}

function recentTable(activities) {
  if (!activities.length) {
    return emptyState('Aucune séance enregistrée',
      'Importez un fichier .fit, .tcx ou .gpx, ou connectez une montre.',
      el('button.btn.primary', { onclick: () => navigate('/seances') }, 'Importer'),
      'activity');
  }
  return dataTable({
    onRowClick: (row) => navigate(`/seance/${row.id}`),
    card: {
      accent: (row) => row.accent,
      avatar: (row) => avatar(row, 'sm'),
      title: (row) => row.name || '—',
      subtitle: (row) => `${row.first_name} ${row.last_name} · `
                       + `${F.sportLabel(row.sport)} · ${F.relative(row.local_date)}`,
      metrics: (row) => [
        ['Durée', F.duration(row.duration_s, 'hm')],
        ['Distance', F.distance(row.distance_m)],
        ['Charge', F.num(row.load, 0)],
      ],
    },
    columns: [
      { label: 'Athlète', render: (row) => el('div.row-tight', [
          avatar(row, 'sm'), el('span.truncate', `${row.first_name} ${row.last_name}`)]) },
      { label: 'Séance', render: (row) => el('div', [
          el('div.truncate', row.name || '—'),
          el('div.faint', { style: { fontSize: '11px' } },
             `${F.sportLabel(row.sport)} · ${F.relative(row.local_date)}`)]) },
      { label: 'Durée', numeric: true,
        render: (row) => el('span.mono', F.duration(row.duration_s, 'hm')) },
      { label: 'Distance', numeric: true,
        render: (row) => el('span.mono', F.distance(row.distance_m)) },
      { label: 'Charge', numeric: true,
        render: (row) => el('span.mono', F.num(row.load, 0)) },
    ],
    rows: activities,
  });
}

function eventRow(event) {
  const tone = event.days_out <= 14 ? 'warn' : '';
  return el('div.list-row', {
    style: { padding: 'var(--sp-2) 0', borderBottom: 'none' },
    onclick: () => navigate(`/athlete/${event.athlete_id}/planning`),
  }, [
    el(`span.badge${event.priority === 'A' ? '.neg' : tone ? `.${tone}` : ''}`,
       event.priority),
    el('div', { style: { minWidth: 0, flex: 1 } }, [
      el('div.truncate', { style: { fontWeight: 550 } }, event.name),
      el('div.faint', { style: { fontSize: '11px' } },
         `${event.first_name} ${event.last_name} · ${F.date(event.date, 'medium')}`),
    ]),
    el('span.mono.muted', { style: { fontSize: 'var(--fs-sm)' } },
       `J−${event.days_out}`),
  ]);
}

function weekStart() {
  const now = new Date();
  const monday = new Date(now);
  monday.setDate(now.getDate() - ((now.getDay() + 6) % 7));
  return monday;
}
