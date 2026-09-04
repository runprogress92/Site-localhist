/**
 * Calendrier mensuel : réalisé, planifié, bien-être et objectifs sur une
 * même grille. La couleur de fond d'un jour porte sa charge.
 */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { store } from '../lib/store.js';
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
        })), { style: { width: '190px' },
               onchange: (e) => { athleteId = Number(e.target.value); load(); } }),
        el('button.btn.sm.icon', {
          onclick: () => { cursor.setMonth(cursor.getMonth() - 1); load(); },
        }, [icon('chevronLeft')]),
        el('button.btn.sm', {
          onclick: () => { cursor = new Date(); cursor.setDate(1); load(); },
        }, "Aujourd'hui"),
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
        card(null, el('div', [
          el('div.cal-grid', { style: { marginBottom: '6px' } },
            F.DAYS_SHORT.map(d => el('div.cal-head', d))),
          el('div.cal-grid', cells),
        ])),
        el('div.row-tight.section', { style: { fontSize: 'var(--fs-sm)', color: 'var(--text-muted)' } }, [
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
