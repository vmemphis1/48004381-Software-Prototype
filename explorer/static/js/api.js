/** Send a request to the local API and return the decoded response. */
async function request(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json().catch(() => ({ error: response.statusText }));
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

export const api = {

  /** Fetch the server status. */
  status:    () => request('/api/status'),

  /** Fetch the question pack. */
  questions: () => request('/api/questions'),

  /** Fetch the ontology schema. */
  schema:    () => request('/api/schema'),

  /** Fetch choices for a partial builder query. */
  builderOptions: (sparql) => request('/api/builder-options', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sparql }),
  }),

  /** Fetch archived document records. */
  documents: () => request('/api/documents'),

  /** Fetch choices for corpus additions. */
  corpusOptions: () => request('/api/corpus/options'),

  /** Archive a document and its evidence. */
  addDocument: (payload) => request('/api/corpus/documents', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }),

  /** Add evidence to an existing document. */
  addSnippets: (documentIri, payload) => request('/api/corpus/snippets', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ...payload, documentIri }),
  }),

  /** Fetch lookup indexes. */
  indexes:   () => request('/api/indexes'),

  /** Fetch details for an ontology resource. */
  resource:  (iri) => request(`/api/resource?iri=${encodeURIComponent(iri)}`),

  /** Fetch evidence for a resource or the corpus. */
  evidence:  (iri) => request(`/api/evidence${iri ? `?iri=${encodeURIComponent(iri)}` : ''}`),

  /** Fetch a graph view with optional focus and depth. */
  graph: (mode, focus, depth = 1) => {
    const params = new URLSearchParams({ mode, depth: String(depth) });
    if (focus) params.set('focus', focus);
    return request(`/api/graph?${params}`);
  },

  /** Execute a SPARQL query. */
  query: (sparql) =>
    request('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sparql }),
    }),

  /** Reload the ontology graph. */
  reload: () => request('/api/reload', { method: 'POST' }),
};

/** Build the local URL for an archived document. */
export const docUrl = (localPath) => `/doc?path=${encodeURIComponent(localPath)}`;
