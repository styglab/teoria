"""Evidence-preserving candidate comparison and explicit Draft construction.

Lexical retrieval proposes concepts; it never establishes semantic equivalence or
publishes definitions. Context compatibility is checked again before Draft creation.
"""
from difflib import SequenceMatcher
import re
import unicodedata
from uuid import UUID

from pydantic import Field
from teoria.features.goods_normalization.contracts import NormalizationProfile, UnitRule, checksum
from teoria.features.goods_normalization.contracts.candidates import CandidateBundle
from teoria.features.goods_normalization.contracts.models import Record

from teoria.features.goods_normalization.profiles.compiler import compile_package


class CandidateSelection(Record):
    group_id: str = Field(pattern=r'^[a-f0-9]{64}$')
    concept_id: UUID
    reverse: bool = False
    units: list[UnitRule] = Field(default_factory=list)


def _text(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(value))).strip().casefold()


def merge_candidate_bundles(bundles: list[CandidateBundle], profile: NormalizationProfile):
    groups = {}
    identities = {}
    for bundle in bundles:
        if bundle.classification_code != profile.classification_code or bundle.ontology != profile.ontology:
            raise ValueError('candidate classification or ontology differs from profile')
        for group in bundle.groups:
            row = groups.setdefault(group.group_id, {'group_id': group.group_id,
                'context': group.context.model_dump(mode='json'), 'aliases': set(), 'observations': {}})
            row['aliases'].update(group.aliases)
            for observation in group.observations:
                identity = (group.context.kind, observation.source_sha256, observation.local_id)
                comparable = observation.model_dump(mode='json', exclude={'document_id'})
                previous = identities.get(identity)
                if previous is not None and previous != (group.group_id, comparable):
                    raise ValueError('conflicting observations across candidate bundles')
                identities[identity] = (group.group_id, comparable)
                existing = row['observations'].get(identity)
                if existing is None or observation.document_id < existing['document_id']:
                    row['observations'][identity] = observation.model_dump(mode='json')
    return [{**row, 'aliases': sorted(row['aliases']),
             'observations': sorted(row['observations'].values(), key=lambda o: (o['source_sha256'], o['local_id']))}
            for _, row in sorted(groups.items())]


def _concepts(ontology):
    objects = {str(o['business_object_id']): str(o['concept_id']) for o in ontology['objects']}
    result = []
    for obj in ontology['objects']:
        result.append({**obj, 'concept_id': str(obj['concept_id']), 'kind': 'entity'})
        for prop in obj['properties']:
            result.append({**prop, 'concept_id': str(prop['concept_id']), 'kind': 'requirement',
                           'owner': str(obj['concept_id'])})
    for rel in ontology['relationships']:
        result.append({**rel, 'concept_id': str(rel['concept_id']), 'kind': 'relation',
            'source': objects[str(rel['source_object_id'])], 'target': objects[str(rel['target_object_id'])]})
    return result


def _eligible(context, concept):
    if context['kind'] != concept['kind'] or context['unresolved_targets']:
        return False
    if context['kind'] == 'requirement':
        allowed_roles = {'requirement_candidate', 'supported_capability', 'existing_reference', 'recommended', 'optional'}
        allowed_scopes = {'per_component', 'system_total', 'per_module', 'per_processor', 'support_limit', 'service'}
        types = {'number': {'integer', 'number', 'decimal', 'float', 'double'},
                 'text': {'string', 'text'}, 'identifier': {'string', 'text'}}
        return (context['target_concept_ids'] == [concept['owner']]
                and context['role'] in allowed_roles and context['scope'] in allowed_scopes
                and concept['value_type'] in types.get(context['value_type'], set()))
    if context['kind'] == 'relation':
        endpoints = (context['source_concept_id'], context['destination_concept_id'])
        return endpoints in {(concept['source'], concept['target']), (concept['target'], concept['source'])}
    return bool(context['source_kind'] and context['source_kind'] != 'unknown')


def propose_candidates(bundles, profile, ontology):
    if checksum(ontology) != profile.ontology.checksum:
        raise ValueError('ontology artifact checksum mismatch')
    concepts = _concepts(ontology)
    rows = merge_candidate_bundles(bundles, profile)
    approved_aliases = {}
    for rule in profile.entities:
        approved_aliases.setdefault(str(rule.concept_id), []).extend(rule.aliases)
    for rule in profile.requirements:
        approved_aliases.setdefault(str(rule.property_concept_id), []).extend(rule.source_property_keys)
    for rule in profile.relations:
        approved_aliases.setdefault(str(rule.relationship_concept_id), []).append(rule.source_kind)
    for row in rows:
        grounded = all(o['grounded'] and o['evidence'] and o['source_text'].strip() for o in row['observations'])
        matches = []
        for concept in concepts:
            if not grounded or not _eligible(row['context'], concept):
                continue
            labels = [concept['stable_key'].rsplit('.', 1)[-1], concept.get('name', ''),
                      *approved_aliases.get(concept['concept_id'], [])]
            score = max(SequenceMatcher(None, _text(alias), _text(label)).ratio()
                        for alias in row['aliases'] for label in labels if label)
            matches.append({'concept_id': concept['concept_id'], 'stable_key': concept['stable_key'],
                'name': concept.get('name', ''), 'lexical_score': round(score, 4),
                'basis': 'lexical_retrieval_with_context_filters_not_semantic_equivalence'})
        matches.sort(key=lambda m: (-m['lexical_score'], m['stable_key']))
        matches = [m for m in matches if m['lexical_score'] >= 0.45][:5]
        context = row['context']
        unclear = (not grounded or context['unresolved_targets']
                   or (context['kind'] == 'entity' and context['source_kind'] == 'unknown')
                   or (context['kind'] == 'requirement' and
                       (context['role'] not in {'requirement_candidate', 'supported_capability', 'existing_reference', 'recommended', 'optional'}
                        or context['scope'] not in {'per_component', 'system_total', 'per_module', 'per_processor', 'support_limit', 'service'}
                        or context['value_type'] not in {'number', 'text', 'identifier'}
                        or len(context['target_concept_ids']) != 1))
                   or (context['kind'] == 'relation' and
                       (not context['source_concept_id'] or not context['destination_concept_id'])))
        row.update(decision='hold' if unclear else 'existing_concept_proposal' if matches else 'new_concept_review',
            matches=matches, document_count=len({o['source_sha256'] for o in row['observations']}),
            observation_count=len(row['observations']), review_status='suggestion_not_approved')
    body = {'schema_version': 1, 'artifact_kind': 'goods_candidate_proposals',
        'classification_code': profile.classification_code, 'ontology': profile.ontology.model_dump(mode='json'),
        'base_profile_checksum': checksum(profile), 'input_checksums': sorted({b.checksum for b in bundles}),
        'groups': rows, 'published': False,
        'policy': 'Literal-context grouping; lexical ranking only. No automatic synonyms, unit inference, new concepts or approval.'}
    return {**body, 'checksum': checksum(body)}


def _check_rule_overlap(profile,ontology):
    for i, left in enumerate(profile.entities):
        for right in profile.entities[i + 1:]:
            # Consumer matching is case sensitive; do not introduce case folding here.
            aliases = lambda rule: {re.sub(r'\s+', '', unicodedata.normalize('NFKC', a)) for a in rule.aliases}
            if set(left.source_kinds) & set(right.source_kinds) and aliases(left) & aliases(right):
                raise ValueError('overlapping entity alias rules')
    for i, left in enumerate(profile.requirements):
        for right in profile.requirements[i + 1:]:
            if (left.target_concept_id == right.target_concept_id
                    and set(left.source_property_keys) & set(right.source_property_keys)
                    and set(left.roles) & set(right.roles) and set(left.scopes) & set(right.scopes)):
                raise ValueError('overlapping requirement rules')
    concepts={c['concept_id']:c for c in _concepts(ontology) if c['kind']=='relation'}
    contexts=[]
    for rule in profile.relations:
        relation=concepts.get(str(rule.relationship_concept_id))
        if relation is None:raise ValueError('unknown relationship concept')
        endpoints=(relation['source'],relation['target'])
        if rule.reverse:endpoints=endpoints[::-1]
        contexts.append((rule.source_kind,*endpoints))
    if len(contexts) != len(set(contexts)):
        raise ValueError('overlapping relation rules')


def draft_from_candidates(bundles, profile, ontology, selections, *, version):
    if version == profile.version:
        raise ValueError('candidate Draft requires a new profile version')
    if not selections or len({s.group_id for s in selections}) != len(selections):
        raise ValueError('select distinct candidate groups')
    report = propose_candidates(bundles, profile, ontology)
    groups = {g['group_id']: g for g in report['groups']}
    concepts = {c['concept_id']: c for c in _concepts(ontology)}
    body = profile.model_dump(mode='json')
    body['version'] = version
    for selection in selections:
        group = groups.get(selection.group_id)
        concept = concepts.get(str(selection.concept_id))
        if not group or group['decision'] == 'hold' or not concept or not _eligible(group['context'], concept):
            raise ValueError('selection is incompatible or lacks resolved source context')
        context = group['context']
        rule_id = 'candidate_' + selection.group_id[:24]
        if context['kind'] == 'entity':
            if selection.reverse or selection.units:
                raise ValueError('entity selection cannot specify direction or units')
            body['entities'].append({'rule_id': rule_id, 'aliases': group['aliases'],
                'source_kinds': [context['source_kind']], 'concept_id': str(selection.concept_id)})
        elif context['kind'] == 'requirement':
            if selection.reverse:
                raise ValueError('requirement selection cannot reverse direction')
            if context['value_type'] == 'number':
                if (len(selection.units) != 1 or selection.units[0].source_unit != context['unit']
                        or selection.units[0].canonical_unit != concept.get('unit')):
                    raise ValueError('explicit source and canonical unit policy required')
            elif selection.units or context['unit'] is not None:
                raise ValueError('text requirements cannot convert units')
            body['requirements'].append({'rule_id': rule_id, 'target_concept_id': concept['owner'],
                'property_concept_id': str(selection.concept_id), 'source_property_keys': [context['source_kind']],
                'roles': [context['role']], 'scopes': [context['scope']], 'value_type': context['value_type'],
                'units': [u.model_dump(mode='json') for u in selection.units]})
        else:
            if selection.units:
                raise ValueError('relation selection cannot specify units')
            endpoints = (context['source_concept_id'], context['destination_concept_id'])
            if selection.reverse:
                endpoints = endpoints[::-1]
            if endpoints != (concept['source'], concept['target']):
                raise ValueError('selected relationship direction differs from endpoints')
            body['relations'].append({'rule_id': rule_id, 'source_kind': context['source_kind'],
                'relationship_concept_id': str(selection.concept_id), 'reverse': selection.reverse})
    draft = NormalizationProfile.model_validate(body)
    _check_rule_overlap(draft,ontology)
    # Reuse the executable contract validator, without persisting or publishing a package.
    compile_package(draft, ontology, revision_id=UUID(int=0), approval_actor='draft_validation')
    return draft, report['checksum']
