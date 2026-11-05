import { el, esc, truncate, confidenceLabel } from './dom.js';
import { api } from './api.js';
import { openInspector } from './inspector.js';

let labelIndex = {};

/** Load the label and evidence indexes used by result cells. */
export async function loadIndexes() {
  const payload = await api.indexes();
  labelIndex = payload.labels || {};
}

/** Look up an IRI by its display label. */
export const iriForLabel = (label) => labelIndex[label];

/** Render a query result cell with links where available. */
export function renderCell(cell) {
  if (!cell) return el('span', { class: 'lit-empty' }, '—');

  if (cell.type === 'uri') {
    const text = cell.label || cell.curie || cell.value;
    const wrap = el('span', {});
    wrap.append(
      el('button', {
        class: 'iri-link',
        title: cell.value,
        onclick: () => openInspector(cell.value),
      }, text),
    );
    return wrap;
  }

  const value = cell.value ?? '';
  if (value === '') return el('span', { class: 'lit-empty' }, '—');

  const resolved = labelIndex[value];
  if (resolved) {
    const wrap = el('span', {});
    wrap.append(
      el('button', {
        class: 'iri-link',
        style: 'border-bottom-style: dotted',
        title: `${value}\nResolved by label to ${resolved}`,
        onclick: () => openInspector(resolved),
      }, value),
    );
    return wrap;
  }

  if (/^https?:\/\//.test(value)) {
    return el('a', { href: value, target: '_blank', rel: 'noopener', title: value },
      truncate(value.replace(/^https?:\/\/(www\.)?/, ''), 52));
  }

  const displayed = confidenceLabel(value);


  if (displayed.length > 150) {
    return el('span', { class: 'lit', title: displayed }, truncate(displayed, 150));
  }
  return el('span', { class: 'lit' }, displayed);
}

export { esc };
