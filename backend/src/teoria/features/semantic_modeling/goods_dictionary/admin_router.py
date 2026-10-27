"""Authenticated dictionary review; the authenticated principal owns all writes."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
import psycopg

from teoria.features.access_control.auth import AdminPrincipal
from teoria.features.semantic_modeling.goods_dictionary.contracts import DictionarySubmission
from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import ConceptDefinition, MappingProposal, MeaningDecision, MeaningResolution


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

    @router.get('/entries/{entry_id}/audit')
    async def audit(entry_id: UUID, actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(require_service().audit(entry_id))}

    def meanings():
        if meaning_service is None:
            raise HTTPException(503, detail={'code':'app_database_unavailable'})
        return meaning_service

    @router.post('/concepts')
    async def propose_concept(payload: ConceptDefinition, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().propose_concept(payload, actor=actor.actor))

    @router.get('/concepts')
    async def concepts(actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(meanings().list_records('concept'))}

    @router.post('/mappings')
    async def propose_mapping(payload: MappingProposal, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().propose_mapping(payload, actor=actor.actor))

    @router.get('/mappings')
    async def mappings(actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(meanings().list_records('mapping'))}

    @router.post('/resolve')
    async def resolve(payload: MeaningResolution, actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().resolve(payload))

    @router.post('/{kind}/{entity_id}/decisions')
    async def decide(kind: Literal['concept','mapping'], entity_id: UUID, payload: MeaningDecision,
                     actor: AdminPrincipal = Depends(principal)):
        return await translate(meanings().decide(kind,entity_id,payload,actor=actor.actor))

    @router.get('/{kind}/{entity_id}/audit')
    async def meaning_audit(kind: Literal['concept','mapping'], entity_id: UUID,
                            actor: AdminPrincipal = Depends(principal)):
        return {'items':await translate(meanings().audit(kind,entity_id))}

    return router
