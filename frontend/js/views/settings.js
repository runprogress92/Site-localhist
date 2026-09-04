/** Réglages : identité, seuils, pondérations, base de données, maintenance. */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { setTheme, store } from '../lib/store.js';
import {
  card, confirmDialog, dataTable, field, input, modal, notifyError, pageTitle,
  segmented, select, setTopbar, statTile, textarea, toast,
} from '../lib/ui.js';

export async function render(root, context) {
  const [config, stats, health, teams] = await Promise.all([
    api.config(), api.stats(), api.health(), api.teams(),
  ]);
  if (context.token.stale) return;
  const thresholds = { ...config.config.thresholds };
  const weights = { ...config.config.readiness_weights };

  setTopbar(pageTitle('Réglages', 'paramètres de calcul, données et maintenance'));

  mount(root, [
    el('div.grid.grid-4.section', [
      statTile('Athlètes', F.num(stats.database.counts.athletes), { tone: 'plain' }),
      statTile('Séances', F.num(stats.database.counts.activities), {
        sub: stats.volume.first_date
          ? `depuis le ${F.date(stats.volume.first_date, 'medium')}` : null, tone: 'plain' }),
      statTile('Volume enregistré', F.duration(stats.volume.duration_s, 'hm'), {
        sub: `${F.distance(stats.volume.distance_m, 0)} · `
           + `${F.num(stats.volume.elevation_m, 0)} m D+`, tone: 'plain' }),
      statTile('Taille de la base', `${F.num(stats.database.size_mb, 1)} Mo`, {
        sub: `${F.num(stats.streams.samples)} échantillons compressés`, tone: 'plain' }),
    ]),

    el('div.grid.grid-2.section', [
      card('Apparence', el('div.col', [
        field('Thème', segmented([{ value: 'dark', label: 'Sombre' },
                                  { value: 'light', label: 'Clair' }],
          store.theme, (v) => { setTheme(v); }),
          'Le thème clair est conçu pour le travail en extérieur ou en réunion.'),
        field('Fenêtre d’analyse par défaut',
          segmented([{ value: 60, label: '60 j' }, { value: 120, label: '120 j' },
                     { value: 365, label: '1 an' }], store.period, (v) => {
            localStorage.setItem('athlytics.period', String(v));
            store.period = v;
            toast('Fenêtre par défaut mise à jour.', 'success');
          })),
      ])),

      card('Identité', el('div.col', [
        field('Nom de l’entraîneur', input({ value: config.config.coach_name,
          onchange: async (e) => {
            await api.updateConfig({ coach_name: e.target.value });
            toast('Enregistré.', 'success');
          } })),
        field('Fuseau horaire', input({ value: config.config.timezone,
          onchange: async (e) => { await api.updateConfig({ timezone: e.target.value }); } })),
      ])),
    ]),

    card('Seuils d’alerte', el('div', [
      el('p.muted', 'Ces valeurs déclenchent les avertissements de la vue d’ensemble. '
        + 'Les repères par défaut viennent de la littérature ; ajustez-les si votre '
        + 'population ou votre discipline le justifie.'),
      el('div.grid.grid-3', { style: { marginTop: 'var(--sp-4)' } }, [
        thresholdField('Ratio A:C — seuil haut', 'acwr_high', thresholds, 0.05,
          'Au-delà, le risque de blessure de surcharge augmente (Gabbett, 2016).'),
        thresholdField('Ratio A:C — seuil bas', 'acwr_low', thresholds, 0.05,
          'En deçà, la charge récente est trop faible pour maintenir la condition.'),
        thresholdField('Monotonie', 'monotony', thresholds, 0.1,
          'Rapport moyenne/écart-type des charges sur 7 jours (Foster, 1998).'),
        thresholdField('Contrainte hebdomadaire', 'strain', thresholds, 100,
          'Charge hebdomadaire × monotonie.'),
        thresholdField('Rampe de CTL', 'ctl_ramp', thresholds, 0.5,
          'Progression maximale de la condition, en points par semaine.'),
        thresholdField('Besoin de sommeil (min)', 'sleep_need_min', thresholds, 15,
          'Référence pour le calcul de la dette de sommeil.'),
      ]),
      el('button.btn.primary', { style: { marginTop: 'var(--sp-4)' },
        onclick: async () => {
          await api.updateConfig({ thresholds });
          toast('Seuils enregistrés. Relancez un recalcul pour les appliquer.', 'success');
        } }, 'Enregistrer les seuils'),
    ]), { className: 'section' }),

    card('Pondération du score de disponibilité', el('div', [
      el('p.muted', 'Le score de disponibilité est une moyenne pondérée de cinq '
        + 'composantes. La somme doit valoir 1,00. Les composantes absentes un jour '
        + 'donné sont ignorées et les poids renormalisés automatiquement.'),
      el('div.grid.grid-3', { style: { marginTop: 'var(--sp-4)' } }, [
        weightField('Variabilité cardiaque', 'hrv', weights),
        weightField('FC de repos', 'rhr', weights),
        weightField('Sommeil', 'sleep', weights),
        weightField('Ressenti déclaré', 'subjective', weights),
        weightField('Bilan de charge', 'load', weights),
      ]),
      el('div.row-tight', { style: { marginTop: 'var(--sp-4)' } }, [
        el('button.btn.primary', { onclick: async () => {
          const total = Object.values(weights).reduce((s, v) => s + v, 0);
          if (Math.abs(total - 1) > 0.01) {
            toast(`La somme des poids vaut ${total.toFixed(2)} au lieu de 1,00.`, 'error');
            return;
          }
          await api.updateConfig({ readiness_weights: weights });
          toast('Pondérations enregistrées.', 'success');
        } }, 'Enregistrer les pondérations'),
        el('span.faint', { id: 'weight-total', style: { fontSize: 'var(--fs-sm)' } },
           `somme actuelle : ${Object.values(weights).reduce((s, v) => s + v, 0).toFixed(2)}`),
      ]),
    ]), { className: 'section' }),

    el('div.grid.grid-2.section', [
      card('Répartition des données', el('div', [
        el('div.hbars', stats.by_sport.slice(0, 8).map((sport, i) => {
          const max = Math.max(...stats.by_sport.map(s => s.n));
          return el('div.hbar-row', [
            el('span.truncate', F.sportLabel(sport.sport)),
            el('div.hbar-track', [el('div.hbar-fill', {
              style: { width: `${(sport.n / max) * 100}%`,
                       background: F.ZONE_COLORS[i % 7] } })]),
            el('span.hbar-value', `${F.num(sport.n)} séances`),
          ]);
        })),
        el('div.label', { style: { marginTop: 'var(--sp-4)', marginBottom: 'var(--sp-2)' } },
           'Origine des séances'),
        el('div.pill-row', stats.by_provider.map(p =>
          el('div.chip', [el('strong', p.provider), el('span.mono', F.num(p.n))]))),
      ])),

      card('Base de données', el('div', [
        el('dl.kv', [
          el('dt', 'Emplacement'),
          el('dd', { style: { fontFamily: 'var(--font-mono)', fontSize: '11px',
                              wordBreak: 'break-all', textAlign: 'left' } },
             stats.database.path),
          el('dt', 'Taille'), el('dd', `${F.num(stats.database.size_mb, 1)} Mo`),
          el('dt', 'Version SQLite'), el('dd', stats.database.sqlite_version),
          el('dt', 'Version Python'), el('dd', health.python),
          el('dt', 'Séries temporelles'), el('dd', F.num(stats.streams.series)),
          el('dt', 'Relevés de bien-être'), el('dd', F.num(stats.database.counts.wellness)),
          el('dt', 'Meilleurs efforts'), el('dd', F.num(stats.database.counts.best_efforts)),
        ]),
        el('div.row-tight.wrap', { style: { marginTop: 'var(--sp-4)' } }, [
          el('button.btn.sm', { onclick: () => { window.location.href = '/api/admin/backup'; } },
             [icon('download'), 'Télécharger une sauvegarde']),
          el('button.btn.sm', { onclick: async () => {
            const result = await api.rebuild();
            toast(`Agrégats recalculés pour ${result.rebuilt} athlète(s).`, 'success');
          } }, [icon('refresh'), 'Recalculer les agrégats']),
        ]),
      ])),
    ]),

    card('Équipes', el('div', [
      teams.teams.length ? dataTable({
        columns: [
          { label: 'Nom', render: (row) => el('div.row-tight', [
              el('span.dot', { style: { width: '9px', height: '9px', borderRadius: '2px',
                                        background: row.color } }), row.name]) },
          { label: 'Sport', render: (row) => row.sport || '—' },
          { label: 'Entraîneur', render: (row) => row.coach || '—' },
          { label: 'Saison', render: (row) => row.season || '—' },
          { label: 'Athlètes', numeric: true,
            render: (row) => el('span.mono', String(row.athletes)) },
        ],
        rows: teams.teams,
      }) : el('div.muted', 'Aucune équipe.'),
      el('button.btn.sm', { style: { marginTop: 'var(--sp-3)' },
        onclick: () => openTeamForm(() => render(root, context)) },
        [icon('plus'), 'Nouvelle équipe']),
    ]), { className: 'section' }),

    card('Zone sensible', el('div.col', [
      el('div.note-box', 'Ces opérations modifient irréversiblement le contenu de la '
        + 'base. Téléchargez une sauvegarde avant de les lancer.'),
      el('div.row-tight.wrap', [
        el('button.btn.sm', { onclick: () => openSeedForm(() => render(root, context)) },
           [icon('layers'), 'Régénérer le jeu de démonstration']),
        el('button.btn.sm.danger', { onclick: async () => {
          if (!await confirmDialog(
            'Toutes les données — athlètes, séances, relevés, plans — seront '
            + 'définitivement effacées. Cette action est irréversible.',
            { title: 'Effacer toutes les données', confirmLabel: 'Tout effacer' })) return;
          await api.resetAll();
          toast('Base réinitialisée.', 'success');
          window.location.reload();
        } }, [icon('trash'), 'Effacer toutes les données']),
      ]),
    ]), { className: 'section' }),

    el('div.muted.center.section', { style: { fontSize: 'var(--fs-sm)' } }, [
      `Athlytics ${health.version} — Python ${health.python}, `
      + 'aucune dépendance externe. Toutes les données restent sur cette machine.',
    ]),
  ]);

  function thresholdField(label, key, target, step, hint) {
    return field(label, input({ type: 'number', step, value: target[key],
      onchange: (e) => { target[key] = Number(e.target.value); } }), hint);
  }

  function weightField(label, key, target) {
    return field(label, input({ type: 'number', step: 0.05, min: 0, max: 1,
      value: target[key],
      onchange: (e) => {
        target[key] = Number(e.target.value);
        const total = Object.values(target).reduce((s, v) => s + v, 0);
        const node = document.getElementById('weight-total');
        if (node) {
          node.textContent = `somme actuelle : ${total.toFixed(2)}`;
          node.style.color = Math.abs(total - 1) > 0.01
            ? 'var(--danger)' : 'var(--text-faint)';
        }
      } }));
  }
}

function openTeamForm(reload) {
  const values = { color: '#4f8ff7' };
  modal({
    title: 'Nouvelle équipe',
    body: el('div.grid.grid-2', [
      field('Nom', input({ onchange: (e) => { values.name = e.target.value; } })),
      field('Sport', input({ onchange: (e) => { values.sport = e.target.value; } })),
      field('Entraîneur', input({ onchange: (e) => { values.coach = e.target.value; } })),
      field('Saison', input({ onchange: (e) => { values.season = e.target.value; } })),
      field('Couleur', input({ type: 'color', value: values.color,
        onchange: (e) => { values.color = e.target.value; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Créer', primary: true, onClick: async () => {
          if (!values.name) { toast('Le nom est obligatoire.', 'error'); return false; }
          await api.createTeam(values); reload();
        } },
    ],
  });
}

function openSeedForm(reload) {
  const values = { athletes: 8, days: 400, force: true };
  modal({
    title: 'Régénérer le jeu de démonstration',
    body: el('div.col', [
      el('div.note-box', 'Cette opération efface la base et reconstruit un historique '
        + 'complet : périodisation, affûtages, blessures, relevés quotidiens. Les '
        + 'séances récentes reçoivent des flux détaillés à 1 Hz, passés dans le même '
        + 'pipeline d’analyse que les fichiers importés.'),
      el('div.grid.grid-2', [
        field('Nombre d’athlètes', input({ type: 'number', min: 1, max: 10,
          value: values.athletes,
          onchange: (e) => { values.athletes = Number(e.target.value); } })),
        field('Historique (jours)', input({ type: 'number', min: 30, max: 900,
          value: values.days,
          onchange: (e) => { values.days = Number(e.target.value); } })),
      ]),
      el('div.field-hint', 'Comptez environ dix secondes de génération par athlète '
        + 'pour 400 jours d’historique.'),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Régénérer', primary: true, onClick: async (close) => {
          toast('Génération en cours, cela peut prendre une minute…', 'info', 60000);
          try {
            const result = await api.seedDemo(values);
            toast(`${result.seeded.activities} séances générées en `
                  + `${result.seeded.seconds} s.`, 'success');
            window.location.reload();
          } catch (error) { notifyError(error); return false; }
        } },
    ],
  });
}
