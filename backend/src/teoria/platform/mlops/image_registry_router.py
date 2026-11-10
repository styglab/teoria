"""Authenticated image catalog; image bytes and credentials remain in the registry."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from teoria.integrations.image_registry import REPOSITORY, TAG, ImageRegistryClient
from teoria.platform.access_control.auth import AdminAuthorizer, AdminPrincipal


def create_image_registry_router(
    *, authorizer: AdminAuthorizer, registry: ImageRegistryClient | None
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/image-registry", tags=["image-registry"])

    async def read(operation):
        if registry is None:
            raise HTTPException(503, detail={"code": "image_registry_not_configured"})
        try:
            return await operation(registry)
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 404:
                raise HTTPException(404, detail={"code": "image_not_found"}) from None
            if status in {401, 403}:
                # An upstream credential failure must not expire the Admin session.
                raise HTTPException(
                    503, detail={"code": "image_registry_auth_failed"}
                ) from None
            raise HTTPException(
                503, detail={"code": "image_registry_unavailable"}
            ) from None
        except httpx.HTTPError:
            raise HTTPException(
                503, detail={"code": "image_registry_unavailable"}
            ) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(
                502, detail={"code": "invalid_image_registry_response"}
            ) from None

    @router.get("/status")
    async def status(principal: AdminPrincipal = Depends(authorizer.require())):
        return {
            "configured": registry is not None,
            "host": registry.host if registry else None,
        }

    @router.get("/repositories")
    async def repositories(
        after: str = Query("", max_length=255),
        limit: int = Query(25, ge=1, le=100),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        return await read(lambda r: r.repositories(after=after, limit=limit))

    @router.get("/tags")
    async def tags(
        repository: str = Query(
            ..., min_length=1, max_length=255, pattern=f"^{REPOSITORY}$"
        ),
        after: str = Query("", max_length=128),
        limit: int = Query(25, ge=1, le=100),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        return await read(lambda r: r.tags(repository, after=after, limit=limit))

    @router.get("/manifest")
    async def manifest(
        repository: str = Query(
            ..., min_length=1, max_length=255, pattern=f"^{REPOSITORY}$"
        ),
        reference: str = Query(
            ...,
            min_length=1,
            max_length=128,
            pattern=f"^(?:{TAG}|sha256:[a-f0-9]{{64}})$",
        ),
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        return await read(lambda r: r.manifest(repository, reference))

    return router
