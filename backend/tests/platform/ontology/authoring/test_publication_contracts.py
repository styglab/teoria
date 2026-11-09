from contextlib import asynccontextmanager
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from teoria.platform.ontology.authoring.publication_contracts import (
    PublishedOntology, PublishedOntologyContext, publication_checksum, select_publication_concepts,
)
from teoria.platform.ontology.authoring.service import OntologyAuthoringService


def publication():
    owner, prop, relationship = [str(uuid4()) for _ in range(3)]
    content = {'namespace':'test', 'version':'1', 'objects':[
        {'business_object_id':'revision', 'concept_id':owner, 'stable_key':'test.item',
         'name':'Item', 'properties':[{'concept_id':prop, 'stable_key':'test.item.capacity',
                                      'name':'Capacity', 'value_type':'number'}]}],
        'relationships':[{'concept_id':relationship, 'stable_key':'test.related', 'name':'Related',
                          'source_object_id':'revision', 'target_object_id':'revision'}]}
    return {'ontology':{'version_id':str(uuid4()), 'namespace':'test', 'version':'1',
                        'checksum':publication_checksum(content)}, 'content':content}, (owner, prop, relationship)


def test_context_resolves_stable_owners_and_relation_endpoints_without_source_state():
    artifact, (owner, prop, relationship) = publication()
    context = PublishedOntologyContext.from_publications([artifact])
    catalog = select_publication_concepts(context.ontologies, [prop, relationship])
    assert set(catalog) == {owner, prop, relationship}
    assert catalog[prop]['owner_concept_id'] == owner
    assert catalog[relationship]['source_concept_id'] == owner
    assert catalog[relationship]['target_concept_id'] == owner
    assert 'revision' not in catalog


@pytest.mark.parametrize('change,code', [('content','checksum'), ('identity','identity')])
def test_content_cannot_be_substituted_under_a_publication_reference(change, code):
    artifact, _ = publication()
    if change == 'content':
        artifact['content']['objects'][0]['name'] = 'Changed meaning'
    else:
        artifact['ontology']['namespace'] = 'other'
    with pytest.raises(ValueError, match=code):
        PublishedOntology.model_validate(artifact)


def test_multiple_versions_of_one_selected_concept_are_ambiguous():
    first, (_, prop, _) = publication()
    second = deepcopy(first)
    second['ontology']['version_id'] = str(uuid4())
    with pytest.raises(ValueError, match='ambiguous'):
        select_publication_concepts([first, second], [prop])


async def test_publication_service_reads_published_status_only_and_rechecks_content():
    artifact, _ = publication()
    connection = object()
    @asynccontextmanager
    async def transaction():
        yield connection
    repository = AsyncMock()
    repository.transaction = transaction
    repository.read_artifact.return_value = {
        'content':artifact['content'], 'checksum':artifact['ontology']['checksum'], 'status':'published'}
    service = OntologyAuthoringService(repository=repository)
    identifier = artifact['ontology']['version_id']
    result = await service.publication(identifier)
    assert result.model_dump(mode='json') == artifact
    repository.read_artifact.assert_awaited_once_with(connection, identifier, statuses=['published'],
                                                      expected_checksum=None, lock=False)
    repository.read_artifact.return_value = None
    with pytest.raises(KeyError):
        await service.publication(identifier)
