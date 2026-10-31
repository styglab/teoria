"""Other requirements retain source clauses, including legacy artifact compatibility."""


def is_other_requirement(row, document):
    if row.get('category') == 'other' or row.get('observation_type') == 'obligation':
        return True
    roles = document.get('parsed_document', document).get('document_assessment', {}).get('node_roles', {})
    return any(roles.get(e.get('node_id')) in {'general_requirement', 'delivery_requirement'}
               for e in row.get('evidence', []))


def other_requirements(document):
    rows = [r for r in document.get('requirements', []) if is_other_requirement(r, document)]
    source_nodes = {e.get('node_id') for r in rows if r.get('observation_type') == 'source_clause'
                    for e in r.get('evidence', [])}
    # A legacy split duty does not duplicate a preserved original clause at the same node.
    return [r for r in rows if r.get('observation_type') != 'obligation'
            or not any(e.get('node_id') in source_nodes for e in r.get('evidence', []))]


def validate_legacy_obligation(duty, entity_ids, document):
    """Old checkpoints remain readable and source-checked; new runs never generate these."""
    if not set(duty['subject_ids']) <= entity_ids:
        raise ValueError('invalid obligation subject')
    if duty.get('modality') not in {'required','prohibited','recommended','permitted','unknown'} or (duty.get('modality')!='unknown' and not duty.get('modality_raw')):
        raise ValueError('invalid obligation modality')
    nodes = {n['node_id']: n for n in document['nodes']}
    evidence = duty.get('evidence', [])
    if len(evidence) != 1 or evidence[0].get('node_id') not in nodes:
        raise ValueError('invalid obligation evidence')
    evidence = evidence[0]
    text = nodes[evidence['node_id']]['text']
    start, end = evidence.get('char_start'), evidence.get('char_end')
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(text):
        raise ValueError('invalid obligation source span')
    quote = text[start:end]
    if duty.get('text') != quote or evidence.get('quote') != quote:
        raise ValueError('obligation source mismatch')
    from teoria.features.specification_processing.parsing.document_evidence import literal
    raw = [duty.get('action_raw'), duty.get('actor_raw'), duty.get('modality_raw'),
           *duty.get('conditions_raw', [])]
    if not duty.get('action_raw') or any(value is not None and
            (not value.strip() or literal(value) not in literal(quote)) for value in raw):
        raise ValueError('invalid obligation source fields')


def preserve_other_attribute(graph, attribute, document, evidence_node_ids):
    """Retain a general clause without asserting that it applies to every product."""
    nodes = {n['node_id']: n for n in document['nodes']}
    node_id = attribute['evidence']['node_id']
    node = nodes[node_id]
    rows = graph.setdefault('requirements', [])
    clause = next((r for r in rows if r.get('observation_type') == 'source_clause'
                   and r.get('id') == 'clause_' + node_id), None)
    if clause is None:
        clause = {'id': 'clause_' + node_id, 'observation_type': 'source_clause',
                  'atomic_requirement': False, 'text': node['text'],
                  'evidence': [{'node_id': node_id, 'quote': node['text'],
                                'native_ref': node.get('native_ref')}], 'review_status': 'needs_review'}
        rows.append(clause)
    clause.update(category='other', subject_ids=[], application_scope='unspecified')
    clause['classification_evidence_node_ids'] = list(dict.fromkeys(evidence_node_ids))
    clause.setdefault('source_observation_ids', []).append(attribute['id'])
