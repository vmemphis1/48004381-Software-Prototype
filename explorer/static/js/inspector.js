import { el, clear, qs, truncate, toast } from './dom.js';
import { api, docUrl } from './api.js';
import { openDocument } from './viewer.js';

/** Find the resource inspector panel. */
const panel = () => qs('#inspector');
let current = null;

/** Close the resource inspector. */
export function closeInspector() {
  panel().hidden = true;
  current = null;
}

/** Load and display a resource and its evidence. */
export async function openInspector(iri, { scrollTo } = {}) {
  const node = panel();
  node.hidden = false;
  current = iri;
  qs('#inspector-title').replaceChildren(el('h3', {}, 'Loading…'));
  clear(qs('#inspector-body'));

  let resource;
  try {
    resource = await api.resource(iri);
  } catch (error) {
    if (current !== iri) return;
    qs('#inspector-body').replaceChildren(
      el('div', { class: 'banner danger' }, String(error.message)));
    return;
  }
  if (current !== iri) return;

  qs('#inspector-title').replaceChildren(
    el('div', {},
      el('h3', {}, resource.label),
      el('code', { class: 'curie' }, resource.curie)),
  );

  const body = clear(qs('#inspector-body'));

  if (resource.types.length) {
    body.append(section('Type', el('div', { class: 'type-tags' },
      resource.types.map((type) => el('button', {
        class: 'iri-link',
        onclick: () => openInspector(type.value),
      }, type.label || type.curie)))));
  }

  if (resource.comment || resource.definition) {
    body.append(section('Definition',
      el('p', { style: 'margin:0;font-size:12.5px;line-height:1.55;color:var(--text-2)' },
        resource.comment || resource.definition)));
  }

  if (resource.document) body.append(documentSection(resource.document));
  if (resource.evidence.length) body.append(evidenceSection(resource.evidence));
  if (resource.relatedEvidence?.length) {
    body.append(section(
      'Evidence on linked statements',
      el('div', {},
        el('p', { class: 'muted', style: 'font-size:11.5px;margin:0 0 9px' },
          'Nothing is recorded directly against this resource. These snippets support '
          + 'statements it is directly linked to.'),
        ...resource.relatedEvidence.map((snippet) => snippetCard(snippet)))));
  }

  if (resource.outgoing.length) {
    body.append(section(
      resource.isClass ? 'Axioms and annotations' : 'Properties',
      linkList(resource.outgoing, 'values')));
  }
  if (resource.incoming.length) {
    body.append(section('Referenced by', linkList(resource.incoming, 'values', true)));
  }

  body.append(section('Explore', el('div', { class: 'snippet-actions' },
    el('button', {
      class: 'ghost-btn',
      onclick: () => { window.location.hash = `#/graph?focus=${encodeURIComponent(iri)}`; },
    }, 'Centre in graph'),
    el('button', {
      class: 'ghost-btn',
      onclick: () => navigator.clipboard.writeText(iri).then(() => toast('IRI copied')),
    }, 'Copy IRI'),
  )));

  if (scrollTo === 'evidence') {
    body.querySelector('.snippet')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
}

/** Build a labeled inspector section. */
function section(title, content) {
  return el('div', { class: 'ins-section' }, el('h4', {}, title), content);
}

/** Build the inspector section for a source document. */
function documentSection(doc) {
  const size = doc.sizeBytes ? `${(doc.sizeBytes / 1048576).toFixed(1)} MB` : '—';
  const list = el('dl', { class: 'kv' });

  /** Add an item to the current view. */
  const add = (key, value) => { list.append(el('dt', {}, key), el('dd', {}, value)); };
  add('type', doc.documentType || '—');
  add('date', doc.documentDate || '—');
  add('retrieved', doc.retrievalDate || '—');
  add('archived', doc.exists
    ? el('span', {}, el('code', { class: 'curie' }, doc.localPath), ` · ${size}`)
    : el('span', {}, 'file missing from corpus/'));
  if (doc.sha256) add('sha-256', el('code', { class: 'curie', title: doc.sha256 }, `${doc.sha256.slice(0, 16)}…`));

  const actions = el('div', { class: 'snippet-actions' });
  if (doc.exists) {
    actions.append(el('button', {
      class: 'primary-btn',
      onclick: () => openDocument(doc),
    }, 'Preview archived copy'));
  }
  if (doc.documentURL) {
    actions.append(el('a', {
      class: 'ghost-btn', href: doc.documentURL, target: '_blank', rel: 'noopener',
    }, 'Official source ↗'));
  }
  return section('Source document', el('div', {}, list, actions));
}

/** Build the inspector section for evidence snippets. */
function evidenceSection(snippets) {
  const wrap = el('div', {});
  for (const snippet of snippets) wrap.append(snippetCard(snippet));
  return section('Evidence', wrap);
}

/** Build an evidence snippet card. */
function snippetCard(snippet) {
  {
    const meta = el('div', { class: 'snippet-meta' });
    if (snippet.document) {
      meta.append(el('span', {}, snippet.document.label));
    }
    if (snippet.pageReference) meta.append(el('span', {}, '·'), el('span', {}, snippet.pageReference));
    if (snippet.sectionReference) meta.append(el('span', {}, '·'), el('em', {}, snippet.sectionReference));

    const actions = el('div', { class: 'snippet-actions' });
    if (snippet.document?.exists) {
      actions.append(el('button', {
        class: 'primary-btn',
        onclick: () => openDocument(snippet.document, {
          page: snippet.pdfPage,
          quote: snippet.exactText,
          caption: snippet.pageReference,
        }),
      }, snippet.pdfPage ? `Open at page ${snippet.pdfPage}` : 'Open document'));
    }
    if (snippet.document?.documentURL) {
      actions.append(el('a', {
        class: 'ghost-btn', href: snippet.document.documentURL, target: '_blank', rel: 'noopener',
      }, 'Official source ↗'));
    }

    return el('div', { class: 'snippet' },
      snippet.viaLabel
        ? el('div', { class: 'snippet-meta', style: 'margin-bottom:7px' },
            el('span', {}, 'via'),
            el('button', {
              class: 'iri-link', style: 'font-size:11.5px',
              onclick: () => openInspector(snippet.viaIri),
            }, snippet.viaLabel))
        : null,
      snippet.exactText ? el('blockquote', {}, `“${snippet.exactText}”`) : null,
      meta, actions);
  }
}

/** Build a list of resource links. */
function linkList(groups, key, inbound = false) {
  const list = el('dl', { class: 'kv' });
  for (const group of groups) {
    const values = el('dd', {});
    group[key].forEach((value, index) => {
      if (index) values.append(', ');
      if (value.type === 'uri') {
        values.append(el('button', {
          class: 'iri-link', title: value.value,
          onclick: () => openInspector(value.value),
        }, value.label || value.curie));
      } else if (/^https?:\/\//.test(value.value)) {
        values.append(el('a', { href: value.value, target: '_blank', rel: 'noopener' },
          truncate(value.value.replace(/^https?:\/\/(www\.)?/, ''), 44)));
      } else {
        const displayed = value.value;
        values.append(el('span', { title: displayed }, truncate(displayed, 190)));
      }
    });
    list.append(
      el('dt', { title: group.predicate.value },
        (inbound ? '← ' : '') + (group.predicate.label || group.predicate.curie)),
      values,
    );
  }
  return list;
}

qs('#inspector-close').addEventListener('click', closeInspector);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && !panel().hidden && qs('#viewer').hidden) closeInspector();
});

export { docUrl };
