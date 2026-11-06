# Explorer audit · 6 November 2026

The audit started from commit `47e9691` and covered the local explorer, its ontology, query pack, glossary, archive, and verification scripts. The results below describe the working tree after the fixes. The [README](README.md) includes the commands to repeat the repository checks.

## Verification

| Check | Observed result |
| --- | --- |
| Clean installation and startup | The documented launcher served the app on port 8042 from a fresh project virtual environment. The status endpoint reported no stale Python modules or question-coverage issues. |
| Automated regression suite | 39 tests passed using Python 3.14 and Node.js 24. |
| Query pack | All 21 queries ran through the command-line runner and live HTTP API. All ten competency questions have query files. CQ7 returned zero rows, the documented gap for explicit framework references in firm policies. |
| Data integrity | Checked all 32 registered archive files against their SHA-256 digests, checked for unregistered archives, and resolved all 26 glossary mappings. The project graph contains 2,668 triples and seven sampled firms. |
| Evidence | The text verifier located all 94 quotations. Headless Chromium independently opened every citation in the local viewer and highlighted the complete quotation or its ordered excerpts. |
| Browser workflows | Exercised all five tabs, resource inspection, graph highlighting, guided and manual queries, bookmark saving and reopening, and PDF and HTML previews. Tested document upload, adding snippets, and persistence after a browser refresh on an isolated copy at a mobile viewport. |
| HTTP and write integrity | Exercised normal and invalid byte ranges, archive path confinement, invalid request bodies, origin and host checks, query edits while the server was running, concurrent additions, duplicate uploads, and rollback after write failure. |

## Corrections

- Explore and Graph now execute the current question file. Label links come from the graph that produced the result. Graph navigation and preview changes discard obsolete asynchronous responses.
- The evidence viewer requires the whole quote, handles inline HTML elements, and respects excerpt order. The headless verifier excludes hidden HTML and checks the specific cited PDF page. The clean installation now includes the AES dependency needed to read the archived PDFs.
- The advanced editor returns triples for DESCRIBE and CONSTRUCT and preserves unbound SELECT results. HTTP queries and the CLI use the local graph and reject external SERVICE and FROM clauses.
- Corpus writers coordinate across explorer processes. Uploads reject unreadable PDFs and out-of-range PDF citations. An uploaded source may omit its original URL and still pass the provenance audit.
- Corrected ontology declarations that could infer a financial-institution class was a source document or a framework was a terminology-usage record. The structural audit now checks populated property domains and ranges.
- CQ1 requires a public policy URL and shows the firm's recorded jurisdiction. The graph captures home jurisdiction, so it can only partially answer the question about operating in Australia. CQ3 shows the source wording and distinguishes voluntary guidance from the EU provision. Results retain the recorded confidence qualifiers.
- Updated the bundled PDF.js and Cytoscape libraries and verified the npm distribution hashes. Updated the Python dependency requirements and tested them in a fresh virtual environment.

## External sources and coverage limits

Three recorded publication URLs returned HTTP 404. Their replacements returned HTTP 200 and identify the same publications. [APRA CPG 234](https://www.apra.gov.au/practice-guides/cpg-234) · [NIST AI RMF 1.0](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10) · [NIST Generative AI Profile](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence)

Nine ANZ, HSBC, or SEC links returned HTTP 403 to automated requests. EUR-Lex returned HTTP 202. The local archive checks cover those files. Live publisher content behind those responses remains unverified.

Browser verification used Chromium on macOS, including a mobile viewport. Native mobile browsers, Safari, Firefox, and Windows were outside the execution matrix. The research corpus is a dated collection of public sources. This audit checked traceability to those sources and did not reassess current law or independently adjudicate each governance claim.
