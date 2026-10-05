from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from teoria.admin.auth import AdminAuthorizer, AdminPrincipal
from teoria.binding.repository import BindingRepository
from teoria.registry.loader import RegistryCatalog


class OpenMetadataBindingInput(BaseModel):
    ontology_ref_type: Literal["object", "property", "relationship", "rule", "metric"]
    ontology_ref_id: UUID | None = None
    ontology_concept_id: UUID | None = None
    target_type: Literal["glossary_term", "data_asset"]
    external_entity_id: str
    entity_type: str
    fully_qualified_name: str
    external_version: str | None = None
    binding_type: str = "represents"
    purpose: str | None = None
    authority: Literal["authoritative", "preferred", "supplemental"] = "supplemental"
    priority: int = Field(default=100, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_ontology_reference(self):
        if self.ontology_ref_id is None and self.ontology_concept_id is None:
            raise ValueError("ontology_ref_id or ontology_concept_id is required")
        return self


class BindingReviewInput(BaseModel):
    decision: Literal["approve", "reject", "deprecate"]
    comment: str | None = None


class CapabilityBindingInput(BaseModel):
    ontology_ref_type: Literal["object", "property", "relationship", "rule", "metric"]
    ontology_ref_id: UUID | None = None
    ontology_concept_id: UUID | None = None
    capability_id: str
    target_scope: Literal["capability", "input", "output"]
    field_path: str | None = None
    binding_type: str = "provides"
    purpose: str | None = None
    authority: Literal["authoritative", "preferred", "supplemental"] = "supplemental"
    priority: int = Field(default=100, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references(self):
        if self.ontology_ref_id is None and self.ontology_concept_id is None:
            raise ValueError("ontology_ref_id or ontology_concept_id is required")
        if self.target_scope == "capability" and self.field_path is not None:
            raise ValueError("capability scope cannot declare field_path")
        if self.target_scope != "capability" and not self.field_path:
            raise ValueError(f"{self.target_scope} scope requires field_path")
        return self


def create_binding_router(
    repository: BindingRepository | None,
    authorizer: AdminAuthorizer,
    catalog: RegistryCatalog,
) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/bindings", tags=["bindings"])

    def require_repository() -> BindingRepository:
        if repository is None:
            raise HTTPException(status_code=503, detail={"code": "app_database_unavailable"})
        return repository

    @router.get("")
    def list_bindings(status: str | None = None, limit: int = Query(100, ge=1, le=500)) -> dict:
        return {"items": require_repository().list_bindings(status=status, limit=limit)}

    @router.get("/validation")
    def validate_bindings() -> dict:
        return require_repository().validate_bindings()

    @router.post("", status_code=201)
    def create_binding(
        payload: OpenMetadataBindingInput,
        principal: AdminPrincipal = Depends(authorizer.require("binding_reviewer", "metadata_admin")),
    ) -> dict:
        try:
            return require_repository().create_openmetadata_binding(
                **payload.model_dump(mode="python"), created_by=principal.actor,
            )
        except psycopg.errors.UniqueViolation as exc:
            raise HTTPException(status_code=409, detail={"code": "active_binding_exists"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "unknown_ontology_reference", "message": str(exc)}) from exc

    @router.post("/capability", status_code=201)
    def create_capability_binding(
        payload: CapabilityBindingInput,
        principal: AdminPrincipal = Depends(authorizer.require("binding_reviewer", "metadata_admin")),
    ) -> dict:
        capability = catalog.capabilities.get(payload.capability_id)
        if capability is None:
            raise HTTPException(status_code=422, detail={"code": "unknown_capability"})
        if payload.target_scope == "input" and payload.field_path not in capability.inputs:
            raise HTTPException(status_code=422, detail={"code": "unknown_capability_input"})
        if payload.target_scope == "output" and payload.field_path not in capability.returns:
            raise HTTPException(status_code=422, detail={"code": "unknown_capability_output"})
        registry_version = catalog.release.version if catalog.release else "draft"
        try:
            return require_repository().create_capability_binding(
                **payload.model_dump(mode="python"),
                contract_version=registry_version,
                registry_version=registry_version,
                created_by=principal.actor,
            )
        except psycopg.errors.UniqueViolation as exc:
            raise HTTPException(status_code=409, detail={"code": "active_binding_exists"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "invalid_capability_binding", "message": str(exc)}) from exc

    @router.post("/{binding_id}/reviews")
    def review_binding(
        binding_id: UUID,
        payload: BindingReviewInput,
        principal: AdminPrincipal = Depends(authorizer.require("binding_reviewer", "ontology_owner")),
    ) -> dict:
        try:
            return require_repository().review_binding(
                binding_id, decision=payload.decision, reviewer=principal.actor, comment=payload.comment,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "binding_not_found"}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail={"code": "invalid_binding_transition", "message": str(exc)}) from exc

    return router
