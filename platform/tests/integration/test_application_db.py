import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from teoria.binding.repository import BindingRepository
from teoria.intelligence.application import ApplicationStateError
from teoria.intelligence.repository import SuggestionRepository
from teoria.intelligence.service import SuggestionApplicationError, SuggestionService
from teoria.ontology.authoring import OntologyAuthoringRepository
from teoria.persistence import apply_migrations

DATABASE_URL = os.environ.get('TEORIA_TEST_APP_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='TEORIA_TEST_APP_DATABASE_URL is not set')


@pytest.fixture(scope='module', autouse=True)
def migrated_database():
    apply_migrations(DATABASE_URL, Path(__file__).parents[2] / 'database/migrations')


def ontology():
    repo = OntologyAuthoringRepository(DATABASE_URL)
    namespace = 'test_' + uuid4().hex
    version = repo.create_ontology(namespace=namespace, name='Test', description='Synthetic ontology', version='1.0', actor='owner')
    version_id = UUID(version['ontology_version_id'])
    obj = repo.add_item(version_id, kind='object', payload={'code': 'Contract', 'name': 'Contract'}, actor='owner')
    prop = repo.add_item(version_id, kind='property', payload={'code': 'amount', 'name': 'Amount', 'object_concept_id': obj['concept_id'], 'value_type': 'decimal'}, actor='owner')
    repo.transition(version_id, action='submit', actor='owner')
    repo.transition(version_id, action='approve', actor='reviewer')
    return repo, namespace, version_id, prop


def approved_draft(repo, namespace, version):
    draft = repo.create_draft(namespace, version=version, actor='owner')
    version_id = UUID(draft['ontology_version_id'])
    repo.transition(version_id, action='submit', actor='owner')
    repo.transition(version_id, action='approve', actor='reviewer')
    return version_id


def suggestion():
    repo = SuggestionRepository(DATABASE_URL)
    row = repo.create(target_type='openmetadata_table', target_ref='openmetadata://table/test-table',
                      suggestion_type='description', proposed_value={'description': 'Approved description', 'table_id': 'test-table'},
                      confidence=.9, rationale='Synthetic test', risk_level='low', model_provider='test',
                      model_name='test', model_version='1', policy_version='1', submitted_by='test:author', evidence=[])
    return repo, UUID(row['suggestion_id'])


def test_suggestion_pages_filter_before_limit_and_preserve_equal_timestamp_order():
    repo, seed = suggestion()
    target = f'openmetadata://table/pagination-{uuid4()}'
    identifiers = [uuid4() for _ in range(55)]
    with psycopg.connect(DATABASE_URL) as connection:
        for index, identifier in enumerate(identifiers):
            connection.execute(
                """INSERT INTO intelligence.suggestions
                       (suggestion_id,target_type,target_ref,suggestion_type,proposed_value,
                        confidence,risk_level,model_provider,model_name,policy_version,submitted_by,status,created_at)
                   SELECT %s,target_type,%s,suggestion_type,proposed_value,confidence,risk_level,
                          model_provider,model_name,policy_version,submitted_by,%s,'2026-10-01T00:00:00Z'
                     FROM intelligence.suggestions WHERE suggestion_id=%s""",
                (identifier, target, 'pending' if index >= 50 else 'applied', seed),
            )
    page = repo.list_page(status='pending', limit=2, target_refs=[target])
    assert len(page['items']) == 2 and page['next_cursor']
    seen = [item['suggestion_id'] for item in page['items']]
    while page['next_cursor']:
        page = repo.list_page(status='pending', limit=2, after=page['next_cursor'], target_refs=[target])
        seen.extend(item['suggestion_id'] for item in page['items'])
    assert seen == sorted((str(value) for value in identifiers[50:]), reverse=True)
    all_page = repo.list_page(status=None, limit=50, target_refs=[target])
    assert len(all_page['items']) == 50 and all_page['next_cursor']
    tail = repo.list_page(status=None, limit=50, target_refs=[target], after=all_page['next_cursor'])
    assert len(tail['items']) == 5 and tail['next_cursor'] is None
    assert len({item['suggestion_id'] for item in all_page['items'] + tail['items']}) == 55
    assert repo.list_page(status=None, limit=50, target_refs=[target + '_neighbor'])['items'] == []
    with pytest.raises(ValueError, match='Invalid suggestion cursor'):
        repo.list_page(status=None, limit=50, after='invalid')


def test_application_summary_distinguishes_retry_from_reconciliation_without_claim_token():
    repo, identifier = suggestion()
    repo.review(identifier, decision='approve', reviewer='reviewer', comment=None)
    claim = repo.start_application(identifier, actor='reviewer')
    assert repo.get(identifier)['next_action'] == 'wait'
    repo.finish_application(identifier, claim_token=claim.token, applied=False, error_code='source_unavailable')
    result = repo.get(identifier)
    assert result['next_action'] == 'retry'
    assert 'claim_token' not in result['application']
    claim = repo.start_application(identifier, actor='reviewer')
    repo.mark_effect_started(claim)
    repo.finish_application(identifier, claim_token=claim.token, applied=False, error_code='source_timeout')
    assert repo.get(identifier)['next_action'] == 'reconcile'


def test_successful_draft_reference_survives_suggestion_reload():
    repo, identifier = suggestion()
    repo.review(identifier, decision='approve', reviewer='reviewer', comment=None)
    claim = repo.start_application(identifier, actor='reviewer', target_system='teoria_binding')
    repo.mark_effect_started(claim)
    reference = f'teoria://binding/{uuid4()}'
    repo.record_effect_result(claim, reference)
    repo.finish_application(identifier, claim_token=claim.token, applied=True, external_change_ref=reference)
    result = repo.get(identifier)
    assert result['application']['external_change_ref'] == reference
    assert result['application']['effect_succeeded_at']
    assert result['next_action'] == 'none'


def test_retry_api_reuses_approval_and_records_authenticated_actor():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.admin.auth import AdminAuthorizer
    from teoria.admin.intelligence_api import create_intelligence_router
    from teoria.metadata.openmetadata import OpenMetadataError
    from teoria.settings import Settings

    repo, identifier = suggestion()

    class Client:
        fail = True
        writes = 0

        async def get(self, *args, **kwargs):
            if self.fail:
                raise OpenMetadataError('source_unavailable', 'Synthetic pre-effect failure')
            return {'id': 'test-table', 'description': None, 'version': 1}

        async def update_table_description(self, *args, **kwargs):
            self.writes += 1
            return {'version': 2}

    metadata = Client()
    service = SuggestionService(repo, metadata)
    with pytest.raises(SuggestionApplicationError):
        asyncio.run(service.review_and_apply(identifier, decision='approve', reviewer='initial-reviewer', comment=None))
    assert repo.get(identifier)['next_action'] == 'retry'
    metadata.fail = False
    app = FastAPI()
    app.include_router(create_intelligence_router(repo, service, AdminAuthorizer(Settings(
        admin_auth_mode='bearer', admin_api_token='synthetic-token',
        admin_api_actor='authenticated-reviewer', admin_api_roles='metadata_reviewer',
    ))))
    http = TestClient(app)
    path = f'/v1/admin/intelligence/suggestions/{identifier}/applications/retry'
    headers = {'Authorization': 'Bearer synthetic-token'}
    response = http.post(path, headers=headers, json={'reviewer': 'forged-reviewer'})
    assert response.status_code == 200 and response.json()['status'] == 'applied'
    assert metadata.writes == 1
    assert len(repo.get(identifier)['reviews']) == 1
    with psycopg.connect(DATABASE_URL) as connection:
        actors = connection.execute(
            "SELECT actor FROM intelligence.application_attempts WHERE change_application_id=%s",
            (repo.get_application(identifier)['change_application_id'],),
        ).fetchall()
    assert {row[0] for row in actors} == {'initial-reviewer', 'authenticated-reviewer'}
    assert http.post(path, headers=headers).status_code == 409
    assert metadata.writes == 1


def test_publication_checksum_matches_locked_content_and_published_edit_is_blocked():
    repo, namespace, version_id, prop = ontology()
    repo.publish(version_id, actor='publisher')
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as c:
        artifact = c.execute('SELECT checksum,content FROM ontology.runtime_artifacts WHERE ontology_version_id=%s', (version_id,)).fetchone()
    expected = hashlib.sha256(json.dumps(artifact['content'], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert artifact['checksum'] == expected
    with pytest.raises(ValueError, match='Only draft'):
        repo.update_item(version_id, kind='property', concept_id=UUID(prop['concept_id']), changes={'name': 'Wrong'}, actor='owner')
    with pytest.raises(ValueError, match='Only draft'):
        repo.delete_item(version_id, kind='property', concept_id=UUID(prop['concept_id']), actor='owner')
    assert repo.get_version(version_id)['objects'][0]['properties'][0]['name'] == 'Amount'


def test_concurrent_versions_publish_in_serial_order():
    repo, namespace, base_id, _ = ontology()
    repo.publish(base_id, actor='publisher')
    versions = [approved_draft(repo, namespace, value) for value in ('2.0', '3.0')]
    barrier = Barrier(2)
    def publish(version_id):
        barrier.wait(timeout=5)
        return repo.publish(version_id, actor='publisher')
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(publish, versions))
    assert len(results) == 2
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute("SELECT count(*) FROM ontology.ontology_versions v JOIN ontology.ontologies o USING(ontology_id) WHERE o.namespace=%s AND v.status='published'", (namespace,)).fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM ontology.runtime_artifacts WHERE ontology_version_id=ANY(%s)', (versions,)).fetchone()[0] == 2


def test_failed_publication_rolls_back_status_artifact_and_audit():
    repo, namespace, base_id, _ = ontology()
    repo.publish(base_id, actor='publisher')
    version_id = approved_draft(repo, namespace, '2.0')
    class FailingAuditRepository(OntologyAuthoringRepository):
        def _audit(self, conn, version_id, concept_id, event_type, *args):
            if event_type == 'published':
                raise RuntimeError('synthetic audit failure')
            return super()._audit(conn, version_id, concept_id, event_type, *args)
    with pytest.raises(RuntimeError, match='synthetic audit'):
        FailingAuditRepository(DATABASE_URL).publish(version_id, actor='publisher')
    assert repo.get_version(base_id)['status'] == 'published'
    assert repo.get_version(version_id)['status'] == 'approved'
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute('SELECT count(*) FROM ontology.runtime_artifacts WHERE ontology_version_id=%s', (version_id,)).fetchone()[0] == 0


def test_binding_approval_uses_current_revision_of_stable_concept():
    repo, namespace, base_id, prop = ontology()
    repo.publish(base_id, actor='publisher')
    bindings = BindingRepository(DATABASE_URL)
    binding = bindings.create_openmetadata_binding(ontology_ref_type='property', ontology_ref_id=None,
        ontology_concept_id=UUID(prop['concept_id']), target_type='data_asset', external_entity_id=str(uuid4()),
        entity_type='table', fully_qualified_name='test.db.schema.table', external_version='1', binding_type='semantic',
        purpose='test', authority='supplemental', priority=100, confidence=.9, provenance={}, created_by='owner')
    next_id = approved_draft(repo, namespace, '2.0')
    repo.publish(next_id, actor='publisher')
    approved = bindings.review_binding(UUID(binding['binding_id']), decision='approve', reviewer='reviewer', comment='test')
    assert approved['status'] == 'approved'
    assert approved['ontology_concept_id'] == prop['concept_id']
    assert approved['ontology_ref_id'] != prop['property_id']
    with pytest.raises(ValueError, match='Cannot approve'):
        bindings.review_binding(UUID(binding['binding_id']), decision='approve', reviewer='other', comment=None)


def test_application_requires_approval_and_blocks_concurrent_and_repeated_effects():
    repo, suggestion_id = suggestion()
    with pytest.raises(ApplicationStateError, match='approved suggestion'):
        repo.start_application(suggestion_id, actor='reviewer')
    repo.review(suggestion_id, decision='approve', reviewer='reviewer', comment='test')
    claim = repo.start_application(suggestion_id, actor='reviewer')
    with pytest.raises(ApplicationStateError) as exc:
        repo.start_application(suggestion_id, actor='other')
    assert exc.value.code == 'application_in_progress'
    repo.mark_effect_started(claim)
    repo.record_effect_result(claim, 'openmetadata://table/test@1')
    repo.finish_application(suggestion_id, applied=True, external_change_ref='openmetadata://table/test@1', claim_token=claim.token)
    with pytest.raises(ApplicationStateError) as exc:
        repo.start_application(suggestion_id, actor='other')
    assert exc.value.code == 'application_already_applied'
    assert repo.get_application(suggestion_id)['attempts'] == 1


def test_expired_pre_effect_claim_can_retry_but_old_writer_is_fenced():
    repo, suggestion_id = suggestion()
    repo.review(suggestion_id, decision='approve', reviewer='reviewer', comment=None)
    old = repo.start_application(suggestion_id, actor='reviewer')
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("UPDATE intelligence.change_applications SET lease_until=now()-interval '1 second' WHERE suggestion_id=%s", (suggestion_id,))
    new = repo.start_application(suggestion_id, actor='reviewer')
    assert new.application_id == old.application_id and new.token != old.token
    with pytest.raises(ApplicationStateError) as exc:
        repo.mark_effect_started(old)
    assert exc.value.code == 'application_claim_lost'
    with pytest.raises(ApplicationStateError):
        repo.finish_application(suggestion_id, applied=False, claim_token=old.token)
    repo.mark_effect_started(new)
    repo.finish_application(suggestion_id, applied=False, error_code='unknown_external_result', claim_token=new.token)
    with pytest.raises(ApplicationStateError) as exc:
        repo.start_application(suggestion_id, actor='reviewer')
    assert exc.value.code == 'application_reconciliation_required'


def test_pre_effect_failure_retains_application_identity_and_attempt_history():
    repo, suggestion_id = suggestion()
    repo.review(suggestion_id, decision='approve', reviewer='reviewer', comment=None)
    first = repo.start_application(suggestion_id, actor='reviewer')
    repo.finish_application(suggestion_id, applied=False, error_code='configuration_missing', claim_token=first.token)
    second = repo.start_application(suggestion_id, actor='retry-actor')
    assert first.application_id == second.application_id
    with psycopg.connect(DATABASE_URL) as c:
        assert c.execute('SELECT actor,outcome FROM intelligence.application_attempts WHERE change_application_id=%s ORDER BY started_at', (first.application_id,)).fetchall() == [('reviewer','failed'),('retry-actor',None)]


def test_description_recovery_reads_target_without_repeating_write():
    repo, suggestion_id = suggestion()
    repo.review(suggestion_id, decision='approve', reviewer='reviewer', comment=None)
    claim = repo.start_application(suggestion_id, actor='reviewer')
    repo.mark_effect_started(claim)
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("UPDATE intelligence.change_applications SET lease_until=now()-interval '1 second' WHERE suggestion_id=%s", (suggestion_id,))
    class ReadOnlyClient:
        reads = 0
        async def get(self, path, **kwargs):
            self.reads += 1
            return {'id':'test-table','description':'Approved description','version':2}
        async def update_table_description(self, *args, **kwargs):
            raise AssertionError('Recovery must not repeat the write')
    client = ReadOnlyClient()
    result = asyncio.run(SuggestionService(repo, client).reconcile_application(suggestion_id, actor='recovery-actor'))
    assert result['status'] == 'applied' and client.reads == 1


def test_success_checkpoint_recovers_database_completion_without_external_call():
    repo, suggestion_id = suggestion()
    repo.review(suggestion_id, decision='approve', reviewer='reviewer', comment=None)
    claim = repo.start_application(suggestion_id, actor='reviewer')
    repo.mark_effect_started(claim)
    repo.record_effect_result(claim, 'openmetadata://table/test@1')
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("UPDATE intelligence.change_applications SET lease_until=now()-interval '1 second' WHERE suggestion_id=%s", (suggestion_id,))
    result = asyncio.run(SuggestionService(repo, None).reconcile_application(suggestion_id, actor='recovery-actor'))
    assert result['status'] == 'applied'


def test_concurrent_approval_requests_do_not_repeat_external_write():
    repo, suggestion_id = suggestion()
    class Client:
        writes = 0
        async def get(self, *args, **kwargs):
            await asyncio.sleep(.02)
            return {'id':'test-table','description':None,'version':1}
        async def update_table_description(self, *args, **kwargs):
            self.writes += 1
            await asyncio.sleep(.02)
            return {'id':'test-table','version':2}
    client = Client()
    service = SuggestionService(repo, client)
    async def execute():
        return await asyncio.gather(*[service.review_and_apply(suggestion_id, decision='approve', reviewer='reviewer', comment=None) for _ in range(2)], return_exceptions=True)
    results = asyncio.run(execute())
    assert client.writes == 1
    assert sum(isinstance(result, dict) and result['status']=='applied' for result in results) == 1
    assert repo.get(suggestion_id)['status'] == 'applied'
    assert repo.get_application(suggestion_id)['attempts'] == 1


@pytest.mark.parametrize('case', ['no_effect', 'invalid_description', 'target_mismatch'])
def test_recovery_does_not_confirm_an_unproven_effect(case):
    repo, suggestion_id = suggestion()
    repo.review(suggestion_id, decision='approve', reviewer='reviewer', comment=None)
    claim = repo.start_application(suggestion_id, actor='reviewer')
    if case != 'no_effect':
        repo.mark_effect_started(claim)
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("UPDATE intelligence.change_applications SET lease_until=now()-interval '1 second' WHERE suggestion_id=%s", (suggestion_id,))
        if case == 'invalid_description':
            c.execute("UPDATE intelligence.suggestions SET proposed_value='{}'::jsonb WHERE suggestion_id=%s", (suggestion_id,))
    class Client:
        async def get(self, *args, **kwargs):
            return {'description': '' if case == 'invalid_description' else 'Different description' if case == 'target_mismatch' else 'Approved description'}
    with pytest.raises(SuggestionApplicationError) as exc:
        asyncio.run(SuggestionService(repo, Client()).reconcile_application(suggestion_id, actor='reviewer'))
    assert exc.value.code == 'application_reconciliation_required'
    assert repo.get(suggestion_id)['status'] == 'approved'


def test_recovery_api_requires_authentication_and_records_principal():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from teoria.admin.auth import AdminAuthorizer
    from teoria.admin.intelligence_api import create_intelligence_router
    from teoria.settings import Settings

    repo, suggestion_id = suggestion()
    repo.review(suggestion_id, decision='approve', reviewer='reviewer', comment=None)
    claim = repo.start_application(suggestion_id, actor='reviewer')
    repo.mark_effect_started(claim)
    repo.record_effect_result(claim, 'openmetadata://table/test@1')
    with psycopg.connect(DATABASE_URL) as c:
        c.execute("UPDATE intelligence.change_applications SET lease_until=now()-interval '1 second' WHERE suggestion_id=%s", (suggestion_id,))
    app = FastAPI()
    authorizer = AdminAuthorizer(Settings(admin_auth_mode='bearer', admin_api_token='synthetic-token',
        admin_api_actor='authenticated-reviewer', admin_api_roles='metadata_reviewer'))
    app.include_router(create_intelligence_router(repo, SuggestionService(repo, None), authorizer))
    client = TestClient(app)
    path = f'/v1/admin/intelligence/suggestions/{suggestion_id}/applications/reconcile'
    assert client.post(path).status_code == 401
    response = client.post(path, headers={'Authorization': 'Bearer synthetic-token'}, json={'actor': 'forged-actor'})
    assert response.status_code == 200 and response.json()['status'] == 'applied'
    with psycopg.connect(DATABASE_URL) as c:
        actor = c.execute("SELECT actor FROM intelligence.application_attempts WHERE change_application_id=%s AND outcome='reconciled' ORDER BY started_at DESC LIMIT 1", (claim.application_id,)).fetchone()[0]
    assert actor == 'authenticated-reviewer'


def test_application_history_pages_ties_and_rejects_other_suggestions_cursor():
    repo, identifier = suggestion()
    repo.review(identifier, decision='approve', reviewer='reviewer', comment=None)
    tokens = []
    for index in range(3):
        claim = repo.start_application(identifier, actor=f'actor:{index}')
        tokens.append(claim.token)
        repo.finish_application(identifier, claim_token=claim.token, applied=False, error_code='source_unavailable')
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("UPDATE intelligence.application_attempts SET started_at='2026-10-01T00:00:00Z' WHERE attempt_id=ANY(%s)", (tokens,))
    first = repo.application_attempts(identifier, limit=2)
    second = repo.application_attempts(identifier, limit=2, after=UUID(first['next_cursor']))
    assert [item['attempt_id'] for item in first['items'] + second['items']] == sorted(map(str, tokens), reverse=True)
    assert second['next_cursor'] is None
    assert {item['actor'] for item in first['items'] + second['items']} == {'actor:0', 'actor:1', 'actor:2'}
    assert all(item['outcome'] == 'failed' and item['error_code'] == 'source_unavailable' for item in first['items'] + second['items'])
    _, other = suggestion()
    assert repo.application_attempts(other) == {'items': [], 'next_cursor': None}
    with pytest.raises(ValueError, match='cursor'):
        repo.application_attempts(other, after=tokens[0])
    with pytest.raises(KeyError):
        repo.application_attempts(uuid4())
