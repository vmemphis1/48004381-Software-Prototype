const STORAGE_KEY = 'afg.query-bookmarks.v1';
let sequence = 0;

/** Check whether a value is a non-array object. */
const isObject = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

/** Create an independent JSON copy of a value. */
const clone = (value) => JSON.parse(JSON.stringify(value));

/** Create a serializable snapshot of a guided builder plan. */
function snapshotPlan(plan) {
  if (!isObject(plan) || plan.version !== 2 || typeof plan.rootClass !== 'string'
    || !Array.isArray(plan.steps) || !Number.isInteger(plan.nextId) || plan.nextId < 1
    || !(plan.hidden instanceof Set || Array.isArray(plan.hidden))) return null;
  const sources = new Set(['record']);
  const ids = new Set();
  for (const step of plan.steps) {
    if (!isObject(step) || !Number.isSafeInteger(step.id) || step.id < 1 || step.id >= plan.nextId
      || ids.has(step.id) || !sources.has(step.from) || typeof step.property !== 'string') return null;
    ids.add(step.id);
    if (step.kind === 'relation') {
      if (step.range != null && typeof step.range !== 'string') return null;
      sources.add(`linked${step.id}`);
    } else if (step.kind !== 'value' || !['is', 'show', 'absent', 'present'].includes(step.op)
      || (step.op === 'is' && typeof step.value !== 'string')) return null;
  }
  const hidden = [...plan.hidden];
  if (!hidden.every((column) => typeof column === 'string')) return null;
  // Sets do not survive JSON serialization; restore() recreates the Set on read.
  return { version: 2, rootClass: plan.rootClass, steps: clone(plan.steps),
    hidden, nextId: plan.nextId };
}

/** Restore a saved bookmark and its builder plan. */
function restore(bookmark) {
  const copy = clone(bookmark);
  if (copy.plan) copy.plan.hidden = new Set(copy.plan.hidden);
  return copy;
}

/** Read and validate saved bookmarks from browser storage. */
function read() {
  try {
    const stored = JSON.parse(globalThis.localStorage.getItem(STORAGE_KEY));
    if (stored?.version !== 1 || !Array.isArray(stored.bookmarks)) return [];
    const ids = new Set();
    return stored.bookmarks.flatMap((value) => {
      if (!isObject(value) || typeof value.id !== 'string' || !value.id.startsWith('bookmark-')
        || ids.has(value.id) || value.kind !== 'bookmark' || typeof value.question !== 'string'
        || typeof value.sparql !== 'string' || !value.sparql.trim()
        || !['guided', 'sparql'].includes(value.mode)
        || typeof value.createdAt !== 'string' || !Number.isFinite(Date.parse(value.createdAt))) return [];
      const bookmark = { id: value.id, kind: 'bookmark', question: value.question,
        sparql: value.sparql, mode: value.mode, createdAt: value.createdAt };
      if (value.plan !== undefined) {
        const plan = snapshotPlan(value.plan);
        // An invalid builder snapshot must not discard the saved runnable SPARQL.
        if (plan) bookmark.plan = plan;
      }
      if (isObject(value.columnLabels)) bookmark.columnLabels = clone(value.columnLabels);
      ids.add(value.id);
      return [bookmark];
    }).sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt));
  } catch {
    return [];
  }
}

/** Persist bookmarks and report storage errors. */
function write(bookmarks, action) {
  try {
    globalThis.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, bookmarks }));
  } catch {
    throw new Error(`Could not ${action} the bookmark. Browser storage is unavailable or full.`);
  }
}

/** List saved bookmarks in display order. */
export function listBookmarks() {
  return read().map(restore);
}

/** Find a saved bookmark by ID. */
export function getBookmark(id) {
  const bookmark = read().find((entry) => entry.id === id);
  return bookmark ? restore(bookmark) : null;
}

/** Find a saved bookmark with the same query. */
export function findBookmark(sparql) {
  if (typeof sparql !== 'string' || !sparql.trim()) return null;
  const bookmark = read().find((entry) => entry.sparql.trim() === sparql.trim());
  return bookmark ? restore(bookmark) : null;
}

/** Save a query and its optional builder plan. */
export function saveBookmark({ question, sparql, mode, plan, columnLabels }) {
  if (typeof sparql !== 'string' || !sparql.trim()) throw new Error('Enter a query before bookmarking it.');
  if (!['guided', 'sparql'].includes(mode)) throw new Error('Choose a query mode before bookmarking it.');
  const bookmarks = read();
  const existing = bookmarks.find((entry) => entry.sparql.trim() === sparql.trim());
  if (existing) return { bookmark: restore(existing), created: false };

  let id;
  do {
    id = `bookmark-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${sequence++}`;
  } while (bookmarks.some((entry) => entry.id === id));
  const bookmark = { id, kind: 'bookmark',
    question: typeof question === 'string' && question.trim() ? question.trim() : 'Saved query',
    sparql, mode, createdAt: new Date().toISOString() };
  if (plan !== undefined) {
    const snapshot = snapshotPlan(plan);
    if (!snapshot) throw new Error('This builder query could not be bookmarked. Try rebuilding the query.');
    bookmark.plan = snapshot;
  }
  if (columnLabels !== undefined) {
    if (!isObject(columnLabels)) throw new Error('The query column labels could not be bookmarked.');
    bookmark.columnLabels = clone(columnLabels);
  }
  write([bookmark, ...bookmarks], 'save');
  return { bookmark: restore(bookmark), created: true };
}

/** Remove a saved bookmark by ID. */
export function removeBookmark(id) {
  const bookmarks = read();
  const remaining = bookmarks.filter((bookmark) => bookmark.id !== id);
  if (remaining.length === bookmarks.length) return false;
  write(remaining, 'remove');
  return true;
}
