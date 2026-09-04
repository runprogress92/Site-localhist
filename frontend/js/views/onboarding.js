/**
 * Premier écran, quand aucun athlète n'existe encore.
 *
 * Trois chemins possibles, présentés dans l'ordre où on les emprunte
 * réellement : découvrir avec des données de démonstration, créer son
 * premier athlète, ou brancher une montre.
 */
import { api } from '../lib/api.js';
import { el, icon, mount } from '../lib/dom.js';
import { navigate } from '../lib/router.js';
import { card, notifyError, toast } from '../lib/ui.js';
import { openAthleteForm } from './athlete-form.js';

export function welcomeScreen(reload) {
  return el('div.welcome', [
    el('div.welcome-head', [
      el('div.brand-mark.welcome-mark', 'A'),
      el('h1', 'Bienvenue dans Athlytics'),
      el('p.muted', { style: { maxWidth: '560px', margin: '0 auto' } },
        'Une plateforme de suivi d’athlètes qui tourne entièrement sur votre '
        + 'machine. Rien ne part vers un service tiers, et il n’y a aucune '
        + 'dépendance à installer.'),
    ]),
    el('div.grid.grid-3.welcome-cards', [
      welcomeCard('layers', 'Découvrir avec des données',
        'Génère 8 athlètes et 13 mois d’historique complet : périodisation, '
        + 'affûtages, relevés quotidiens, séances détaillées à la seconde. '
        + 'Le meilleur moyen de voir ce que fait l’outil.',
        'Générer un jeu de démonstration', 'primary', async (button) => {
          button.disabled = true;
          button.textContent = 'Génération en cours…';
          toast('Génération lancée : comptez environ deux minutes.', 'info', 20000);
          try {
            const result = await api.seedDemo({ athletes: 8, days: 400, force: true });
            toast(`${result.seeded.activities} séances générées.`, 'success');
            window.location.reload();
          } catch (error) {
            notifyError(error);
            button.disabled = false;
            button.textContent = 'Générer un jeu de démonstration';
          }
        }),
      welcomeCard('users', 'Créer un athlète',
        'Renseignez l’identité et les seuils physiologiques — fréquence '
        + 'cardiaque maximale, FC au seuil, FTP ou allure seuil. Ce sont eux '
        + 'qui rendent la charge d’entraînement comparable dans le temps.',
        'Nouvel athlète', '', () => openAthleteForm(null, reload)),
      welcomeCard('watch', 'Brancher une montre',
        'Garmin, Polar et COROS exportent tous des fichiers que l’application '
        + 'lit nativement. La synchronisation directe demande en plus un '
        + 'compte développeur auprès de la marque.',
        'Voir les connexions', '', () => navigate('/connexions')),
    ]),
    el('div.welcome-foot.muted', [
      'Vos données resteront dans un unique fichier SQLite, sur cette machine. ',
      el('a', { href: '#/reglages', onclick: () => navigate('/reglages') },
         'Réglages'), ' permet de le sauvegarder à tout moment.',
    ]),
  ]);
}

function welcomeCard(iconName, title, text, action, variant, onClick) {
  const button = el(`button.btn${variant ? `.${variant}` : ''}`, {
    style: { marginTop: 'auto', width: '100%' },
    onclick: () => onClick(button),
  }, action);
  return el('div.card.welcome-card', [
    el('div.welcome-icon', [icon(iconName)]),
    el('div.card-title', title),
    el('p.muted', { style: { fontSize: 'var(--fs-sm)', lineHeight: '1.65' } }, text),
    button,
  ]);
}
