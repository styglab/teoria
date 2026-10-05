from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from teoria.admin.auth import AdminAuthorizer, AdminPrincipal
from teoria.ontology.authoring import OntologyAuthoringRepository


class DraftInput(BaseModel):
    version: str
    based_on_version_id: UUID | None = None


class OntologyInput(BaseModel):
    namespace: str
    name: str
    description: str
    version: str = "0.1.0"


class TransitionInput(BaseModel):
    action: Literal["submit", "request_changes", "approve", "revoke"]
    comment: str | None = None


class AuthoringItemInput(BaseModel):
    code: str
    name: str
    description: str = ""
    stable_key: str | None = None
    identity_policy: dict[str, Any] = Field(default_factory=dict)
    object_concept_id: UUID | None = None
    source_object_concept_id: UUID | None = None
    target_object_concept_id: UUID | None = None
    subject_object_concept_id: UUID | None = None
    value_type: str | None = None
    cardinality: Literal["one", "optional", "many"] = "optional"
    unit: str | None = None
    temporal: bool = False
    transitive: bool = False
    source_cardinality: str = "many"
    target_cardinality: str = "many"
    expression_language: str | None = None
    expression: dict[str, Any] | None = None
    evaluator_key: str | None = None
    rule_version: str = "1.0"
    formula: dict[str, Any] | None = None
    aggregation: str | None = None
    grain: list[str] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    metric_version: str = "1.0"
    time_basis: str | None = None


class AuthoringPatchInput(BaseModel):
    changes: dict[str, Any]


def create_ontology_authoring_router(repository: OntologyAuthoringRepository | None, authorizer: AdminAuthorizer) -> APIRouter:
    router = APIRouter(prefix="/v1/admin/ontology-authoring", tags=["ontology-authoring"])

    def repo() -> OntologyAuthoringRepository:
        if repository is None:
            raise HTTPException(status_code=503, detail={"code": "app_database_unavailable"})
        return repository

    def translate(call):
        try:
            return call()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail={"code": "ontology_not_found"}) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_ontology_operation", "message": str(exc)},
            ) from exc

    @router.post("/ontologies", status_code=201)
    def create_ontology(
        payload: OntologyInput,
        principal: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return translate(
            lambda: repo().create_ontology(**payload.model_dump(), actor=principal.actor)
        )

    @router.get("/ontologies/{namespace}/versions")
    def versions(namespace: str): return {"items":repo().list_versions(namespace)}

    @router.get("/ontologies/{namespace}/concepts")
    def concepts(namespace: str,published_only:bool=True): return {"items":repo().list_concepts(namespace,published_only=published_only)}

    @router.post("/ontologies/{namespace}/versions",status_code=201)
    def create_draft(namespace: str,payload:DraftInput,principal:AdminPrincipal=Depends(authorizer.require("ontology_owner"))):
        return translate(lambda:repo().create_draft(namespace,version=payload.version,based_on_version_id=payload.based_on_version_id,actor=principal.actor))

    @router.get("/versions/{version_id}")
    def get_version(version_id:UUID): return translate(lambda:repo().get_version(version_id))

    @router.post("/versions/{version_id}/items/{kind}",status_code=201)
    def add_item(version_id:UUID,kind:Literal["object","property","relationship","rule","metric"],payload:AuthoringItemInput,principal:AdminPrincipal=Depends(authorizer.require("ontology_owner"))):
        data=payload.model_dump(mode="json",exclude_none=True)
        return translate(lambda:repo().add_item(version_id,kind=kind,payload=data,actor=principal.actor))

    @router.patch("/versions/{version_id}/items/{kind}/{concept_id}")
    def update_item(version_id:UUID,kind:Literal["object","property","relationship","rule","metric"],concept_id:UUID,payload:AuthoringPatchInput,principal:AdminPrincipal=Depends(authorizer.require("ontology_owner"))):
        return translate(lambda:repo().update_item(version_id,kind=kind,concept_id=concept_id,changes=payload.changes,actor=principal.actor))

    @router.delete("/versions/{version_id}/items/{kind}/{concept_id}",status_code=204)
    def delete_item(version_id:UUID,kind:Literal["object","property","relationship","rule","metric"],concept_id:UUID,principal:AdminPrincipal=Depends(authorizer.require("ontology_owner"))):
        translate(lambda:repo().delete_item(version_id,kind=kind,concept_id=concept_id,actor=principal.actor))

    @router.get("/versions/{version_id}/validation")
    def validation(version_id:UUID): return translate(lambda:repo().validate(version_id))

    @router.get("/versions/{version_id}/binding-impact")
    def binding_impact(version_id:UUID): return translate(lambda:repo().binding_impact(version_id))

    @router.get("/versions/{version_id}/diff")
    def diff(version_id:UUID,against:UUID): return translate(lambda:repo().diff(version_id,against))

    @router.get("/versions/{version_id}/audit")
    def audit(version_id:UUID): return {"items":translate(lambda:repo().audit(version_id))}

    @router.post("/versions/{version_id}/transitions")
    def transition(version_id:UUID,payload:TransitionInput,principal:AdminPrincipal=Depends(authorizer.require("ontology_owner"))):
        return translate(lambda:repo().transition(version_id,action=payload.action,actor=principal.actor,comment=payload.comment))

    @router.post("/versions/{version_id}/publish")
    def publish(version_id:UUID,principal:AdminPrincipal=Depends(authorizer.require("ontology_owner"))):
        return translate(lambda:repo().publish(version_id,actor=principal.actor))

    return router
