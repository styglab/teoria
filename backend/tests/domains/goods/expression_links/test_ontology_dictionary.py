"""Publication identity, scoped expression interpretation, and immutable replay."""
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from teoria.domains.goods.expression_links.contracts import dictionary_checksum
from teoria.domains.goods.expression_links.snapshot_contracts import (
    approved_dictionary_snapshot, parse_dictionary_snapshot, resolve_snapshot,
)
from teoria.domains.goods.expression_links.expression_contracts import expression_snapshot
from teoria.domains.goods.normalization.meaning_proposals.expression_alignment import apply_concept_meanings


def fixture():
    version, owner, prop, entry, attr = [str(uuid4()) for _ in range(5)]
    content = {'namespace':'goods_test','version':'1', 'objects':[{
        'business_object_id':str(uuid4()), 'concept_id':owner,'stable_key':'goods_test.inverter',
        'name':'인버터','description':'직류 전력을 교류 전력으로 변환하는 장치.',
        'properties':[{'concept_id':prop,'stable_key':'goods_test.inverter.output',
            'name':'정격출력','description':'정격 조건에서 출력하는 전력.', 'value_type':'decimal',
            'unit':'W','quantity_dimension':'power','allowed_units':['W','kW']}]}],
        'relationships':[], 'rules':[], 'metrics':[]}
    ref = {'version_id':version,'namespace':content['namespace'],'version':'1','checksum':dictionary_checksum(content)}
    sources = [dict(entry_id=entry,kind='item_type',status='approved',owner_entry_id=None,preferred_name='인버터'),
               dict(entry_id=attr,kind='characteristic',status='approved',owner_entry_id=entry,preferred_name='정격 출력')]
    mappings = [dict(mapping_id=str(uuid4()),source_entry_id=s['entry_id'],ontology_version_id=version,
        target_concept_id=owner if s['kind']=='item_type' else prop,
        owner_concept_id=None if s['kind']=='item_type' else owner,
        classification_code='1234567890',scope_mode='classified',relation='equivalent',status='approved') for s in sources]
    return expression_snapshot([{'ontology':ref,'content':content}],mappings,sources)


def test_snapshot_uses_stable_ontology_ids_and_preserves_raw_requirement():
    snapshot = fixture()
    entry = snapshot.sources[0]['entry_id']
    attr = next(s['entry_id'] for s in snapshot.sources if s['kind']=='characteristic')
    result = resolve_snapshot(snapshot, [attr], '1234567890')
    meaning = result['items'][0]
    assert meaning['status']=='resolved' and meaning['ontology']['checksum']==snapshot.ontologies[0]['ontology']['checksum']
    docs = [{'entities':[], 'attributes':[dict(id='a1',source_term_ref='source_term:'+attr,
                value_raw='3',unit_raw='kW',operator='gte',semantic_scope='per_item')]}]
    original = deepcopy(docs)
    aligned = apply_concept_meanings(docs, result)['documents'][0]['attributes'][0]
    assert docs==original and aligned['ontology_concept_ref']==meaning['concept_id']
    assert aligned['value_raw']=='3' and aligned['operator']=='gte'
    assert 'dictionary_concept_ref' not in aligned and 'typed_value' not in aligned
    assert resolve_snapshot(snapshot,[entry],None)['items'][0]['status']=='unresolved'


def test_ambiguous_owners_related_links_and_versions_never_silently_equate():
    snapshot=fixture()
    attr=next(s['entry_id'] for s in snapshot.sources if s['kind']=='characteristic')
    other=deepcopy(snapshot.mappings)
    owner=next(m for m in other if m['owner_concept_id'] is None)
    owner['relation']='related'
    held=expression_snapshot(snapshot.ontologies,other,snapshot.sources)
    assert resolve_snapshot(held,[attr],'1234567890')['items'][0]['status']=='unresolved'
    # Two reviewed publication versions cannot be chosen by recency or spelling.
    second=deepcopy(snapshot.ontologies[0]);second['ontology']['version_id']=str(uuid4())
    links=[*snapshot.mappings,*[{**m,'ontology_version_id':second['ontology']['version_id'],'mapping_id':str(uuid4())} for m in snapshot.mappings]]
    ambiguous=expression_snapshot([*snapshot.ontologies,second],links,snapshot.sources)
    root=next(s['entry_id'] for s in snapshot.sources if s['kind']=='item_type')
    assert resolve_snapshot(ambiguous,[root],'1234567890')['items'][0]['status']=='held'
    assert resolve_snapshot(ambiguous,[attr],'1234567890')['items'][0]['status']=='unresolved'


def test_nested_publication_checksums_and_owner_constraints_are_verified():
    snapshot=fixture();body=snapshot.model_dump(mode='json')
    body['ontologies'][0]['content']['objects'][0]['name']='tampered'
    body['checksum']=dictionary_checksum({k:body[k] for k in ['ontologies','mappings','sources']})
    with pytest.raises(ValidationError,match='ontology artifact checksum'):
        parse_dictionary_snapshot(body)
    links=deepcopy(snapshot.mappings)
    next(m for m in links if m['owner_concept_id'])['owner_concept_id']=str(uuid4())
    with pytest.raises(ValidationError,match='target or owner'):
        expression_snapshot(snapshot.ontologies,links,snapshot.sources)


def test_release_ignores_unmapped_observations_and_frozen_replay_has_no_live_dependency():
    snapshot=fixture();release=approved_dictionary_snapshot(snapshot)
    extra=dict(entry_id=str(uuid4()),kind='item_type',status='approved',owner_entry_id=None,preferred_name='새 표현')
    changed=expression_snapshot(snapshot.ontologies,snapshot.mappings,[*snapshot.sources,extra])
    assert approved_dictionary_snapshot(changed).checksum==release.checksum
    encoded=release.model_dump_json()
    parsed=parse_dictionary_snapshot(encoded)
    entry=next(s['entry_id'] for s in parsed.sources if s['kind']=='item_type')
    assert resolve_snapshot(parsed,[entry],'1234567890')['items'][0]['status']=='resolved'
