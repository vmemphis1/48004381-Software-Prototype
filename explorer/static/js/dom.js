/** Create a DOM element with attributes and children. */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else if (key.startsWith('on')) node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (value === true) node.setAttribute(key, '');
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

/** Escape a value for safe HTML display. */
export const esc = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/** Find the first matching element in a scope. */
export const qs = (selector, scope = document) => scope.querySelector(selector);

/** Find all matching elements in a scope. */
export const qsa = (selector, scope = document) => [...scope.querySelectorAll(selector)];

/** Remove all children from a DOM node. */
export function clear(node) {
  while (node.firstChild) node.firstChild.remove();
  return node;
}

/** Shorten text at a word boundary. */
export function truncate(text, limit) {
  const value = String(text ?? '');
  if (value.length <= limit) return value;
  const cut = value.slice(0, limit);
  const space = cut.lastIndexOf(' ');
  return `${cut.slice(0, space > limit * 0.6 ? space : limit)}…`;
}

/** Map a recorded confidence value to a display label. */
export function confidenceLabel(value) {
  const text = String(value ?? '');
  const match = text.match(/^(high|medium|low)\s+-\s+/i);
  return match ? match[1].toLowerCase() : text;
}

let toastTimer;

/** Show a temporary notification. */
export function toast(message, ms = 2600) {
  const node = qs('#toast');
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, ms);
}

/** Build a loading indicator. */
export function loading(label = 'Running…') {
  return el('div', { class: 'loading-row' }, el('span', { class: 'spinner' }), ' ', label);
}

const KEYWORDS = /\b(SELECT|DISTINCT|WHERE|PREFIX|OPTIONAL|FILTER|NOT|EXISTS|ORDER|BY|GROUP|LIMIT|OFFSET|UNION|BIND|AS|ASC|DESC|VALUES|MINUS|ASK|CONSTRUCT|COUNT|IF|BOUND|STR|COALESCE|IN|a)\b/g;

/** Apply syntax highlighting to a SPARQL query. */
export function highlightSparql(query) {
  return esc(query)
    .replace(/^(\s*#.*)$/gm, '<span class="cm">$1</span>')
    .replace(/(&quot;[^&]*?&quot;|&#39;[^&]*?&#39;)/g, '<span class="str">$1</span>')
    .replace(/(\?[A-Za-z_]\w*)/g, '<span class="var">$1</span>')
    .replace(KEYWORDS, '<span class="kw">$&</span>');
}

/** Copy text to the clipboard and report the result. */
export function copy(text, message = 'Copied to clipboard') {
  navigator.clipboard.writeText(text).then(
    () => toast(message),
    () => toast('Could not copy'),
  );
}
