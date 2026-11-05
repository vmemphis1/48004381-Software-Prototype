import { el, qs, clear, toast } from './dom.js';
import { docUrl } from './api.js';

let pdfjs = null;
let doc = null;
let currentDoc = null;
let pageNumber = 1;
let scale = 1.25;
let pendingQuote = null;
let renderToken = 0;

/** Find the document viewer element. */
const view = () => qs('#viewer');

/** Find the document preview stage. */
const stage = () => qs('#viewer-stage');

/** Load the PDF viewer library when needed. */
async function ensurePdfjs() {
  if (pdfjs) return pdfjs;
  pdfjs = await import('/static/vendor/pdf.min.mjs');
  pdfjs.GlobalWorkerOptions.workerSrc = '/static/vendor/pdf.worker.min.mjs';
  return pdfjs;
}

/** Close the current document preview. */
export function closeViewer() {
  view().hidden = true;
  clear(stage());
  doc?.destroy?.();
  doc = null;
  currentDoc = null;
  pendingQuote = null;
}

/** Open an archived document at its referenced page and quote. */
export async function openDocument(document_, { page, quote, caption } = {}) {
  currentDoc = document_;
  pendingQuote = quote || null;
  pageNumber = page || 1;

  view().hidden = false;
  qs('#viewer-title').textContent = document_.label;
  qs('#viewer-sub').textContent = [document_.documentType, caption].filter(Boolean).join(' · ');

  const source = qs('#viewer-source');
  source.hidden = !document_.documentURL;
  if (document_.documentURL) source.href = document_.documentURL;

  const quoteBar = qs('#viewer-quote');
  if (quote) {
    quoteBar.hidden = false;
    quoteBar.replaceChildren(
      el('span', { class: 'label' }, 'Cited text'),
      el('span', {}, `“${quote}”`),
    );
  } else {
    quoteBar.hidden = true;
  }

  clear(stage()).append(el('div', { class: 'viewer-loading' },
    el('span', { class: 'spinner' }), ' Opening archived copy…'));

  if (document_.format === 'pdf') {
    await openPdf(document_);
  } else {
    openHtml(document_, quote);
  }
}

/** Load an archived PDF into the viewer. */
async function openPdf(document_) {
  const token = ++renderToken;
  try {
    const lib = await ensurePdfjs();


    const task = lib.getDocument({ url: docUrl(document_.localPath) });
    const loaded = await task.promise;
    if (token !== renderToken) { loaded.destroy(); return; }
    doc = loaded;
  } catch (error) {
    clear(stage()).append(el('div', { class: 'banner danger' },
      `Could not open the PDF: ${error.message}`));
    return;
  }

  qs('#viewer-pager').hidden = false;
  qs('#viewer-zoom-in').hidden = false;
  qs('#viewer-zoom-out').hidden = false;
  qs('#page-total').textContent = `/ ${doc.numPages}`;
  pageNumber = Math.min(Math.max(1, pageNumber), doc.numPages);
  await renderPage();
}

/** Render the selected PDF page and its evidence highlight. */
async function renderPage() {
  if (!doc) return;
  const token = ++renderToken;
  qs('#page-num').value = String(pageNumber);

  const page = await doc.getPage(pageNumber);
  if (token !== renderToken) return;

  const viewport = page.getViewport({ scale: scale * (window.devicePixelRatio > 1 ? 1 : 1) });
  const ratio = window.devicePixelRatio || 1;

  const canvas = el('canvas');
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;

  const textLayer = el('div', { class: 'pdf-text' });
  textLayer.style.width = `${Math.floor(viewport.width)}px`;
  textLayer.style.height = `${Math.floor(viewport.height)}px`;

  textLayer.style.setProperty('--scale-factor', String(scale));

  const wrap = el('div', { class: 'pdf-page' }, canvas, textLayer);
  clear(stage()).append(wrap);

  const context = canvas.getContext('2d');
  context.scale(ratio, ratio);
  try {
    await page.render({ canvasContext: context, viewport }).promise;
  } catch (error) {


    if (error?.name === 'RenderingCancelledException') return;
    throw error;
  }
  if (token !== renderToken) return;

  try {
    const layer = new pdfjs.TextLayer({
      textContentSource: page.streamTextContent(),
      container: textLayer,
      viewport,
    });
    await layer.render();
  } catch (error) {


    console.warn('text layer failed', error);
    toast('This page rendered, but its text layer could not be built, so the quote is not highlighted.', 4200);
    return;
  }
  if (token !== renderToken) return;

  if (pendingQuote) {
    const found = highlight(textLayer, pendingQuote);
    if (!found) {
      toast('The cited text is not on this page as a contiguous run — the page is shown unhighlighted.', 4200);
    }
  }
}

/** Normalize text for matching evidence quotations. */
function normalise(text) {
  return text
    .replace(/[‘’ʼ]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[‐-―−]/g, '-')
    .replace(/ﬁ/g, 'fi').replace(/ﬂ/g, 'fl')
    .replace(/ /g, ' ')
    .toLowerCase();
}

/** Split an evidence quote into matchable text runs. */
function quoteRuns(quote) {
  return quote
    .split(/\.\.\.|…/)
    .map((part) => part.replace(/^[\s;:,]+|[\s;:,]+$/g, ''))
    .filter(Boolean);
}

/** Highlight a quote within rendered PDF text. */
function highlight(container, quote) {
  const spans = [...container.querySelectorAll('span')];
  if (!spans.length) return false;

  let joined = '';
  const owner = [];
  let compact = '';
  const compactOwner = [];
  let lastWasSpace = true;
  spans.forEach((span, index) => {
    for (const character of `${normalise(span.textContent)} `) {
      if (/\s/.test(character)) {
        if (lastWasSpace) continue;
        joined += ' '; owner.push(index); lastWasSpace = true;
      } else {
        joined += character; owner.push(index); lastWasSpace = false;
        compact += character; compactOwner.push(index);
      }
    }
  });

  /** Find the text spans covering a quote run. */
  const locate = (run) => {
    const at = joined.indexOf(run);
    if (at !== -1) return new Set(owner.slice(at, at + run.length));
    const squeezed = run.replace(/\s+/g, '');
    const compactAt = compact.indexOf(squeezed);
    if (compactAt !== -1) {
      return new Set(compactOwner.slice(compactAt, compactAt + squeezed.length));
    }
    return null;
  };

  const target = normalise(quote).replace(/\s+/g, ' ').trim();
  const runs = quoteRuns(target);

  if (runs.length > 1) {
    const marked = runs.map(locate).filter(Boolean);
    if (!marked.length) return false;
    marked.forEach((hit) => hit.forEach((index) => spans[index].classList.add('hit')));
    const first = Math.min(...marked.flatMap((hit) => [...hit]));
    spans[first].scrollIntoView({ block: 'center', behavior: 'smooth' });
    return true;
  }

  const attempts = [target];
  const words = target.split(' ');
  for (const count of [14, 10, 7, 5]) {
    if (words.length > count) attempts.push(words.slice(0, count).join(' '));
  }

  for (const attempt of attempts) {
    const hit = locate(attempt);
    if (!hit) continue;
    hit.forEach((index) => spans[index].classList.add('hit'));
    spans[Math.min(...hit)].scrollIntoView({ block: 'center', behavior: 'smooth' });
    return true;
  }
  return false;
}

/** Open an archived HTML document in the preview. */
function openHtml(document_, quote) {
  qs('#viewer-pager').hidden = true;
  qs('#viewer-zoom-in').hidden = true;
  qs('#viewer-zoom-out').hidden = true;


  const frame = el('iframe', {
    src: docUrl(document_.localPath),
    sandbox: 'allow-same-origin',
    title: document_.label,
  });
  clear(stage()).append(frame);

  frame.addEventListener('load', () => {
    if (!quote) return;
    try {
      const inner = frame.contentDocument;
      if (!inner) return;
      const style = inner.createElement('style');
      style.textContent = 'mark.afg-hit{background:#ffe9a8;box-shadow:0 0 0 3px #ffe9a8;border-radius:2px;}';
      inner.head?.append(style);
      if (!markInDocument(inner, quote)) {
        toast('The cited text was not found verbatim in this file — showing the page unhighlighted.', 4200);
      }
    } catch {

    }
  });
}

/** Highlight a quote in an archived HTML document. */
function markInDocument(inner, quote) {
  const target = normalise(quote).replace(/\s+/g, ' ').trim().slice(0, 90);
  const walker = inner.createTreeWalker(inner.body, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const at = normalise(node.textContent).replace(/\s+/g, ' ').indexOf(target.slice(0, 40));
    if (at === -1) continue;
    const mark = inner.createElement('mark');
    mark.className = 'afg-hit';
    const range = inner.createRange();
    range.setStart(node, Math.max(0, at));
    range.setEnd(node, Math.min(node.textContent.length, at + target.length));
    try {
      range.surroundContents(mark);
      mark.scrollIntoView({ block: 'center' });
      return true;
    } catch {
      node.parentElement?.scrollIntoView({ block: 'center' });
      return true;
    }
  }
  return false;
}

/** Navigate to a PDF page. */
function goTo(next) {
  if (!doc) return;
  pageNumber = Math.min(Math.max(1, next), doc.numPages);
  pendingQuote = null;
  renderPage();
}

qs('#viewer-close').addEventListener('click', closeViewer);
qs('#page-prev').addEventListener('click', () => goTo(pageNumber - 1));
qs('#page-next').addEventListener('click', () => goTo(pageNumber + 1));
qs('#page-num').addEventListener('change', (event) => goTo(Number(event.target.value)));
qs('#viewer-zoom-in').addEventListener('click', () => { scale = Math.min(3, scale + 0.25); renderPage(); });
qs('#viewer-zoom-out').addEventListener('click', () => { scale = Math.max(0.5, scale - 0.25); renderPage(); });

document.addEventListener('keydown', (event) => {
  if (view().hidden) return;
  if (event.key === 'Escape') closeViewer();
  if (event.target.tagName === 'INPUT') return;
  if (event.key === 'ArrowRight' || event.key === 'PageDown') goTo(pageNumber + 1);
  if (event.key === 'ArrowLeft' || event.key === 'PageUp') goTo(pageNumber - 1);
});

export { currentDoc };
