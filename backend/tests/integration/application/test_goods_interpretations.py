"""Actual SQL, publication/profile approval and concurrent document interpretation review."""
import asyncio
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import yaml

from backend.tests.domains.goods.normalization.test_interpretations import meaning_case
from teoria.domains.goods.data_processing.storage.artifact_reader import verified_artifact
from teoria.domains.goods.data_processing.storage.artifact_store import artifact_store
from teoria.domains.goods.normalization.contracts import checksum
from teoria.domains.goods.normalization.meaning_proposals.interpretation_repository import InterpretationRepository
from teoria.domains.goods.normalization.meaning_proposals.interpretation_service import InterpretationService
from teoria.domains.goods.normalization.profiles.service import NormalizationProfileService
from teoria.platform.ontology.authoring.blueprint import OntologyBlueprint, apply_ontology_blueprint
from teoria.platform.ontology.authoring.service import OntologyAuthoringService
from teoria.integrations.application_database import apply_migrations

DATABASE_URL = os.getenv('TEORIA_TEST_APP_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='isolated Application DB required')


async def test_sql_review_approval_replay_and_application_preserve_original(tmp_path):
    await apply_migrations(DATABASE_URL, Path('backend/migrations/application'))
    authoring = OntologyAuthoringService(DATABASE_URL)
    blueprint = OntologyBlueprint.model_validate(yaml.safe_load(Path('backend/authoring/ontology_blueprints/goods.yaml').read_text()))
    blueprint.target_version='99.0.'+str(uuid4().int % 100000000)
    created = await apply_ontology_blueprint(authoring,blueprint,actor='fixture:author')
    version_id=UUID(created['ontology_version_id'])
    for action in ['submit','approve']:
        await authoring.transition(version_id,action=action,actor='fixture:ontology-reviewer')
    await authoring.publish(version_id,actor='fixture:publisher')
    publication=await authoring.publication(version_id)
    profiles=NormalizationProfileService(DATABASE_URL,ontology_authoring=authoring)
    template=json.loads(Path('docs/domains/goods/specifications/examples/server_memory_profile.json').read_text())
    template['profile_key']='review_sql_'+uuid4().hex
    created=await profiles.create_from_template(version_id,template,actor='fixture:author')
    profile_id=UUID(created['revision_id'])
    for action in ['submit','approve']: await profiles.transition(profile_id,action=action,actor='fixture:profile-reviewer')
    request,result,_,_,_=meaning_case()
    request.review_id='review_sql_'+uuid4().hex
    request.profile_revision_id=profile_id
    keys={row['stable_key']:UUID(row['concept_id']) for obj in publication.content['objects'] for row in [obj,*obj['properties']]}
    request.entities[0].concept_id=keys['goods.server'];request.entities[1].concept_id=keys['goods.memory_module']
    for prop,key in zip(request.properties,['goods.memory_module.capacity','goods.server.memory_capacity_per_socket_limit','goods.server.memory_slot_count']):
        prop.concept_id=keys[key]
    request.compositions[0].composition_concept_id=keys['goods.composition_statement']
    request.compositions[0].quantity_property_concept_id=keys['goods.composition_statement.quantity_value']
    async with artifact_store(tmp_path.as_uri()) as store:
        ref=await store.put('source_result.json',json.dumps(result).encode())
    request.result.uri,request.result.sha256=ref.uri,ref.sha256
    service=InterpretationService(InterpretationRepository(DATABASE_URL),profiles,authoring,
        lambda r:verified_artifact(r,tmp_path),lambda:artifact_store(tmp_path.as_uri()))
    created=await service.create(request,actor='fixture:author');revision=UUID(created['revision_id'])
    assert (await service.create(request,actor='fixture:author'))['revision_id']==str(revision)
    with pytest.raises(ValueError,match='approval_required'):await service.export(revision)
    await service.transition(revision,action='submit',expected_status='draft',expected_request_checksum=checksum(request),actor='fixture:author')
    outcomes=await asyncio.gather(*[service.transition(revision,action='approve',expected_status='in_review',
        expected_request_checksum=checksum(request),actor='fixture:reviewer_'+str(i)) for i in range(2)],return_exceptions=True)
    assert sum(isinstance(x,dict) for x in outcomes)==1
    assert sum(isinstance(x,ValueError) for x in outcomes)==1
    approval=await service.export(revision)
    assert approval['approval_actor'].startswith('fixture:reviewer_')
    applied=await service.apply(revision,run_id='sql_fixture',actor='fixture:operator',expected_request_checksum=checksum(request))
    assert applied==await service.apply(revision,run_id='sql_fixture',actor='fixture:operator',expected_request_checksum=checksum(request))
    audit=await service.audit(revision)
    assert [e['action'] for e in audit]==['created','submit','approve','apply']
    assert audit[-1]['actor']=='fixture:operator'
    assert json.loads((tmp_path/'source_result.json').read_text())==result
    assert (await authoring.publication(version_id))==publication
    await service.transition(revision,action='deprecate',expected_status='approved',expected_request_checksum=checksum(request),actor='fixture:reviewer')
    with pytest.raises(ValueError,match='approval_required'):await service.export(revision)

    # Approval state and its audit must roll back together if recording the event fails.
    from unittest.mock import AsyncMock
    request.review_id='rollback_sql_'+uuid4().hex
    another=await service.create(request,actor='fixture:author');pending=UUID(another['revision_id'])
    await service.transition(pending,action='submit',expected_status='draft',expected_request_checksum=checksum(request),actor='fixture:author')
    record_event=service.repository.event
    service.repository.event=AsyncMock(side_effect=RuntimeError('isolated audit failure'))
    try:
        with pytest.raises(RuntimeError,match='audit failure'):
            await service.transition(pending,action='approve',expected_status='in_review',expected_request_checksum=checksum(request),actor='fixture:reviewer')
    finally:
        service.repository.event=record_event
    assert (await service.get(pending))['status']=='in_review'
    assert [e['action'] for e in await service.audit(pending)]==['created','submit']
