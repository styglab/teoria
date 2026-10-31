"""Source-backed target names, descriptive text and contextual aliases; never merge IDs."""
from pydantic import BaseModel, ConfigDict, Field
from teoria.features.specification_processing.parsing.document_evidence import literal


class TargetName(BaseModel):
    model_config = ConfigDict(extra='forbid')
    entity_id: str
    name: str = Field(min_length=1)
    aliases: list[tuple[str, str]] = Field(default_factory=list)  # node ID, source name
    descriptions: list[tuple[str, str]] = Field(default_factory=list)


def validate_target_names(observations, labels, nodes, allowed, *, kinds=None):
    errors, seen = [], set()
    for observation in observations:
        identifier = observation.entity_id
        if identifier not in labels or identifier in seen:
            errors.append('invalid or repeated name target')
            continue
        seen.add(identifier)
        if not literal(observation.name) or literal(observation.name) not in literal(labels[identifier]):
            errors.append('core name must be a source span of the frozen original name')
        if (kinds or {}).get(identifier) in {'product','material'} and literal(observation.name)!=literal(labels[identifier]):
            errors.append('product and material names must retain the original variant; use aliases without shortening')
        for node_id, text in [*observation.aliases, *observation.descriptions]:
            if node_id not in allowed or not literal(text) or literal(text) not in literal(nodes[node_id]['text']):
                errors.append('name observation lacks source evidence')
    return errors


def apply_target_names(entities, observations, document):
    nodes = {n['node_id']: n for n in document['nodes']}
    lookup = {e['id']: e for e in entities}
    for observation in observations:
        entity = lookup[observation.entity_id]
        original = entity['name']
        entity['name_raw'] = original
        entity['name'] = observation.name
        def evidence(node_id, text):
            return {'node_id': node_id, 'quote': text, 'native_ref': nodes[node_id].get('native_ref')}
        aliases = list(observation.aliases)
        if literal(original) != literal(observation.name):
            aliases.insert(0, (entity['evidence'][0]['node_id'], original))
        seen = {literal(observation.name)}
        entity['aliases'] = []
        for node_id, text in aliases:
            if literal(text) in seen:
                continue
            entity['aliases'].append({'name': text, 'evidence': [evidence(node_id, text)]})
            seen.add(literal(text))
        entity['descriptions'] = [{'text': text, 'evidence': [evidence(node_id, text)]}
                                  for node_id, text in observation.descriptions]


def validate_materialized_names(entity, document):
    if 'name_raw' not in entity:
        return
    nodes = {n['node_id']: n for n in document['nodes']}
    if not literal(entity['name']) or literal(entity['name']) not in literal(entity['name_raw']):
        raise ValueError('core name changed original identity')
    if not any(literal(entity['name_raw']) in literal(nodes[e['node_id']]['text'])
               for e in entity.get('evidence',[]) if e.get('node_id') in nodes):
        raise ValueError('original name source mismatch')
    if entity.get('kind') in {'product','material'} and literal(entity['name'])!=literal(entity['name_raw']):
        raise ValueError('product variant removed from original name')
    for field, value_key in [('aliases', 'name'), ('descriptions', 'text')]:
        for row in entity.get(field, []):
            evidence = row.get('evidence', [])
            if not evidence or not literal(row[value_key]):
                raise ValueError('name observation lacks evidence')
            for reference in evidence:
                node_id = reference.get('node_id')
                if node_id not in nodes or literal(row[value_key]) not in literal(nodes[node_id]['text']):
                    raise ValueError('name observation source mismatch')
                if document.get('document_assessment', {}).get('node_roles', {}).get(node_id) == 'table_of_contents':
                    raise ValueError('navigation cannot establish a name alias')
