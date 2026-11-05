# Explorer
## Dependencies and setup

The prototype needs Python 3 and a modern web browser. Its Python dependencies
are listed in `scripts/requirements.txt`: `rdflib>=7.0,<8` runs the graph and
queries, and `pypdf>=5.0` is used by the evidence verification script. The
browser libraries Cytoscape.js and PDF.js are included in the repository.

From a terminal in the repository root, create a virtual environment and install
the Python dependencies (Python 3.14 has been used for this project):

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r scripts/requirements.txt
```

The launcher uses Bash and `lsof` to detect an existing server on its port.
It attempts to install the requirements if `rdflib` cannot be imported, but
installing them explicitly also ensures that `pypdf` is available.

## Run the prototype

With the virtual environment active, run:

```bash
explorer/run.sh
```

The server opens the explorer at <http://127.0.0.1:8042/>. Press Ctrl+C in the
terminal to stop it. To choose another port, use `explorer/run.sh --port 8043`, for example.

To run the test suite, also install Node.js (version 24 has been used for this
project) and run `python3 -m unittest discover -s explorer/tests -v`.

**Explore** — the default landing view. It shows the ten competency questions
and supporting queries as cards, followed by **Bookmarks** for your saved Build
queries. Select a card to run it, inspect a result and open its source. Select
the active card again to hide its results. A bookmark
can also be reopened in Build or removed from the list.

**Build a question** — choose a populated record type, follow recorded links,
and filter by values that actually exist in the matching records. Each step's
choices and counts come from executing the preceding steps, so an unused schema
relationship cannot send a new question straight to an empty result. Changing
a step keeps later selections when they still match; the first invalid choice
and its later steps are cleared with an explanation. Removing a step also
removes later steps.

**Graph** — the populated individuals, the class hierarchy, or the neighbourhood
of one resource. Click a node to inspect it, double-click to re-centre on it.
Nodes with provenance carry a green ring. "See in graph" from a result
highlights exactly the resources that question returned.

**Schema** — the class hierarchy and property vocabulary. Open a resource to
see its recorded scope and properties.

**Corpus** — the archived regulatory and firm documents and what each one yielded.
Use **Add document** to archive a PDF or UTF-8 HTML file (up to 25 MB), record its
title, type, source date and optional URL, and choose its related organisation
or regulatory framework. You can also create a new institution or framework.
Add exact quotations with page/section references and confidence, then either
support an existing graph record or create a typed record and choose its
relationship to the source organisation. Additional links can connect a policy
to a framework, a definition to a concept, and other compatible records.
New governance statements include a topic and source status so the persona
queries can find them. Evidence defaults to review pending.
