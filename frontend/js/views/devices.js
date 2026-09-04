/**
 * Connexions aux montres : Garmin, Polar, COROS.
 *
 * La page dit clairement ce qui fonctionne sans clé d'API (l'import de
 * fichiers, qui couvre les trois marques) et ce que la connexion directe
 * apporte en plus.
 */
import { api } from '../lib/api.js';
import { clear, el, icon, mount } from '../lib/dom.js';
import * as F from '../lib/format.js';
import { navigate } from '../lib/router.js';
import { store } from '../lib/store.js';
import {
  avatar, card, dataTable, field, input, modal, notifyError, pageTitle,
  select, setTopbar, statTile, toast,
} from '../lib/ui.js';
import { openUpload } from './athlete.js';

const STATUS_LABELS = {
  connected: 'relié', expired: 'jeton expiré', error: 'en erreur',
  disconnected: 'non relié', pending: 'autorisation en cours',
};

export async function render(root, context) {
  const [providers, log, hardware] = await Promise.all([
    api.providers(), api.syncLog(25), api.hardware(),
  ]);
  if (context.token.stale) return;

  setTopbar(pageTitle('Montres et connexions',
    'Garmin · Polar · COROS — synchronisation directe ou import de fichiers'));

  const connected = providers.providers.reduce((s, p) => s + p.connected_count, 0);
  const configured = providers.providers.filter(p => p.configured).length;

  mount(root, [
    el('div.grid.grid-4.section', [
      statTile('Comptes reliés', String(connected), {
        sub: `sur ${store.athletes.length} athlètes`, tone: connected ? 'pos' : 'plain' }),
      statTile('Connecteurs configurés', `${configured}/3`, {
        sub: 'clés d’application enregistrées', tone: 'plain' }),
      statTile('Montres identifiées', String(hardware.devices.length), {
        sub: 'depuis les fichiers importés', tone: 'plain' }),
      statTile('Dernière synchronisation',
        log.log.length ? F.relative(log.log[0].started_at) : '—', {
        sub: log.log.length ? log.log[0].message?.slice(0, 40) : 'aucune', tone: 'plain' }),
    ]),

    card('Import de fichiers — fonctionne immédiatement', el('div', [
      el('p.muted', providers.file_import.note),
      el('div.grid.grid-3', { style: { marginTop: 'var(--sp-4)' } }, [
        exportHowTo('Garmin', 'Garmin Connect → une activité → menu ⋯ → '
          + '« Exporter le fichier d’origine » (.fit).'),
        exportHowTo('Polar', 'Polar Flow → une séance → « Exporter la session » '
          + '→ TCX ou GPX. L’export global est disponible dans les réglages du compte.'),
        exportHowTo('COROS', 'Application COROS ou coros.com → une activité → '
          + '« Exporter » → FIT, TCX ou GPX.'),
      ]),
      el('div.row-tight', { style: { marginTop: 'var(--sp-4)' } }, [
        el('button.btn.primary', {
          onclick: () => {
            if (!store.athletes.length) { toast('Créez d’abord un athlète.', 'error'); return; }
            openUpload(store.athletes[0].id, () => render(root, context));
          },
        }, [icon('upload'), 'Importer des fichiers']),
        el('span.faint', { style: { fontSize: 'var(--fs-sm)' } },
           'formats acceptés : ' + providers.file_import.formats.join(', ')),
      ]),
    ]), { subtitle: 'aucune clé d’API requise, aucune donnée ne quitte votre machine',
          className: 'section' }),

    el('section.section', [
      el('div.section-head', [
        el('div', [
          el('div.section-title', 'Synchronisation directe'),
          el('div.section-sub', 'Les trois marques exigent un compte développeur. '
            + 'Une fois les identifiants renseignés, chaque athlète autorise l’accès '
            + 'depuis sa fiche et les séances arrivent automatiquement.'),
        ]),
      ]),
      el('div.col', { style: { gap: 'var(--sp-4)' } },
        providers.providers.map(provider =>
          providerCard(provider, providers.base_url, () => render(root, context)))),
    ]),

    hardware.devices.length ? card('Matériel détecté', dataTable({
      columns: [
        { label: 'Athlète', render: (row) => row.athlete
            ? el('div.row-tight', [avatar(row.athlete, 'sm'),
                `${row.athlete.first_name} ${row.athlete.last_name}`]) : '—' },
        { label: 'Appareil', render: (row) => el('span', row.device_name) },
        { label: 'Source', render: (row) => el('span.badge', row.provider) },
        { label: 'Séances', numeric: true,
          render: (row) => el('span.mono', F.num(row.sessions)) },
        { label: 'Dernière utilisation', render: (row) =>
            el('span.muted', F.relative(row.last_seen)) },
      ],
      rows: hardware.devices,
    }), { flush: true, className: 'section',
          subtitle: 'identifié à partir des métadonnées des fichiers importés' }) : null,

    card('Journal des synchronisations', log.log.length ? dataTable({
      columns: [
        { label: 'Date', render: (row) => el('span.mono', F.date(row.started_at, 'medium')
            + ' ' + F.time(row.started_at)) },
        { label: 'Connecteur', render: (row) => el('span.badge', row.provider) },
        { label: 'Athlète', render: (row) => row.first_name
            ? `${row.first_name} ${row.last_name}` : '—' },
        { label: 'Statut', render: (row) => el(
            `span.badge${row.status === 'ok' ? '.pos' : row.status === 'error' ? '.neg' : '.warn'}`,
            row.status) },
        { label: 'Importées', numeric: true,
          render: (row) => el('span.mono', String(row.imported || 0)) },
        { label: 'Détail', render: (row) => el('span.muted.truncate',
            { style: { maxWidth: '380px' } }, row.message || '') },
      ],
      rows: log.log,
    }) : el('div.muted', 'Aucune synchronisation enregistrée.'),
      { flush: !!log.log.length, className: 'section' }),
  ]);
}

function exportHowTo(brand, text) {
  return el('div', [
    el('div', { style: { fontWeight: 600, marginBottom: '4px' } }, brand),
    el('div.muted', { style: { fontSize: 'var(--fs-sm)', lineHeight: '1.6' } }, text),
  ]);
}

function providerCard(provider, baseUrl, reload) {
  const help = provider.help || {};
  return el('div.provider-card', [
    el('div.provider-head', [
      el('div.provider-logo', { style: { background: provider.color } },
         provider.label.slice(0, 2).toUpperCase()),
      el('div', { style: { flex: 1 } }, [
        el('div', { style: { fontWeight: 620, fontSize: 'var(--fs-md)' } }, provider.label),
        el('div.faint', { style: { fontSize: 'var(--fs-sm)' } },
           `${provider.auth_kind === 'oauth1' ? 'OAuth 1.0a' : 'OAuth 2.0'}`
           + `${provider.supports_push ? ' · notifications push' : ''}`),
      ]),
      provider.configured
        ? el('span.badge.pos', [el('span.dot'), `${provider.connected_count} relié(s)`])
        : el('span.badge', 'non configuré'),
      el('button.btn.sm', { onclick: () => openConfig(provider, reload) },
         [icon('settings'), 'Identifiants']),
    ]),
    el('div.provider-body', [
      help.steps ? el('div.provider-steps',
        help.steps.map(step => el('div.provider-step', step))) : null,
      help.note ? el('div.note-box', help.note) : null,

      el('div.col', { style: { gap: 'var(--sp-2)', marginTop: 'var(--sp-4)' } }, [
        el('div.label', 'URL à déclarer dans la console développeur'),
        urlBox('Redirection OAuth', provider.redirect_uri),
        provider.supports_push ? urlBox('Notifications push', provider.webhook_url) : null,
        el('div.field-hint',
          'Ces URL pointent vers votre machine. Elles conviennent tant que la console '
          + 'du fabricant accepte « localhost » ; sinon, exposez temporairement le port '
          + 'le temps de l’autorisation.'),
      ]),

      provider.accounts.length ? el('div', { style: { marginTop: 'var(--sp-4)' } }, [
        el('div.label', { style: { marginBottom: 'var(--sp-2)' } }, 'Comptes reliés'),
        el('div.col', { style: { gap: 'var(--sp-2)' } }, provider.accounts.map(account =>
          el('div.between', [
            el('div.row-tight', [
              el('span.dot', { style: { width: '7px', height: '7px', borderRadius: '50%',
                background: account.status === 'connected'
                            ? (account.has_token ? 'var(--positive)' : 'var(--text-faint)')
                          : account.status === 'expired' ? 'var(--warning)'
                          : 'var(--danger)' } }),
              el('span', `${account.first_name} ${account.last_name}`),
              el('span.badge', STATUS_LABELS[account.status] || account.status),
              account.status === 'connected' && !account.has_token
                ? el('span.badge.warn', {
                    title: 'Compte du jeu de démonstration : aucun jeton d’accès réel '
                         + 'n’est enregistré, la synchronisation renverra une erreur.',
                  }, 'démonstration') : null,
            ]),
            el('div.row-tight', [
              el('span.faint', { style: { fontSize: '11px' } },
                 account.last_sync_at ? F.relative(account.last_sync_at) : 'jamais synchronisé'),
              el('button.btn.sm.ghost', {
                onclick: async () => {
                  try {
                    const result = await api.sync(provider.key,
                                                  { athlete_id: account.athlete_id, days: 30 });
                    const outcome = Object.values(result.results)[0];
                    toast(outcome.message || outcome.status,
                          outcome.status === 'error' ? 'error' : 'success');
                    reload();
                  } catch (error) { notifyError(error); }
                },
              }, [icon('refresh'), 'Synchroniser']),
              el('button.btn.sm.ghost', {
                onclick: async () => {
                  await api.disconnect(provider.key, account.athlete_id);
                  toast('Compte délié.', 'success');
                  reload();
                }, title: 'Délier',
              }, [icon('close')]),
            ]),
          ]))),
      ]) : null,

      el('div.row-tight', { style: { marginTop: 'var(--sp-4)' } }, [
        el('button.btn.sm.primary', {
          disabled: !provider.configured,
          title: provider.configured ? '' : 'Renseignez d’abord les identifiants',
          onclick: () => openConnect(provider, reload),
        }, [icon('link'), 'Relier un athlète']),
        el('a.btn.sm.ghost', { href: provider.doc_url, target: '_blank', rel: 'noopener' },
           [icon('file'), 'Documentation officielle']),
      ]),
    ]),
  ]);
}

function urlBox(label, url) {
  return el('div.row-tight', [
    el('span.faint', { style: { fontSize: '11px', minWidth: '132px' } }, label),
    el('div.url-box', { style: { flex: 1 } }, [
      el('code', url),
      el('button.btn.ghost.icon', {
        title: 'Copier',
        onclick: async (e) => {
          try {
            await navigator.clipboard.writeText(url);
            toast('URL copiée.', 'success');
          } catch { toast('Copie impossible dans ce navigateur.', 'error'); }
        },
      }, [icon('clipboard')]),
    ]),
  ]);
}

function openConfig(provider, reload) {
  const values = {};
  modal({
    title: `Identifiants d’application — ${provider.label}`,
    body: el('div.col', [
      el('div.note-box', 'Ces identifiants restent stockés dans la base locale du '
        + 'projet, sur votre machine. Ils ne sont jamais transmis ailleurs qu’au '
        + 'serveur d’authentification du fabricant.'),
      field(provider.auth_kind === 'oauth1' ? 'Consumer Key' : 'Client ID',
        input({ onchange: (e) => { values.client_id = e.target.value.trim(); } })),
      field(provider.auth_kind === 'oauth1' ? 'Consumer Secret' : 'Client Secret',
        input({ type: 'password',
                onchange: (e) => { values.client_secret = e.target.value.trim(); } })),
      field('URL de redirection', input({ value: provider.redirect_uri,
        onchange: (e) => { values.redirect_uri = e.target.value.trim(); } }),
        'Doit correspondre exactement à celle déclarée dans la console du fabricant.'),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Enregistrer', primary: true, onClick: async () => {
          if (!values.client_id || !values.client_secret) {
            toast('Les deux identifiants sont nécessaires.', 'error');
            return false;
          }
          await api.saveProvider(provider.key, values);
          toast(`${provider.label} configuré.`, 'success');
          reload();
        } },
    ],
  });
}

function openConnect(provider, reload) {
  let athleteId = store.athletes[0]?.id;
  modal({
    title: `Relier un athlète à ${provider.label}`,
    body: el('div.col', [
      field('Athlète', select(store.athletes.map(a => ({
        value: a.id, label: `${a.first_name} ${a.last_name}` })),
        { onchange: (e) => { athleteId = Number(e.target.value); } })),
      el('div.note-box', 'Une fenêtre du fabricant va s’ouvrir pour que l’athlète '
        + 'autorise l’accès à ses données. Le jeton obtenu est stocké localement ; '
        + 'vous pourrez le révoquer à tout moment depuis cette page.'),
    ]),
    actions: [
      { label: 'Annuler', onClick: () => {} },
      { label: 'Ouvrir l’autorisation', primary: true, onClick: async () => {
          try {
            const result = await api.authorizeUrl(provider.key, athleteId);
            window.open(result.authorize_url, 'athlytics-oauth',
                        'width=620,height=760');
            toast('Terminez l’autorisation dans la fenêtre ouverte.', 'info');
            setTimeout(reload, 8000);
          } catch (error) { notifyError(error); return false; }
        } },
    ],
  });
}
