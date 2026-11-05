import { el, clear, toast, loading } from '../dom.js';
import { api } from '../api.js';
import { state } from '../state.js';
import { openInspector } from '../inspector.js';
import { iriForLabel } from '../cells.js';

let cy = null;
let cytoscapeLib = null;
let hiddenTypes = new Set();
let currentMode = 'instances';


const PALETTE = ['#2f4b7c', '#a05195', '#d45087', '#f95d6a', '#ff7c43', '#ffa600',
  '#4a7c59', '#2a9d8f', '#577590', '#7b6d8d', '#8a6552', '#4d6a6d'];
const typeColour = new Map();

/** Choose a graph color for a resource type. */
function colourFor(typeIri, typeLabel) {
  const key = typeIri || typeLabel || 'untyped';
  if (!typeColour.has(key)) typeColour.set(key, PALETTE[typeColour.size % PALETTE.length]);
  return typeColour.get(key);
}

/** Load the graph visualization library when needed. */
async function ensureCytoscape() {
  if (cytoscapeLib) return cytoscapeLib;
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/static/vendor/cytoscape.min.js';
    script.onload = resolve;
    script.onerror = () => reject(new Error('Could not load cytoscape from static/vendor/'));
    document.head.append(script);
  });
  cytoscapeLib = window.cytoscape;
  return cytoscapeLib;
}

/** Render the interactive graph explorer. */
export async function render(container, params = {}) {
  const layout = el('div', { class: 'graph-layout' });
  const toolbar = el('div', { class: 'graph-toolbar' });
  const canvasWrap = el('div', { style: 'position:relative;flex:1 1 auto;display:flex' });
  const canvas = el('div', { id: 'cy' });
  canvasWrap.append(canvas);
  layout.append(toolbar, canvasWrap);
  container.replaceChildren(layout);

  currentMode = params.focus ? 'focus' : (params.mode || 'instances');

  const modeSelect = el('select', {
    onchange: (event) => {
      const next = event.target.value;
      const hash = next === 'focus' && params.focus
        ? `#/graph?focus=${encodeURIComponent(params.focus)}`
        : `#/graph?mode=${next}`;
      window.location.hash = hash;
    },
  }, [
    ['instances', 'Individuals'],
    ['schema', 'Classes'],
  ].map(([value, label]) => {
    const option = el('option', { value }, label);
    if (value === currentMode) option.selected = true;
    return option;
  }));
  if (currentMode === 'focus') {
    const option = el('option', { value: 'focus' }, 'Focus — neighbourhood');
    option.selected = true;
    modeSelect.prepend(option);
  }

  const depthSelect = el('select', {
    onchange: (event) => {
      window.location.hash =
        `#/graph?focus=${encodeURIComponent(params.focus)}&depth=${event.target.value}`;
    },
  }, [1, 2, 3].map((depth) => {
    const option = el('option', { value: depth }, `${depth} hop${depth > 1 ? 's' : ''}`);
    if (String(depth) === String(params.depth || 1)) option.selected = true;
    return option;
  }));

  const search = el('input', {
    type: 'search', placeholder: 'Find a node…', style: 'min-width:190px',
    oninput: (event) => filterByText(event.target.value),
  });

  const layoutSelect = el('select', {
    onchange: (event) => runLayout(event.target.value),
  }, [['cose', 'Organic'], ['concentric', 'Concentric'], ['breadthfirst', 'Hierarchy'],
    ['circle', 'Circle'], ['grid', 'Grid']].map(([value, label]) => {
    const option = el('option', { value }, label);
    if (value === (currentMode === 'schema' ? 'breadthfirst' : 'cose')) option.selected = true;
    return option;
  }));


  toolbar.append(...[
    modeSelect,
    currentMode === 'focus' ? depthSelect : null,
    search, layoutSelect,
    el('button', { class: 'ghost-btn', onclick: () => cy?.fit(undefined, 40) }, 'Fit'),
    el('span', { class: 'muted', style: 'font-size:12px;margin-left:auto' },
      'Click a node to inspect · double-click to expand'),
  ].filter(Boolean));

  clear(canvas).append(loading('Building the graph…'));

  let payload;
  try {
    payload = await api.graph(currentMode, params.focus, Number(params.depth || 1));
  } catch (error) {
    clear(canvas).append(el('div', { class: 'banner danger' }, String(error.message)));
    return;
  }

  await draw(canvas, payload, canvasWrap);

  if (params.q) await highlightQuestion(params.q);
  if (params.focus) {
    const node = cy.$id(params.focus);
    if (node.length) { node.addClass('pinned'); cy.center(node); }
  }
}

/** Draw the selected graph using Cytoscape. */
async function draw(canvas, payload, canvasWrap) {
  const cytoscape = await ensureCytoscape();
  clear(canvas);
  typeColour.clear();

  const counts = new Map();
  for (const node of payload.nodes) {
    const key = node.typeLabel || 'Untyped';
    counts.set(key, (counts.get(key) || 0) + 1);
  }

  [...counts.entries()].sort((a, b) => b[1] - a[1])
    .forEach(([label]) => colourFor(null, label));

  const elements = [
    ...payload.nodes.map((node) => ({
      data: {
        id: node.id,
        label: node.label,
        typeLabel: node.typeLabel || 'Untyped',
        colour: colourFor(null, node.typeLabel || 'Untyped'),
        size: Math.max(18, Math.min(46, 15 + node.degree * 1.6)),
        evidence: node.hasEvidence,
      },
    })),
    ...payload.edges.map((edge) => ({
      data: { id: edge.id, source: edge.source, target: edge.target, label: edge.label },
    })),
  ];

  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  cy = cytoscape({
    container: canvas,
    elements,
    wheelSensitivity: 0.25,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': 'data(colour)',
          width: 'data(size)', height: 'data(size)',
          label: 'data(label)',
          'font-size': 10,
          'font-family': '-apple-system, system-ui, sans-serif',
          color: dark ? '#e9e7e3' : '#1c1a17',
          'text-valign': 'bottom', 'text-margin-y': 4,
          'text-max-width': 130, 'text-wrap': 'ellipsis',
          'text-background-color': dark ? '#16171a' : '#f6f5f2',
          'text-background-opacity': 0.78,
          'text-background-padding': 2,
          'border-width': 0,
          'transition-property': 'opacity, border-width',
          'transition-duration': '140ms',
        },
      },
      { selector: 'node[?evidence]', style: { 'border-width': 2.5, 'border-color': dark ? '#7fc4a0' : '#2f6b4f' } },
      { selector: 'node.pinned', style: { 'border-width': 4, 'border-color': dark ? '#8fb0e8' : '#2f4b7c' } },
      { selector: 'node.match', style: { 'border-width': 4, 'border-color': '#ffa600' } },
      { selector: 'node.dim', style: { opacity: 0.12 } },
      {
        selector: 'edge',
        style: {
          width: 1.2,
          'line-color': dark ? '#474b54' : '#cec9be',
          'target-arrow-color': dark ? '#474b54' : '#cec9be',
          'target-arrow-shape': 'triangle', 'arrow-scale': 0.7,
          'curve-style': 'bezier',
          label: 'data(label)', 'font-size': 8.5,
          color: dark ? '#8d8a84' : '#7d776d',
          'text-rotation': 'autorotate',
          'text-background-color': dark ? '#16171a' : '#f6f5f2',
          'text-background-opacity': 0.85, 'text-background-padding': 1.5,
          'text-opacity': 0,
        },
      },
      { selector: 'edge.show-label', style: { 'text-opacity': 1 } },
      { selector: 'edge.dim', style: { opacity: 0.06, 'text-opacity': 0 } },
      { selector: 'edge.hot', style: { width: 2.4, 'line-color': '#ffa600', 'target-arrow-color': '#ffa600', 'text-opacity': 1 } },
    ],
  });


  cy.layout(layoutOptions(currentMode === 'schema' ? 'breadthfirst' : 'cose')).run();


  cy.on('tap', 'node', (event) => openInspector(event.target.id()));
  cy.on('dbltap', 'node', async (event) => {
    const id = event.target.id();
    window.location.hash = `#/graph?focus=${encodeURIComponent(id)}&depth=1`;
  });
  cy.on('mouseover', 'node', (event) => {
    event.target.connectedEdges().addClass('show-label');
  });
  cy.on('mouseout', 'node', (event) => {
    event.target.connectedEdges().removeClass('show-label');
  });

  canvasWrap.querySelector('.graph-legend')?.remove();
  canvasWrap.append(legend(counts));
}

/** Choose layout settings for the current graph. */
function layoutOptions(name) {


  const count = cy ? cy.nodes().length : 60;
  const roomy = count < 30;
  if (name === 'cose') {
    return {
      name: 'cose', animate: false, padding: 40,
      nodeRepulsion: roomy ? 26000 : 9000,
      idealEdgeLength: roomy ? 170 : 92,
      nodeOverlap: roomy ? 40 : 14,
      gravity: roomy ? 0.35 : 0.7,
      numIter: 1400,
      componentSpacing: roomy ? 200 : 120,
    };
  }
  if (name === 'breadthfirst') {
    return { name: 'breadthfirst', directed: true, padding: 40, spacingFactor: 1.15, animate: false };
  }
  if (name === 'concentric') {
    return {
      name: 'concentric', padding: 40, animate: false,
      concentric: (node) => node.degree(), levelWidth: () => 2,
    };
  }
  return { name, padding: 40, animate: false };
}

/** Apply a graph layout. */
function runLayout(name) {
  if (!cy) return;
  cy.layout(layoutOptions(name)).run();
}

/** Build a legend for graph resource types. */
function legend(counts) {
  const box = el('div', { class: 'graph-legend' }, el('h4', {}, 'Types — click to hide'));
  for (const [label] of [...counts.entries()].sort((a, b) => b[1] - a[1])) {
    const row = el('div', {
      class: `legend-row${hiddenTypes.has(label) ? ' off' : ''}`,
      onclick: () => {
        if (hiddenTypes.has(label)) hiddenTypes.delete(label); else hiddenTypes.add(label);
        row.classList.toggle('off');
        applyTypeFilter();
      },
    },
      el('span', { class: 'legend-dot', style: `background:${colourFor(null, label)}` }),
      el('span', {}, label));
    box.append(row);
  }
  box.append(el('div', { class: 'legend-row', style: 'margin-top:7px;border-top:1px solid var(--border);padding-top:7px;cursor:default' },
    el('span', { class: 'legend-dot', style: 'background:transparent;border:2.5px solid var(--ok)' }),
    el('span', { class: 'muted' }, 'has evidence')));
  return box;
}

/** Apply the selected graph type filters. */
function applyTypeFilter() {
  if (!cy) return;
  cy.nodes().forEach((node) => {
    node.style('display', hiddenTypes.has(node.data('typeLabel')) ? 'none' : 'element');
  });
}

/** Filter graph nodes by matching text. */
function filterByText(text) {
  if (!cy) return;
  const needle = text.trim().toLowerCase();
  cy.elements().removeClass('dim match');
  if (!needle) return;
  const matched = cy.nodes().filter((node) => node.data('label').toLowerCase().includes(needle));
  if (!matched.length) return;
  cy.elements().addClass('dim');
  matched.removeClass('dim').addClass('match');
  matched.neighborhood().removeClass('dim');
  cy.fit(matched, 90);
}

/** Highlight the resources returned by a question. */
async function highlightQuestion(questionId) {
  const question = state.questions.find((q) => q.id === questionId);
  if (!question) return;
  let payload;
  try {
    payload = await api.query(question.sparql);
  } catch { return; }

  const iris = new Set();
  for (const row of payload.result.rows) {
    for (const cell of row) {
      if (!cell) continue;
      if (cell.type === 'uri') iris.add(cell.value);
      else {
        const resolved = iriForLabel(cell.value);
        if (resolved) iris.add(resolved);
      }
    }
  }
  if (!iris.size) { toast('That question returned no resources to highlight.'); return; }

  const matched = cy.nodes().filter((node) => iris.has(node.id()));
  if (!matched.length) { toast('Those resources are not in this graph view.'); return; }
  cy.elements().addClass('dim');
  matched.removeClass('dim').addClass('match');
  matched.neighborhood().removeClass('dim');
  matched.connectedEdges().filter((edge) =>
    iris.has(edge.source().id()) && iris.has(edge.target().id())).addClass('hot').removeClass('dim');
  cy.fit(matched.union(matched.neighborhood()), 70);
  toast(`Highlighting ${matched.length} resources returned by ${question.number ? `CQ${question.number}` : question.id}.`, 3600);
}
