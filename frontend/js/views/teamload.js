/** Charge du groupe : matrice quotidienne et classement par volume. */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import {
  avatar, card, dataTable, formBadge, notifyError, pageTitle, segmented, setTopbar,
} from '../lib/ui.js';
import { loadMatrix } from '../charts/streams.js';
import { sparkline } from '../charts/plots.js';

export async function render(root, context) {
  let days = 42;
  const board = el('div');
  mount(root, board);

  async function load() {
    setTopbar(pageTitle('Charge du groupe',
      `charge quotidienne des ${days} derniers jours`,
      segmented([{ value: 28, label: '4 sem.' }, { value: 42, label: '6 sem.' },
                 { value: 84, label: '12 sem.' }], days, (v) => { days = v; load(); })));
    mount(board, el('div.loading-screen', [el('span.spinner')]));
    try {
      const [matrix, overview] = await Promise.all([
        api.teamMatrix(days), api.teamOverview()]);
      const totals = matrix.matrix.map(row => ({
        athlete: row.athlete, total: row.total,
        cells: row.cells,
        mean: row.total / Math.max(1, row.cells.filter(c => c.load).length),
        restDays: row.cells.filter(c => !c.load).length,
        state: overview.athletes.find(a => a.id === row.athlete.id) || {},
      }));

      mount(board, [
        card('Matrice charge × jour', el('div', { id: 'matrix' }), {
          subtitle: 'une ligne par athlète, une case par jour. Plus la case est dense, '
                  + 'plus la charge du jour est élevée. Les colonnes claires sont les '
                  + 'jours de repos du groupe.',
          className: 'section' }),
        card('Volume et récupération', dataTable({
          sortable: true, initialSort: { key: 'total', dir: 'desc' },
          onRowClick: (row) => navigate(`/athlete/${row.athlete.id}`),
          columns: [
            { label: 'Athlète', key: 'name', render: (row) => el('div.row-tight', [
                avatar(row.athlete, 'sm'),
                `${row.athlete.first_name} ${row.athlete.last_name}`]) },
            { label: 'Profil de charge', render: (row) =>
                el('div.chart-box', { id: `tspark-${row.athlete.id}`,
                                      style: { width: '180px', height: '30px' } }) },
            { label: 'Charge cumulée', key: 'total', numeric: true,
              render: (row) => el('span.mono', { style: { fontWeight: 600 } },
                                  F.num(row.total, 0)) },
            { label: 'Moyenne / jour actif', key: 'mean', numeric: true,
              render: (row) => el('span.mono', F.num(row.mean, 0)) },
            { label: 'Jours de repos', key: 'restDays', numeric: true,
              render: (row) => el('span.mono', { style: { color: row.restDays < days / 14
                ? 'var(--warning)' : 'var(--text)' } }, String(row.restDays)) },
            { label: 'Condition', numeric: true,
              render: (row) => el('span.mono', F.num(row.state.ctl, 1)) },
            { label: 'Forme', numeric: true,
              render: (row) => formBadge(row.state.tsb, row.state.form) },
            { label: 'Ratio A:C', numeric: true, render: (row) =>
                el('span.mono', { style: { color: F.acwrColor(row.state.acwr) } },
                   F.num(row.state.acwr, 2)) },
          ],
          rows: totals.map(t => ({ ...t,
            name: `${t.athlete.last_name} ${t.athlete.first_name}` })),
        }), { flush: true }),
      ]);

      loadMatrix(document.getElementById('matrix'), {
        dates: matrix.dates, matrix: matrix.matrix,
        onCellClick: (athlete) => navigate(`/athlete/${athlete.id}`),
      });
      for (const row of totals) {
        const node = document.getElementById(`tspark-${row.athlete.id}`);
        if (node) {
          sparkline(node, { values: row.cells.map(c => c.load || 0),
                            color: row.athlete.accent, height: 30 });
        }
      }
    } catch (error) { notifyError(error); }
  }
  await load();
}
