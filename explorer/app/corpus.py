"""Validated corpus additions, persisted to the same Turtle queried by every view."""
from __future__ import annotations

import base64
import binascii
from contextlib import contextmanager
from datetime import date
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlparse
from uuid import uuid4

from pypdf import PdfReader
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, OWL, RDF, RDFS, XSD

from .graph_service import AFG, GraphService, PREFIXES
from . import views

A = lambda name: URIRef(AFG + name)
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_BODY_BYTES = 36 * 1024 * 1024
_PROVENANCE = {'hasEvidence', 'supportsAssertion', 'extractedFrom', 'observedInDocument'}
_INTERNAL_FIELDS = {'localPath', 'sha256', 'retrievalDate', 'extractionDate', 'exactText',
                    'pageReference', 'sectionReference', 'confidenceLevel', 'documentURL',
                    'documentDate', 'documentType', 'sourceDocument'}


def _text(value, name, required=False, limit=25000):
    """Validate, trim, and return a bounded text value."""
    if value is None:
        value = ''
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f'{name} must be text of at most {limit} characters.')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{name} is required.')
    return value


def _object(value, name):
    """Validate that a value is an object."""
    if not isinstance(value, dict):
        raise ValueError(f'{name} must be an object.')
    return value


def _is_a(graph, types, expected):
    """Check whether any supplied type is the expected class or a subclass."""
    return any(URIRef(expected) in set(graph.transitive_objects(URIRef(t), RDFS.subClassOf))
               for t in types)


def _types(graph, node):
    """Return the explicit non-generic types of a graph node."""
    return [str(t) for t in graph.objects(node, RDF.type) if t != OWL.NamedIndividual]


def _allowed_class(service, value):
    """Validate a class that can be created as a supported record."""
    iri = _text(value, 'Record type', True, 1000)
    if iri not in service.classes or not iri.startswith(AFG):
        raise ValueError('Choose a record type from the ontology.')
    if any(_is_a(service.graph, [iri], A(name)) for name in ('SourceDocument', 'EvidenceSnippet')):
        raise ValueError('Documents and snippets are created separately from supported records.')
    return URIRef(iri)


def corpus_options(service):
    """Return the existing resources and schema choices for corpus additions."""
    graph = service.graph
    records = []
    for node in set(graph.subjects(RDF.type, OWL.NamedIndividual)):
        types = _types(graph, node)
        if any(_is_a(graph, types, A(name)) for name in ('SourceDocument', 'EvidenceSnippet')):
            continue
        records.append({**service.describe_term(str(node)), 'types': types})
    records.sort(key=lambda r: (r.get('label') or r['curie']).lower())
    owners = [r for r in records if any(_is_a(graph, r['types'], A(name))
                                      for name in ('GovernanceActor', 'RegulatoryFramework'))]
    classes = [c for c in service.classes.values() if c['iri'].startswith(AFG)
               and not any(_is_a(graph, [c['iri']], A(name))
                           for name in ('SourceDocument', 'EvidenceSnippet'))]
    properties = [p for p in service.properties.values()
                  if p['iri'].startswith(AFG) and p['iri'][len(AFG):] not in _PROVENANCE | _INTERNAL_FIELDS]
    topics = sorted({str(v) for v in graph.objects(None, A('statementTopic'))})
    return {'owners': owners, 'records': records, 'classes': sorted(classes, key=lambda c: c['label']),
            'properties': properties, 'topics': topics, 'maxFileBytes': MAX_FILE_BYTES}


def _owner(service, payload, additions):
    """Resolve or create the source organisation or regulatory framework."""
    spec = _object(payload.get('owner'), 'Related organisation or framework')
    if spec.get('iri'):
        node = URIRef(_text(spec['iri'], 'Related resource', True, 1000))
        types = _types(service.graph, node)
        if not any(_is_a(service.graph, types, A(name))
                   for name in ('GovernanceActor', 'RegulatoryFramework')):
            raise ValueError('Choose an existing organisation or regulatory framework.')
        return node, types
    cls = URIRef(_text(spec.get('classIri'), 'Organisation or framework type', True, 1000))
    if cls not in (A('FinancialInstitution'), A('RegulatoryFramework')):
        raise ValueError('A new source organisation must be a financial institution or regulatory framework.')
    label = _text(spec.get('label'), 'Organisation or framework name', True, 1000)
    node = A('CorpusActor_' + uuid4().hex)
    additions.add((node, RDF.type, OWL.NamedIndividual))
    additions.add((node, RDF.type, cls))
    additions.add((node, RDFS.label, Literal(label)))
    jurisdiction = _text(spec.get('jurisdiction'), 'Jurisdiction', limit=1000)
    if jurisdiction:
        additions.add((node, A('jurisdiction'), Literal(jurisdiction)))
    return node, [str(cls)]


def _link(service, additions, record, record_types, spec, owner, owner_types):
    """Validate and add a relationship between compatible records."""
    spec = _object(spec, 'Graph link')
    predicate = URIRef(_text(spec.get('property'), 'Relationship', True, 1000))
    prop = service.properties.get(str(predicate))
    if not prop or prop['kind'] != 'object' or str(predicate).removeprefix(AFG) in _PROVENANCE:
        raise ValueError('Choose a supported graph relationship.')
    target_iri = _text(spec.get('target'), 'Linked record', True, 1000)
    target = owner if target_iri == '@owner' else URIRef(target_iri)
    if target == owner:
        target_types = owner_types
    else:
        target_types = _types(service.graph, target)
        if not target_types:
            raise ValueError('The linked graph record no longer exists.')

    direction = spec.get('direction', 'out')
    if direction not in ('out', 'in'):
        raise ValueError('A graph link must have an incoming or outgoing direction.')
    # Check domain and range after orienting the link, including incoming links.
    subject, obj = (record, target) if direction == 'out' else (target, record)
    subject_types, object_types = (record_types, target_types) if direction == 'out' else (target_types, record_types)
    for required in prop['domain']:
        if not _is_a(service.graph, subject_types, required):
            raise ValueError(f'The source record does not match the domain of “{prop["label"]}”.')
    for required in prop['range']:
        if not _is_a(service.graph, object_types, required):
            raise ValueError(f'The linked record does not match the range of “{prop["label"]}”.')
    additions.add((subject, predicate, obj))


def _target(service, additions, spec, owner, owner_types, document, quote):
    """Resolve or create the record supported by an evidence snippet."""
    spec = _object(spec, 'Supported record')
    if spec.get('iri'):
        node = URIRef(_text(spec['iri'], 'Supported record', True, 1000))
        types = _types(service.graph, node)
        if (node, RDF.type, OWL.NamedIndividual) not in service.graph or any(_is_a(service.graph, types, A(name)) for name in ('SourceDocument', 'EvidenceSnippet')):
            raise ValueError('Choose an existing graph record to support.')
    else:
        cls = _allowed_class(service, spec.get('classIri'))
        types = [str(cls)]
        node = A('CorpusRecord_' + uuid4().hex)
        label = _text(spec.get('label'), 'Record name or summary', True)
        additions.add((node, RDF.type, OWL.NamedIndividual))
        additions.add((node, RDF.type, cls))
        additions.add((node, RDFS.label, Literal(label)))
        details = _object(spec.get('details', {}), 'Record details')
        for iri, raw in details.items():
            prop = service.properties.get(iri)
            if not prop or prop['kind'] != 'data' or iri.removeprefix(AFG) in _INTERNAL_FIELDS:
                raise ValueError('Choose a supported detail for the new record.')
            if any(not _is_a(service.graph, types, d) for d in prop['domain']):
                raise ValueError(f'“{prop["label"]}” does not apply to this record type.')
            value = _text(raw, prop['label'])
            if value:
                datatype = URIRef(prop['range'][0]) if prop['range'] else None

                # Plain RDF literals already represent strings; retain other declared datatypes.
                if datatype == XSD.string:
                    datatype = None
                if datatype == XSD.anyURI:
                    _url(value)
                additions.add((node, URIRef(iri), Literal(value, datatype=datatype)))
        links = spec.get('links', [])
        if not isinstance(links, list) or not links or len(links) > 30:
            raise ValueError('Connect the new record to its related organisation or framework.')
        if not any(isinstance(link, dict) and link.get('target') == '@owner' for link in links):
            raise ValueError('The new record needs a link to the related organisation or framework.')
        for link in links:
            _link(service, additions, node, types, link, owner, owner_types)
        if _is_a(service.graph, types, A('GovernanceStatement')):
            for field in ('statementTopic', 'statementStatus'):
                if not additions.value(node, A(field)):
                    raise ValueError('New governance statements require a topic and source status.')
            if not additions.value(node, A('statementText')):
                additions.add((node, A('statementText'), Literal(label)))
        # Populate fields that source-specific queries rely on when no value was supplied.
        if _is_a(service.graph, types, A('DefinitionStatement')) and not additions.value(node, A('definitionText')):
            additions.add((node, A('definitionText'), Literal(quote)))
        if _is_a(service.graph, types, A('TerminologyUsage')):
            if not additions.value(node, A('usedByActor')) or not additions.value(node, A('denotesConcept')):
                raise ValueError('A terminology usage needs an actor and a mapped concept.')
            additions.add((node, A('observedInDocument'), document))
            if not additions.value(node, A('usesTerminology')):
                additions.add((node, A('usesTerminology'), Literal(label)))
    if _is_a(service.graph, types, A('GovernanceStatement')):
        additions.add((document, A('hasStatement'), node))
    return node


def _pdf_page_count(source) -> int:
    """Verify that an archived PDF can open without a password and has pages."""
    try:
        count = len(PdfReader(source).pages)
    except Exception as exc:
        raise ValueError('The PDF could not be opened. Choose a readable PDF without a password.') from exc
    if not count:
        raise ValueError('The PDF contains no pages.')
    return count


def _snippets(service, payload, additions, owner, owner_types, document, page_count=None):
    """Validate evidence snippets and add their graph statements."""
    snippets = payload.get('snippets', [])
    if not isinstance(snippets, list) or len(snippets) > 50:
        raise ValueError('Add at most 50 snippets at a time.')
    identifiers = []
    for index, spec in enumerate(snippets, 1):
        spec = _object(spec, f'Snippet {index}')
        quote = _text(spec.get('exactText'), f'Exact quote for snippet {index}', True)
        page = _text(spec.get('pageReference'), f'Page reference for snippet {index}', True, 1000)
        pdf_page = views.parse_pdf_page(page)
        if page_count is not None and (pdf_page is None or not 1 <= pdf_page <= page_count):
            raise ValueError(f'Enter a PDF page from 1 to {page_count}, for example PDF page 1.')
        if page_count is None and pdf_page is not None:
            raise ValueError('For HTML use a section, printed page, or Not paginated.')
        target = _target(service, additions, spec.get('target'), owner, owner_types, document, quote)
        node = A('CorpusEvidence_' + uuid4().hex)
        identifiers.append(str(node))
        for triple in ((node, RDF.type, OWL.NamedIndividual), (node, RDF.type, A('EvidenceSnippet')),
                       (node, RDFS.label, Literal(f'Corpus evidence: {quote[:100]}')),
                       (node, A('exactText'), Literal(quote)), (node, A('pageReference'), Literal(page)),
                       (node, A('extractedFrom'), document), (node, A('supportsAssertion'), target),
                       (target, A('hasEvidence'), node),
                       (node, A('extractionDate'), Literal(date.today(), datatype=XSD.date))):
            additions.add(triple)
        confidence = _text(spec.get('confidenceLevel') or 'Review pending; user-supplied evidence',
                           'Confidence', limit=1000)
        additions.add((node, A('confidenceLevel'), Literal(confidence)))
        section = _text(spec.get('sectionReference'), 'Section reference', limit=1000)
        if section:
            additions.add((node, A('sectionReference'), Literal(section)))
    return identifiers


def _url(value):
    """Validate and return an optional document URL."""
    if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
        raise ValueError('Source URLs must start with http:// or https:// and include a host.')
    return value


@contextmanager
def _write_lock(service):
    """Lock a stable sibling inode because the Turtle file is atomically replaced."""
    with service._lock, service.ontology.with_suffix('.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        # Closing the descriptor releases the OS lock, including on process exit.
        yield


def _append(service, additions):
    """Append without reformatting existing Turtle; never replace a concurrent edit."""
    path = service.ontology
    stamp = service._stamps
    if service._current_stamps() != stamp:
        raise ValueError('The ontology changed while saving. Please try again.')
    original = path.read_text(encoding='utf-8')
    for prefix, namespace in PREFIXES.items():
        additions.bind(prefix or 'afg', namespace)
    text = original + '\n\n# Added through the Explorer Corpus page.\n' + additions.serialize(format='turtle')
    # Parse the combined content before replacing the working ontology.
    Graph().parse(data=text, format='turtle')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.corpus-', suffix='.ttl', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # Detect edits made while the replacement was being prepared.
        if service._current_stamps() != stamp:
            raise ValueError('The ontology changed while saving. Your form is kept; please try again.')
        temporary.chmod(path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def save_document(service: GraphService, payload: dict):
    """Validate, archive, and record a new source document and its evidence."""
    payload = _object(payload, 'Document')
    title = _text(payload.get('title'), 'Document title', True, 1000)
    file = _object(payload.get('file'), 'Archived file')
    name = Path(_text(file.get('name'), 'File name', True, 1000).replace('\\', '/')).name
    suffix = Path(name).suffix.lower()
    if suffix not in ('.pdf', '.html', '.htm'):
        raise ValueError('Upload a PDF or HTML document.')
    encoded = _text(file.get('content'), 'File content', True, (MAX_FILE_BYTES + 2) // 3 * 4)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError('The uploaded file could not be decoded.') from exc
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError('Documents must contain data and be at most 25 MB.')
    if suffix == '.pdf' and not data.startswith(b'%PDF-'):
        raise ValueError('The uploaded file is not a PDF.')
    page_count = _pdf_page_count(BytesIO(data)) if suffix == '.pdf' else None
    if suffix != '.pdf':
        try:
            data.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('HTML documents must use UTF-8 text encoding.') from exc
    document_class = URIRef(_text(payload.get('documentClass'), 'Document category', True, 1000))
    if document_class not in (A('SourceDocument'), A('FirmAIGovernanceDisclosure')):
        raise ValueError('Choose a source document or firm disclosure.')
    digest = hashlib.sha256(data).hexdigest()
    source_url = _url(_text(payload.get('documentURL'), 'Source URL', limit=5000))
    with _write_lock(service):
        service.ensure_fresh()
        duplicate = service.graph.value(predicate=A('sha256'), object=Literal(digest))
        if duplicate:
            raise ValueError(f'This file is already in the corpus as “{service.labels.get(str(duplicate), str(duplicate))}”. Use Add snippets on that document.')
        additions = Graph()
        owner, owner_types = _owner(service, payload, additions)
        if document_class == A('FirmAIGovernanceDisclosure') and not _is_a(service.graph, owner_types, A('FinancialInstitution')):
            raise ValueError('A firm disclosure must be linked to a financial institution.')
        document = A('CorpusDocument_' + uuid4().hex)
        safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', Path(name).stem)[:100] + suffix
        relative = Path('corpus/uploads') / (uuid4().hex + '-' + safe_name)
        archive = (service.root / relative).resolve()
        if not archive.is_relative_to((service.root / 'corpus').resolve()):
            raise ValueError('The upload destination must be inside the corpus.')
        for triple in ((document, RDF.type, OWL.NamedIndividual), (document, RDF.type, document_class),
                       (document, RDFS.label, Literal(title)), (document, A('localPath'), Literal(relative.as_posix())),
                       (document, A('sha256'), Literal(digest)),
                       (document, A('retrievalDate'), Literal(date.today(), datatype=XSD.date)),
                       (owner, DCTERMS.source, document)):
            additions.add(triple)
        if document_class == A('FirmAIGovernanceDisclosure'):
            additions.add((owner, A('hasGovernanceDisclosure'), document))
        for field, value in (('documentURL', source_url), ('documentDate', _text(payload.get('documentDate'), 'Document date', True, 1000)),
                             ('documentType', _text(payload.get('documentType'), 'Document type', True, 1000))):
            if value:
                additions.add((document, A(field), Literal(value, datatype=XSD.anyURI if field == 'documentURL' else None)))
        snippets = _snippets(service, payload, additions, owner, owner_types, document, page_count)
        archive.parent.mkdir(parents=True, exist_ok=True)
        # Write the file first, then remove it if the ontology update fails.
        handle = archive.open('xb')
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            _append(service, additions)
        except Exception:
            archive.unlink(missing_ok=True)
            raise
        service.reload(force=True)
        return {'document': views.document_record(service, str(document)), 'snippets': snippets,
                'owner': str(owner), 'triplesAdded': len(additions)}


def add_snippets(service: GraphService, document_iri: str, payload: dict):
    """Add validated evidence to an existing source document."""
    payload = _object(payload, 'Evidence')
    with _write_lock(service):
        service.ensure_fresh()
        document = URIRef(_text(document_iri, 'Document', True, 1000))
        record = views.document_record(service, str(document))
        if not record or not record['exists']:
            raise ValueError('Choose a document with an existing archive.')
        page_count = (_pdf_page_count(service.root / record['localPath']) if record['format'] == 'pdf' else None)
        additions = Graph()
        owner, owner_types = _owner(service, payload, additions)
        snippets = _snippets(service, payload, additions, owner, owner_types, document, page_count)
        if not snippets:
            raise ValueError('Add at least one evidence snippet.')
        additions.add((owner, DCTERMS.source, document))
        _append(service, additions)
        service.reload(force=True)
        return {'document': views.document_record(service, str(document)), 'snippets': snippets,
                'owner': str(owner), 'triplesAdded': len(additions)}
