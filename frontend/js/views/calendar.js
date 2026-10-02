/**
 * Calendrier mensuel : réalisé, planifié, bien-être et objectifs sur une
 * même grille. La couleur de fond d'un jour porte sa charge.
 *
 * Sur téléphone, la grille de sept colonnes devient un agenda vertical :
 * à 390 px de large, une case de mois fait 44 px et ne montre qu'un titre
 * tronqué à trois lettres, ce qui n'apprend rien. La liste garde les mêmes
 * informations — séance réalisée, séance planifiée, objectif, charge — mais
 * lisibles.
 */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { store } from '../lib/store.js';
import { viewport } from '../lib/viewport.js';
import {
  avatar, card, emptyState, notifyError, pageTitle, select, setTopbar, statTile,
} from '../lib/ui.js';

export async function render(root, context) {
  if (!store.athletes.length) {
    setTopbar(pageTitle('Calendrier'));
    mount(root, emptyState('Aucun athlète', 'Créez un athlète pour afficher un calendrier.'));
    return;
  }
  let athleteId = Number(context.query.athlete) || store.athletes[0].id;
  let cursor = new Date();
  cursor.setDate(1);

  const board = el('div');
  mount(root, board);

  async function load() {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const last = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 0);
    const gridStart = F.addDays(first, -((first.getDay() + 6) % 7));
    const gridEnd = F.addDays(last, (7 - ((last.getDay() + 6) % 7) - 1));

    const athlete = store.athletes.find(a => a.id === athleteId) || store.athletes[0];
    setTopbar(pageTitle('Calendrier',
      `${athlete.first_name} ${athlete.last_name} — ${F.date(first, 'month')}`,
      el('div.row-tight', [
        select(store.athletes.map(a => ({
          value: a.id, label: `${a.first_name} ${a.last_name}`, selected: a.id === athleteId,
        })), { style: viewport.isMobile
                 ? { flex: '1 1 auto', minWidth: '0' } : { width: '190px' },
               onchange: (e) => { athleteId = Number(e.target.value); load(); } }),
        el('button.btn.sm.icon', {
          onclick: () => { cursor.setMonth(cursor.getMonth() - 1); load(); },
        }, [icon('chevronLeft')]),
        el('button.btn.sm', {
          onclick: () => { cursor = new Date(); cursor.setDate(1); load(); },
        }, viewport.isMobile ? "Auj." : "Aujourd'hui"),
        el('button.btn.sm.icon', {
          onclick: () => { cursor.setMonth(cursor.getMonth() + 1); load(); },
        }, [icon('chevronRight')]),
      ])));

    mount(board, el('div.loading-screen', [el('span.spinner')]));
    try {
      const data = await api.calendar(athleteId, {
        from: F.isoDate(gridStart), to: F.isoDate(gridEnd) });
      const byDate = Object.fromEntries(data.days.map(d => [d.date, d]));
      const maxLoad = Math.max(1, ...data.days.map(d => d.load?.load || 0));

      const cells = [];
      for (let d = new Date(gridStart); d <= gridEnd; d = F.addDays(d, 1)) {
        const key = F.isoDate(d);
        const day = byDate[key] || { date: key, activities: [], planned: [], events: [] };
        const inMonth = d.getMonth() === cursor.getMonth();
        const ratio = (day.load?.load || 0) / maxLoad;
        cells.push(el(`div.cal-day${inMonth ? '' : '.other'}${day.is_today ? '.today' : ''}`, {
          style: ratio > 0 ? {
            background: `color-mix(in srgb, var(--accent) ${Math.round(ratio * 22)}%, var(--surface))`,
          } : null,
        }, [
          el('div.cal-daynum', [
            el('span', String(d.getDate())),
            day.wellness?.readiness != null
              ? el('span.dot', {
                  title: `Disponibilité ${F.num(day.wellness.readiness, 0)}/100`,
                  style: { width: '6px', height: '6px', borderRadius: '50%',
                           background: F.readinessColor(day.wellness.readiness_flag) },
                }) : null,
          ]),
          ...day.events.map(event => el('div.cal-item.event',
            { title: event.name }, `🎯 ${event.name}`)),
          ...day.activities.map(activity => el('div.cal-item', {
            title: `${activity.name} — ${F.duration(activity.duration_s, 'hm')}`,
            style: { borderLeftColor: athlete.accent },
            onclick: () => navigate(`/seance/${activity.id}`),
          }, `${F.duration(activity.duration_s, 'hm')} · ${activity.name}`)),
          ...day.planned.filter(p => p.status === 'planned').map(item =>
            el('div.cal-item.planned', { title: item.description || item.name },
               `${item.name}`)),
          day.load?.load ? el('div.faint', {
            style: { fontSize: '10px', marginTop: 'auto', textAlign: 'right' },
          }, `${F.num(day.load.load, 0)} pts`) : null,
        ]));
      }

      const monthDays = data.days.filter(d =>
        F.parseDate(d.date).getMonth() === cursor.getMonth());
      const totals = monthDays.reduce((acc, d) => ({
        load: acc.load + (d.load?.load || 0),
        duration: acc.duration + d.activities.reduce((s, a) => s + (a.duration_s || 0), 0),
        distance: acc.distance + d.activities.reduce((s, a) => s + (a.distance_m || 0), 0),
        sessions: acc.sessions + d.activities.length,
      }), { load: 0, duration: 0, distance: 0, sessions: 0 });

      mount(board, [
        el('div.grid.grid-4.section', [
          statTile('Séances du mois', String(totals.sessions), { tone: 'plain' }),
          statTile('Durée', F.duration(totals.duration, 'hm'), { tone: 'plain' }),
          statTile('Distance', F.distance(totals.distance, 0), { tone: 'plain' }),
          statTile('Charge cumulée', F.num(totals.load, 0), { tone: 'plain' }),
        ]),
        data.blocks.length ? el('div.pill-row.section', data.blocks.map(block =>
          el('div.chip', [el('strong', block.phase || block.name),
            el('span.faint', `${F.date(block.start_date, 'short')} → `
                           + `${F.date(block.end_date, 'short')}`)]))) : null,
        viewport.isMobile
          ? agenda(data.days, athlete, cursor)
          : card(null, el('div', [
              el('div.cal-grid', { style: { marginBottom: '6px' } },
                F.DAYS_SHORT.map(d => el('div.cal-head', d))),
              el('div.cal-grid', cells),
            ])),
        viewport.isMobile
          ? el('div.agenda-legend.section', [
              el('span', [el('i.agenda-key'), 'réalisée']),
              el('span', [el('i.agenda-key.planned'), 'planifiée']),
              el('span', [el('i.agenda-key.event'), 'objectif']),
            ])
          : el('div.row-tight.section', { style: { fontSize: 'var(--fs-sm)',
                                                   color: 'var(--text-muted)' } }, [
              el('span.badge', 'séance réalisée'),
              el('span.badge', { style: { borderStyle: 'dashed' } }, 'séance planifiée'),
              el('span.badge.neg', 'objectif'),
              el('span', '— l’intensité du fond indique la charge du jour'),
            ]),
      ]);
    } catch (error) { notifyError(error); }
  }
  await load();
}

/**
 * Agenda vertical du mois, pour téléphone.
 *
 * Tous les jours du mois sont listés, y compris ceux sans séance : la
 * succession des jours de repos fait partie de la lecture d'une semaine
 * d'entraînement, la masquer donnerait un planning plus dense qu'il n'est.
 */
function agenda(days, athlete, cursor) {
  const month = cursor.getMonth();
  const rows = [];
  let lastWeek = null;

  for (const day of days) {
    const d = F.parseDate(day.date);
    if (d.getMonth() !== month) continue;
    const week = weekIndex(d);
    if (lastWeek !== null && week !== lastWeek) {
      rows.push(el('div.agenda-sep'));
    }
    lastWeek = week;

    const items = [
      ...day.events.map(event =>
        el('div.agenda-item.event', [icon('target', 'agenda-icon'), event.name])),
      ...day.activities.map(activity => el('div.agenda-item', {
        onclick: () => navigate(`/seance/${activity.id}`),
        style: { borderLeftColor: athlete.accent },
      }, [
        el('div.agenda-item-main', [
          el('span.agenda-item-name.truncate', activity.name),
          el('span.agenda-item-meta',
             [F.duration(activity.duration_s, 'hm'),
              activity.distance_m ? F.distance(activity.distance_m, 1) : null,
             ].filter(Boolean).join(' · ')),
        ]),
        icon('chevronRight', 'agenda-chevron'),
      ])),
      ...day.planned.filter(p => p.status === 'planned').map(item =>
        el('div.agenda-item.planned', [
          el('div.agenda-item-main', [
            el('span.agenda-item-name.truncate', item.name),
            item.description
              ? el('span.agenda-item-meta.truncate', item.description) : null,
          ]),
        ])),
    ];

    rows.push(el(`div.agenda-day${day.is_today ? '.today' : ''}`, [
      el('div.agenda-date', [
        el('span.agenda-dow', F.DAYS_SHORT[(d.getDay() + 6) % 7]),
        el('span.agenda-num', String(d.getDate())),
        day.wellness?.readiness != null
          ? el('span.agenda-dot', {
              title: `Disponibilité ${F.num(day.wellness.readiness, 0)}/100`,
              style: { background: F.readinessColor(day.wellness.readiness_flag) },
            }) : null,
      ]),
      el('div.agenda-body', items.length ? items : el('div.agenda-rest', 'repos')),
      day.load?.load
        ? el('div.agenda-load', [el('strong', F.num(day.load.load, 0)),
                                 el('span.faint', 'pts')])
        : el('div.agenda-load'),
    ]));
  }
  return el('div.card.flush.section', el('div.agenda', rows));
}

/** Numéro de semaine ISO approché : suffit à séparer les semaines affichées. */
function weekIndex(d) {
  const monday = F.addDays(d, -((d.getDay() + 6) % 7));
  return Math.floor(monday.getTime() / 86400000);
}
