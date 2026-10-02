/** Journal global des séances, tous athlètes confondus. */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { store } from '../lib/store.js';
import {
  avatar, card, dataTable, emptyState, field, notifyError, pageTitle, select,
  setTopbar, statTile, toast,
} from '../lib/ui.js';
import { openUpload } from './athlete.js';

export async function render(root, context) {
  const state = {
    athlete_id: context.query.athlete || '', sport: '', search: '',
    from: '', page: 0, sort: 'start_time', order: 'desc',
  };

  setTopbar(pageTitle('Séances', 'journal complet, tous athlètes confondus',
    el('div.row-tight', [
      el('button.btn.sm', {
        onclick: () => { window.location.href = '/api/activities/export.csv'; },
      }, [icon('download'), 'Exporter']),
      el('button.btn.sm.primary', {
        onclick: () => {
          const target = state.athlete_id || store.athletes[0]?.id;
          if (!target) { toast('Créez d’abord un athlète.', 'error'); return; }
          openUpload(Number(target), load);
        },
      }, [icon('upload'), 'Importer']),
    ])));

  // Sur téléphone, les filtres occupaient un écran entier avant le premier
  // résultat. Ils sont repliés par défaut et s'ouvrent à la demande.
  const filterBody = el('div.filters-body.row-tight.wrap', [
    el('div.search-box', [
      icon('search'),
      el('input.input', {
        placeholder: 'Rechercher une séance…',
        oninput: debounce((e) => { state.search = e.target.value; state.page = 0; load(); }),
      }),
    ]),
    select([{ value: '', label: 'Tous les athlètes' },
      ...store.athletes.map(a => ({ value: a.id, label: `${a.first_name} ${a.last_name}`,
                                    selected: String(a.id) === String(state.athlete_id) }))],
      { style: { width: '190px' },
        onchange: (e) => { state.athlete_id = e.target.value; state.page = 0; load(); } }),
    select([{ value: '', label: 'Tous les sports' },
      ...Object.entries(store.sports || F.SPORT_LABELS).map(([k, v]) => ({ value: k, label: v }))],
      { style: { width: '170px' },
        onchange: (e) => { state.sport = e.target.value; state.page = 0; load(); } }),
    field('À partir du', el('input.input', { type: 'date', style: { width: '150px' },
      onchange: (e) => { state.from = e.target.value; state.page = 0; load(); } })),
  ]);

  const filters = el('div.filters.section', [
    el('button.filters-toggle', {
      onclick: () => {
        filters.classList.toggle('open');
        const open = filters.classList.contains('open');
        filters.querySelector('.filters-toggle-label').textContent =
          open ? 'Masquer les filtres' : 'Filtrer et rechercher';
      },
    }, [icon('filter'), el('span.filters-toggle-label', 'Filtrer et rechercher'),
        icon('chevronDown', 'filters-chevron')]),
    filterBody,
  ]);

  const summary = el('div.grid.grid-4.section');
  const container = el('div');
  mount(root, [filters, summary, container]);

  async function load() {
    mount(container, el('div.loading-screen', [el('span.spinner')]));
    try {
      const data = await api.activities({
        athlete_id: state.athlete_id || undefined,
        sport: state.sport || undefined,
        search: state.search || undefined,
        from: state.from || undefined,
        limit: 50, offset: state.page * 50,
        sort: state.sort, order: state.order,
      });
      const rows = data.activities;
      const totals = rows.reduce((acc, r) => ({
        duration: acc.duration + (r.duration_s || 0),
        distance: acc.distance + (r.distance_m || 0),
        load: acc.load + (r.load || 0),
        elevation: acc.elevation + (r.elevation_gain_m || 0),
      }), { duration: 0, distance: 0, load: 0, elevation: 0 });

      mount(summary, [
        statTile('Séances trouvées', F.num(data.total), { tone: 'plain' }),
        statTile('Durée (page)', F.duration(totals.duration, 'hm'), { tone: 'plain' }),
        statTile('Distance (page)', F.distance(totals.distance, 0), { tone: 'plain' }),
        statTile('Dénivelé (page)', `${F.num(totals.elevation, 0)} m`, { tone: 'plain' }),
      ]);

      mount(container, [
        card(null, rows.length ? table(rows) : emptyState(
          'Aucune séance', 'Aucun résultat pour ces filtres.'), { flush: true }),
        data.total > 50 ? el('div.between', { style: { marginTop: 'var(--sp-4)' } }, [
          el('span.muted', `${data.offset + 1}–${Math.min(data.offset + 50, data.total)} `
                         + `sur ${F.num(data.total)}`),
          el('div.row-tight', [
            el('button.btn.sm', { disabled: state.page === 0,
              onclick: () => { state.page -= 1; load(); } }, 'Précédent'),
            el('button.btn.sm', { disabled: data.offset + 50 >= data.total,
              onclick: () => { state.page += 1; load(); } }, 'Suivant'),
          ]),
        ]) : null,
      ]);
    } catch (error) { notifyError(error); }
  }

  function table(rows) {
    return dataTable({
      onRowClick: (row) => navigate(`/seance/${row.id}`),
      card: {
        accent: (row) => row.accent,
        avatar: (row) => avatar({ ...row, accent: row.accent }, 'sm'),
        title: (row) => row.name || '—',
        subtitle: (row) => `${row.first_name} ${row.last_name.charAt(0)}. · `
                         + `${row.sport_label} · ${F.date(row.local_date, 'medium')}`,
        metrics: (row) => [
          ['Durée', F.duration(row.duration_s, 'hm')],
          row.distance_m ? ['Distance', F.distance(row.distance_m)] : null,
          row.avg_hr ? ['FC moy', `${F.num(row.avg_hr, 0)}`] : null,
          ['Charge', F.num(row.load, 0)],
        ],
      },
      columns: [
        { label: 'Athlète', render: (row) => el('div.row-tight', [
            avatar({ ...row, accent: row.accent }, 'sm'),
            el('span.truncate', `${row.first_name} ${row.last_name[0]}.`)]) },
        { label: 'Date', render: (row) => el('div', [
            el('div.mono', F.date(row.local_date, 'medium')),
            el('div.faint', { style: { fontSize: '10.5px' } }, F.time(row.start_time))]) },
        { label: 'Séance', render: (row) => el('div', [
            el('div.truncate', { style: { fontWeight: 550 } }, row.name),
            el('div.faint', { style: { fontSize: '11px' } },
               `${row.sport_label}${row.provider !== 'manual' ? ` · ${row.provider}` : ''}`)]) },
        { label: 'Durée', numeric: true,
          render: (row) => el('span.mono', F.duration(row.duration_s, 'hm')) },
        { label: 'Distance', numeric: true,
          render: (row) => el('span.mono', F.distance(row.distance_m)) },
        { label: 'D+', numeric: true, render: (row) => el('span.mono.muted',
            row.elevation_gain_m ? `${F.num(row.elevation_gain_m, 0)} m` : '—') },
        { label: 'Allure', numeric: true,
          render: (row) => el('span.mono', F.paceForSport(row.sport, row.avg_speed_ms)) },
        { label: 'FC', numeric: true,
          render: (row) => el('span.mono', row.avg_hr ? F.num(row.avg_hr, 0) : '—') },
        { label: 'Charge', numeric: true, render: (row) =>
            el('span.mono', { style: { fontWeight: 600 } }, F.num(row.load, 0)) },
      ],
      rows,
    });
  }

  await load();
}

function debounce(fn, wait = 300) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
}
