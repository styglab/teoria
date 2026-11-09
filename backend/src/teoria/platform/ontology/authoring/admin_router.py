from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from teoria.platform.access_control.auth import AdminAuthorizer, AdminPrincipal
from teoria.platform.ontology.authoring.service import OntologyAuthoringService
from teoria.platform.ontology.authoring.publication_contracts import PublishedOntology
from teoria.platform.ontology.authoring.blueprint import OntologyBlueprint


class DraftInput(BaseModel):
    version: str
    based_on_version_id: UUID | None = None


class OntologyInput(BaseModel):
    namespace: str
    name: str
    description: str
    version: str = "0.1.0"


class TransitionInput(BaseModel):
    action: Literal["submit", "request_changes", "approve", "revoke", "deprecate"]
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
    quantity_dimension: str | None = None
    allowed_units: list[str] = Field(default_factory=list)
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


class BlueprintPreviewInput(BaseModel):
    blueprint: OntologyBlueprint


class BlueprintDraftInput(BlueprintPreviewInput):
    expected_plan_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')
    rationale: str = Field(min_length=10, max_length=4000)


def create_ontology_authoring_router(
    repository: OntologyAuthoringService | None, authorizer: AdminAuthorizer,
    *, dependency_reader=None,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/admin/ontology-authoring", tags=["ontology-authoring"]
    )

    def repo() -> OntologyAuthoringService:
        if repository is None:
            raise HTTPException(
                status_code=503, detail={"code": "app_database_unavailable"}
            )
        return repository

    async def translate(call):
        try:
            return await call
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail={"code": "ontology_not_found"}
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "invalid_ontology_operation", "message": str(exc)},
            ) from exc

    @router.post("/ontologies", status_code=201)
    async def create_ontology(
        payload: OntologyInput,
        principal: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return await translate(
            (repo().create_ontology(**payload.model_dump(), actor=principal.actor))
        )

    @router.get("/ontologies")
    async def ontologies():
        return {"items": (await repo().list_ontologies())}

    @router.get("/ontologies/{namespace}/versions")
    async def versions(namespace: str):
        return {"items": (await repo().list_versions(namespace))}

    @router.get("/ontologies/{namespace}/concepts")
    async def concepts(namespace: str, published_only: bool = True):
        return {
            "items": (
                await repo().list_concepts(namespace, published_only=published_only)
            )
        }

    @router.post("/ontologies/{namespace}/versions", status_code=201)
    async def create_draft(
        namespace: str,
        payload: DraftInput,
        principal: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return await translate(
            repo().create_draft(
                namespace,
                version=payload.version,
                based_on_version_id=payload.based_on_version_id,
                actor=principal.actor,
            )
        )

    @router.get("/versions/{version_id}")
    async def get_version(version_id: UUID):
        return await translate(repo().get_version(version_id))

    @router.post('/versions/{version_id}/blueprint-preview')
    async def preview_blueprint(version_id: UUID, payload: BlueprintPreviewInput,
                                principal: AdminPrincipal = Depends(authorizer.require('ontology_owner'))):
        return await translate(repo().preview_blueprint(version_id, payload.blueprint))

    @router.post('/versions/{version_id}/blueprint-drafts', status_code=201)
    async def prepare_blueprint_draft(version_id: UUID, payload: BlueprintDraftInput,
                                     principal: AdminPrincipal = Depends(authorizer.require('ontology_owner'))):
        return await translate(repo().prepare_blueprint_draft(version_id, payload.blueprint,
            expected_plan_checksum=payload.expected_plan_checksum, actor=principal.actor, rationale=payload.rationale))

    @router.get("/versions/{version_id}/publication", response_model=PublishedOntology)
    async def publication(
        version_id: UUID,
        principal: AdminPrincipal = Depends(authorizer.require()),
    ):
        return await translate(repo().publication(version_id))

    @router.post("/versions/{version_id}/items/{kind}", status_code=201)
    async def add_item(
        version_id: UUID,
        kind: Literal["object", "property", "relationship", "rule", "metric"],
        payload: AuthoringItemInput,
        principal: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        data = payload.model_dump(mode="json", exclude_none=True)
        return await translate(
            repo().add_item(version_id, kind=kind, payload=data, actor=principal.actor)
        )

    @router.patch("/versions/{version_id}/items/{kind}/{concept_id}")
    async def update_item(
        version_id: UUID,
        kind: Literal["object", "property", "relationship", "rule", "metric"],
        concept_id: UUID,
        payload: AuthoringPatchInput,
        principal: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return await translate(
            repo().update_item(
                version_id,
                kind=kind,
                concept_id=concept_id,
                changes=payload.changes,
                actor=principal.actor,
            )
        )

    @router.delete("/versions/{version_id}/items/{kind}/{concept_id}", status_code=204)
    async def delete_item(
        version_id: UUID,
        kind: Literal["object", "property", "relationship", "rule", "metric"],
        concept_id: UUID,
        principal: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        await translate(
            repo().delete_item(
                version_id, kind=kind, concept_id=concept_id, actor=principal.actor
            )
        )

    @router.get("/versions/{version_id}/validation")
    async def validation(version_id: UUID):
        return await translate(repo().validate(version_id))

    @router.get("/versions/{version_id}/binding-impact")
    async def binding_impact(version_id: UUID):
        result = await translate(repo().binding_impact(version_id))
        if dependency_reader is not None:
            result['dependency_impact'] = await translate(dependency_reader(version_id))
        return result

    @router.get("/versions/{version_id}/diff")
    async def diff(version_id: UUID, against: UUID):
        return await translate(repo().diff(version_id, against))

    @router.get("/versions/{version_id}/audit")
    async def audit(version_id: UUID):
        return {"items": (await translate(repo().audit(version_id)))}

    @router.post("/versions/{version_id}/transitions")
    async def transition(
        version_id: UUID,
        payload: TransitionInput,
        principal: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return await translate(
            repo().transition(
                version_id,
                action=payload.action,
                actor=principal.actor,
                comment=payload.comment,
            )
        )

    @router.post("/versions/{version_id}/publish")
    async def publish(
        version_id: UUID,
        principal: AdminPrincipal = Depends(authorizer.require("ontology_owner")),
    ):
        return await translate(repo().publish(version_id, actor=principal.actor))

    return router
