import { el, clear, highlightSparql, copy, loading, toast, confidenceLabel, truncate } from '../dom.js';
import { api } from '../api.js';
import { state, setState } from '../state.js';
import { findBookmark, getBookmark, saveBookmark } from '../bookmarks.js';
import { resultPanel } from './ask.js';
import { compile } from './builder-model.js';
export { compile } from './builder-model.js';

let schema;
let revision = 0;
let queryRevision = 0;
const friendly = {
  FinancialInstitution: 'Financial firms', EvidenceSnippet: 'Evidence passages',
  TerminologyUsage: 'Terms used by organisations', AIGovernanceBody: 'AI oversight bodies',
  GovernancePolicy: 'Governance policies',
};

/** Extract the local name from an IRI. */
const local = (iri) => iri?.split(/[#/]/).pop();

/** Look up a schema label for an IRI. */
const label = (iri) => schema.byIri[iri]?.label || local(iri) || 'Linked records';

/** Return a friendly label for a builder topic. */
const topic = (iri) => friendly[local(iri)] || label(iri);

/** Format a matching-record count. */
const countLabel = (n) => `${n} matching ${n === 1 ? 'record' : 'records'}`;

/** Create an empty guided query plan. */
function newPlan(rootClass) {
  return { version: 2, rootClass, steps: [], hidden: new Set(), nextId: 1 };
}

/** Copy the leading steps of a guided query plan. */
function prefix(plan, length) {
  return { ...plan, steps: plan.steps.slice(0, length), hidden: new Set() };
}

/** Choose the label for a builder node. */
function nodeLabel(node) {
  return node.var === 'record' ? topic(node.iri)
    : `${node.label || label(node.iri)} · step ${state.builder.steps.findIndex((s) => `linked${s.id}` === node.var) + 2}`;
}

/** Build a select control from the supplied choices. */
function select(name, choices, value, change) {
  const node = el('select', { 'aria-label': name, onchange: (event) => change(event.target.value) },
    choices.map(([id, text]) => el('option', { value: id }, text)));

  node.value = value ?? '';
  return node;
}

/** Build a labeled form control. */
function field(name, control) {
  return el('label', { class: 'builder-field' }, el('span', {}, name), control);
}

/** Check whether a builder step is available in the current context. */
function stepAvailable(step, context) {
  const kind = step.kind === 'relation' ? 'relationships' : 'fields';
  const selected = context.nodes[step.from]?.[kind]?.find((option) => option.property === step.property
    && (step.kind !== 'relation' || option.range === step.range));
  return Boolean(selected && (step.kind === 'relation'
    || ((step.op !== 'is' || selected.values.some((v) => v.value === step.value))
      && (step.op !== 'absent' || selected.absent))));
}

/** Render the question builder view. */
export async function render(container, params = {}) {
  let restored = params.bookmark ? getBookmark(params.bookmark) : null;
  if (restored) {
    setState(restored.mode === 'guided' && restored.plan
      ? { builderMode: 'guided', builder: restored.plan }
      : { builderMode: 'sparql', builderSparql: restored.sparql });
  } else if (params.bookmark) {
    toast('This bookmark is no longer available.');
  }
  const page = el('div', { class: 'page' });
  container.replaceChildren(page);
  const workspace = el('div', {});
  const modes = el('div', { class: 'builder-mode', role: 'group', 'aria-label': 'Query mode' },
    [['guided', 'Builder'], ['sparql', 'SPARQL (advanced)']].map(([mode, text]) =>
      el('button', { class: 'chip-toggle', dataset: { mode }, onclick: () => showMode(mode) }, text)));

  /** Switch between the guided builder and manual editor. */
  const showMode = async (mode) => {
    // A newer mode switch or redraw invalidates outstanding requests.
    const current = ++revision;
    setState({ builderMode: mode });
    modes.querySelectorAll('button').forEach((button) => {
      const active = button.dataset.mode === mode;
      button.classList.toggle('on', active);
      button.setAttribute('aria-pressed', String(active));
    });
    clear(workspace);
    const results = el('div', { id: 'result-panel', 'aria-live': 'polite' });
    if (mode === 'sparql') {
      workspace.append(manualEditor(results, current), results);
      return;
    }
    workspace.append(loading('Finding available records…'));
    let payload;
    try {
      payload = await api.schema();
    } catch (error) {
      if (current !== revision || !workspace.isConnected) return;
      clear(workspace).append(el('div', { class: 'banner danger', role: 'alert' },
        `Could not load dropdown choices: ${error.message}`));
      return;
    }
    if (current !== revision || !workspace.isConnected) return;
    if (restored?.plan
      && !payload.classes.some((c) => c.iri === restored.plan.rootClass && c.totalInstances > 0)) {
      setState({ builderSparql: restored.sparql });
      restored = null;
      toast('The saved record type is no longer available. Opened the bookmarked SPARQL instead.', 5000);
      await showMode('sparql');
      return;
    }
    restored = null;
    await renderGuided(workspace, results, payload);
  };
  page.append(el('div', { class: 'page-head' }, el('h2', {}, 'Build')), modes, workspace);
  await showMode(state.builderMode);
}

/** Render the guided query builder. */
async function renderGuided(workspace, results, payload) {
  schema = { ...payload, byIri: Object.fromEntries(payload.classes.map((c) => [c.iri, c])) };
  schema.populated = payload.classes.filter((c) => c.totalInstances > 0
    && (c.iri.startsWith('https://w3id.org/ai-finance-governance#') || c.directInstances > 0))
    .sort((a, b) => topic(a.iri).localeCompare(topic(b.iri)));
  clear(workspace);
  if (!schema.populated.length) {
    workspace.append(el('p', {}, 'There are no records to search yet.'));
    return;
  }
  if (state.builder?.version !== 2 || !schema.populated.some((c) => c.iri === state.builder.rootClass)) {
    const start = schema.populated.find((c) => local(c.iri) === 'FinancialInstitution') || schema.populated[0];
    setState({ builder: newPlan(start.iri) });
  }
  const left = el('div', {});
  const right = el('div', {});
  workspace.append(el('div', { class: 'builder' }, left, right), results);
  await draw(left, right, results);
}

/** Create the manual SPARQL editor and its actions. */
function manualEditor(results, current) {

  /** Compile the current guided plan to SPARQL. */
  const builderQuery = () => compile(state.builder?.version === 2 ? state.builder
    : newPlan('https://w3id.org/ai-finance-governance#FinancialInstitution')).sparql;
  if (state.builderSparql === null) setState({ builderSparql: builderQuery() });
  let running = false;
  const validation = el('p', { class: 'builder-help', role: 'alert', hidden: true },
    'Enter a SPARQL query before running it.');

  /** Update the current controls from their state. */
  const update = () => {
    setState({ builderSparql: editor.value });
    runButton.disabled = running || !editor.value.trim();
    bookmark.update();
    validation.hidden = true;
    editor.removeAttribute('aria-invalid');
  };

  /** Execute the current editor query. */
  const execute = async () => {
    if (running) return;
    const submitted = editor.value;
    if (!submitted.trim()) {
      validation.hidden = false;
      editor.setAttribute('aria-invalid', 'true');
      editor.focus();
      return;
    }
    running = true;
    runButton.disabled = true;
    runButton.textContent = 'Running…';
    editor.removeAttribute('aria-invalid');
    try {
      const ok = await run(submitted.trim(), 'Custom SPARQL query results', {}, results, current,
        { showSparql: true });
      if (ok === false && editor.value === submitted) editor.setAttribute('aria-invalid', 'true');
    } finally {
      running = false;
      runButton.disabled = !editor.value.trim();
      runButton.textContent = 'Run query';
    }
  };
  const editor = el('textarea', {
    id: 'manual-sparql', class: 'sparql-editor', rows: 14, spellcheck: 'false',
    autocapitalize: 'off', autocomplete: 'off', 'aria-describedby': 'manual-sparql-help',
    oninput: update,
    onkeydown: (event) => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        execute();
      }
    },
  });
  editor.value = state.builderSparql;
  const runButton = el('button', { class: 'primary-btn', type: 'submit',
    disabled: !editor.value.trim() }, 'Run query');
  const bookmark = bookmarkControls(() => ({
    question: 'Custom SPARQL query', sparql: editor.value, mode: 'sparql',
  }));
  return el('form', { class: 'builder-panel builder-manual', onsubmit: (event) => {
    event.preventDefault();
    execute();
  } },
  el('label', { for: 'manual-sparql', class: 'sparql-label' }, 'SPARQL query'),
  el('p', { id: 'manual-sparql-help', class: 'builder-help' },
    'Write or paste a query against the local knowledge graph. Include the prefixes your query uses. '
    + 'Press Ctrl+Enter or ⌘+Enter to run.'),
  editor, validation,
  el('div', { class: 'builder-add manual-actions' }, runButton,
    state.builder?.version === 2 ? el('button', { class: 'ghost-btn', type: 'button', onclick: () => {
      editor.value = builderQuery();
      update();
      editor.focus();
    } }, 'Load dropdown query') : null,
    el('button', { class: 'ghost-btn', type: 'button',
      onclick: () => copy(editor.value, 'SPARQL copied') }, 'Copy SPARQL'),
    el('button', { class: 'ghost-btn', type: 'button',
      onclick: () => copy(saveable(editor.value), 'Query file copied') }, 'Copy as .rq file')),
  bookmark.node);
}

/** Draw the guided builder controls and results. */
async function draw(left, right, results) {
  const current = ++revision;
  const plan = state.builder;

  /** Redraw the guided builder. */
  const redraw = () => draw(left, right, results);
  clear(results);
  left.setAttribute('aria-busy', 'true');

  left.querySelectorAll('button, select').forEach((control) => { control.disabled = true; });
  clear(right).append(el('div', { class: 'builder-panel' }, loading('Checking matching records…')));
  let contexts;
  try {
    // Each step must use choices from matches before that step, not the final query.
    contexts = await Promise.all(Array.from({ length: plan.steps.length + 1 }, (_, i) =>
      api.builderOptions(compile(prefix(plan, i)).sparql)));
  } catch (error) {
    if (current !== revision || !left.isConnected) return;
    left.removeAttribute('aria-busy');
    clear(right).append(el('div', { class: 'builder-panel' },
      el('p', {}, `Could not check available choices: ${error.message}`),
      el('button', { class: 'ghost-btn', onclick: redraw }, 'Try again')));
    return;
  }
  if (current !== revision || !left.isConnected) return;
  left.removeAttribute('aria-busy');
  if (plan.revalidate) {
    delete plan.revalidate;
    // Keep dependent steps until the first one that no longer matches the data.
    const invalid = plan.steps.findIndex((step, index) => !stepAvailable(step, contexts[index]));
    if (invalid !== -1) {
      plan.steps.splice(invalid);
      toast(`Step ${invalid + 2} no longer matches. That step and later steps were cleared.`);
      return redraw();
    }
  }
  const built = compile(plan);
  const final = contexts.at(-1);

  /** Update a builder step and refresh its dependent choices. */
  const change = (index, mutate, remove = false) => {
    mutate();
    if (remove) {
      const removed = plan.steps.splice(index);
      if (removed.length > 1) toast('Later steps were also removed because they use the earlier choices.');
    } else {
      plan.revalidate = true;
    }
    const available = compile(plan);
    const validColumns = new Set([...available.nodes, ...available.values].map((n) => n.var));
    plan.hidden = new Set([...plan.hidden].filter((name) => validColumns.has(name)));
    redraw();
  };
  const panel = el('div', { class: 'builder-panel' });
  panel.append(el('div', { class: 'step root' }, field('1. What do you want to find?',
    select('What do you want to find?', schema.populated.map((c) => [c.iri, topic(c.iri)]),
      plan.rootClass, (value) => { setState({ builder: newPlan(value) }); redraw(); }))));

  plan.steps.forEach((step, index) => {
    const nodes = compile(prefix(plan, index)).nodes;
    const context = contexts[index];
    const kind = step.kind === 'relation' ? 'relationships' : 'fields';
    const sources = nodes.filter((n) => context.nodes[n.var]?.[kind]?.length);
    const options = context.nodes[step.from]?.[kind] || [];
    const row = el('div', { class: 'step builder-step' },
      el('div', { class: 'builder-step-head' },
        el('strong', {}, `${index + 2}. ${step.kind === 'relation' ? 'Follow a recorded link' : 'Choose a recorded detail'}`),
        el('button', { class: 'icon-btn', 'aria-label': `Remove step ${index + 2}`,
          title: 'Remove this step and later steps',
          onclick: () => change(index, () => {}, true) }, '×')));


    if (!stepAvailable(step, context)) {
      row.append(el('p', {}, 'This choice no longer has matching data. Remove this step to choose again.'));
      panel.append(row);
      return;
    }
    row.append(field('For', select(`Records for step ${index + 2}`,
      sources.map((n) => [n.var, nodeLabel(n)]), step.from, (value) => change(index, () => {
        step.from = value;
        const first = context.nodes[value][kind][0];
        step.property = first.property;
        step.propertyLabel = first.label;
        if (step.kind === 'relation') step.range = first.range;
        else { step.op = 'present'; step.value = ''; }
      }))));
    const properties = [...new Map(options.map((o) => [o.property, o])).values()];
    row.append(field(step.kind === 'relation' ? 'Relationship' : 'Detail',
      select(`Property for step ${index + 2}`, properties.map((p) => [p.property, p.label]),
        step.property, (value) => change(index, () => {
          const chosen = options.find((o) => o.property === value);
          step.property = value;
          step.propertyLabel = chosen.label;
          if (step.kind === 'relation') step.range = chosen.range;
          else { step.op = 'present'; step.value = ''; }
        }))));
    if (step.kind === 'relation') {
      row.append(field('Linked record type', select(`Linked record type for step ${index + 2}`,
        options.filter((o) => o.property === step.property)
          .map((o) => [o.range || '', `${o.range ? label(o.range) : 'Any recorded type'}`]),
        step.range, (value) => change(index, () => { step.range = value || null; }))),
      el('p', { class: 'builder-help' }, 'Keep only records with this link. The linked records are added as a result column.'));
    } else {
      const chosen = options.find((o) => o.property === step.property);
      const operations = [
        ['present', `Has a recorded value`],
        ['is', 'Matches a specific value'],
        ['show', 'Show this detail without filtering'],
      ];
      if (chosen.absent) operations.push(['absent', `Has no recorded value`]);
      row.append(field('How to use it', select(`Condition for step ${index + 2}`, operations, step.op,
        (value) => change(index, () => {
          step.op = value;
          step.value = chosen.values[0]?.value || '';
        }))));
      if (step.op === 'is') row.append(field('Recorded value', select(`Value for step ${index + 2}`,
        chosen.values.map((v) => [v.value, confidenceLabel(v.value)]), step.value,
        (value) => change(index, () => { step.value = value; }))));
      if (step.op === 'show') row.append(el('p', { class: 'builder-help' }, 'Missing details appear as blank cells; records stay in the results.'));
      if (step.op === 'absent') row.append(el('p', { class: 'builder-help' }, 'A missing value means it is not recorded in the collected documents.'));
    }
    panel.append(row);
  });

  /** Add an item to the current view. */
  const add = (kind) => {
    const key = kind === 'relation' ? 'relationships' : 'fields';
    const from = [...built.nodes].reverse().find((n) => final.nodes[n.var]?.[key]?.length);
    const button = el('button', { class: 'chip-toggle', disabled: !from, onclick: () => {
      const option = final.nodes[from.var][key][0];
      plan.steps.push({ id: plan.nextId++, kind, from: from.var,
        property: option.property, propertyLabel: option.label,
        ...(kind === 'relation' ? { range: option.range } : { op: 'present', value: '' }) });
      redraw();
    } }, kind === 'relation' ? '+ Add a linked record' : '+ Filter or show a detail');
    if (!from) button.title = 'No recorded choices are available for the current matches';
    return button;
  };
  panel.append(el('div', { class: 'builder-add' }, add('relation'), add('value'),
    plan.steps.length ? el('button', { class: 'chip-toggle', onclick: () => {
      setState({ builder: newPlan(plan.rootClass) }); redraw();
    } }, 'Clear steps') : null));
  if (plan.steps.length) panel.append(el('p', { class: 'builder-help' },
    'Selections are kept while they still match. If a step stops matching or is removed, later steps are cleared.'));
  const columns = [...built.nodes, ...built.values];
  panel.append(el('div', { class: 'section-label', style: 'margin-top:22px' }, 'Result columns'),
    el('div', { class: 'builder-add' }, columns.map((entry) => {
      const on = !plan.hidden.has(entry.var);
      return el('button', { class: `chip-toggle${on ? ' on' : ''}`, 'aria-pressed': String(on),
        disabled: on && columns.filter((c) => !plan.hidden.has(c.var)).length === 1,
        onclick: () => { if (on) plan.hidden.add(entry.var); else plan.hidden.delete(entry.var); redraw(); },
      }, entry.var === 'record' ? topic(entry.iri) : entry.label || label(entry.iri));
    })));
  clear(left).append(panel);

  const description = describe(plan);
  const columnLabels = Object.fromEntries(columns.map((entry) => [entry.var,
    entry.var === 'record' ? topic(entry.iri) : entry.label?.replace(/^has /, '') || label(entry.iri)]));
  const details = el('details', { class: 'builder-code' },
    el('summary', {}, 'View or copy SPARQL (advanced)'),
    el('pre', { class: 'sparql', html: highlightSparql(built.sparql) }),
    el('div', { class: 'builder-add' },
      el('button', { class: 'ghost-btn', onclick: () => copy(built.sparql, 'SPARQL copied') }, 'Copy SPARQL'),
      el('button', { class: 'ghost-btn', onclick: () => copy(saveable(built.sparql), 'Query file copied') }, 'Copy as .rq file')));
  const bookmark = bookmarkControls(() => ({
    question: truncate(description.join(' '), 160), sparql: built.sparql,
    mode: 'guided', plan, columnLabels,
  }));
  clear(right).append(el('div', { class: 'builder-panel builder-summary' },
    el('div', { class: 'section-label' }, 'Your question'),
    el('p', { class: 'builder-question' }, description[0]),
    description.length > 1 ? el('ul', {}, description.slice(1).map((text) => el('li', {}, text))) : null,
    el('div', { class: 'builder-match', role: 'status' }, countLabel(final.count)),
    el('button', { class: 'primary-btn', disabled: !final.count,
      onclick: () => run(built.sparql, `Results for ${topic(plan.rootClass).toLowerCase()}`,
        columnLabels, results, current) }, 'Show results'),
    bookmark.node,
    details));
}

/** Build the controls for saving the current query. */
function bookmarkControls(query) {
  const error = el('p', { class: 'builder-help', role: 'alert', hidden: true });
  const title = el('input', { type: 'text', 'aria-label': 'Bookmark name',
    oninput: () => { error.hidden = true; },
    onkeydown: (event) => {
      if (event.key === 'Enter') { event.preventDefault(); save(); }
      if (event.key === 'Escape') { event.preventDefault(); close(); }
    } });

  /** Close the current form. */
  const close = () => { form.hidden = true; error.hidden = true; button.focus(); };

  /** Save the current entry. */
  const save = () => {
    if (!query().sparql.trim()) return;
    if (!title.value.trim()) {
      error.textContent = 'Enter a name for this bookmark.';
      error.hidden = false;
      title.focus();
      return;
    }
    try {
      const { created } = saveBookmark({ ...query(), question: title.value.trim() });
      form.hidden = true;
      error.hidden = true;
      update();
      toast(created ? 'Bookmark saved. Find it under Explore → Bookmarks.' : 'This query is already bookmarked.');
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    }
  };
  const button = el('button', { type: 'button', class: 'ghost-btn', onclick: () => {
    title.value = query().question;
    form.hidden = false;
    error.hidden = true;
    title.focus();
    title.select();
  } }, 'Bookmark query');
  const saveButton = el('button', { type: 'button', class: 'primary-btn', onclick: save }, 'Save bookmark');
  const form = el('div', { class: 'bookmark-save', hidden: true },
    field('Bookmark name', title),
    el('div', { class: 'builder-add' }, saveButton,
      el('button', { type: 'button', class: 'ghost-btn', onclick: close }, 'Cancel')), error);
  const node = el('div', { class: 'builder-bookmark' }, button, form);

  /** Update the current controls from their state. */
  const update = () => {
    const sparql = query().sparql;
    const saved = Boolean(findBookmark(sparql));
    button.textContent = saved ? 'Bookmarked' : 'Bookmark query';
    button.disabled = saved || !sparql.trim();
    button.setAttribute('aria-pressed', String(saved));
    saveButton.disabled = !sparql.trim();
  };
  update();
  return { node, update };
}

/** Describe the selected builder plan in plain language. */
function describe(plan) {
  const names = { record: topic(plan.rootClass) };
  const sentences = [`Find ${topic(plan.rootClass).toLowerCase()} in the collected documents.`];
  for (const step of plan.steps) {
    const subject = names[step.from];
    if (step.kind === 'relation') {
      sentences.push(`${subject}: follow “${step.propertyLabel}” to ${step.range ? label(step.range).toLowerCase() : 'any linked record'}.`);
      names[`linked${step.id}`] = step.range ? label(step.range) : `Records linked by “${step.propertyLabel}”`;
    } else {
      const condition = { present: 'must have a recorded value', absent: 'must have no recorded value',
        show: 'show the value when available', is: `must match “${confidenceLabel(step.value)}”` }[step.op];
      sentences.push(`${subject} → ${step.propertyLabel}: ${condition}.`);
    }
  }
  return sentences;
}

/** Prepare a query for saving with its question. */
function saveable(sparql) {
  return '# Created with the explorer Build tab.\n'
    + '# Add the question, expected result and caveats before committing.\n' + sparql + '\n';
}

/** Run a built query and display its results. */
async function run(sparql, title, columnLabels, container, current, { showSparql = false } = {}) {
  const request = ++queryRevision;

  /** Check whether the current query request is still active. */
  const active = () => current === revision && request === queryRevision && container.isConnected;
  container.setAttribute('aria-busy', 'true');
  clear(container).append(loading('Finding results…'));
  try {
    const payload = await api.query(sparql);
    if (!active()) return;
    clear(container).append(resultPanel(
      { question: title, sparql, columnLabels, header: [], number: null },
      payload, { showSparql }));
    container.scrollIntoView({ behavior: 'smooth', block: 'start' });
    return payload.result.ok;
  } catch (error) {
    if (!active()) return;
    clear(container).append(el('div', { class: 'banner danger', role: 'alert' }, error.message));
    return false;
  } finally {
    if (active()) container.removeAttribute('aria-busy');
  }
}
