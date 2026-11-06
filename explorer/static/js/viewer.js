import { el, qs, clear, toast } from './dom.js';
import { quoteRanges } from './quote-match.js';
import { docUrl } from './api.js';

let pdfjs = null;
let doc = null;
let loadingTask = null;
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
  ++renderToken;
  view().hidden = true;
  clear(stage());
  loadingTask?.destroy();
  loadingTask = null;
  doc = null;
  currentDoc = null;
  pendingQuote = null;
}

/** Open an archived document at its referenced page and quote. */
export async function openDocument(document_, { page, quote, caption } = {}) {
  closeViewer();
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

  for (const id of ['#viewer-pager', '#viewer-zoom-in', '#viewer-zoom-out']) qs(id).hidden = true;
  if (document_.format === 'pdf') {
    await openPdf(document_);
  } else {
    openHtml(document_, quote);
  }
}

/** Load an archived PDF into the viewer. */
async function openPdf(document_) {
  // Discard a slower PDF load if another render was started in the meantime.
  const token = ++renderToken;
  try {
    const lib = await ensurePdfjs();


    if (token !== renderToken) return;
    const assets = '/static/vendor/';
    loadingTask = lib.getDocument({ url: docUrl(document_.localPath),
      cMapUrl: assets + 'cmaps/', standardFontDataUrl: assets + 'standard_fonts/',
      wasmUrl: assets + 'wasm/', iccUrl: assets + 'iccs/',
    });
    const loaded = await loadingTask.promise;
    if (token !== renderToken) return;
    doc = loaded;
  } catch (error) {
    if (token !== renderToken) return;
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
  try {
    await drawPage(token);
  } catch (error) {
    if (token === renderToken) clear(stage()).append(el('div', { class: 'banner danger' },
      `Could not render page ${pageNumber}: ${error.message}`));
  }
}

async function drawPage(token) {
  qs('#page-num').value = String(pageNumber);

  const page = await doc.getPage(pageNumber);
  if (token !== renderToken) return;

  const viewport = page.getViewport({ scale });
  const ratio = window.devicePixelRatio || 1;

  const canvas = el('canvas');
  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${Math.floor(viewport.width)}px`;
  canvas.style.height = `${Math.floor(viewport.height)}px`;

  const textLayer = el('div', { class: 'pdf-text' });
  textLayer.style.width = `${Math.floor(viewport.width)}px`;
  textLayer.style.height = `${Math.floor(viewport.height)}px`;

  textLayer.style.setProperty('--total-scale-factor', String(scale * page.userUnit));

  const wrap = el('div', { class: 'pdf-page' }, canvas, textLayer);
  clear(stage()).append(wrap);

  await page.render({ canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] }).promise;
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

function highlight(container, quote) {
  const spans = [...container.querySelectorAll('span[role="presentation"]')];
  const ranges = quoteRanges(spans.map(span => span.textContent
    + (span.nextElementSibling?.tagName === 'BR' ? '\n' : '')), quote);
  for (const { index } of ranges) spans[index].classList.add('hit');
  if (ranges.length) spans[ranges[0].index].scrollIntoView({ block: 'center' });
  return ranges.length > 0;
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
    if (!quote || !frame.isConnected) return;
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
  const walker = inner.createTreeWalker(inner.body, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement?.closest('script,style,noscript,template,[hidden],ix\\:hidden')
        && node.textContent.trim()) nodes.push(node);
  }
  const ranges = quoteRanges(nodes.map(node => node.textContent), quote);
  let first;
  // Split from the end so earlier offsets in the same text node remain valid.
  for (const { index, start, end } of ranges.reverse()) {
    const range = inner.createRange();
    range.setStart(nodes[index], start);
    range.setEnd(nodes[index], end);
    first = inner.createElement('mark');
    first.className = 'afg-hit';
    range.surroundContents(first);
  }
  first?.scrollIntoView({ block: 'center' });
  return Boolean(first);
}

/** Navigate to a PDF page. */
function goTo(next) {
  if (!doc) return;
  pageNumber = Math.min(Math.max(1, Number.isFinite(next) ? Math.trunc(next) : pageNumber), doc.numPages);
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
  if (event.key === 'Escape') { event.stopImmediatePropagation(); closeViewer(); return; }
  if (event.target.tagName === 'INPUT') return;
  if (event.key === 'ArrowRight' || event.key === 'PageDown') goTo(pageNumber + 1);
  if (event.key === 'ArrowLeft' || event.key === 'PageUp') goTo(pageNumber - 1);
});

export { currentDoc };
