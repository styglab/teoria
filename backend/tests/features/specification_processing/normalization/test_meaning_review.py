"""Owner/scope suggestions stay separate from source and execution authority."""
from copy import deepcopy
import hashlib
import json
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest

from teoria.features.semantic_modeling.ontology.publication_contracts import publication_checksum
from teoria.features.semantic_modeling.ontology.review_contracts import OntologyReviewSnapshot
from teoria.features.specification_processing.normalization.meaning_review import (
    MeaningReviewInput, build_meaning_review, prepare_meaning_review,
)


def example():
    version, server, memory, socket, slots, capacity = [str(uuid4()) for _ in range(6)]
    content = {'ontology_version_id': version, 'namespace': 'fixture', 'version': '2', 'status': 'draft',
        'objects': [
            {'concept_id': server, 'name': '서버', 'stable_key': 'fixture.server', 'properties': [
                {'concept_id': socket, 'name': '소켓당 지원 상한', 'stable_key': 'fixture.server.socket_limit',
                 'value_type': 'decimal', 'unit': 'GB', 'allowed_units': ['GB', 'TB']},
                {'concept_id': slots, 'name': '총 슬롯 수', 'stable_key': 'fixture.server.slots',
                 'value_type': 'integer', 'unit': '개', 'allowed_units': ['개']}]},
            {'concept_id': memory, 'name': '메모리 모듈', 'stable_key': 'fixture.memory', 'properties': [
                {'concept_id': capacity, 'name': '모듈 용량', 'stable_key': 'fixture.memory.capacity',
                 'value_type': 'decimal', 'unit': 'GB', 'allowed_units': ['GB', 'TB']}]}]}
    ref = {'version_id': version, 'namespace': 'fixture', 'version': '2', 'status': 'draft',
           'content_checksum': publication_checksum(content)}
    document = {'document_id': 'd', 'source': {'sha256': 'a' * 64},
        'entities': [
            {'id': 'root', 'name': '서버', 'evidence': [{'node_id': 'title'}]},
            {'id': 'memory', 'name': 'DDR5 32GB RDIMM', 'evidence': [{'node_id': 'spec'}]},
            {'id': 'slots', 'name': 'DIMM 슬롯', 'evidence': [{'node_id': 'spec'}]}],
        'attributes': [], 'parsed_document': {'nodes': [
            {'node_id': 'title', 'kind': 'cell', 'text': '서버'},
            {'node_id': 'spec', 'kind': 'cell',
             'text': 'DDR5 32GB RDIMM x 2개\n총 슬롯 수 : 32 개 DIMM 슬롯\n최대 용량: CPU 소켓당 최대 3TB 지원'}]}}
    for local, owner, raw, value, unit, role, scope in [
        ('module', 'memory', 'DDR5', '32', 'GB', 'requirement_candidate', 'per_module'),
        ('limit', 'root', '최대 용량', '3', 'TB', 'supported_capability', 'support_limit'),
        ('count', 'slots', '총 슬롯 수', '32', '개', 'requirement_candidate', 'system_total'),
    ]:
        document['attributes'].append({'id': local, 'subject_ids': [owner], 'property_raw': raw,
            'property_key': local, 'data_type': 'number', 'value_raw': value, 'unit_raw': unit,
            'operator': 'lte' if local == 'limit' else 'eq', 'operator_raw': '최대' if local == 'limit' else None,
            'qualifiers_raw': [], 'semantic_role': role, 'semantic_scope': scope, 'evidence': {'node_id': 'spec'}})
    result = {'artifact_kind': 'specification_document_result', 'document_id': 'd',
              'source_sha256': 'a' * 64, 'extracted': {'documents': [document]}}
    def evidence(node, quote):
        return [{'document_id': 'd', 'node_id': node, 'quote': quote}]
    request = MeaningReviewInput.model_validate({'review_id': 'fixture_review',
        'result': {'uri': 'file:///fixture/result.json', 'sha256': 'b' * 64},
        'document_id': 'd', 'source_sha256': 'a' * 64, 'ontology': ref,
        'entities': [
            {'subject_id': 'root', 'concept_id': server, 'evidence': evidence('title', '서버'),
             'rationale': '서버 대상의 원문 이름과 정의를 대조하는 제안이다.'},
            {'subject_id': 'memory', 'concept_id': memory, 'evidence': evidence('spec', 'DDR5 32GB RDIMM'),
             'rationale': '모듈 구성의 원문 이름과 정의를 대조하는 제안이다.'}],
        'properties': [
            {'observation_id': 'module', 'concept_id': capacity, 'subject_id': 'memory', 'semantic_scope': 'per_module',
             'evidence': evidence('spec', 'DDR5 32GB RDIMM x 2개'), 'rationale': '32GB는 구성 모듈당 용량이며 전체 용량을 계산하지 않는다.'},
            {'observation_id': 'limit', 'concept_id': socket, 'subject_id': 'root', 'semantic_scope': 'per_socket',
             'evidence': evidence('spec', 'CPU 소켓당 최대 3TB 지원'), 'rationale': '소켓당 지원 상한을 구체화하는 검토 제안이며 원래 scope를 보존한다.'},
            {'observation_id': 'count', 'concept_id': slots, 'subject_id': 'root', 'semantic_scope': 'system_total',
             'evidence': evidence('spec', '총 슬롯 수 : 32 개 DIMM 슬롯'), 'rationale': '슬롯 자체와 서버의 슬롯 수를 구별하는 소유 대상 검토 제안이다.'}]})
    return request, result, OntologyReviewSnapshot(context=ref, content=content)


def test_interpretations_preserve_observations_and_record_only_proposed_owner_scope_changes():
    request, result, snapshot = example()
    before = deepcopy(result)
    report = build_meaning_review(request, result, snapshot)
    assert result == before and report['observations_unchanged']
    assert report['summary'] == {'selected_observations': 5, 'requires_review': 5, 'held': 0,
        'source_entities': 3, 'source_attributes': 3, 'unselected_entities': 1, 'unselected_attributes': 0,
        'proposed_interpretation_changes': 2}
    rows = {r['observation_id']: r for r in report['observations'] if r['kind'] == 'property'}
    assert rows['limit']['source']['semantic_scope'] == 'support_limit'
    assert rows['limit']['interpretation']['semantic_scope'] == 'per_socket'
    assert rows['limit']['changes'] == ['semantic_scope']
    assert rows['count']['source']['subject_ids'] == ['slots']
    assert rows['count']['interpretation']['subject_id'] == 'root'
    assert rows['count']['changes'] == ['subject_ids']
    assert rows['module']['source']['value_raw'] == '32' and rows['module']['changes'] == []
    assert report['authority'] == 'suggestion' and not report['auto_applied']
    assert not report['published'] and not report['semantic_equivalence_confirmed']
    assert report['checksum'] == publication_checksum({k: v for k, v in report.items() if k != 'checksum'})


@pytest.mark.parametrize('bad,reason', [
    ('quote', 'review_quote_not_in_source'), ('node', 'review_evidence_reference_mismatch'),
    ('document', 'review_evidence_reference_mismatch'), ('owner', 'review_property_owner_mismatch'),
    ('missing_owner', 'review_subject_unresolved'), ('concept', 'review_property_not_in_context'),
    ('scope', 'review_role_or_scope_unresolved'), ('role', 'review_role_or_scope_unresolved'),
    ('unit', 'review_unit_not_allowed'), ('condition', 'source_condition_mismatch'),
    ('integer', 'review_integer_value_required'),
])
def test_invalid_candidates_are_held_with_evidence_and_source_intact(bad, reason):
    request, result, snapshot = example()
    prop = request.properties[1]
    attribute = result['extracted']['documents'][0]['attributes'][1]
    if bad == 'quote': prop.evidence[0].quote = 'CPU 소켓당 최대 8TB 지원'
    elif bad == 'node': prop.evidence[0].node_id = 'missing'
    elif bad == 'document': prop.evidence[0].document_id = 'other'
    elif bad == 'owner': prop.subject_id = 'memory'
    elif bad == 'missing_owner': prop.subject_id = 'slots'
    elif bad == 'concept': prop.concept_id = uuid4()
    elif bad == 'scope': prop.semantic_scope = 'unknown'
    elif bad == 'role': attribute['semantic_role'] = 'invented'
    elif bad == 'condition': attribute['qualifiers_raw'] = ['항상']
    elif bad == 'unit':
        snapshot.content['objects'][0]['properties'][0]['allowed_units'] = ['GB']
        snapshot.context = snapshot.context.model_copy(update={'content_checksum': publication_checksum(snapshot.content)})
        request.ontology = snapshot.context
    elif bad == 'integer':
        request.properties[2].concept_id = UUID(snapshot.content['objects'][0]['properties'][1]['concept_id'])
        result['extracted']['documents'][0]['attributes'][2]['value_raw'] = '32.5'
        result['extracted']['documents'][0]['parsed_document']['nodes'][1]['text'] = 'DDR5 32GB RDIMM x 2개\n총 슬롯 수 : 32.5 개 DIMM 슬롯\nCPU 소켓당 최대 3TB 지원'
        request.properties[2].evidence[0].quote = '총 슬롯 수 : 32.5 개 DIMM 슬롯'
    before = deepcopy(result)
    report = build_meaning_review(request, result, snapshot)
    row = next(r for r in report['observations'] if r['observation_id'] == ('count' if bad == 'integer' else 'limit'))
    assert row['status'] == 'held' and row['reason'] == reason
    assert result == before


def test_review_context_is_distinct_from_publication_and_rejects_stale_drafts():
    from teoria.features.semantic_modeling.ontology.publication_contracts import PublishedOntologyContext
    request, _, snapshot = example()
    changed = deepcopy(snapshot.content)
    changed['objects'][0]['name'] = 'Changed meaning'
    with pytest.raises(ValueError, match='content_changed'):
        OntologyReviewSnapshot(context=request.ontology, content=changed)
    with pytest.raises(ValueError):
        PublishedOntologyContext.model_validate(snapshot.model_dump(mode='json'))
    _, result, _ = example()
    snapshot.content['objects'][0]['name'] = 'Changed in memory'
    with pytest.raises(ValueError, match='content_changed'):
        build_meaning_review(request, result, snapshot)


async def test_frozen_result_and_live_version_are_checked_before_immutable_artifact_write(tmp_path):
    request, result, snapshot = example()
    path = tmp_path / 'result.json'
    raw = json.dumps(result).encode()
    path.write_bytes(raw)
    request.result.uri, request.result.sha256 = path.as_uri(), hashlib.sha256(raw).hexdigest()
    api = AsyncMock()
    api.ontology_review_version.return_value = snapshot
    output = await prepare_meaning_review(request, (tmp_path / 'artifacts').as_uri(), api=api)
    replay = await prepare_meaning_review(request, (tmp_path / 'artifacts').as_uri(), api=api)
    assert replay == output
    assert output['summary']['requires_review'] == 5
    assert api.ontology_review_version.await_args.args[0] == request.ontology
    request.properties[0].rationale = '검토 근거 변경은 같은 산출물을 덮어쓰지 않고 새 review_id를 요구한다.'
    with pytest.raises(ValueError, match='immutable artifact conflict'):
        await prepare_meaning_review(request, (tmp_path / 'artifacts').as_uri(), api=api)
    path.write_bytes(raw + b' ')
    api.ontology_review_version.reset_mock()
    with pytest.raises(ValueError, match='bytes_changed'):
        await prepare_meaning_review(request, (tmp_path / 'artifacts').as_uri(), api=api)
    api.ontology_review_version.assert_not_awaited()


async def test_authoring_http_checks_review_identity_and_does_not_request_publication():
    import httpx
    from teoria.features.specification_processing.authoring_client import GoodsAuthoringClient
    request, _, snapshot = example()
    def handler(req):
        assert req.headers['Authorization'] == 'Bearer fixture-token'
        assert req.url.path.endswith('/versions/' + str(request.ontology.version_id))
        return httpx.Response(200, json=snapshot.content)
    async with GoodsAuthoringClient(base_url='http://fixture', token='fixture-token',
            transport=httpx.MockTransport(handler)) as api:
        assert await api.ontology_review_version(request.ontology) == snapshot
        changed = request.ontology.model_copy(update={'content_checksum': 'f' * 64})
        with pytest.raises(ValueError, match='content_changed'):
            await api.ontology_review_version(changed)


@pytest.mark.parametrize('kind', ['specification_meaning_review', 'specification_ontology_alignment_comparison'])
def test_suggestions_cannot_be_passed_as_authority_to_profile_application(kind):
    from teoria.features.specification_processing.normalization.profile_application import apply_profile
    with pytest.raises(ValueError, match='cannot authorize'):
        apply_profile({}, None, run_id='fixture', meaning_alignment={'artifact_kind': kind})
