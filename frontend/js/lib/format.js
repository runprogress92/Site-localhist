/**
 * Formatage localisé (fr-FR).
 *
 * Toutes les grandeurs sont stockées en unités SI côté serveur ; la
 * conversion vers l'unité d'affichage se fait ici, en un seul endroit.
 */
const LOCALE = 'fr-FR';

export function num(value, decimals = 0, fallback = '—') {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return Number(value).toLocaleString(LOCALE, {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  });
}

export function signed(value, decimals = 0, fallback = '—') {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  const formatted = num(Math.abs(value), decimals);
  return value > 0 ? `+${formatted}` : value < 0 ? `−${formatted}` : formatted;
}

export function pct(value, decimals = 0, fallback = '—') {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return `${num(value, decimals)} %`;
}

/** Durée en secondes → « 1 h 24 » ou « 42 min » ou « 3:42 ». */
// Espace insécable : « 2 h 14 » ne doit jamais se couper en fin de ligne,
// ni « 45 min » laisser son unité seule sur la ligne suivante. La typographie
// française demande une espace entre le nombre et l'unité ; l'insécable
// garde les deux ensemble.
const NB = '\u00a0';

export function duration(seconds, style = 'auto') {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
  const total = Math.round(Math.abs(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (style === 'clock') {
    return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
                 : `${m}:${String(s).padStart(2, '0')}`;
  }
  if (style === 'hm') return h > 0 ? `${h}${NB}h${NB}${String(m).padStart(2, '0')}`
                                   : `${m}${NB}min`;
  if (style === 'long') {
    if (total < 60) return `${s}${NB}s`;
    const parts = [];
    if (h) parts.push(`${h}${NB}h`);
    if (m || !h) parts.push(`${m}${NB}min`);
    return parts.join(' ');
  }
  if (h > 0) return `${h}${NB}h${NB}${String(m).padStart(2, '0')}`;
  if (m > 0) {
    return `${m}${NB}min ${s > 0 && m < 10 ? String(s).padStart(2, '0') + NB + 's' : ''}`.trim();
  }
  return `${s}${NB}s`;
}

/** Distance en mètres → km ou m selon l'échelle. */
export function distance(meters, decimals = null) {
  if (meters === null || meters === undefined || Number.isNaN(meters)) return '—';
  if (meters < 1000) return `${num(meters, 0)}${NB}m`;
  const km = meters / 1000;
  const d = decimals !== null ? decimals : (km >= 100 ? 0 : 1);
  return `${num(km, d)}${NB}km`;
}

/** Allure en secondes par kilomètre → « 4:12 /km ». */
export function pace(secondsPerKm, unit = '/km') {
  if (!secondsPerKm || secondsPerKm <= 0 || secondsPerKm > 3600) return '—';
  const total = Math.round(secondsPerKm);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}${NB}${unit}`;
}

export function speedToPace(metersPerSecond) {
  if (!metersPerSecond || metersPerSecond <= 0) return null;
  return 1000 / metersPerSecond;
}

/** Vitesse en m/s → km/h. */
export function speed(metersPerSecond, decimals = 1) {
  if (!metersPerSecond) return '—';
  return `${num(metersPerSecond * 3.6, decimals)}${NB}km/h`;
}

/** Allure de natation : secondes aux 100 m. */
export function swimPace(metersPerSecond) {
  if (!metersPerSecond || metersPerSecond <= 0) return '—';
  const total = Math.round(100 / metersPerSecond);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}${NB}/100${NB}m`;
}

export function paceForSport(sport, metersPerSecond) {
  if (!metersPerSecond) return '—';
  if (sport === 'swimming') return swimPace(metersPerSecond);
  if (sport === 'cycling' || sport === 'e_biking') return speed(metersPerSecond);
  return pace(speedToPace(metersPerSecond));
}

const MONTHS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
  'août', 'septembre', 'octobre', 'novembre', 'décembre'];
const MONTHS_SHORT = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.',
  'août', 'sept.', 'oct.', 'nov.', 'déc.'];
const DAYS = ['dimanche', 'lundi', 'mardi', 'mercredi', 'jeudi', 'vendredi', 'samedi'];
export const DAYS_SHORT = ['lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim'];

export function parseDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function date(value, style = 'short') {
  const d = parseDate(value);
  if (!d) return '—';
  if (style === 'short')   return `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
  if (style === 'medium')  return `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]} ${d.getFullYear()}`;
  if (style === 'long')    return `${d.getDate()} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  if (style === 'weekday') return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}`;
  if (style === 'iso')     return isoDate(d);
  if (style === 'month')   return `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
  if (style === 'monthShort') return `${MONTHS_SHORT[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
  return d.toLocaleDateString(LOCALE);
}

export function time(value) {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function isoDate(d = new Date()) {
  const date = d instanceof Date ? d : parseDate(d);
  if (!date) return '';
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function addDays(value, days) {
  const d = parseDate(value) || new Date();
  const copy = new Date(d);
  copy.setDate(copy.getDate() + days);
  return copy;
}

export function daysBetween(a, b) {
  const d1 = parseDate(a), d2 = parseDate(b);
  if (!d1 || !d2) return null;
  return Math.round((d2 - d1) / 86400000);
}

/** « il y a 3 jours », « demain », « dans 2 semaines ». */
export function relative(value) {
  const days = daysBetween(new Date(), value);
  if (days === null) return '—';
  if (days === 0) return "aujourd'hui";
  if (days === 1) return 'demain';
  if (days === -1) return 'hier';
  if (days < 0) {
    const n = Math.abs(days);
    if (n < 7) return `il y a ${n} jours`;
    if (n < 31) return `il y a ${Math.round(n / 7)} semaines`;
    if (n < 365) return `il y a ${Math.round(n / 30)} mois`;
    return `il y a ${Math.round(n / 365)} an${n >= 730 ? 's' : ''}`;
  }
  if (days < 7) return `dans ${days} jours`;
  if (days < 31) return `dans ${Math.round(days / 7)} semaines`;
  if (days < 365) return `dans ${Math.round(days / 30)} mois`;
  return `dans ${Math.round(days / 365)} an${days >= 730 ? 's' : ''}`;
}

export function initials(first = '', last = '') {
  return `${(first[0] || '').toUpperCase()}${(last[0] || '').toUpperCase()}`;
}

export function bytes(value) {
  if (!value) return '0 o';
  const units = ['o', 'ko', 'Mo', 'Go'];
  let i = 0, n = value;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${num(n, i === 0 ? 0 : 1)} ${units[i]}`;
}

export const SPORT_LABELS = {
  running: 'Course à pied', trail_running: 'Trail', cycling: 'Vélo',
  swimming: 'Natation', walking: 'Marche', hiking: 'Randonnée',
  rowing: 'Aviron', training: 'Cardio', strength_training: 'Musculation',
  cross_country_skiing: 'Ski de fond', e_biking: 'VAE', other: 'Autre',
};
export const sportLabel = (key) => SPORT_LABELS[key] || key || '—';

export const SPORT_ICONS = {
  running: 'activity', trail_running: 'trending', cycling: 'zap',
  swimming: 'layers', rowing: 'activity', strength_training: 'target',
};

/** Couleur associée à une valeur de TSB (forme). */
export function formColor(tsb) {
  if (tsb === null || tsb === undefined) return 'var(--text-faint)';
  if (tsb > 20) return 'var(--info)';
  if (tsb > 5) return 'var(--positive)';
  if (tsb > -12) return 'var(--text-muted)';
  if (tsb > -28) return 'var(--warning)';
  return 'var(--danger)';
}

export function readinessColor(flag) {
  return { vert: 'var(--positive)', ambre: 'var(--warning)', rouge: 'var(--danger)' }[flag]
    || 'var(--text-faint)';
}

export function acwrColor(value) {
  if (value === null || value === undefined) return 'var(--text-faint)';
  if (value > 1.5) return 'var(--danger)';
  if (value > 1.3) return 'var(--warning)';
  if (value < 0.8) return 'var(--info)';
  return 'var(--positive)';
}

export function severityColor(severity) {
  return { critical: 'var(--danger)', warning: 'var(--warning)', info: 'var(--info)' }[severity]
    || 'var(--text-faint)';
}

export const ZONE_COLORS = ['var(--z1)', 'var(--z2)', 'var(--z3)', 'var(--z4)',
  'var(--z5)', 'var(--z6)', 'var(--z7)'];
