/**
 * Détection du format d'affichage.
 *
 * Une seule source de vérité, partagée par le CSS (points de rupture) et le
 * JavaScript (choix d'un tableau ou de cartes, infobulle au survol ou au
 * toucher). Les deux doivent basculer au même pixel, sinon on obtient des
 * états intermédiaires incohérents — un tableau mobile dans une mise en
 * page de bureau, par exemple.
 */
const BREAKPOINT_MOBILE = 820;   // identique à layout.css et mobile.css
const BREAKPOINT_COMPACT = 1180;

const listeners = new Set();

export const viewport = {
  width: window.innerWidth,
  height: window.innerHeight,
  isMobile: window.innerWidth <= BREAKPOINT_MOBILE,
  isCompact: window.innerWidth <= BREAKPOINT_COMPACT,
  /** Appareil tactile : décide infobulle au survol ou au toucher. */
  isTouch: window.matchMedia('(hover: none)').matches
           || navigator.maxTouchPoints > 0,
  /** Application lancée depuis l'écran d'accueil (mode autonome). */
  isStandalone: window.matchMedia('(display-mode: standalone)').matches
                || window.navigator.standalone === true,
};

function measure() {
  const wasMobile = viewport.isMobile;
  viewport.width = window.innerWidth;
  viewport.height = window.innerHeight;
  viewport.isMobile = window.innerWidth <= BREAKPOINT_MOBILE;
  viewport.isCompact = window.innerWidth <= BREAKPOINT_COMPACT;
  if (wasMobile !== viewport.isMobile) {
    listeners.forEach(fn => fn(viewport));
  }
}

let timer;
window.addEventListener('resize', () => {
  clearTimeout(timer);
  timer = setTimeout(measure, 150);
});
window.addEventListener('orientationchange', () => setTimeout(measure, 250));

/** Prévient uniquement lors d'un *changement* de format, pas à chaque pixel. */
export function onLayoutChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * Hauteur réelle de la fenêtre, exposée en variable CSS.
 *
 * Sur iOS, `100vh` inclut la barre d'adresse de Safari, qui se rétracte au
 * défilement : une mise en page calée sur `100vh` déborde donc toujours un
 * peu. `--vh` donne la hauteur effectivement visible.
 */
function setViewportHeight() {
  document.documentElement.style.setProperty('--vh', `${window.innerHeight * 0.01}px`);
}
setViewportHeight();
window.addEventListener('resize', setViewportHeight);
window.addEventListener('orientationchange', () => setTimeout(setViewportHeight, 250));

if (viewport.isTouch) document.documentElement.classList.add('touch');
if (viewport.isStandalone) document.documentElement.classList.add('standalone');
