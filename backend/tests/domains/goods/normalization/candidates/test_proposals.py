"""Candidate and link planning use pinned values without executing workflow I/O."""
from copy import deepcopy
from uuid import UUID

from backend.tests.domains.goods.workflows.test_meaning_links import inverter_case
from teoria.domains.goods.expression_links.expression_contracts import expression_snapshot
from teoria.domains.goods.normalization.candidates.proposals import (
    collect_semantic_candidates, plan_profile_expression_links,
)
from teoria.domains.goods.normalization.contracts import NormalizationProfile
from teoria.domains.goods.normalization.profiles.compiler import compile_package


def pending_power_case():
    snapshot, corpus = inverter_case()
    corpus['documents'][0]['attributes'][0]['unit_raw'] = 'W'
    corpus['documents'][0]['parsed_document']['nodes'][0]['text'] = '인버터 정격 출력 3 W 이상'
    publication = snapshot.ontologies[0]
    owner = publication['content']['objects'][0]
    prop = owner['properties'][0]
    profile = NormalizationProfile.model_validate({
        'profile_key': 'inverter_fixture', 'version': '1', 'classification_code': corpus['classification_code'],
        'ontology': publication['ontology'],
        'entities': [{'rule_id': 'inverter', 'concept_id': owner['concept_id']}],
        'requirements': [{'rule_id': 'power', 'target_concept_id': owner['concept_id'],
            'property_concept_id': prop['concept_id'], 'roles': ['requirement_candidate'], 'scopes': ['per_item'],
            'value_type': 'number', 'units': [{'source_unit': 'W', 'canonical_unit': 'W'}]}]})
    package = compile_package(profile, publication['content'], revision_id=UUID(int=900), approval_actor='fixture:reviewer')
    links = [{**m, 'status': 'draft'} if m['owner_concept_id'] else m for m in snapshot.mappings]
    return corpus, package, expression_snapshot(snapshot.ontologies, links, snapshot.sources)


def accept_power_rule(package, snapshot, bundle):
    group, = bundle.groups
    profile = package.profile.model_copy(update={'requirements': [package.profile.requirements[0].model_copy(
        update={'rule_id': 'semantic_' + group.group_id[:24]})]})
    return compile_package(profile, snapshot.ontologies[0]['content'], revision_id=package.profile_revision_id,
                           approval_actor=package.approval_actor)


def test_candidate_collection_preserves_inputs_and_registered_expression_provenance():
    corpus, package, snapshot = pending_power_case()
    before = (deepcopy(corpus), package.model_dump_json(), snapshot.model_dump_json())
    bundle = collect_semantic_candidates(corpus, package, snapshot, run_id='fixture', phase='requirements')
    group, = bundle.groups
    observation, = group.observations
    source = next(s for s in snapshot.sources if s['kind'] == 'characteristic')
    assert group.context.kind == 'requirement' and observation.local_id == 'power'
    assert observation.raw['source_term_ref'] == 'source_term:' + source['entry_id']
    assert observation.raw['value_raw'] == '3' and observation.raw['unit_raw'] == 'W'
    assert collect_semantic_candidates(corpus, package, snapshot, run_id='fixture', phase='entities').groups == []
    assert (corpus, package.model_dump_json(), snapshot.model_dump_json()) == before


def test_only_accepted_profile_rules_propose_new_links_without_approving_them():
    corpus, package, snapshot = pending_power_case()
    bundle = collect_semantic_candidates(corpus, package, snapshot, run_id='fixture', phase='requirements')
    power_id = str(package.profile.requirements[0].property_concept_id)
    held = plan_profile_expression_links(bundle, package, snapshot, corpus)
    assert all(str(p.target_concept_id) != power_id for p in held['proposals'])
    approved_package = accept_power_rule(package, snapshot, bundle)
    before = snapshot.model_dump_json()
    planned = plan_profile_expression_links(bundle, approved_package, snapshot, corpus)
    proposed = next(p for p in planned['proposals'] if str(p.target_concept_id) == power_id)
    assert str(proposed.owner_concept_id) == str(approved_package.profile.entities[0].concept_id)
    assert proposed.ontology == approved_package.profile.ontology and proposed.relation == 'equivalent'
    assert 'status' not in proposed.model_dump() and planned['unresolved'] == []
    assert snapshot.model_dump_json() == before


def test_missing_literal_expression_routes_to_document_interpretation():
    corpus, package, snapshot = pending_power_case()
    corpus['documents'][0]['attributes'][0]['property_raw'] = None
    bundle = collect_semantic_candidates(corpus, package, snapshot, run_id='fixture', phase='requirements')
    package = accept_power_rule(package, snapshot, bundle)
    planned = plan_profile_expression_links(bundle, package, snapshot, corpus)
    assert planned['unresolved'] == [{'document_id': 'inverter', 'observation_id': 'power',
        'route': 'document_interpretation', 'reason': 'no_registered_source_expression'}]
    assert all(p.owner_concept_id is None for p in planned['proposals'])
