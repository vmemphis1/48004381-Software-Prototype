import { el, clear, loading } from '../dom.js';
import { api } from '../api.js';
import { openInspector } from '../inspector.js';

const AFG = 'https://w3id.org/ai-finance-governance#';

/** Render the ontology schema browser. */
export async function render(container) {
  const page = el('div', { class: 'page' });
  container.replaceChildren(page);
  page.append(head(), loading('Reading the schema…'));

  let data;
  try {
    data = await api.schema();
  } catch (error) {
    clear(page).append(head(), el('div', { class: 'banner danger' }, String(error.message)));
    return;
  }
  clear(page).append(head());

  const project = data.classes.filter((c) => c.iri.startsWith(AFG));
  const imported = data.classes.filter((c) => !c.iri.startsWith(AFG) && c.totalInstances > 0);


  const ownProperties = data.properties.filter((p) => p.iri.startsWith(AFG));

  const layout = el('div', { class: 'schema-layout' });
  layout.append(
    el('div', {},
      el('div', { class: 'section-label', style: 'margin-top:0' },
        'Class hierarchy'),
      tree(data.classes, project),
      imported.length
        ? el('div', {},
            el('div', { class: 'section-label' }, 'Reused from imported vocabularies'),
            el('div', { class: 'tree' }, el('ul', {}, imported.map((cls) => el('li', {}, node(cls))))))
        : null),
    el('div', {},
      el('div', { class: 'section-label', style: 'margin-top:0' },
        'Properties'),
      properties(data.properties)),
  );
  page.append(layout);
}

/** Build the section heading and actions. */
function head() {
  return el('div', { class: 'page-head' },
    el('h2', {}, 'Schema'));
}

/** Build a class node for the schema tree. */
function node(cls) {
  return el('div', { class: 'tree-node' },
    el('button', { class: 'iri-link', onclick: () => openInspector(cls.iri) }, cls.label),
    cls.comment ? el('span', { class: 'muted', style: 'font-size:11px' }, '·') : null);
}

/** Build the schema class hierarchy. */
function tree(all, roots) {
  const byIri = Object.fromEntries(all.map((c) => [c.iri, c]));
  const children = new Map();
  const top = [];
  for (const cls of roots) {
    const parents = cls.parents.filter((p) => byIri[p] && roots.includes(byIri[p]));
    if (!parents.length) top.push(cls);
    for (const parent of parents) {
      if (!children.has(parent)) children.set(parent, []);
      children.get(parent).push(cls);
    }
  }
  const seen = new Set();
  /** Build one branch of the class hierarchy. */
  const branch = (cls) => {
    if (seen.has(cls.iri)) return el('li', {}, node(cls));
    seen.add(cls.iri);
    const kids = (children.get(cls.iri) || []).sort((a, b) => a.label.localeCompare(b.label));
    return el('li', {}, node(cls), kids.length ? el('ul', {}, kids.map(branch)) : null);
  };
  return el('div', { class: 'tree' },
    el('ul', {}, top.sort((a, b) => a.label.localeCompare(b.label)).map(branch)));
}

/** Render the schema property list. */
function properties(list) {
  const wrap = el('div', {});
  for (const kind of ['object', 'data']) {
    const group = list.filter((property) => property.kind === kind && property.iri.startsWith(AFG));
    if (!group.length) continue;
    wrap.append(el('div', { class: 'section-label' },
      kind === 'object' ? 'Object properties' : 'Data properties'));
    for (const property of group.sort((a, b) => b.uses - a.uses || a.label.localeCompare(b.label))) {
      wrap.append(el('div', { class: 'prop-row' },
        el('div', {},
          el('button', { class: 'iri-link', onclick: () => openInspector(property.iri) }, property.label),
          el('div', { class: 'prop-sig' },
            `${property.domain.map(short).join(', ') || 'any'} → ${property.range.map(short).join(', ') || 'any'}`))));
    }
  }
  return wrap;
}

/** Extract the local name from an IRI. */
const short = (iri) => iri.split(/[#/]/).pop();
