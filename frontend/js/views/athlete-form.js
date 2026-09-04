/**
 * Création et modification d'un athlète.
 *
 * Le formulaire couvre l'identité et le profil physiologique dans la même
 * fenêtre : créer un athlète sans ses seuils produirait des charges
 * d'entraînement fausses dès la première séance importée.
 */
import { api } from '../lib/api.js';
import { el } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { field, input, modal, notifyError, select, textarea, toast } from '../lib/ui.js';

const SPORTS = [
  ['running', 'Course à pied'], ['trail_running', 'Trail'], ['cycling', 'Vélo'],
  ['swimming', 'Natation'], ['rowing', 'Aviron'], ['walking', 'Marche'],
  ['hiking', 'Randonnée'], ['strength_training', 'Musculation'], ['other', 'Autre'],
];
const LEVELS = ['loisir', 'compétiteur', 'national', 'élite', 'pro'];
const ACCENTS = ['#4f8ff7', '#3fb98c', '#e08d3c', '#d8543f', '#b1418b', '#7b56c9',
                 '#5b8fd6', '#c9c04a'];

export function openAthleteForm(existing, onDone) {
  const isNew = !existing;
  const values = {
    sex: existing?.sex || 'F',
    primary_sport: existing?.primary_sport || 'running',
    level: existing?.level || 'compétiteur',
    accent: existing?.accent || ACCENTS[Math.floor(Math.random() * ACCENTS.length)],
  };
  const physio = {};

  const swatches = el('div.row-tight', ACCENTS.map(color =>
    el('button', {
      type: 'button',
      style: {
        width: '24px', height: '24px', borderRadius: '6px', background: color,
        border: color === values.accent ? '2px solid var(--text)' : '2px solid transparent',
        cursor: 'pointer',
      },
      onclick: (event) => {
        values.accent = color;
        [...swatches.children].forEach(b => { b.style.border = '2px solid transparent'; });
        event.currentTarget.style.border = '2px solid var(--text)';
      },
    })));

  modal({
    title: isNew ? 'Nouvel athlète' : 'Modifier la fiche',
    wide: true,
    body: el('div.col', { style: { gap: 'var(--sp-5)' } }, [
      el('div', [
        el('div.label', { style: { marginBottom: 'var(--sp-3)' } }, 'Identité'),
        el('div.grid.grid-3', [
          field('Prénom *', input({ value: existing?.first_name || '',
            onchange: (e) => { values.first_name = e.target.value.trim(); } })),
          field('Nom *', input({ value: existing?.last_name || '',
            onchange: (e) => { values.last_name = e.target.value.trim(); } })),
          field('Date de naissance', input({ type: 'date',
            value: existing?.birth_date || '',
            onchange: (e) => { values.birth_date = e.target.value; } })),
          field('Sexe', select([
            { value: 'F', label: 'Féminin', selected: values.sex === 'F' },
            { value: 'M', label: 'Masculin', selected: values.sex === 'M' },
            { value: 'X', label: 'Non précisé', selected: values.sex === 'X' }],
            { onchange: (e) => { values.sex = e.target.value; } }),
            'Détermine les coefficients du TRIMP et les normes de VO2max.'),
          field('Taille (cm)', input({ type: 'number',
            value: existing?.height_cm || '',
            onchange: (e) => { values.height_cm = Number(e.target.value) || null; } })),
          field('Poids (kg)', input({ type: 'number', step: '0.1',
            value: existing?.weight_kg || '',
            onchange: (e) => {
              values.weight_kg = Number(e.target.value) || null;
              physio.weight_kg = values.weight_kg;
            } })),
          field('Sport principal', select(SPORTS.map(([v, l]) =>
            ({ value: v, label: l, selected: values.primary_sport === v })),
            { onchange: (e) => { values.primary_sport = e.target.value; } })),
          field('Discipline', input({ value: existing?.discipline || '',
            placeholder: 'ex. 10 km / semi-marathon',
            onchange: (e) => { values.discipline = e.target.value; } })),
          field('Niveau', select(LEVELS.map(l =>
            ({ value: l, label: l, selected: values.level === l })),
            { onchange: (e) => { values.level = e.target.value; } })),
        ]),
        field('Couleur d’identification', swatches),
      ]),

      el('div', [
        el('div.label', { style: { marginBottom: 'var(--sp-2)' } },
           'Profil physiologique'),
        el('div.field-hint', { style: { marginBottom: 'var(--sp-3)' } },
          'Facultatif, mais déterminant : sans seuils, la charge des séances '
          + 'importées ne peut être calculée que très approximativement. '
          + 'La FC au seuil est la valeur la plus utile — mesurez-la sur un '
          + 'effort maximal de 30 minutes.'),
        el('div.grid.grid-4', [
          field('FC maximale', input({ type: 'number', placeholder: 'bpm',
            onchange: (e) => { physio.hr_max = Number(e.target.value) || null; } })),
          field('FC de repos', input({ type: 'number', placeholder: 'bpm',
            onchange: (e) => { physio.hr_rest = Number(e.target.value) || null; } })),
          field('FC au seuil (LT2)', input({ type: 'number', placeholder: 'bpm',
            onchange: (e) => { physio.hr_lt2 = Number(e.target.value) || null; } })),
          field('VO2max', input({ type: 'number', step: '0.1', placeholder: 'ml/kg/min',
            onchange: (e) => { physio.vo2max = Number(e.target.value) || null; } })),
          field('FTP', input({ type: 'number', placeholder: 'watts',
            onchange: (e) => { physio.ftp_w = Number(e.target.value) || null; } })),
          field('Puissance critique', input({ type: 'number', placeholder: 'watts',
            onchange: (e) => { physio.cp_w = Number(e.target.value) || null; } })),
          field('Allure au seuil', input({ placeholder: 'ex. 3:45',
            onchange: (e) => {
              const match = /^(\d+)[:'](\d{1,2})$/.exec(e.target.value.trim());
              physio.threshold_pace_s_km = match
                ? Number(match[1]) * 60 + Number(match[2]) : null;
            } }), 'minutes:secondes par kilomètre'),
          field('Allure en natation', input({ placeholder: 'ex. 1:35 / 100 m',
            onchange: (e) => {
              const match = /^(\d+)[:'](\d{1,2})$/.exec(e.target.value.trim());
              physio.critical_speed_ms = match
                ? Number((100 / (Number(match[1]) * 60 + Number(match[2]))).toFixed(4))
                : null;
            } })),
        ]),
      ]),
      field('Notes', textarea({ value: existing?.notes || '', rows: 2,
        onchange: (e) => { values.notes = e.target.value; } })),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      {
        label: isNew ? 'Créer l’athlète' : 'Enregistrer', primary: true,
        onClick: async () => {
          if (isNew && (!values.first_name || !values.last_name)) {
            toast('Le prénom et le nom sont obligatoires.', 'error');
            return false;
          }
          try {
            const cleanPhysio = Object.fromEntries(
              Object.entries(physio).filter(([, v]) => v !== null && v !== undefined));
            if (isNew) {
              const created = await api.createAthlete(
                Object.keys(cleanPhysio).length
                  ? { ...values, physiology: cleanPhysio } : values);
              const { refreshRoster } = await import('../main.js');
              await refreshRoster();
              toast(`${values.first_name} ${values.last_name} a été créé·e.`, 'success');
              navigate(`/athlete/${created.id}`);
            } else {
              await api.updateAthlete(existing.id, values);
              if (Object.keys(cleanPhysio).length) {
                await api.addPhysiology(existing.id, {
                  ...cleanPhysio, effective_date: F.isoDate(new Date()) });
              }
              const { refreshRoster } = await import('../main.js');
              await refreshRoster();
              toast('Fiche mise à jour.', 'success');
              if (onDone) onDone();
            }
          } catch (error) { notifyError(error); return false; }
        },
      },
    ],
  });
}
