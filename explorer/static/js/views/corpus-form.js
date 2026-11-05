import { el, clear } from '../dom.js';
import { api } from '../api.js';

const AFG = 'https://w3id.org/ai-finance-governance#';

/** Build a project ontology IRI from a local name. */
const iri = (name) => AFG + name;

/** Choose a display label for a corpus record. */
const display = (record) => record.label || record.curie || record.iri;

/** Build a corpus form input. */
const input = (attrs = {}) => el('input', { class: 'corpus-control', type: 'text', ...attrs });

/** Build a labeled form control. */
const field = (name, control, help) => el('label', { class: 'corpus-field' },
  el('span', {}, name), control, help ? el('small', {}, help) : null);

/** Build a select control from the supplied choices. */
function select(choices, attrs = {}) {
  return el('select', { class: 'corpus-control', ...attrs },
    choices.map(([value, label]) => el('option', { value }, label)));
}

/** Read an uploaded file as a data URL. */
function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('Could not read the selected file. Please select it again.'));
    reader.readAsDataURL(file);
  });
}

/** Build the form for adding a document and supporting evidence. */
export function corpusForm(options, { document, onCancel, onSaved }) {
  const classes = Object.fromEntries(options.classes.map((c) => [c.iri, c]));

  /** Check whether a type belongs to the expected class hierarchy. */
  const isA = (types, expected) => {
    const seen = new Set();
    const pending = [...types];
    while (pending.length) {
      const type = pending.pop();
      if (type === expected) return true;
      if (seen.has(type)) continue;
      seen.add(type);
      pending.push(...(classes[type]?.parents || []));
    }
    return false;
  };
  const objectProperties = options.properties.filter((p) => p.kind === 'object');
  const dataProperties = options.properties.filter((p) => p.kind === 'data');

  /** Check whether a relationship can connect the selected types. */
  const compatible = (property, from, to) => property.domain.every((d) => isA(from, d))
    && property.range.every((r) => isA(to, r));

  /** Build available relationship choices for the selected records. */
  const linkChoices = (from, to) => objectProperties.flatMap((p) => [
    ...(compatible(p, from, to) ? [[`out|${p.iri}`, `New record → ${p.label} → linked record`]] : []),
    ...(compatible(p, to, from) ? [[`in|${p.iri}`, `Linked record → ${p.label} → new record`]] : []),
  ]);
  const targets = [...options.records, ...options.classes.map((c) => ({ ...c,
    label: `Type: ${c.label}`, types: ['http://www.w3.org/2002/07/owl#Class'] }))];
  const targetByIri = Object.fromEntries(targets.map((r) => [r.iri || r.value, r]));
  const ownerSelect = select([['', 'Choose an organisation or framework'],
    ...options.owners.map((r) => [r.value, display(r)]), ['new', '+ New organisation or framework']],
  { required: true, 'aria-label': 'Related organisation or framework', onchange: refreshOwner });
  const ownerClass = select([[iri('FinancialInstitution'), 'Financial institution'],
    [iri('RegulatoryFramework'), 'Regulatory framework']], { onchange: refreshOwner });
  const ownerName = input({ maxlength: 1000 });
  const jurisdiction = input({ maxlength: 1000 });
  const newOwner = el('div', { class: 'corpus-grid', hidden: true },
    field('Type', ownerClass), field('Name', ownerName), field('Jurisdiction (optional)', jurisdiction));

  /** Return the selected source owner types. */
  const ownerTypes = () => ownerSelect.value === 'new' ? [ownerClass.value]
    : options.owners.find((r) => r.value === ownerSelect.value)?.types || [];
  ownerSelect.value = document?.relatedResources?.find((value) => options.owners.some((r) => r.value === value)) || '';

  const snippets = [];

  /** Refresh fields when the source owner changes. */
  function refreshOwner() {
    newOwner.hidden = ownerSelect.value !== 'new';
    ownerName.required = !newOwner.hidden;
    snippets.forEach((snippet) => snippet.refreshLinks());
  }
  const title = input({ required: !document, maxlength: 1000 });
  const file = input({ type: 'file', accept: '.pdf,.html,.htm', required: !document,
    onchange: () => {
      if (!title.value) title.value = file.files[0]?.name.replace(/\.[^.]+$/, '') || '';
      if (/\.html?$/i.test(file.files[0]?.name || '')) {
        snippets.forEach((s) => { if (!s.page.value) s.page.value = 'Not paginated'; });
      }
    },
  });
  const documentClass = select([[iri('SourceDocument'), 'Source document'],
    [iri('FirmAIGovernanceDisclosure'), 'Firm AI governance disclosure']]);
  const documentType = input({ required: !document, maxlength: 1000, placeholder: 'Annual report, policy, guidance…' });
  const documentDate = input({ required: !document, maxlength: 1000, placeholder: '2026, 9 October 2026, or Not stated' });
  const documentURL = input({ type: 'url', maxlength: 5000, placeholder: 'https://…' });
  const snippetList = el('div', { class: 'corpus-snippets' });
  const topicsId = 'corpus-topics';
  const topics = el('datalist', { id: topicsId }, options.topics.map((text) => el('option', { value: text })));

  /** Add an evidence snippet editor to the form. */
  function addSnippet() {
    const quote = el('textarea', { class: 'corpus-control', rows: 4, required: true, maxlength: 25000 });
    const page = input({ required: true, maxlength: 1000, placeholder: 'PDF page 3 or Not paginated' });
    if (document?.format === 'html' || /\.html?$/i.test(file.files[0]?.name || '')) page.value = 'Not paginated';
    const section = input({ maxlength: 1000 });
    const confidence = select([
      ['Review pending; user-supplied evidence', 'Review pending'],
      ['high - user assessed', 'High (user assessed)'],
      ['medium - user assessed', 'Medium (user assessed)'],
      ['low - user assessed', 'Low (user assessed)'],
    ]);
    const mode = select([['new', 'Create a new graph record'], ['existing', 'Support an existing graph record']],
      { onchange: () => {
        existingArea.hidden = mode.value !== 'existing';
        newArea.hidden = mode.value !== 'new';
        existing.disabled = mode.value !== 'existing';
        newArea.querySelectorAll('input, select, textarea, button').forEach((c) => { c.disabled = mode.value !== 'new'; });
      } });
    const existing = select([['', 'Choose the record this quote supports'],
      ...options.records.map((r) => [r.value, display(r)])], { required: true, disabled: true });
    const existingArea = el('div', { hidden: true }, field('Supported graph record', existing));
    const recordClass = select(options.classes.map((c) => [c.iri, c.label]), { onchange: refreshRecord });
    recordClass.value = iri('GovernanceStatement');
    const name = el('textarea', { class: 'corpus-control', rows: 2, required: true, maxlength: 25000 });
    const primaryLink = select([], { required: true });
    const detailsArea = el('div', { class: 'corpus-grid' });
    let detailControls = [];
    const extraLinks = [];
    const extraList = el('div', {});

    /** Refresh compatible primary relationship choices. */
    function refreshPrimary(initial = false) {
      const previous = primaryLink.value;
      const choices = linkChoices([recordClass.value], ownerTypes());
      primaryLink.replaceChildren(el('option', { value: '' }, choices.length ? 'Choose a relationship' : 'Choose a compatible source and record type'),
        ...choices.map(([value, text]) => el('option', { value }, text)));
      primaryLink.value = choices.some(([value]) => value === previous) ? previous
        : initial ? (choices.find(([value]) => value === `in|${iri('hasStatement')}`)?.[0] || '') : '';
    }

    /** Add another relationship editor to a record. */
    function addExtraLink() {
      const target = select([['', 'Choose a linked record'], ...targets.map((r) => [r.iri || r.value, display(r)])], { required: true });
      const property = select([], { required: true });

      /** Refresh the choices for an additional relationship. */
      const refresh = () => {
        const previous = property.value;
        const choices = linkChoices([recordClass.value], targetByIri[target.value]?.types || []);
        property.replaceChildren(el('option', { value: '' }, 'Choose a relationship'),
          ...choices.map(([value, text]) => el('option', { value }, text)));
        property.value = choices.some(([value]) => value === previous) ? previous : '';
      };
      target.addEventListener('change', refresh);
      const row = el('div', { class: 'corpus-link-row' }, field('Linked record', target), field('Relationship', property),
        el('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove additional link', onclick: () => {
          extraLinks.splice(extraLinks.indexOf(entry), 1); row.remove();
        } }, '×'));
      const entry = { target, property, refresh };
      extraLinks.push(entry);
      extraList.append(row);
      refresh();
    }

    /** Refresh the fields for the selected supported record. */
    function refreshRecord() {
      const saved = Object.fromEntries(detailControls.map(({ property, control }) => [property.iri, control.value]));
      detailControls = dataProperties.filter((p) => p.iri !== iri('statementText')
        && p.domain.every((d) => isA([recordClass.value], d))).map((property) => {
        const required = isA([recordClass.value], iri('GovernanceStatement'))
          && [iri('statementTopic'), iri('statementStatus')].includes(property.iri);
        const control = input({ required, maxlength: 25000,
          ...(property.iri === iri('statementTopic') ? { list: topicsId } : {}),
        });
        control.value = saved[property.iri] || (property.iri === iri('statementStatus') ? 'User supplied; review pending' : '');
        return { property, control };
      });
      detailsArea.replaceChildren(...detailControls.map(({ property, control }) => field(property.label, control)));
      refreshPrimary(true);
      extraLinks.forEach((link) => link.refresh());
    }
    const newArea = el('div', { class: 'corpus-record' },
      el('div', { class: 'corpus-grid' }, field('Record type', recordClass),
        field('Record name or summary', name), field('Connect to related organisation or framework', primaryLink)),
      detailsArea,
      el('p', { class: 'builder-help' }, 'Choose the type and links that the quoted source supports. A governance statement keeps its topic and source status.'),
      el('details', { class: 'disclose' }, el('summary', {}, 'Additional graph links (optional)'), extraList,
        el('button', { class: 'ghost-btn', type: 'button', onclick: addExtraLink }, '+ Add graph link')));
    const row = el('section', { class: 'corpus-snippet' },
      el('div', { class: 'corpus-snippet-head' }, el('strong', {}, 'Evidence snippet'),
        el('button', { class: 'icon-btn', type: 'button', 'aria-label': 'Remove snippet', onclick: () => {
          snippets.splice(snippets.indexOf(entry), 1); row.remove();
        } }, '×')),
      field('Exact quote', quote, 'Paste the source wording, including any qualifications.'),
      el('div', { class: 'corpus-grid' }, field('Page reference', page), field('Section (optional)', section),
        field('Confidence', confidence)), field('How this snippet connects to the graph', mode), existingArea, newArea);

    /** Decode a selected relationship and its target. */
    const decodeLink = (value, target) => {
      const [direction, property] = value.split('|');
      return { direction, property, target };
    };
    const entry = { page, refreshLinks: () => refreshPrimary(), read: () => ({
      exactText: quote.value, pageReference: page.value, sectionReference: section.value, confidenceLevel: confidence.value,
      target: mode.value === 'existing' ? { iri: existing.value } : {
        classIri: recordClass.value, label: name.value,
        details: Object.fromEntries(detailControls.filter(({ control }) => control.value.trim())
          .map(({ property, control }) => [property.iri, control.value])),
        links: [decodeLink(primaryLink.value, '@owner'),
          ...extraLinks.map((link) => decodeLink(link.property.value, link.target.value))],
      },
    }) };
    snippets.push(entry);
    snippetList.append(row);
    refreshRecord();
  }

  const error = el('div', { class: 'banner danger', role: 'alert', hidden: true });
  const submit = el('button', { class: 'primary-btn', type: 'submit' }, document ? 'Save snippets and links' : 'Save document and snippets');
  const controls = el('fieldset', { class: 'corpus-controls' },
    document ? el('p', { class: 'corpus-document-title' }, document.label)
      : el('div', { class: 'corpus-grid' }, field('Document title', title),
        field('Archived file', file, 'PDF or HTML, up to 25 MB.'), field('Document category', documentClass),
        field('Document type', documentType), field('Date as printed in the source', documentDate),
        field('Original source URL (optional)', documentURL)),
    field('Related organisation or framework', ownerSelect), newOwner,
    el('p', { class: 'builder-help' }, 'The document is linked as a source for this organisation or framework. New records also connect through the relationship you select.'),
    topics, snippetList,
    el('button', { class: 'ghost-btn', type: 'button', onclick: addSnippet }, '+ Add evidence snippet'),
    el('div', { class: 'builder-add manual-actions' }, submit,
      el('button', { class: 'ghost-btn', type: 'button', onclick: onCancel }, 'Cancel')));
  const form = el('form', { class: 'builder-panel corpus-form', onsubmit: async (event) => {
    event.preventDefault();
    if (controls.disabled || !form.reportValidity()) return;
    error.hidden = true;
    controls.disabled = true;
    submit.textContent = 'Saving…';
    let saved;
    try {
      const payload = {
        owner: ownerSelect.value === 'new' ? { classIri: ownerClass.value, label: ownerName.value, jurisdiction: jurisdiction.value }
          : { iri: ownerSelect.value },
        snippets: snippets.map((s) => s.read()),
      };
      if (document) saved = await api.addSnippets(document.iri, payload);
      else {
        const selected = file.files[0];
        if (!selected || !/\.(pdf|html|htm)$/i.test(selected.name)) throw new Error('Select a PDF or HTML document.');
        if (selected.size > options.maxFileBytes) throw new Error('Documents may be at most 25 MB.');
        saved = await api.addDocument({ ...payload, title: title.value, documentClass: documentClass.value,
          documentType: documentType.value, documentDate: documentDate.value, documentURL: documentURL.value,
          file: { name: selected.name, content: await readFile(selected) } });
      }
    } catch (reason) {
      error.textContent = reason.message;
      error.hidden = false;
      controls.disabled = false;
      submit.textContent = document ? 'Save snippets and links' : 'Save document and snippets';
      error.scrollIntoView({ behavior: 'smooth', block: 'center' });
      return;
    }
    await onSaved(saved);
  } },
  el('h3', {}, document ? 'Add evidence to a document' : 'Add a document to the corpus'),
  el('p', { class: 'builder-help' }, 'Save an archived source and evidence links so they can be found in future queries.'), error, controls);
  addSnippet();
  refreshOwner();
  return form;
}
