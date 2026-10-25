"""Authenticated goods profile authoring; Pipeline consumers use exported files only."""
from typing import Literal
import asyncio
from uuid import UUID
from fastapi import APIRouter,Depends,HTTPException,Response
from pydantic import BaseModel,ConfigDict,Field
import psycopg
from teoria.admin.auth import AdminAuthorizer,AdminPrincipal
from teoria_goods_normalization import NormalizationProfile,canonical_bytes
from .repository import NormalizationProfileRepository
from teoria_goods_normalization.candidates import CandidateBundle
from .candidate_proposals import CandidateSelection


class TransitionInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action: Literal['submit','request_changes','approve','reject','deprecate']
    comment: str|None=None


class TemplateInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    ontology_version_id: UUID
    profile_template: dict


class CandidateInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    base_revision_id: UUID
    bundles: list[CandidateBundle] = Field(min_length=1,max_length=50)


class CandidateDraftInput(CandidateInput):
    version: str = Field(min_length=1,max_length=100)
    selections: list[CandidateSelection] = Field(min_length=1,max_length=5000)


class SemanticInput(CandidateInput):
    model: str = Field(min_length=1,max_length=100)
    timeout: int = Field(default=300,ge=1,le=600)


class SemanticDraftInput(CandidateInput):
    semantic_report: dict
    version: str = Field(min_length=1,max_length=100)


class SemanticProfileInput(SemanticDraftInput):
    published_version_id: UUID


class SemanticCycleInput(SemanticInput):
    version: str = Field(min_length=1,max_length=100)
    auto_approve: bool = False


def create_normalization_profile_router(repository: NormalizationProfileRepository|None,authorizer: AdminAuthorizer):
    router=APIRouter(prefix='/v1/admin/goods/normalization-profiles',tags=['goods-normalization'])
    principal_dependency=authorizer.require('ontology_owner')
    meaning_slots=asyncio.Semaphore(1)
    def repo():
        if repository is None:raise HTTPException(503,detail={'code':'app_database_unavailable'})
        return repository
    async def translate(call):
        try:return await call
        except KeyError as exc:raise HTTPException(404,detail={'code':'normalization_profile_not_found'}) from exc
        except (ValueError,psycopg.IntegrityError) as exc:
            raise HTTPException(409,detail={'code':'invalid_normalization_profile_operation'}) from exc
        except TimeoutError as exc:raise HTTPException(504,detail={'code':'semantic_model_timeout'}) from exc
        except (RuntimeError,OSError) as exc:raise HTTPException(503,detail={'code':'semantic_model_unavailable'}) from exc

    @router.post('',status_code=201)
    async def create(payload: NormalizationProfile,principal: AdminPrincipal=Depends(principal_dependency)):
        return await translate(repo().create(payload,actor=principal.actor))
    @router.post('/from-template',status_code=201)
    async def from_template(payload: TemplateInput,principal: AdminPrincipal=Depends(principal_dependency)):
        return await translate(repo().create_from_template(payload.ontology_version_id,payload.profile_template,actor=principal.actor))
    @router.post('/candidate-proposals')
    async def candidate_proposals(payload: CandidateInput,principal: AdminPrincipal=Depends(principal_dependency)):
        return await translate(repo().candidate_proposals(payload.base_revision_id,payload.bundles))
    @router.post('/from-candidates',status_code=201)
    async def from_candidates(payload: CandidateDraftInput,principal: AdminPrincipal=Depends(principal_dependency)):
        return await translate(repo().create_from_candidates(payload.base_revision_id,payload.bundles,
            payload.selections,version=payload.version,actor=principal.actor))
    @router.post('/semantic-proposals')
    async def semantic_proposals(payload: SemanticInput,principal: AdminPrincipal=Depends(principal_dependency)):
        from .semantic_resolution import resolve_meanings
        profile,ontology=await translate(repo()._candidate_context(payload.base_revision_id))
        async with meaning_slots:
            return await translate(resolve_meanings(payload.bundles,profile,ontology,model=payload.model,timeout=payload.timeout))
    @router.post('/semantic-ontology-drafts',status_code=201)
    async def semantic_ontology_draft(payload: SemanticDraftInput,principal: AdminPrincipal=Depends(principal_dependency)):
        from .semantic_authoring import create_ontology_draft
        return await translate(create_ontology_draft(repo(),payload.base_revision_id,payload.bundles,
            payload.semantic_report,version=payload.version,actor=principal.actor))
    @router.post('/semantic-profile-drafts',status_code=201)
    async def semantic_profile_draft(payload: SemanticProfileInput,principal: AdminPrincipal=Depends(principal_dependency)):
        from .semantic_authoring import materialize_profile
        return await translate(materialize_profile(repo(),payload.base_revision_id,payload.bundles,
            payload.semantic_report,published_version_id=payload.published_version_id,version=payload.version,actor=principal.actor))
    @router.post('/semantic-cycles')
    async def semantic_cycle(payload: SemanticCycleInput,principal: AdminPrincipal=Depends(principal_dependency)):
        from .semantic_workflow import run_semantic_cycle
        async with meaning_slots:
            return await translate(run_semantic_cycle(repo(),payload.base_revision_id,payload.bundles,
                model=payload.model,version=payload.version,actor=principal.actor,
                auto_approve=payload.auto_approve,timeout=payload.timeout))
    @router.get('/{revision_id}')
    async def get(revision_id: UUID,principal: AdminPrincipal=Depends(principal_dependency)):
        return await translate(repo().get(revision_id))
    @router.put('/{revision_id}')
    async def update(revision_id: UUID,payload: NormalizationProfile,principal: AdminPrincipal=Depends(principal_dependency)):
        return await translate(repo().update(revision_id,payload,actor=principal.actor))
    @router.post('/{revision_id}/transitions')
    async def transition(revision_id: UUID,payload: TransitionInput,principal: AdminPrincipal=Depends(principal_dependency)):
        return await translate(repo().transition(revision_id,**payload.model_dump(),actor=principal.actor))
    @router.get('/{revision_id}/package')
    async def export(revision_id: UUID,principal: AdminPrincipal=Depends(principal_dependency)):
        package=await translate(repo().export(revision_id))
        return Response(canonical_bytes(package),media_type='application/json',headers={'ETag':f'"{package.checksum}"'})
    @router.get('/{revision_id}/audit')
    async def audit(revision_id: UUID,principal: AdminPrincipal=Depends(principal_dependency)):
        return {'items':await translate(repo().audit(revision_id))}
    return router
