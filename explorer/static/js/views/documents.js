import { el, clear, loading } from '../dom.js';
import { api } from '../api.js';
import { openInspector } from '../inspector.js';
import { openDocument } from '../viewer.js';
import { corpusForm } from './corpus-form.js';

/** Render archived documents and their evidence. */
export async function render(container, { saved } = {}) {
  const page = el('div', { class: 'page' });
  const editor = el('div', {});
  let editRevision = 0;
  /** Open the document editor. */
  const edit = async (document) => {
    const current = ++editRevision;
    clear(editor).append(loading('Finding graph records and relationships…'));
    editor.scrollIntoView({ behavior: 'smooth', block: 'start' });
    try {
      const options = await api.corpusOptions();
      if (current !== editRevision || !editor.isConnected) return;
      clear(editor).append(corpusForm(options, { document,
        onCancel: () => { ++editRevision; clear(editor); },
        onSaved: async (result) => {
          if (current === editRevision && editor.isConnected) await render(container, { saved: result });
        },
      }));
    } catch (error) {
      if (current !== editRevision || !editor.isConnected) return;
      clear(editor).append(el('div', { class: 'banner danger', role: 'alert' }, String(error.message)));
    }
  };
  /** Build the document list heading. */
  const header = () => head(() => edit());
  container.replaceChildren(page);
  page.append(header(), editor, loading('Reading the corpus…'));

  let documents;
  let evidence;
  try {
    [{ documents }, { evidence }] = await Promise.all([api.documents(), api.evidence()]);
  } catch (error) {
    if (page.isConnected) clear(page).append(header(), editor, el('div', { class: 'banner danger' }, String(error.message)));
    return;
  }
  if (!page.isConnected) return;
  clear(page).append(header(), editor);
  if (saved) page.append(el('div', { class: 'banner ok', role: 'status' },
    `Saved “${saved.document.label}” and ${saved.snippets.length} evidence snippet(s). The document and links are available to queries now.`));

  const byDocument = new Map();
  for (const snippet of evidence) {
    const key = snippet.document?.iri;
    if (!key) continue;
    if (!byDocument.has(key)) byDocument.set(key, []);
    byDocument.get(key).push(snippet);
  }

  const missing = documents.filter((doc) => !doc.exists);
  if (missing.length) {
    page.append(el('div', { class: 'banner danger' },
      el('span', {}, el('strong', {}, `${missing.length} archived file(s) are missing from corpus/. `),
        'The graph still records their checksum and URL, but the preview cannot open them.')));
  }

  page.append(el('div', { class: 'card-grid' }, documents.map((doc) => {
    const snippets = byDocument.get(doc.iri) || [];
    return el('div', { class: 'qcard', style: 'cursor:default' },
      el('div', { class: 'qcard-top' },
        el('span', { class: 'document-format' }, doc.format.toUpperCase())),
      el('div', { class: 'qcard-q', style: 'font-size:14px' }, doc.label),
      el('div', { class: 'qcard-desc' },
        [doc.documentType, doc.documentDate, doc.sizeBytes ? `${(doc.sizeBytes / 1048576).toFixed(1)} MB` : null]
          .filter(Boolean).join(' · ')),
      el('div', { class: 'qcard-foot' },
        doc.exists
          ? el('button', { class: 'primary-btn', onclick: () => openDocument(doc) }, 'Preview')
          : null,
        el('button', { class: 'ghost-btn', onclick: () => openInspector(doc.iri) }, 'In the graph'),
        el('button', { class: 'ghost-btn', onclick: () => edit(doc) }, 'Add snippets'),
        doc.documentURL
          ? el('a', { class: 'ghost-btn', href: doc.documentURL, target: '_blank', rel: 'noopener' }, 'Source ↗')
          : null),
      snippets.length
        ? el('details', { class: 'disclose', style: 'margin-top:6px' },
            el('summary', {}, 'What was extracted'),
            el('div', {}, snippets.map((snippet) => el('div', { class: 'snippet' },
              el('blockquote', {}, `“${snippet.exactText}”`),
              el('div', { class: 'snippet-meta' },
                el('span', {}, snippet.pageReference || 'page not recorded'),
                snippet.sectionReference ? el('span', {}, snippet.sectionReference) : null),
              snippet.supports?.length ? el('div', { class: 'snippet-actions' },
                el('span', { class: 'muted' }, 'Supports:'),
                snippet.supports.map((target) => el('button', { class: 'iri-link',
                  onclick: () => openInspector(target.value) }, target.label || target.curie))) : null,
              el('div', { class: 'snippet-actions' },
                doc.exists
                  ? el('button', {
                      class: 'ghost-btn',
                      onclick: () => openDocument(doc, {
                        page: snippet.pdfPage, quote: snippet.exactText, caption: snippet.pageReference,
                      }),
                    }, snippet.pdfPage ? `Open at page ${snippet.pdfPage}` : 'Open')
                  : null,
                el('button', {
                  class: 'ghost-btn',
                  onclick: () => openInspector(snippet.iri),
                }, 'Inspect snippet'))))))
        : null);
  })));
}

/** Build the section heading and actions. */
function head(add) {
  return el('div', { class: 'page-head corpus-head' },
    el('h2', {}, 'Corpus'), el('button', { class: 'primary-btn', onclick: add }, '+ Add document'));
}
