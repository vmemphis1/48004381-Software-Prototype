import { qs, toast, el } from './dom.js';
import { api } from './api.js';
import { closeInspector } from './inspector.js';

import * as ask from './views/ask.js';
import * as builder from './views/builder.js';
import * as graph from './views/graph.js';
import * as schema from './views/schema.js';
import * as documents from './views/documents.js';

const ROUTES = [
  { id: 'ask', label: 'Explore', view: ask },
  { id: 'build', label: 'Build', view: builder },
  { id: 'graph', label: 'Graph', view: graph },
  { id: 'schema', label: 'Schema', view: schema },
  { id: 'corpus', label: 'Corpus', view: documents },
];

/** Parse the current URL hash into a route and parameters. */
function parseHash() {
  const raw = window.location.hash.replace(/^#\/?/, '') || 'ask';
  const [id, query] = raw.split('?');
  return { id: id || 'ask', params: Object.fromEntries(new URLSearchParams(query || '')) };
}

let navigation = 0;

/** Render the view selected by the current route. */
async function route() {
  const current = ++navigation;
  const { id, params } = parseHash();
  const entry = ROUTES.find((r) => r.id === id);
  if (!entry) {
    window.location.hash = '#/ask';
    return;
  }
  qs('#tabs').querySelectorAll('button').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.route === entry.id);
  });
  graph.dispose();
  closeInspector();
  const view = qs('#view');
  view.scrollTop = 0;
  try {
    await entry.view.render(view, params);
  } catch (error) {
    if (current !== navigation) return;
    view.replaceChildren(el('div', { class: 'page' },
      el('div', { class: 'banner danger' }, `${entry.label} failed to render: ${error.message}`)));
    console.error(error);
  }
}

/** Build the navigation tabs. */
function buildTabs() {
  const tabs = qs('#tabs');
  for (const entry of ROUTES) {
    tabs.append(el('button', {
      dataset: { route: entry.id },
      onclick: () => { window.location.hash = `#/${entry.id}`; },
    }, entry.label));
  }
}

/** Refresh the server status and stale-code warning. */
async function refreshStatus() {
  const status = await api.status();
  if (status.integrity?.length) {
    toast(`Integrity warning: ${status.integrity[0]}`, 6000);
  }


  if (status.staleSource?.length) {
    const note = qs('#status-note');
    note.hidden = false;
    note.textContent = 'Restart required — server is running old code';
    note.title =
      `Changed since this server started: ${status.staleSource.join(', ')}.\n`
      + 'The Turtle files reload automatically; this server\'s Python does not.\n'
      + 'Stop it with Ctrl-C and run explorer/run.sh again.';
    toast('This server is running older code than the files on disk. '
      + 'Restart it (Ctrl-C, then explorer/run.sh) before trusting what you see.', 12000);
  } else {
    qs('#status-note').hidden = true;
  }
}

/** Initialize the explorer and route the first view. */
async function boot() {
  buildTabs();

  qs('#reload').addEventListener('click', async () => {
    qs('#reload').disabled = true;
    try {
      await api.reload();
      await refreshStatus();
      await route();
      toast('Reloaded from disk.');
    } catch (error) {
      toast(`Reload failed: ${error.message}`, 5000);
    } finally {
      qs('#reload').disabled = false;
    }
  });

  await refreshStatus();
  window.addEventListener('hashchange', route);
  await route();
}

boot().catch((error) => {
  qs('#view').replaceChildren(el('div', { class: 'page' },
    el('div', { class: 'banner danger' },
      `The explorer could not start: ${error.message}. Is the server still running?`)));
});
