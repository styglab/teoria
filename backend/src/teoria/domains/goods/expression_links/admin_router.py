"""Authenticated dictionary review; the authenticated principal owns all writes."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
import psycopg

from teoria.platform.access_control.auth import AdminPrincipal
from teoria.domains.goods.expression_links.contracts import DictionarySubmission
from teoria.domains.goods.expression_links.snapshot_contracts import ConceptDefinition, MappingProposal, MeaningDecision, MeaningResolution
from teoria.domains.goods.expression_links.snapshot_contracts import DictionaryChangeSet
from teoria.domains.goods.expression_links.snapshot_contracts import RelatedMeaningContext
from teoria.domains.goods.expression_links.snapshot_contracts import DictionaryMeaningReset
from teoria.domains.goods.expression_links.expression_contracts import OntologyMappingProposal, DictionaryDraftImport


def create_goods_dictionary_router(service, authorizer, meaning_service=None):
    router = APIRouter(prefix='/v1/admin/goods/dictionary',tags=['goods-dictionary'])
    principal = authorizer.require('ontology_owner')

    def require_service():
        if service is None:
            raise HTTPException(503,detail={'code':'app_database_unavailable'})
        return service

    async def translate(call):
        try:
            return jsonable_encoder(await call)
        except KeyError as exc:
            raise HTTPException(404,detail={'code':'dictionary_operation_not_found'}) from exc
        except (ValueError,psycopg.IntegrityError) as exc:
            raise HTTPException(409,detail={'code':'dictionary_operation_conflict','message':str(exc)}) from exc

    @router.post('/operations/{operation_id}')
    async def author(operation_id: str, payload: DictionarySubmission, actor: AdminPrincipal = Depends(principal)):
        return await translate(require_service().author(operation_id,payload,actor=actor.actor))

    @router.get('/operations/{operation_id}')
    async def operation(operation_id: str, actor: AdminPrincipal = Depends(principal)):
        return await translate(require_service().operation(operation_id,actor=actor.actor))

    @router.get('/entries')
    async def entries(query: str = Query(default='',max_length=300),
                      kind: Literal['item_type','characteristic'] | None = None,
                      limit: int = Query(default=100,ge=1,le=500),
                      actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(require_service().list_entries(query=query,kind=kind,limit=limit))}

    @router.get('/entries/{entry_id}/evidence')
    async def source_evidence(entry_id: UUID, actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(meanings().source_evidence(entry_id))}

    @router.get('/entries/{entry_id}/audit')
    async def audit(entry_id: UUID, actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(require_service().audit(entry_id))}

    def meanings():
        if meaning_service is None:
            raise HTTPException(503, detail={'code':'app_database_unavailable'})
        return meaning_service

    @router.get('/classifications')
    async def classifications(query: str = Query('',max_length=10,pattern=r'^[0-9]*$'),
                              offset: int = Query(0,ge=0), limit: int = Query(25,ge=1,le=100),
                              actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().classifications(query=query,offset=offset,limit=limit))

    @router.get('/catalog')
    async def catalog(kind: Literal['concept','mapping','source'] = 'concept',
                      query: str = Query('',max_length=300),
                      status: Literal['draft','approved','rejected','deprecated'] | None = None,
                      concept_kind: Literal['item_type','characteristic'] | None = None,
                      classification: str | None = Query(None,pattern=r'^(?:[0-9]{10}|unclassified)$'),
                      unresolved: bool = False,
                      historical: bool = False,
                      offset: int = Query(0,ge=0), limit: int = Query(25,ge=1,le=500),
                      actor: AdminPrincipal = Depends(principal)):
        if unresolved and (kind != "source" or classification is None):
            raise HTTPException(422,detail={"code":"unresolved_requires_scoped_source"})
        options = {'historical': True} if historical else {}
        return await translate(meanings().catalog(kind,query=query,status=status,concept_kind=concept_kind,offset=offset,limit=limit,classification=classification,unresolved=unresolved,**options))

    @router.post('/concepts')
    async def propose_concept(payload: ConceptDefinition, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().propose_concept(payload, actor=actor.actor))

    @router.post('/ontology-draft-imports')
    async def import_legacy(payload: DictionaryDraftImport, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().import_legacy_definitions(payload, actor=actor.actor))

    @router.get('/concepts')
    async def concepts(actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(meanings().list_records('concept'))}

    @router.post('/mappings')
    async def propose_mapping(payload: OntologyMappingProposal | MappingProposal, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().propose_mapping(payload, actor=actor.actor))

    @router.get('/mappings')
    async def mappings(actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(meanings().list_records('mapping'))}

    @router.post('/resolve')
    async def resolve(payload: MeaningResolution, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().resolve(payload))

    @router.get('/snapshot')
    async def snapshot(actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().snapshot())

    @router.post('/reset-meanings')
    async def reset_meanings(payload: DictionaryMeaningReset, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().reset_meanings(payload,actor=actor.actor))

    @router.post('/related-context')
    async def related_context(payload: RelatedMeaningContext, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().related_context(payload))

    @router.post('/maintenance/{operation_id}')
    async def maintain(operation_id: str, payload: DictionaryChangeSet, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().apply_changes(operation_id,payload,actor=actor.actor))

    @router.post('/maintenance-preview')
    async def preview(payload: DictionaryChangeSet, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().preview_changes(payload))

    @router.post('/{kind}/{entity_id}/decisions')
    async def decide(kind: Literal['concept','mapping'], entity_id: UUID, payload: MeaningDecision,
                     actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().decide(kind,entity_id,payload,actor=actor.actor))

    @router.get('/{kind}/{entity_id}/audit')
    async def meaning_audit(kind: Literal['concept','mapping'], entity_id: UUID,
                            actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(meanings().audit(kind,entity_id))}

    return router
