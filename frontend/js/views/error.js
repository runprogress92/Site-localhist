import { el, mount } from '../lib/dom.js';
import { emptyState, setTopbar } from '../lib/ui.js';

export function renderError(error) {
  setTopbar([el('h1', 'Erreur')]);
  mount(document.getElementById('content'), emptyState(
    'Une erreur est survenue',
    error?.message || 'Erreur inconnue.',
    el('button.btn', { onclick: () => window.location.reload() }, 'Recharger la page'),
    'alert'));
}
export const render = renderError;
