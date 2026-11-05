import { el, qs, clear, highlightSparql, copy, loading, truncate, toast } from '../dom.js';
import { api } from '../api.js';
import { state, setState } from '../state.js';
import { renderCell } from '../cells.js';
import { listBookmarks, removeBookmark } from '../bookmarks.js';

let requestRevision = 0;

/** Render the question cards and saved queries. */
export async function render(container, params = {}) {
  const page = el('div', { class: 'page' });
  container.replaceChildren(page);

  if (!state.questions.length) {
    page.append(loading('Reading the query pack…'));
    const { questions } = await api.questions();
    setState({ questions });
  }

  const results = el('div', { id: 'result-panel' });
  const competency = state.questions.filter((q) => q.kind === 'competency');
  const supporting = state.questions.filter((q) => q.kind === 'supporting');

  clear(page);
  page.append(el('div', { class: 'page-head' },
    el('h2', {}, 'Explore')));

  page.append(el('div', { class: 'section-label' }, 'Competency questions'));
  page.append(el('div', { class: 'card-grid' }, competency.map((q) => card(q, results))));
  page.append(el('div', { class: 'section-label' }, 'Supporting queries'));
  page.append(el('div', { class: 'card-grid' }, supporting.map((q) => card(q, results))));
  const bookmarks = el('div', {});
  const savedQuestions = renderBookmarks(bookmarks, results);
  page.append(el('section', { 'aria-labelledby': 'bookmarks-heading' },
    el('h3', { id: 'bookmarks-heading', class: 'section-label' }, 'Bookmarks'), bookmarks));
  page.append(results);

  const wanted = params.q || state.activeQuestionId;
  if (wanted) {
    const question = [...state.questions, ...savedQuestions].find((q) => q.id === wanted);
    if (question) run(question, results, false);
  }
}

/** Render saved queries and their actions. */
function renderBookmarks(container, results) {
  let bookmarks;
  try {
    bookmarks = listBookmarks();
  } catch (error) {
    clear(container).append(el('div', { class: 'banner danger', role: 'alert' },
      `Could not load bookmarks: ${error.message}`));
    return [];
  }
  clear(container);
  if (!bookmarks.length) {
    container.append(el('div', { class: 'empty-state bookmarks-empty' },
      el('strong', {}, 'No bookmarks yet'),
      el('p', {}, 'Build a query in the Build tab, then choose Bookmark query to save it here for later.')));
    return bookmarks;
  }
  container.append(el('div', { class: 'card-grid bookmark-grid' }, bookmarks.map((question) =>
    el('article', { class: 'qcard bookmark-card', dataset: { question: question.id } },
      el('button', {
        type: 'button', class: 'bookmark-run',
        'aria-label': `Run bookmark: ${question.question}`,
        onclick: () => toggleQuestion(question, results),
      },
      el('span', { class: 'qcard-top' },
        el('span', { class: 'qnum' }, 'BOOKMARK'),
        el('span', { class: 'qcard-desc' }, question.mode === 'sparql' ? 'SPARQL' : 'Builder')),
      el('span', { class: 'qcard-q' }, truncate(question.question, 190)),
      el('span', { class: 'qcard-desc' }, 'Run saved query')),
      el('div', { class: 'qcard-foot' },
        el('a', { class: 'ghost-btn', href: `#/build?bookmark=${encodeURIComponent(question.id)}` }, 'Open in Build'),
        el('button', {
          type: 'button', class: 'ghost-btn',
          'aria-label': `Remove bookmark: ${question.question}`,
          onclick: () => {
            try {
              removeBookmark(question.id);
              if (state.activeQuestionId === question.id) {

                ++requestRevision;
                setState({ activeQuestionId: null });
                clear(results);
              }
              renderBookmarks(container, results);
              toast('Bookmark removed');
            } catch (error) {
              toast(`Could not remove bookmark: ${error.message}`, 5000);
            }
          },
        }, 'Remove bookmark'))))));
  container.querySelectorAll('.qcard').forEach((node) => {
    node.classList.toggle('is-active', node.dataset.question === state.activeQuestionId);
  });
  return bookmarks;
}

/** Build a question card. */
function card(question, results) {
  const node = el('button', {
    class: 'qcard',
    dataset: { question: question.id },
    onclick: () => toggleQuestion(question, results),
  },
    el('div', { class: 'qcard-top' },
      el('span', { class: `qnum${question.number ? '' : ' supporting'}` },
        question.number ? `CQ${question.number}` : 'QUERY')),
    el('div', { class: 'qcard-q' }, truncate(question.question, 190)),
  );
  return node;
}

/** Open or close a question and its results. */
function toggleQuestion(question, container) {
  if (state.activeQuestionId !== question.id) return run(question, container, true);


  ++requestRevision;
  setState({ activeQuestionId: null });
  document.querySelectorAll('.qcard').forEach((node) => {
    node.classList.remove('is-active');
  });
  clear(container);
}

/** Run a selected question and show its results. */
export async function run(question, container, scroll = true) {
  const revision = ++requestRevision;
  setState({ activeQuestionId: question.id });
  document.querySelectorAll('.qcard').forEach((node) => {
    node.classList.toggle('is-active', node.dataset.question === question.id);
  });

  container = container || qs('#result-panel');
  if (!container) return;
  clear(container).append(el('div', { style: 'margin-top:26px' }, loading()));

  let payload;
  try {
    payload = await api.query(question.sparql);
  } catch (error) {
    if (revision !== requestRevision || !container.isConnected) return;
    clear(container).append(el('div', { class: 'banner danger' }, String(error.message)));
    return;
  }
  if (revision !== requestRevision || !container.isConnected) return;
  clear(container).append(resultPanel(question, payload));


  if (scroll) container.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/** Build a panel displaying query results and optional SPARQL. */
export function resultPanel(question, payload, { showSparql = true } = {}) {
  const result = payload.result;
  const wrap = el('div', { style: 'margin-top:26px' });

  const head = el('div', { class: 'result-head' },
    el('div', {},
      el('h2', {}, question.question),
      question.number ? el('div', { class: 'result-cq' }, `CQ${question.number}`) : null),
    el('div', { class: 'result-actions' },
      el('button', { class: 'ghost-btn', onclick: () => copy(question.sparql, 'SPARQL copied') }, 'Copy SPARQL'),
      question.id && question.kind !== 'bookmark' ? el('button', {
        class: 'ghost-btn',
        onclick: () => { window.location.hash = `#/graph?q=${encodeURIComponent(question.id)}`; },
      }, 'See in graph') : null),
  );
  wrap.append(head);

  if (!result.ok) {
    wrap.append(el('div', { class: 'banner danger' }, result.error));
  } else if (result.boolean !== null && result.boolean !== undefined) {
    wrap.append(el('div', { class: `banner ${result.boolean ? 'ok' : 'gap'}` },
      el('strong', {}, result.boolean ? 'Yes' : 'No')));
  } else if (!result.count) {
    wrap.append(emptyState(question));
  } else {
    wrap.append(table(result, question.columnLabels));
  }

  if (question.notes) {
    wrap.append(el('details', { class: 'disclose' },
      el('summary', {}, 'What this result means'),
      el('p', { class: 'result-note', html: question.notes.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>') })));
  }

  if (showSparql) {
    wrap.append(el('details', { class: 'disclose' },
      el('summary', {}, 'SPARQL'),
      el('pre', { class: 'sparql', html: highlightSparql(question.sparql) })));
  }

  return wrap;
}

/** Explain an empty query result. */
function emptyState(question) {
  const expected = question.expectEmpty
    ? 'This query is documented as correctly returning nothing.'
    : 'No rows matched.';
  return el('div', { class: 'empty-state' },
    el('strong', {}, 'Not verified in the collected corpus'),
    el('p', {}, `${expected} An empty result is never a claim that the organisations `
      + 'lack the practice — it means the link is not evidenced by the documents gathered '
      + 'so far.'));
}

/** Build a results table. */
function table(result, columnLabels = {}) {
  const head = el('tr', {}, result.columns.map((column) => el('th', {}, columnLabels[column] || column)));
  const body = el('tbody', {},
    result.rows.map((row) => el('tr', {}, row.map((cell) => el('td', {}, renderCell(cell))))));
  return el('div', { class: 'table-wrap' },
    el('table', { class: 'grid' }, el('thead', {}, head), body));
}

export { table as resultTable };
