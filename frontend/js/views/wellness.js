/**
 * Tableau des relevés quotidiens : qui a répondu, dans quel état.
 * C'est la première chose qu'un entraîneur regarde le matin.
 */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import {
  avatar, card, emptyState, field, input, modal, notifyError, pageTitle,
  readinessBadge, scaleField, setTopbar, statTile, textarea, toast,
} from '../lib/ui.js';
import { gauge } from '../charts/plots.js';

export async function render(root, context) {
  let day = context.query.date || F.isoDate(new Date());
  const board = el('div');

  async function load() {
    const data = await api.wellnessToday(day);
    setTopbar(pageTitle('Bien-être du jour',
      `${data.submitted} relevé(s) sur ${data.total} athlètes`,
      el('div.row-tight', [
        el('button.btn.sm.icon', {
          onclick: () => { day = F.isoDate(F.addDays(day, -1)); load(); },
          title: 'Jour précédent' }, [icon('chevronLeft')]),
        el('input.input', { type: 'date', value: day, style: { width: '150px' },
          onchange: (e) => { day = e.target.value; load(); } }),
        el('button.btn.sm.icon', {
          onclick: () => { day = F.isoDate(F.addDays(day, 1)); load(); },
          title: 'Jour suivant' }, [icon('chevronRight')]),
      ])));

    const missing = data.athletes.filter(a => !a.submitted);
    const scores = data.athletes.filter(a => a.readiness != null).map(a => a.readiness);
    const mean = scores.length ? scores.reduce((s, v) => s + v, 0) / scores.length : null;

    mount(board, [
      el('div.grid.grid-4.section', [
        statTile('Taux de réponse', `${F.num(100 * data.submitted / Math.max(1, data.total), 0)} %`, {
          sub: `${data.submitted}/${data.total} athlètes`,
          tone: data.submitted === data.total ? 'pos' : 'warn' }),
        statTile('Disponibilité moyenne', F.num(mean, 0), { unit: '/100',
          color: mean >= 65 ? 'var(--positive)' : mean >= 50 ? 'var(--warning)' : 'var(--danger)',
          tone: 'plain' }),
        statTile('Athlètes en vert',
          String(data.athletes.filter(a => a.flag === 'vert').length), { tone: 'pos' }),
        statTile('Athlètes en rouge',
          String(data.athletes.filter(a => a.flag === 'rouge').length), {
          tone: data.athletes.some(a => a.flag === 'rouge') ? 'neg' : 'plain' }),
      ]),

      missing.length ? el('div.note-box.section', [
        el('strong', 'Relevés manquants : '),
        missing.map(a => `${a.first_name} ${a.last_name}`).join(', '),
        '. Un questionnaire non rempli n’est pas une donnée neutre : il empêche de '
        + 'calculer la disponibilité et fait perdre le signal le plus précoce dont on dispose.',
      ]) : null,

      el('div.wellness-grid', data.athletes.map(athlete => athleteCard(athlete, day, load))),
    ]);
  }

  mount(root, board);
  await load();
}

function athleteCard(athlete, day, reload) {
  const w = athlete.wellness;
  return el(`div.wellness-card.${athlete.flag || 'inconnu'}`, [
    el('div.between', [
      el('div.row-tight', { style: { cursor: 'pointer' },
                            onclick: () => navigate(`/athlete/${athlete.id}`) }, [
        avatar(athlete, 'sm'),
        el('div', [
          el('div', { style: { fontWeight: 570 } },
             `${athlete.first_name} ${athlete.last_name}`),
          athlete.status === 'injured'
            ? el('span.badge.neg', { style: { fontSize: '10px' } }, 'blessé') : null,
        ]),
      ]),
      readinessBadge(athlete.readiness, athlete.flag),
    ]),
    w ? el('div', [
      row('VFC (RMSSD)', w.hrv_rmssd ? `${F.num(w.hrv_rmssd, 0)} ms` : '—'),
      row('FC de repos', w.resting_hr ? `${F.num(w.resting_hr, 0)} bpm` : '—'),
      row('Sommeil', w.sleep_total_min ? F.duration(w.sleep_total_min * 60, 'hm') : '—'),
      row('Fatigue', w.fatigue ? `${w.fatigue}/7` : '—'),
      row('Douleurs', w.soreness ? `${w.soreness}/7` : '—'),
      row('Indice de Hooper', w.hooper_index ? F.num(w.hooper_index, 1) : '—'),
      w.notes ? el('div.definition', { style: { marginTop: 'var(--sp-2)' } }, w.notes) : null,
    ]) : el('div.muted', { style: { fontSize: 'var(--fs-sm)', padding: 'var(--sp-3) 0' } },
        'Aucun relevé pour ce jour.'),
    el('button.btn.sm', { style: { marginTop: 'auto' },
      onclick: () => openForm(athlete, day, reload) },
      [icon(w ? 'edit' : 'plus'), w ? 'Modifier' : 'Saisir']),
  ]);
}

function row(label, value) {
  return el('div.wellness-row', [el('span.muted', label), el('span', value)]);
}

function openForm(athlete, day, reload) {
  const existing = athlete.wellness || {};
  const values = { date: day };
  modal({
    title: `Relevé de ${athlete.first_name} ${athlete.last_name} — ${F.date(day, 'long')}`,
    body: el('div.col', { style: { gap: 'var(--sp-4)' } }, [
      el('div.grid.grid-2', [
        field('VFC — RMSSD (ms)', input({ type: 'number', step: '0.1',
          value: existing.hrv_rmssd || '',
          onchange: (e) => { values.hrv_rmssd = Number(e.target.value) || null; } }),
          'Mesure du matin, au réveil, en position couchée ou assise.'),
        field('FC de repos (bpm)', input({ type: 'number', value: existing.resting_hr || '',
          onchange: (e) => { values.resting_hr = Number(e.target.value) || null; } })),
        field('Sommeil (heures)', input({ type: 'number', step: '0.25',
          value: existing.sleep_total_min ? existing.sleep_total_min / 60 : '',
          onchange: (e) => { values.sleep_total_min = e.target.value
            ? Number(e.target.value) * 60 : null; } })),
        field('Poids (kg)', input({ type: 'number', step: '0.1',
          value: existing.weight_kg || '',
          onchange: (e) => { values.weight_kg = Number(e.target.value) || null; } })),
      ]),
      el('div.label', 'Ressenti — 1 = très bon, 7 = très mauvais'),
      scaleField('Fatigue', 'fatigue', existing.fatigue, (v) => { values.fatigue = v; }),
      scaleField('Douleurs musculaires', 'soreness', existing.soreness,
                 (v) => { values.soreness = v; }),
      scaleField('Qualité du sommeil', 'sleep_quality', existing.sleep_quality,
                 (v) => { values.sleep_quality = v; }),
      scaleField('Stress perçu', 'stress_subj', existing.stress_subj,
                 (v) => { values.stress_subj = v; }),
      scaleField('Humeur', 'mood', existing.mood, (v) => { values.mood = v; }),
      scaleField('Motivation', 'motivation', existing.motivation,
                 (v) => { values.motivation = v; }),
      field('Remarque', textarea({ value: existing.notes || '',
        onchange: (e) => { values.notes = e.target.value || null; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          try {
            const result = await api.saveWellness(athlete.id, values);
            toast(`Disponibilité ${F.num(result.readiness.score, 0)}/100 — `
                  + `${result.readiness.flag}.`, 'success');
            reload();
          } catch (error) { notifyError(error); return false; }
        } },
    ],
  });
}
