/**
 * Intégration « application » : installation, hors-ligne, mise à jour.
 *
 * Trois comportements qu'un site n'a pas et qu'une application doit avoir :
 * pouvoir s'installer sur l'écran d'accueil, dire clairement quand les
 * données affichées ne sont plus fraîches, et se mettre à jour sans que
 * l'utilisateur ait à vider quoi que ce soit.
 */
import { el, icon, mount } from './dom.js';
import { toast } from './ui.js';
import { viewport } from './viewport.js';

let deferredPrompt = null;
let registration = null;

/* --------------------------------------------------------- enregistrement */
export async function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return null;
  // Un service worker exige une origine sûre. Consulté depuis un téléphone
  // via l'adresse locale du PC en HTTP, l'enregistrement échouerait ; on
  // n'essaie même pas, pour ne pas polluer la console.
  if (!window.isSecureContext) {
    document.documentElement.classList.add('no-sw');
    return null;
  }
  try {
    registration = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
    registration.addEventListener('updatefound', () => {
      const incoming = registration.installing;
      if (!incoming) return;
      incoming.addEventListener('statechange', () => {
        // Un nouveau worker « installé » alors qu'un autre contrôle déjà la
        // page : c'est une mise à jour, pas une première installation.
        if (incoming.state === 'installed' && navigator.serviceWorker.controller) {
          showUpdateBanner();
        }
      });
    });
    return registration;
  } catch (error) {
    console.warn('Service worker non enregistré :', error.message);
    return null;
  }
}

function showUpdateBanner() {
  const banner = el('div.install-banner', [
    el('div.install-banner-text', [
      el('strong', 'Nouvelle version disponible'),
      el('span.muted', 'Rechargez pour en profiter.'),
    ]),
    el('button.btn.sm.primary', {
      onclick: () => {
        registration?.waiting?.postMessage('skip-waiting');
        window.location.reload();
      },
    }, 'Recharger'),
    el('button.btn.sm.ghost.icon', {
      onclick: () => banner.remove(), 'aria-label': 'Plus tard',
    }, [icon('close')]),
  ]);
  document.body.appendChild(banner);
}

/* ---------------------------------------------------------- installation */
export function watchInstallPrompt() {
  window.addEventListener('beforeinstallprompt', (event) => {
    // Chrome propose sa propre barre : on la retient pour déclencher
    // l'installation depuis notre interface, au bon moment.
    event.preventDefault();
    deferredPrompt = event;
    document.documentElement.classList.add('installable');
  });
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    document.documentElement.classList.remove('installable');
    toast('Athlytics est installé sur votre écran d’accueil.', 'success');
  });
}

export const canInstall = () => deferredPrompt !== null;

export async function promptInstall() {
  if (!deferredPrompt) return 'unavailable';
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  deferredPrompt = null;
  return outcome;
}

/** iOS n'expose aucune API d'installation : il faut décrire le geste. */
export function isIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}

/* ------------------------------------------------------------- hors ligne */
let offlineBanner = null;

export function watchConnection() {
  const update = () => {
    if (navigator.onLine) hideOfflineBanner();
    else showOfflineBanner();
  };
  window.addEventListener('online', update);
  window.addEventListener('offline', update);
  update();
}

function showOfflineBanner() {
  if (offlineBanner) return;
  offlineBanner = el('div.offline-bar', [
    icon('alert'),
    el('span', 'Hors ligne — les chiffres affichés datent de la dernière '
             + 'connexion, et rien ne peut être enregistré.'),
  ]);
  document.body.appendChild(offlineBanner);
  document.documentElement.classList.add('offline');
}

function hideOfflineBanner() {
  if (!offlineBanner) return;
  offlineBanner.remove();
  offlineBanner = null;
  document.documentElement.classList.remove('offline');
}

/**
 * Bandeau proposant l'installation.
 *
 * Il n'apparaît qu'au bout de trois visites : proposer d'installer une
 * application qu'on découvre est le meilleur moyen de se faire refuser.
 * Un refus est mémorisé trente jours.
 */
export function maybeOfferInstall() {
  if (viewport.isStandalone) return;
  if (!viewport.isMobile) return;

  const dismissed = Number(localStorage.getItem('athlytics.install.dismissed') || 0);
  if (Date.now() - dismissed < 30 * 86400_000) return;

  const visits = Number(localStorage.getItem('athlytics.visits') || 0) + 1;
  localStorage.setItem('athlytics.visits', String(visits));
  if (visits < 3) return;

  const ios = isIOS();
  if (!ios && !canInstall()) return;

  setTimeout(() => {
    const banner = el('div.install-banner', [
      el('img', { src: '/assets/icons/icon-192.png', width: 38, height: 38,
                  alt: '', style: { borderRadius: '9px' } }),
      el('div.install-banner-text', [
        el('strong', 'Installer Athlytics'),
        el('span.muted', ios
          ? 'Appuyez sur Partager, puis « Sur l’écran d’accueil ».'
          : 'Un accès direct, en plein écran, depuis votre écran d’accueil.'),
      ]),
      ios ? null : el('button.btn.sm.primary', {
        onclick: async () => { await promptInstall(); banner.remove(); },
      }, 'Installer'),
      el('button.btn.sm.ghost.icon', {
        onclick: () => {
          localStorage.setItem('athlytics.install.dismissed', String(Date.now()));
          banner.remove();
        },
        'aria-label': 'Ne plus proposer',
      }, [icon('close')]),
    ]);
    document.body.appendChild(banner);
  }, 4000);
}

export function initPwa() {
  registerServiceWorker();
  watchInstallPrompt();
  watchConnection();
  maybeOfferInstall();
}
