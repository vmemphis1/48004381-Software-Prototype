import { el, esc, truncate } from './dom.js';
import { openInspector } from './inspector.js';

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

  const resolved = cell.resolvedIri;
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

  const displayed = value;


  if (displayed.length > 150) {
    return el('span', { class: 'lit', title: displayed }, truncate(displayed, 150));
  }
  return el('span', { class: 'lit' }, displayed);
}

export { esc };
