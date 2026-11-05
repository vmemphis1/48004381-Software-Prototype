const AFG = 'https://w3id.org/ai-finance-governance#';

/** Format an IRI as a project-prefixed or absolute SPARQL term. */
const term = (iri) => iri.startsWith(AFG) ? `:${iri.slice(AFG.length)}` : `<${iri}>`;

/** Compile a guided builder plan into a SPARQL query and projected columns. */
export function compile(plan) {
  const nodes = [{ var: 'record', iri: plan.rootClass }];
  const values = [];
  const lines = [`  ?record rdf:type/rdfs:subClassOf* ${term(plan.rootClass)} .`];
  for (const step of plan.steps) {
    const variable = `${step.kind === 'relation' ? 'linked' : 'field'}${step.id}`;
    const triple = `?${step.from} ${term(step.property)} ?${variable} .`;
    if (step.kind === 'relation') {
      lines.push(`  ${triple}`);
      if (step.range) lines.push(`  ?${variable} rdf:type/rdfs:subClassOf* ${term(step.range)} .`);
      nodes.push({ var: variable, iri: step.range, label: step.propertyLabel });
    } else {
      if (step.op === 'absent') {
        lines.push(`  FILTER NOT EXISTS { ${triple} }`);
        continue;
      }
      lines.push(step.op === 'show' ? `  OPTIONAL { ${triple} }` : `  ${triple}`);
      if (step.op === 'is') {
        lines.push(`  FILTER(STR(?${variable}) = ${JSON.stringify(step.value)})`);
      }
      values.push({ var: variable, label: step.propertyLabel });
    }
  }
  const projected = [...nodes, ...values].filter((n) => !plan.hidden?.has(n.var)).map((n) => `?${n.var}`);
  if (!projected.length) projected.push('?record');
  return {
    nodes, values,
    sparql: [
      'PREFIX : <https://w3id.org/ai-finance-governance#>',
      'PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>',
      'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>',
      '', `SELECT DISTINCT ${projected.join(' ')}`, 'WHERE {', ...lines, '}',
      `ORDER BY ${projected[0]}`,
    ].join('\n'),
  };
}
