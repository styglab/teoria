"""Group unresolved observations by explicit context, preserving source evidence."""
from teoria.features.goods_normalization.contracts import checksum
from teoria.features.goods_normalization.contracts.candidates import CandidateBundle, CandidateContext

from teoria.features.specification_processing.parsing.document_evidence import attribute_is_grounded, literal


def collect_profile_candidates(corpus, normalized, package):
    groups = {}
    pending = normalized['unresolved_observations']
    for doc in corpus['documents']:
        document_id = doc['document_id']
        nodes = {n['node_id']: n['text'] for n in doc['parsed_document']['nodes']}
        source_entities = {e['id']: e for e in doc['entities']}
        result = next(d for d in normalized['documents'] if d['document_id'] == document_id)
        resolved = {e['source_entity_id']: e for e in result['entities']}
        unresolved = [c for c in pending if c['document_id'] == document_id]
        entity_ids = {c['source_entity_id'] for c in unresolved if c['kind'] == 'entity'}
        attribute_ids = {c['attribute_id']: c for c in unresolved if c['kind'] == 'requirement'}
        relation_ids = {c['source_relation_id'] for c in unresolved if c['kind'] == 'relation'}

        def add(context, local_id, raw, evidence, grounded, aliases):
            context = CandidateContext.model_validate(context)
            group_id = checksum(context)
            group = groups.setdefault(group_id, {'group_id': group_id,
                'context': context.model_dump(mode='json'), 'aliases': set(), 'observations': {}})
            group['aliases'].update(aliases)
            source_text=[]
            for ref in evidence:
                if 'node_id' in ref:
                    text=nodes.get(ref['node_id'],'')
                    source_text.append(text[ref.get('char_start',0):ref.get('char_end',len(text))])
                else:
                    source_text.extend(nodes.get(node_id,'') for node_id in ref.get('source_node_ids',[]))
            observation = {'document_id': document_id, 'source_sha256': doc['source']['sha256'],
                'local_id': local_id, 'raw': raw, 'evidence': evidence, 'grounded': grounded,
                'source_text':'\n'.join(source_text)}
            identity = (observation['source_sha256'], local_id)
            previous = group['observations'].get(identity)
            if previous is not None and any(previous[k] != observation[k] for k in ('raw', 'evidence', 'grounded', 'source_text')):
                raise ValueError('conflicting repeated source observation')
            group['observations'].setdefault(identity, observation)

        for entity_id in sorted(entity_ids):
            entity = source_entities[entity_id]
            evidence = entity.get('evidence', [])
            grounded = bool(literal(entity['name'])) and any(
                literal(entity['name']) in literal(nodes.get(e.get('node_id'), '')) for e in evidence)
            add({'kind': 'entity', 'label': literal(entity['name']) or '<empty>', 'source_kind': entity['kind']},
                entity_id, entity, evidence, grounded, [entity['name']])
        for attribute in doc['attributes']:
            if attribute['id'] not in attribute_ids:
                continue
            pending_attribute = attribute_ids[attribute['id']]
            subjects = attribute['subject_ids']
            target_ids = sorted({resolved[s]['concept_id'] for s in subjects
                if s in resolved and resolved[s].get('concept_id')})
            missing = sorted({literal(source_entities[s]['name']) if s in source_entities else '<missing>'
                for s in subjects if s not in resolved or not resolved[s].get('concept_id')})
            if not subjects:
                missing = ['<missing>']
            evidence = attribute.get('evidence', {})
            add({'kind': 'requirement', 'label': literal(attribute['property_key']),
                 'source_kind': attribute['property_key'], 'target_concept_ids': target_ids,
                 'unresolved_targets': missing, 'role': pending_attribute['role'],
                 'scope': pending_attribute['semantic_scope'], 'value_type': attribute['data_type'],
                 'unit': attribute.get('unit_raw')}, attribute['id'], attribute,
                [evidence], attribute_is_grounded(doc, attribute),
                [attribute['property_key'], attribute.get('property_raw') or attribute['property_key']])
        for relation in doc['relations']:
            if relation['id'] not in relation_ids:
                continue
            evidence = relation.get('evidence', [])
            endpoints = [resolved.get(relation[k], {}).get('concept_id') for k in ('source_id', 'target_id')]
            missing = [literal(source_entities[s]['name']) if s in source_entities else '<missing>'
                for s, concept in zip([relation['source_id'], relation['target_id']], endpoints) if not concept]
            add({'kind': 'relation', 'label': literal(relation['kind']), 'source_kind': relation['kind'],
                 'source_concept_id': endpoints[0], 'destination_concept_id': endpoints[1],
                 'unresolved_targets': sorted(set(missing))}, relation['id'], relation, evidence,
                bool(evidence) and all(e.get('node_id') in nodes and nodes[e['node_id']].strip() for e in evidence),
                [relation['kind']])
    rows = [{**group, 'aliases': sorted(group['aliases']),
             'observations': sorted(group['observations'].values(), key=lambda o: (o['source_sha256'], o['local_id']))}
            for _, group in sorted(groups.items())]
    body = {'schema_version': 1, 'artifact_kind': 'goods_meaning_candidates',
            'classification_code': corpus['classification_code'],
            'ontology': package.profile.ontology.model_dump(mode='json'), 'groups': rows}
    return CandidateBundle.model_validate({**body, 'checksum': checksum(body)}).model_dump(mode='json')
