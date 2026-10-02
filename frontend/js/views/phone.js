/**
 * Section « Connecter mon téléphone » des réglages.
 *
 * Le but : qu'un entraîneur non technicien puisse consulter ses athlètes au
 * bord du terrain sans jamais taper une adresse IP. On affiche donc un QR
 * code qui contient déjà le code d'accès, et seulement en second recours
 * l'adresse et le code en clair, pour un deuxième appareil qui arriverait
 * plus tard.
 *
 * Le code d'accès n'est pas décoratif : dès que le serveur écoute sur le
 * réseau, n'importe quel appareil du même Wi-Fi peut atteindre le port. Les
 * données suivies ici sont des données de santé ; elles ne doivent pas être
 * lisibles par tout un vestiaire.
 */
import { api } from '../lib/api.js';
import { el, icon } from '../lib/dom.js';
import { card, confirmDialog, notifyError, toast } from '../lib/ui.js';

/**
 * Construit la carte complète.
 *
 * @param {object} state   réponse de GET /api/network
 * @param {Function} reload  rappel pour redessiner la vue après changement
 */
export function phoneCard(state, reload) {
  return card('Connecter mon téléphone', body(state, reload), {
    subtitle: state.enabled
      ? 'accès ouvert au réseau local'
      : 'consulter vos athlètes depuis un téléphone, sur le même Wi-Fi',
    className: 'section',
  });
}

function body(state, reload) {
  if (!state.addresses.length) return noNetwork();
  return el('div.phone-share', [
    state.enabled ? enabledPanel(state, reload) : disabledPanel(state, reload),
  ]);
}

/* -------------------------------------------------- accès non encore ouvert */
function disabledPanel(state, reload) {
  return el('div.col', [
    el('div.note-box', [
      el('strong', 'Pour l’instant, le site n’est visible que sur cet ordinateur. '),
      'En ouvrant l’accès, vous pourrez le consulter depuis votre téléphone ou '
      + 'votre tablette — à condition qu’ils soient connectés au même réseau '
      + 'Wi-Fi, et que cet ordinateur reste allumé avec la fenêtre noire ouverte. '
      + 'Rien n’est envoyé sur Internet : le téléphone affiche le site de cet '
      + 'ordinateur, pas une copie en ligne.',
    ]),
    el('ul.phone-steps', [
      step('1', 'Vous activez l’accès ci-dessous.'),
      step('2', 'Un QR code apparaît : vous le scannez avec l’appareil photo.'),
      step('3', 'Le téléphone ouvre le site, déjà déverrouillé.'),
      step('4', '« Ajouter à l’écran d’accueil » place l’icône sur le téléphone.'),
    ]),
    el('div.row-tight.wrap', [
      el('button.btn.primary', {
        onclick: async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          try {
            const result = await api.setNetwork(true);
            toast(result.requires_restart
              ? 'Accès activé. Relancez le site avec « LANCER-SUR-LE-TELEPHONE » '
                + 'pour que le téléphone puisse s’y connecter.'
              : 'Accès activé.', 'success');
            reload();
          } catch (error) { button.disabled = false; notifyError(error); }
        },
      }, [icon('phone'), 'Ouvrir l’accès depuis le téléphone']),
    ]),
    el('div.faint.phone-small',
       'Vous pourrez refermer cet accès à tout moment, d’un seul clic.'),
  ]);
}

/* ------------------------------------------------------------ accès ouvert */
function enabledPanel(state, reload) {
  return el('div.col', [
    state.requires_restart ? restartNotice() : null,
    el('div.phone-grid', [
      el('div.phone-qr', [
        el('div.phone-qr-frame', { html: state.qr_svg || '' }),
        el('div.phone-qr-caption', 'Scannez avec l’appareil photo'),
      ]),
      el('div.col.phone-howto', [
        el('ol.phone-steps.numbered', [
          step(null, 'Vérifiez que le téléphone est sur le même Wi-Fi que cet '
                   + 'ordinateur.'),
          step(null, 'Ouvrez l’appareil photo et visez le QR code : le lien '
                   + 'contient déjà le code d’accès.'),
          step(null, 'Sur iPhone, dans Safari : Partager › Sur l’écran d’accueil. '
                   + 'Sur Android, dans Chrome : menu ⋮ › Ajouter à l’écran '
                   + 'd’accueil.'),
        ]),
        manualBlock(state),
      ]),
    ]),
    detailsNotes(state),
    el('div.row-tight.wrap.phone-actions', [
      el('button.btn.sm', {
        onclick: () => copy(state.phone_url),
      }, [icon('link'), 'Copier le lien']),
      el('button.btn.sm', {
        onclick: async () => {
          if (!await confirmDialog(
            'Un nouveau code sera tiré au sort. Les téléphones déjà reliés '
            + 'devront rescanner le QR code pour continuer à accéder au site.',
            { title: 'Renouveler le code d’accès', danger: false,
              confirmLabel: 'Renouveler' })) return;
          try {
            await api.renewCode();
            toast('Nouveau code généré.', 'success');
            reload();
          } catch (error) { notifyError(error); }
        },
      }, [icon('refresh'), 'Renouveler le code']),
      el('button.btn.sm.danger', {
        onclick: async () => {
          if (!await confirmDialog(
            'Le site redeviendra visible uniquement depuis cet ordinateur. '
            + 'Les téléphones perdront l’accès immédiatement.',
            { title: 'Refermer l’accès réseau', confirmLabel: 'Refermer' })) return;
          try {
            await api.setNetwork(false);
            toast('Accès réseau refermé.', 'success');
            reload();
          } catch (error) { notifyError(error); }
        },
      }, [icon('close'), 'Refermer l’accès']),
    ]),
  ]);
}

function manualBlock(state) {
  return el('div.phone-manual', [
    el('div.label', 'Ou à la main, si le QR code ne passe pas'),
    el('dl.kv.phone-kv', [
      el('dt', 'Adresse'),
      el('dd', el('span.mono.phone-url', `${state.addresses[0]}:${state.port}`)),
      el('dt', 'Code d’accès'),
      el('dd', el('span.phone-code', formatCode(state.code))),
    ]),
    state.addresses.length > 1 ? el('div.faint.phone-small',
      'Cet ordinateur a plusieurs adresses réseau (Wi-Fi et câble, par '
      + 'exemple). Si la première ne répond pas, essayez : '
      + state.addresses.slice(1).map(a => `${a}:${state.port}`).join(', ')) : null,
  ]);
}

function restartNotice() {
  return el('div.alert.warning', [
    icon('alert', 'alert-icon'),
    el('div', [
      el('div.alert-title', 'Il reste une étape'),
      el('div.alert-msg',
         'L’accès est autorisé, mais le site n’écoute encore que cet ordinateur. '
         + 'Fermez la fenêtre noire, puis relancez-la en double-cliquant sur '
         + '« LANCER-SUR-LE-TELEPHONE » au lieu de « LANCER-LE-SITE ». Le QR '
         + 'code ci-dessous s’affichera aussi directement dans cette fenêtre.'),
    ]),
  ]);
}

function detailsNotes(state) {
  const notes = state.notes || {};
  return el('details.phone-details', [
    el('summary', 'Bon à savoir (sécurité, hors ligne, limites)'),
    el('div.col.phone-details-body', [
      note('Même réseau', notes.same_wifi),
      note('Sécurité', notes.security),
      note('iPhone', notes.ios),
      note('Android', notes.android),
    ]),
  ]);
}

function note(label, text) {
  if (!text) return null;
  return el('div.note-box', [el('strong', `${label} — `), text]);
}

function noNetwork() {
  return el('div.note-box', [
    el('strong', 'Aucun réseau détecté. '),
    'Cet ordinateur ne semble relié à aucun réseau local : il n’y a pas '
    + 'd’adresse à donner au téléphone. Connectez le Wi-Fi ou branchez le '
    + 'câble réseau, puis rouvrez cette page.',
  ]);
}

function step(number, text) {
  return el('li.phone-step', [
    number ? el('span.phone-step-num', number) : null,
    el('span', text),
  ]);
}

/** « 481902 » → « 481 902 » : plus facile à lire et à dicter. */
function formatCode(code) {
  if (!code) return '——————';
  return `${String(code).slice(0, 3)} ${String(code).slice(3)}`;
}

async function copy(text) {
  if (!text) return;
  try {
    // L'API presse-papiers exige un contexte sécurisé ; sur une adresse LAN
    // en HTTP elle est absente, d'où la sélection manuelle en repli.
    await navigator.clipboard.writeText(text);
    toast('Lien copié.', 'success');
  } catch {
    const node = document.querySelector('.phone-url');
    if (node) {
      const range = document.createRange();
      range.selectNodeContents(node);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      toast('Copie automatique refusée par le navigateur : l’adresse est '
            + 'sélectionnée, faites Ctrl+C.', 'info', 6000);
    }
  }
}
