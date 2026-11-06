"""Regression coverage for browser-local query bookmarks using the actual JS module.

Run with the other explorer tests: python3 -m unittest discover -s explorer/tests -v
Requires Node.js, like the builder compiler tests.
"""
from pathlib import Path
import subprocess
import unittest


REPOSITORY = Path(__file__).resolve().parents[2]
BOOTSTRAP = """
import assert from 'node:assert/strict';
const storage = new Map();
globalThis.localStorage = {
  getItem(key) { return storage.get(key) ?? null; },
  setItem(key, value) { storage.set(key, String(value)); },
};
const moduleUrl = new URL('./explorer/static/js/bookmarks.js', `file://${process.cwd()}/`);
const bookmarks = await import(moduleUrl.href);
const query = {question: 'Financial firms', sparql: '  SELECT ?firm WHERE { ?firm ?p ?v }\\n', mode: 'sparql'};
"""


def run_javascript(script):
    """Run the bookmark module in a JavaScript test harness."""
    result = subprocess.run(
        ['node', '--input-type=module', '-e', BOOTSTRAP + script],
        cwd=REPOSITORY, capture_output=True, text=True,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)


class BookmarkTests(unittest.TestCase):
    def test_saved_query_survives_module_reload_with_exact_editor_text(self):
        """Check that saved query survives module reload with exact editor text."""
        run_javascript("""
const saved = bookmarks.saveBookmark(query);
assert.equal(saved.created, true);
assert.ok(saved.bookmark.id.startsWith('bookmark-'));
assert.equal(saved.bookmark.kind, 'bookmark');
assert.ok(Number.isFinite(Date.parse(saved.bookmark.createdAt)));
// The query string forces a fresh module instance while retaining shared storage.
const reloaded = await import(moduleUrl.href + '?reload');
assert.deepEqual(reloaded.listBookmarks(), [saved.bookmark]);
assert.equal(reloaded.getBookmark(saved.bookmark.id).sparql, query.sparql);
assert.equal(storage.size, 1);
""")

    def test_guided_plan_and_labels_are_independent_snapshots(self):
        """Check that guided plan and labels are independent snapshots."""
        run_javascript("""
const plan = {version: 2, rootClass: 'urn:Firm', nextId: 8, hidden: new Set(['field7']),
  steps: [{id: 7, kind: 'value', property: 'urn:name', from: 'record', op: 'is', value: '  ACME  '}]};
const labels = {record: 'Financial firms', field7: 'Firm name'};
const {bookmark} = bookmarks.saveBookmark({...query, mode: 'guided', plan, columnLabels: labels});
plan.hidden.clear();
plan.steps[0].value = 'Changed';
labels.record = 'Changed';
bookmark.plan.hidden.add('record');
bookmark.plan.steps[0].value = 'Changed again';
bookmark.columnLabels.record = 'Changed again';
const reloaded = await import(moduleUrl.href + '?reload');
const restored = reloaded.getBookmark(bookmark.id);
assert.equal(restored.plan.version, 2);
assert.equal(restored.plan.nextId, 8);
assert.ok(restored.plan.hidden instanceof Set);
assert.deepEqual([...restored.plan.hidden], ['field7']);
assert.equal(restored.plan.steps[0].value, '  ACME  ');
assert.equal(restored.columnLabels.record, 'Financial firms');
restored.plan.hidden.clear();
restored.plan.steps.length = 0;
assert.equal(reloaded.listBookmarks()[0].plan.steps.length, 1);
assert.deepEqual([...reloaded.findBookmark(query.sparql).plan.hidden], ['field7']);
""")

    def test_trimmed_duplicates_keep_original_query_and_bookmark(self):
        """Check that trimmed duplicates keep original query and bookmark."""
        run_javascript("""
const first = bookmarks.saveBookmark(query);
const duplicate = bookmarks.saveBookmark({...query, sparql: query.sparql.trim(), question: 'Different title'});
assert.equal(duplicate.created, false);
assert.deepEqual(duplicate.bookmark, first.bookmark);
assert.equal(bookmarks.listBookmarks().length, 1);
assert.equal(bookmarks.findBookmark('\\n' + query.sparql + '  ').id, first.bookmark.id);
assert.equal(bookmarks.findBookmark('SELECT * WHERE {}'), null);
""")

    def test_removal_persists_and_unknown_id_returns_false(self):
        """Check that removal persists and unknown id returns false."""
        run_javascript("""
const first = bookmarks.saveBookmark(query).bookmark;
const second = bookmarks.saveBookmark({...query, sparql: 'ASK { ?s ?p ?o }'}).bookmark;
assert.notEqual(first.id, second.id);
assert.equal(bookmarks.removeBookmark(first.id), true);
const reloaded = await import(moduleUrl.href + '?reload');
assert.equal(reloaded.getBookmark(first.id), null);
assert.deepEqual(reloaded.listBookmarks().map(value => value.id), [second.id]);
assert.equal(reloaded.removeBookmark('unknown'), false);
assert.equal(reloaded.removeBookmark(second.id), true);
assert.deepEqual(reloaded.listBookmarks(), []);
""")

    def test_each_operation_reads_other_tabs_changes_and_sorts_newest_first(self):
        """Check that each operation reads other tabs changes and sorts newest first."""
        run_javascript("""
bookmarks.saveBookmark(query);
const [key] = storage.keys();
const original = bookmarks.listBookmarks()[0];
const earlier = {...original, id: 'bookmark-earlier', createdAt: '2020-01-01T00:00:00.000Z'};
const later = {...original, id: 'bookmark-later', sparql: 'ASK {}', createdAt: '2025-01-01T00:00:00.000Z'};
// Replace storage directly to simulate a write from another browser tab.
localStorage.setItem(key, JSON.stringify({version: 1, bookmarks: [earlier, later]}));
assert.deepEqual(bookmarks.listBookmarks().map(value => value.id), ['bookmark-later', 'bookmark-earlier']);
assert.equal(bookmarks.getBookmark(original.id), null);
assert.equal(bookmarks.findBookmark('ASK {}').id, 'bookmark-later');
bookmarks.saveBookmark({...query, sparql: 'SELECT * {}'});
assert.equal(bookmarks.listBookmarks().length, 3);
assert.equal(bookmarks.removeBookmark('bookmark-earlier'), true);
""")

    def test_missing_or_malformed_storage_does_not_break_reads_or_next_save(self):
        """Check that missing or malformed storage does not break reads or next save."""
        run_javascript("""
assert.deepEqual(bookmarks.listBookmarks(), []);
assert.equal(bookmarks.getBookmark('missing'), null);
assert.equal(bookmarks.findBookmark(null), null);
assert.equal(bookmarks.removeBookmark('missing'), false);
bookmarks.saveBookmark(query);
const [key] = storage.keys();
for (const invalid of ['not JSON', 'null', '{}', '{"version":2,"bookmarks":[]}',
  '{"version":1,"bookmarks":[null,{"sparql":13}]}']) {
  storage.set(key, invalid);
  assert.deepEqual(bookmarks.listBookmarks(), []);
  assert.equal(bookmarks.saveBookmark(query).created, true);
  assert.equal(bookmarks.listBookmarks().length, 1);
}
""")

    def test_invalid_builder_snapshot_keeps_runnable_query(self):
        """Check that invalid builder snapshot keeps runnable query."""
        run_javascript("""
bookmarks.saveBookmark(query);
const [key] = storage.keys();
const data = JSON.parse(storage.get(key));
data.bookmarks[0].plan = {version: 2, hidden: 42};
storage.set(key, JSON.stringify(data));
const [restored] = bookmarks.listBookmarks();
assert.equal(restored.sparql, query.sparql);
assert.equal(restored.plan, undefined);
assert.throws(() => bookmarks.saveBookmark({...query, sparql: 'ASK {}', mode: 'guided', plan: {}}),
  /builder query could not be bookmarked/);
assert.throws(() => bookmarks.saveBookmark({...query, sparql: '   '}), /Enter a query/);
""")

    def test_storage_failures_are_reported_without_claiming_success(self):
        """Check that storage failures are reported without claiming success."""
        run_javascript("""
const {bookmark} = bookmarks.saveBookmark(query);
const originalWrite = localStorage.setItem;
localStorage.setItem = () => { throw new Error('Quota exceeded'); };
assert.throws(() => bookmarks.saveBookmark({...query, sparql: 'ASK {}'}), /Could not save.*storage/);
assert.throws(() => bookmarks.removeBookmark(bookmark.id), /Could not remove.*storage/);
assert.equal(bookmarks.listBookmarks().length, 1);
localStorage.setItem = originalWrite;
Object.defineProperty(globalThis, 'localStorage', {configurable: true,
  get() { throw new Error('Storage blocked'); }});
assert.deepEqual(bookmarks.listBookmarks(), []);
assert.throws(() => bookmarks.saveBookmark(query), /Could not save.*storage/);
""")


if __name__ == '__main__':
    unittest.main()
