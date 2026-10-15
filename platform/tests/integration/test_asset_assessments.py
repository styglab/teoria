import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import psycopg
import pytest

from teoria.intelligence.asset_assessment.models import AssessmentOutput, AssessmentRequest
from teoria.intelligence.asset_assessment.repository import AssessmentRepository
from teoria.intelligence.asset_assessment.service import AssetAssessmentService
from teoria.intelligence.repository import SuggestionRepository
from teoria.persistence import apply_migrations

DATABASE_URL = os.environ.get('TEORIA_TEST_APP_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='TEORIA_TEST_APP_DATABASE_URL is not set')


@pytest.fixture(scope='module', autouse=True)
def migrated_database():
    apply_migrations(DATABASE_URL, Path(__file__).parents[2] / 'database/migrations')


def create(repo, *, identifier=None):
    identifier = identifier or uuid4()
    return repo.create(target_ref={'system': 'openmetadata', 'entity_id': str(identifier),
        'entity_type': 'table', 'fully_qualified_name': f's.d.c.t_{identifier.hex}', 'version': 1.0},
        request=AssessmentRequest(table_fqn=f's.d.c.t_{identifier.hex}', scopes=['metadata_enrichment']),
        actor='test:requester', model='synthetic')


def proposal(job):
    return {'target_type': 'openmetadata_table',
        'target_ref': f"openmetadata://table/{job['target_ref']['fully_qualified_name']}",
        'suggestion_type': 'description', 'proposed_value': {'description': 'Synthetic proposal'},
        'confidence': .6, 'risk_level': 'medium', 'rationale': 'Synthetic evidence',
        'model_provider': 'test', 'model_name': 'synthetic', 'model_version': None,
        'policy_version': 'asset_assessment_v1', 'submitted_by': 'test:requester',
        'evidence': [{'evidence_type': 'synthetic', 'source_ref': 'test://source'}]}


def test_duplicate_requests_and_claims_are_serialized():
    repo = AssessmentRepository(DATABASE_URL)
    identifier = uuid4()
    with ThreadPoolExecutor(max_workers=2) as executor:
        rows = list(executor.map(lambda _: create(repo, identifier=identifier), range(2)))
    assert rows[0]['assessment_id'] == rows[1]['assessment_id']
    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed = list(executor.map(lambda _: repo.claim(), range(2)))
    jobs = [job for job in claimed if job]
    assert len(jobs) == 1
    assert repo.finish(jobs[0], proposals=[], findings=[])
    assert repo.get(jobs[0]['assessment_id'])['status'] == 'completed'


def test_expired_worker_cannot_publish_and_pending_proposals_are_reused():
    repo = AssessmentRepository(DATABASE_URL)
    create(repo)
    old = repo.claim()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("UPDATE intelligence.asset_assessments SET lease_until=now()-interval '1 second' WHERE assessment_id=%s", (old['assessment_id'],))
    new = repo.claim()
    assert new['claim_token'] != old['claim_token']
    assert repo.finish(old, proposals=[proposal(old)], findings=[]) is False
    assert repo.finish(new, proposals=[proposal(new)], findings=[])
    first = repo.get(new['assessment_id'])
    assert len(first['suggestion_ids']) == 1
    assert 'claim_token' not in first
    assert SuggestionRepository(DATABASE_URL).get(UUID(first['suggestion_ids'][0]))['status'] == 'pending'
    create(repo, identifier=UUID(new['target_ref']['entity_id']))
    repeated = repo.claim()
    assert repo.finish(repeated, proposals=[proposal(repeated)], findings=[])
    assert repo.get(repeated['assessment_id'])['suggestion_ids'] == first['suggestion_ids']


def test_proposals_and_final_state_are_one_transaction():
    repo = AssessmentRepository(DATABASE_URL)
    create(repo)
    job = repo.claim()
    invalid = {**proposal(job), 'target_ref': 'zz-invalid://test', 'confidence': 2}
    with pytest.raises(psycopg.errors.CheckViolation):
        repo.finish(job, proposals=[proposal(job), invalid], findings=[])
    assert repo.get(job['assessment_id'])['suggestion_ids'] == []
    assert repo.get(job['assessment_id'])['status'] == 'running'
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute('SELECT count(*) FROM intelligence.suggestions WHERE target_ref=%s', (proposal(job)['target_ref'],)).fetchone()[0] == 0
    repo.finish(job, proposals=[], findings=[], error_code='test_failure')


def test_worker_pipeline_persists_generated_proposal_without_approval():
    repo = AssessmentRepository(DATABASE_URL)
    row = create(repo)
    job = repo.claim()
    fqn = row['target_ref']['fully_qualified_name']
    metadata = SimpleNamespace(get_table_by_name=AsyncMock(return_value={
        'id': row['target_ref']['entity_id'], 'name': 'synthetic', 'version': 1.0,
        'fullyQualifiedName': fqn, 'columns': []}))
    model = SimpleNamespace(model='synthetic', generate=AsyncMock(return_value=AssessmentOutput.model_validate({
        'changes': [{'kind': 'description', 'description': 'Synthetic generated description', 'confidence': .8,
                     'reason': 'Synthetic metadata', 'evidence_ids': ['table']}]})))
    asyncio.run(AssetAssessmentService(repo, metadata, None, model).process(job))
    result = repo.get(job['assessment_id'])
    assert result['status'] == 'completed' and len(result['suggestion_ids']) == 1
    saved = SuggestionRepository(DATABASE_URL).get(UUID(result['suggestion_ids'][0]))
    assert saved['status'] == 'pending' and saved['submitted_by'] == 'test:requester'
    assert saved['reviews'] == []


def test_repeated_worker_crashes_end_after_three_claims():
    repo = AssessmentRepository(DATABASE_URL)
    row = create(repo)
    job = repo.claim()
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute("UPDATE intelligence.asset_assessments SET attempts=3,lease_until=now()-interval '1 second' WHERE assessment_id=%s", (job['assessment_id'],))
    assert repo.claim() is None
    result = repo.get(UUID(row['assessment_id']))
    assert result['status'] == 'failed'
    assert result['error_code'] == 'worker_lease_exhausted'
    assert not repo.finish(job, proposals=[proposal(job)], findings=[])
