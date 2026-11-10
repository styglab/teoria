"""Review and apply document interpretations through an authenticated domain boundary."""
import asyncio
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field

from teoria.domains.goods.contracts import Record
from teoria.domains.goods.data_processing.storage.artifact_reader import ArtifactReadError
from teoria.domains.goods.normalization.application.meaning_application import InterpretationRequest
from teoria.platform.access_control.auth import AdminPrincipal


class InterpretationTransition(Record):
    action: Literal['submit', 'approve', 'reject', 'deprecate']
    expected_status: Literal['draft', 'in_review', 'approved', 'rejected', 'deprecated']
    expected_request_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    comment: str | None = Field(default=None, max_length=2000)


class InterpretationApplication(Record):
    run_id: str = Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')
    expected_request_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')


def create_interpretation_router(service, authorizer):
    router = APIRouter(prefix='/v1/admin/goods/interpretations', tags=['goods-interpretations'])
    principal = authorizer.require('ontology_owner')
    slots = asyncio.Semaphore(2)

    async def invoke(method, *args, **kwargs):
        if service is None:
            raise HTTPException(503, detail={'code': 'app_database_unavailable'})
        try:
            async with slots:
                return await getattr(service, method)(*args, **kwargs)
        except KeyError:
            raise HTTPException(404, detail={'code': 'interpretation_not_found'}) from None
        except ArtifactReadError as exc:
            raise HTTPException(exc.status_code, detail={'code': exc.detail}) from None
        except (ValueError, psycopg.IntegrityError):
            raise HTTPException(409, detail={'code': 'invalid_interpretation_operation'}) from None

    @router.post('', status_code=201)
    async def create(payload: InterpretationRequest, actor: AdminPrincipal = Depends(principal)):
        return await invoke('create', payload, actor=actor.actor)

    @router.get('/{revision_id}')
    async def get(revision_id: UUID, actor: AdminPrincipal = Depends(principal)):
        return await invoke('get', revision_id)

    @router.get('/{revision_id}/review')
    async def review(revision_id: UUID, actor: AdminPrincipal = Depends(principal)):
        return await invoke('review', revision_id)

    @router.post('/{revision_id}/transitions')
    async def transition(revision_id: UUID, payload: InterpretationTransition, actor: AdminPrincipal = Depends(principal)):
        return await invoke('transition', revision_id, **payload.model_dump(), actor=actor.actor)

    @router.get('/{revision_id}/approval')
    async def export(revision_id: UUID, actor: AdminPrincipal = Depends(principal)):
        return await invoke('export', revision_id)

    @router.post('/{revision_id}/applications')
    async def apply(revision_id: UUID, payload: InterpretationApplication, actor: AdminPrincipal = Depends(principal)):
        return await invoke('apply', revision_id, **payload.model_dump(), actor=actor.actor)

    @router.get('/{revision_id}/audit')
    async def audit(revision_id: UUID, actor: AdminPrincipal = Depends(principal)):
        return await invoke('audit', revision_id)

    return router
