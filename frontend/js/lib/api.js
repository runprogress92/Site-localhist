/**
 * Client HTTP de l'API.
 *
 * Un cache mémoire court (30 s) évite de refaire les mêmes requêtes en
 * naviguant entre les vues ; il est invalidé dès qu'une écriture a lieu.
 */
const CACHE_TTL = 30_000;
const cache = new Map();
const inflight = new Map();

export class ApiError extends Error {
  constructor(message, status, detail) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

function buildUrl(path, params) {
  const url = new URL(path, window.location.origin);
  for (const [key, value] of Object.entries(params || {})) {
    if (value === null || value === undefined || value === '') continue;
    url.searchParams.set(key, value);
  }
  return url.pathname + url.search;
}

async function request(method, path, { params, body, raw = false } = {}) {
  const url = buildUrl(path, params);
  const options = { method, headers: {} };
  if (body !== undefined) {
    if (body instanceof FormData) {
      options.body = body;
    } else {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
  }
  const response = await fetch(url, options);
  if (raw) {
    if (!response.ok) throw new ApiError(`HTTP ${response.status}`, response.status);
    return response;
  }
  let payload = null;
  const text = await response.text();
  if (text) {
    try { payload = JSON.parse(text); }
    catch { payload = { error: text.slice(0, 300) }; }
  }
  if (!response.ok) {
    throw new ApiError(payload?.error || `Erreur ${response.status}`,
                       response.status, payload?.detail);
  }
  return payload;
}

export async function get(path, params, { fresh = false } = {}) {
  const key = buildUrl(path, params);
  const now = Date.now();
  if (!fresh) {
    const hit = cache.get(key);
    if (hit && now - hit.at < CACHE_TTL) return hit.value;
    if (inflight.has(key)) return inflight.get(key);
  }
  const promise = request('GET', path, { params })
    .then((value) => { cache.set(key, { value, at: Date.now() }); return value; })
    .finally(() => inflight.delete(key));
  inflight.set(key, promise);
  return promise;
}

function mutate(method) {
  return async (path, body, params) => {
    const result = await request(method, path, { body, params });
    cache.clear();
    return result;
  };
}

export const post = mutate('POST');
export const patch = mutate('PATCH');
export const put = mutate('PUT');
export const del = mutate('DELETE');

export async function upload(path, files, params) {
  const form = new FormData();
  for (const file of files) form.append('file', file, file.name);
  const result = await request('POST', path, { body: form, params });
  cache.clear();
  return result;
}

export function download(path, params) {
  window.location.href = buildUrl(path, params);
}

export function invalidate() { cache.clear(); }

/* ------------------------------------------------------- points d'entrée */
export const api = {
  health:        () => get('/api/health', null, { fresh: true }),
  config:        () => get('/api/config'),
  updateConfig:  (body) => patch('/api/config', body),
  stats:         () => get('/api/admin/stats', null, { fresh: true }),

  athletes:      (params) => get('/api/athletes', params),
  athlete:       (id) => get(`/api/athletes/${id}`),
  createAthlete: (body) => post('/api/athletes', body),
  updateAthlete: (id, body) => patch(`/api/athletes/${id}`, body),
  deleteAthlete: (id, hard) => del(`/api/athletes/${id}`, null, { hard }),
  summary:       (id, days) => get(`/api/athletes/${id}/summary`, { days }),
  zones:         (id, date) => get(`/api/athletes/${id}/zones`, { date }),
  zoneModel:     (id, kind, model) => get(`/api/athletes/${id}/zones/${kind}`, { model }),
  addPhysiology: (id, body) => post(`/api/athletes/${id}/physiology`, body),
  powerCurve:    (id, params) => get(`/api/athletes/${id}/power-curve`, params),
  records:       (id, kind) => get(`/api/athletes/${id}/records`, { kind }),
  progression:   (id, months) => get(`/api/athletes/${id}/progression`, { months }),
  pmc:           (id, params) => get(`/api/athletes/${id}/pmc`, params),
  loadBreakdown: (id, params) => get(`/api/athletes/${id}/load`, params),
  calendar:      (id, params) => get(`/api/athletes/${id}/calendar`, params),
  zoneDist:      (id, params) => get(`/api/athletes/${id}/zone-distribution`, params),
  estimates:     (id) => get(`/api/athletes/${id}/estimates`),
  predictions:   (id, params) => get(`/api/athletes/${id}/predictions`, params),
  fueling:       (id, params) => get(`/api/athletes/${id}/fueling`, params),

  activities:    (params) => get('/api/activities', params),
  activity:      (id) => get(`/api/activities/${id}`),
  streams:       (id, params) => get(`/api/activities/${id}/streams`, params),
  updateActivity: (id, body) => patch(`/api/activities/${id}`, body),
  deleteActivity: (id) => del(`/api/activities/${id}`),
  reanalyze:     (id) => post(`/api/activities/${id}/reanalyze`),
  uploadFiles:   (athleteId, files) => upload('/api/activities/upload', files,
                                              { athlete_id: athleteId }),

  wellness:      (id, params) => get(`/api/athletes/${id}/wellness`, params),
  saveWellness:  (id, body) => post(`/api/athletes/${id}/wellness`, body),
  readiness:     (id, date) => get(`/api/athletes/${id}/readiness`, { date }),
  hrv:           (id, days) => get(`/api/athletes/${id}/hrv`, { days }),
  wellnessToday: (date) => get('/api/wellness/today', { date }),

  teamOverview:  () => get('/api/team/overview'),
  teamMatrix:    (days) => get('/api/team/matrix', { days }),
  compare:       (params) => get('/api/compare', params),
  search:        (q) => get('/api/search', { q }),

  planned:       (id, params) => get(`/api/athletes/${id}/planned`, params),
  createPlanned: (id, body) => post(`/api/athletes/${id}/planned`, body),
  updatePlanned: (id, body) => patch(`/api/planned/${id}`, body),
  deletePlanned: (id) => del(`/api/planned/${id}`),
  matchPlanned:  (id) => post(`/api/athletes/${id}/planned/match`),
  generateWeek:  (id, body) => post(`/api/athletes/${id}/planned/generate`, body),
  compliance:    (id, weeks) => get(`/api/athletes/${id}/compliance`, { weeks }),
  blocks:        (id) => get(`/api/athletes/${id}/blocks`),
  createBlock:   (id, body) => post(`/api/athletes/${id}/blocks`, body),
  events:        (id) => get(`/api/athletes/${id}/events`),
  createEvent:   (id, body) => post(`/api/athletes/${id}/events`, body),
  updateEvent:   (id, body) => patch(`/api/events/${id}`, body),
  deleteEvent:   (id) => del(`/api/events/${id}`),
  taper:         (id, params) => get(`/api/athletes/${id}/taper`, params),

  tests:         (id) => get(`/api/athletes/${id}/tests`),
  createTest:    (id, body) => post(`/api/athletes/${id}/tests`, body),
  testAnalysis:  (id) => get(`/api/tests/${id}/analysis`),
  deleteTest:    (id) => del(`/api/tests/${id}`),

  notes:         (id) => get(`/api/athletes/${id}/notes`),
  addNote:       (id, body) => post(`/api/athletes/${id}/notes`, body),
  deleteNote:    (id) => del(`/api/notes/${id}`),
  injuries:      (id) => get(`/api/athletes/${id}/injuries`),
  addInjury:     (id, body) => post(`/api/athletes/${id}/injuries`, body),
  updateInjury:  (id, body) => patch(`/api/injuries/${id}`, body),
  ackAlert:      (id) => post(`/api/alerts/${id}/acknowledge`),

  providers:     () => get('/api/devices/providers', null, { fresh: true }),
  saveProvider:  (key, body) => post(`/api/devices/${key}/config`, body),
  authorizeUrl:  (key, athleteId) => get(`/api/devices/${key}/authorize`,
                                         { athlete_id: athleteId, json: true },
                                         { fresh: true }),
  sync:          (key, params) => post(`/api/devices/${key}/sync`, {}, params),
  disconnect:    (key, athleteId) => del(`/api/devices/${key}/accounts/${athleteId}`),
  syncLog:       (limit) => get('/api/devices/sync-log', { limit }, { fresh: true }),
  hardware:      () => get('/api/devices/hardware'),

  teams:         () => get('/api/teams'),
  createTeam:    (body) => post('/api/teams', body),
  rebuild:       (body) => post('/api/admin/rebuild', body || {}),
  seedDemo:      (body) => post('/api/admin/seed', body),
  resetAll:      () => del('/api/admin/reset', null, { confirm: true }),
};
