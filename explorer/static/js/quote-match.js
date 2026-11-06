/** Find complete, ordered excerpts and map them back to the original text nodes. */
function compact(text) {
  return text.toLowerCase().replace(/[‘’ʼ]/g, "'").replace(/[“”]/g, '"')
    .replace(/[‐-―−]/g, '-').replace(/ﬁ/g, 'fi').replace(/ﬂ/g, 'fl').replace(/\s+/gu, '');
}

export function quoteRanges(parts, quote) {
  const runs = quote.split(/\.\.\.|…/).map(run => compact(run.replace(/^[\s;:,]+|[\s;:,]+$/g, ''))).filter(Boolean);
  if (!runs.length) return [];

  // First preserve printed hyphens. Retry with line-end hyphenation removed.
  for (const repair of [false, true]) {
    const chunks = parts.map(text => compact(repair ? text.replace(/[-‐-―]\s*\n\s*/g, '') : text));
    const source = chunks.join('');
    let cursor = 0;
    const hits = [];
    for (const run of runs) {
      const start = source.indexOf(run, cursor);
      if (start < 0) break;
      cursor = start + run.length;
      hits.push([start, cursor]);
    }
    if (hits.length !== runs.length) continue;

    const ranges = [];
    let offset = 0;
    for (let index = 0; index < chunks.length; index++) {
      const end = offset + chunks[index].length;
      const overlaps = hits.filter(([a, b]) => a < end && b > offset);
      if (end > offset && overlaps.length) {
        const raw = parts[index];
        const skipped = new Set();
        if (repair) {
          for (const match of raw.matchAll(/[-‐-―]\s*\n\s*/g)) skipped.add(match.index);
        }
        const offsets = [];
        for (let i = 0; i < raw.length; i++) {
          if (!skipped.has(i)) {
            for (let n = compact(raw[i]).length; n > 0; n--) offsets.push(i);
          }
        }
        for (const [a, b] of overlaps) ranges.push({
          index, start: offsets[Math.max(a - offset, 0)],
          end: offsets[Math.min(b, end) - offset - 1] + 1,
        });
      }
      offset = end;
    }
    return ranges;
  }
  return [];
}
