"""Compile approved expression/profile snapshots into a frozen, read-only Runtime view.

The compiler never publishes Ontology or approves links. Runtime reads this view
and its verified bundle only; it does not query authoring DB or source documents.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from teoria.domains.goods.contracts import StandardReference
from teoria.domains.goods.normalization.application.meaning_application import ApprovedInterpretation, apply_interpretation
from teoria.domains.goods.expression_links.expression_contracts import (
    OntologyDictionarySnapshot,
    approved_expression_snapshot,
    resolve_expression_snapshot,
)
from teoria.domains.goods.normalization.application.profile_application import (
    apply_profile,
)
from teoria.domains.goods.normalization.contracts import NormalizationPackage, checksum
from teoria.domains.goods.normalization.contracts.models import Record
from teoria.domains.goods.normalization.meaning_proposals.expression_alignment import (
    apply_concept_meanings,
)
from teoria.domains.goods.normalization.profiles.compiler import compile_package
from teoria.platform.ontology.authoring.observations import SemanticObservation
from teoria.platform.ontology.authoring.publication_contracts import (
    OntologyPublicationRef,
)
from teoria.platform.ontology.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)
from teoria.platform.ontology.runtime.mapping.materializer import MaterializedObject
from teoria.platform.ontology.runtime.provenance import Provenance

CAPABILITY_ID = "get_goods_document_requirements"
PROCESSOR_ID = "goods.document_requirements"


class RequirementsViewInput(Record):
    version: str = Field(pattern=r"^\d{4}\.\d{2}\.\d{2}\.\d+$")
    run_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    profile_revision_id: UUID
    extraction: StandardReference
    alignment: StandardReference
    execution_receipt: StandardReference
    interpretation_revision_ids: list[UUID] = Field(default_factory=list, max_length=100)


class RequirementDocument(Record):
    run_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    document_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    entities: list[dict]
    observations: list[SemanticObservation]
    compositions: list[dict] = Field(default_factory=list)
    deferred_count: int = Field(ge=0)


class RequirementsView(Record):
    schema_version: Literal[1] = 1
    artifact_kind: Literal["goods_runtime_requirements"] = "goods_runtime_requirements"
    version: str = Field(pattern=r"^\d{4}\.\d{2}\.\d{2}\.\d+$")
    ontology: OntologyPublicationRef
    package: NormalizationPackage
    expression_snapshot_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    extraction: StandardReference
    alignment: StandardReference
    execution_receipt: StandardReference
    concept_labels: dict[str, str]
    interpretation_approvals: list[ApprovedInterpretation] = Field(default_factory=list)
    documents: list[RequirementDocument] = Field(min_length=1)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="before")
    @classmethod
    def verify_serialized_checksum(cls, value):
        if isinstance(value, dict) and value.get('checksum') != checksum(
                {k: v for k, v in value.items() if k != 'checksum'}):
            raise ValueError('goods_runtime_view_checksum_mismatch')
        return value

    @model_validator(mode="after")
    def consistent_references(self):
        if self.ontology != self.package.profile.ontology:
            raise ValueError("goods_runtime_view_ontology_mismatch")
        keys = [(d.run_id, d.document_id) for d in self.documents]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_runtime_document")
        concepts = {str(c.concept_id): c for c in self.package.concepts}
        approvals = {str(a.revision_id): a for a in self.interpretation_approvals}
        if len(approvals) != len(self.interpretation_approvals):
            raise ValueError("duplicate_interpretation_approval")
        for approval in approvals.values():
            if (approval.package_checksum != self.package.checksum
                    or approval.ontology != self.ontology):
                raise ValueError("runtime_interpretation_context_mismatch")

        def verify_approval(source, document):
            ref = source.get('approved_interpretation', {})
            approval = approvals.get(ref.get('revision_id'))
            if (approval is None or ref.get('checksum') != approval.checksum
                    or ref.get('approval_actor') != approval.approval_actor
                    or ref.get('request_checksum') != checksum(approval.request)
                    or approval.request.document_id != document.document_id
                    or approval.request.source_sha256 != document.source_sha256):
                raise ValueError('runtime_interpretation_approval_required')

        observation_ids = set()
        for document in self.documents:
            subjects = {e["observation_id"]: e["concept_id"] for e in document.entities}
            for observation in document.observations:
                concept = concepts.get(str(observation.concept_id))
                if (
                    observation.ontology != self.ontology
                    or concept is None
                    or concept.kind != "property"
                    or any(
                        subjects.get(s) != str(concept.object_concept_id)
                        for s in observation.subject_refs
                    )
                ):
                    raise ValueError(
                        "runtime_observation_owner_or_publication_mismatch"
                    )
                source = observation.source
                if (
                    source.get("kind") != "document"
                    or source.get("document_id") != document.document_id
                    or source.get("run_id") != document.run_id
                    or source.get("source_sha256") != document.source_sha256
                    or source.get("package_checksum") != self.package.checksum
                ):
                    raise ValueError("runtime_observation_source_mismatch")
                links = [
                    source.get("property_connection", {}),
                    *source.get("subject_connections", []),
                ]
                if source.get("approved_interpretation"):
                    verify_approval(source, document)
                elif (
                    source.get("expression_snapshot_checksum")
                    != self.expression_snapshot_checksum
                    or len(links) != len(observation.subject_refs) + 1
                    or any(
                        not link.get("source_entry_id") or not link.get("mapping_ids")
                        for link in links
                    )
                ):
                    raise ValueError("runtime_approved_expression_connections_required")
                if observation.observation_id in observation_ids:
                    raise ValueError("duplicate_runtime_observation")
                observation_ids.add(observation.observation_id)
            for composition in document.compositions:
                verify_approval(composition['source'], document)
                if (composition['ontology'] != self.ontology.model_dump(mode='json')
                        or composition['parent_ref'] not in subjects or composition['child_ref'] not in subjects
                        or composition['parent_ref'] == composition['child_ref']
                        or composition['composition_id'] in observation_ids):
                    raise ValueError('runtime_composition_reference_mismatch')
                observation_ids.add(composition['composition_id'])
        return self


def compile_requirements_view(
    *,
    version,
    run_id,
    corpus,
    alignment,
    package,
    snapshot,
    extraction_ref,
    alignment_ref,
    receipt_ref,
    interpretations=(),
):
    """Inputs must come from approved Admin exports and checksum-verified artifacts."""
    exported_snapshot = OntologyDictionarySnapshot.model_validate(snapshot)
    snapshot = approved_expression_snapshot(exported_snapshot)
    package = NormalizationPackage.model_validate(package)
    reference = package.profile.ontology.model_dump(mode="json")
    publication = next(
        (a for a in exported_snapshot.ontologies if a["ontology"] == reference), None
    )
    if publication is None:
        raise ValueError("profile_publication_not_in_approved_expression_snapshot")
    rebuilt = compile_package(
        package.profile,
        publication["content"],
        revision_id=package.profile_revision_id,
        approval_actor=package.approval_actor,
    )
    if rebuilt.checksum != package.checksum:
        raise ValueError("profile_package_differs_from_published_definition")
    originals = {d["document_id"]: d for d in corpus["documents"]}
    documents = deepcopy(alignment["documents"])
    if len({d["document_id"] for d in documents}) != len(documents):
        raise ValueError("duplicate_alignment_document")
    entries = set()
    for document in documents:
        original = originals.get(document["document_id"])
        if (
            original is None
            or document["source_sha256"] != original["source"]["sha256"]
        ):
            raise ValueError("alignment_source_mismatch")
        for collection in ("entities", "attributes"):
            raw = {o["id"]: o for o in original[collection]}
            if len(document[collection]) != len(raw) or {
                o["id"] for o in document[collection]
            } != set(raw):
                raise ValueError("alignment_observation_set_mismatch")
            for observation in document[collection]:
                if any(
                    observation.get(k) != v for k, v in raw[observation["id"]].items()
                ):
                    raise ValueError("alignment_changed_source_observation")
                term = observation.get("source_term_ref", "")
                if term.startswith("source_term:"):
                    entries.add(term.removeprefix("source_term:"))
    # Re-resolve against the approved snapshot; do not trust a saved 'resolved' label.
    resolution = resolve_expression_snapshot(
        snapshot, sorted(entries), corpus["classification_code"]
    )
    meanings = apply_concept_meanings(documents, resolution)
    normalized, _ = apply_profile(
        corpus, package, run_id=run_id, meaning_alignment=meanings
    )
    approvals, applications, selected = [], {}, set()
    for item in interpretations:
        approval = ApprovedInterpretation.model_validate(item['approval'])
        doc_id = approval.request.document_id
        source_result = item['source_result']
        if (source_result.get('artifact_kind') != 'specification_document_result'
                or len(source_result['extracted']['documents']) != 1
                or source_result['extracted']['documents'][0] != originals.get(doc_id)):
            raise ValueError('interpretation_extraction_document_mismatch')
        selection = {(doc_id, p.observation_id) for p in approval.request.properties}
        selection.update((doc_id, c.quantity_observation_id) for c in approval.request.compositions)
        if selected.intersection(selection):
            raise ValueError('overlapping_interpretation_selections')
        selected.update(selection)
        applied = apply_interpretation(approval, source_result, package,
            {'ontology': reference, 'content': publication['content']}, run_id=run_id)
        applications.setdefault(doc_id, []).append(applied)
        approvals.append(approval)
    result = []
    for document in normalized["documents"]:
        original = originals[document["document_id"]]
        entities = {e['observation_id']: e for e in document['entities'] if e['status'] == 'applied'}
        observations = [r['semantic_observation'] for r in document['requirements']
                        if (document['document_id'], r['semantic_observation']['source']['attribute_id']) not in selected]
        compositions = []
        for applied in applications.get(document['document_id'], []):
            for entity in applied['entities']:
                existing = entities.get(entity['observation_id'])
                if existing and existing['concept_id'] != entity['concept_id']:
                    raise ValueError('runtime_interpretation_entity_conflict')
                entities[entity['observation_id']] = entity
            observations.extend(applied['observations'])
            compositions.extend(applied['compositions'])
        deferred = sum(1 for c in normalized['unresolved_observations']
            if c.get('document_id') == document['document_id']
            and (document['document_id'], c.get('attribute_id')) not in selected
            and not (c.get('kind') == 'entity' and c.get('observation_id') in entities)
            and not any(c.get('source_relation_id') == comp['source_relation_id'] for comp in compositions))
        result.append(
            RequirementDocument(
                run_id=run_id,
                document_id=document["document_id"],
                source_sha256=original["source"]["sha256"],
                entities=list(entities.values()),
                observations=observations,
                compositions=compositions,
                deferred_count=deferred,
            )
        )
    if not any(d.observations or d.compositions for d in result):
        raise ValueError("no_approved_requirements_to_export")
    labels = {
        str(p["concept_id"]): p["name"]
        for obj in publication["content"]["objects"]
        for p in [obj, *obj["properties"]]
    }
    body = dict(
        concept_labels=labels,
        version=version,
        ontology=reference,
        package=package.model_dump(mode="json"),
        expression_snapshot_checksum=snapshot.checksum,
        extraction=extraction_ref,
        alignment=alignment_ref,
        execution_receipt=receipt_ref,
        documents=[d.model_dump(mode="json") for d in result],
    )
    body["interpretation_approvals"] = [a.model_dump(mode="json") for a in approvals]
    body.update(schema_version=1, artifact_kind="goods_runtime_requirements")
    return RequirementsView(**body, checksum=checksum(body))


def load_requirements_view(path: Path, expected_sha256: str, publications: list[dict]):
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("goods_runtime_view_too_large")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("goods_runtime_view_file_checksum_mismatch")
    view = RequirementsView.model_validate_json(raw)
    if path.parent.name != view.version:
        raise ValueError("goods_runtime_view_version_directory_required")
    reference = view.ontology
    if not any(
        str(p["ontology_version_id"]) == str(reference.version_id)
        and p["namespace"] == reference.namespace
        and p["version"] == reference.version
        and p["checksum"] == reference.checksum
        for p in publications
    ):
        raise ValueError("goods_runtime_view_not_in_runtime_bundle")
    return view


def requirements_handler(view: RequirementsView):
    async def query(runner, catalog, capability_id, inputs):
        document = next(
            (
                d
                for d in view.documents
                if d.run_id == inputs["run_id"]
                and d.document_id == inputs["document_id"]
            ),
            None,
        )
        if document is None:
            raise CapabilityExecutionError(
                "resource_not_found",
                "Document has no published requirements view",
                capability_id=capability_id,
            )
        offset, limit = inputs.get("offset", 0), inputs.get("limit", 100)
        if (
            type(offset) is not int
            or type(limit) is not int
            or offset < 0
            or not 1 <= limit <= 100
        ):
            raise CapabilityExecutionError(
                "invalid_requirements_page",
                "Invalid requirements page",
                capability_id=capability_id,
            )
        values = document.observations
        if inputs.get("concept_id"):
            values = [o for o in values if str(o.concept_id) == inputs["concept_id"]]
        provenance = Provenance(
            kind="source",
            source="goods_runtime_view",
            operation="document_requirements",
            mapping=PROCESSOR_ID,
            observed_at=datetime.now(timezone.utc),
            record_keys=[document.run_id, document.document_id],
        )
        obj = MaterializedObject(
            ontology="goods_requirements",
            object_type="document",
            object_id=f"{document.run_id}:{document.document_id}",
            properties={
                "result_id": f"{document.run_id}:{document.document_id}",
                "run_id": document.run_id,
                "document_id": document.document_id,
                "source_sha256": document.source_sha256,
                "view_version": view.version,
                "view_checksum": view.checksum,
                "total": len(values),
                "offset": offset,
                "limit": limit,
                "deferred_count": document.deferred_count,
            },
            provenance=[provenance],
            property_provenance={},
            semantic_observations=values[offset : offset + limit],
        )
        return CapabilityResult(
            capability_id=capability_id,
            objects=[obj],
            outcome={
                "ontology": view.ontology.model_dump(mode="json"),
                "profile_revision_id": str(view.package.profile_revision_id),
                "package_checksum": view.package.checksum,
                "expression_snapshot_checksum": view.expression_snapshot_checksum,
                "execution_receipt_sha256": view.execution_receipt.sha256,
                "concepts": view.concept_labels,
                "compositions": document.compositions,
                "subjects": {e["observation_id"]: e["name_raw"] for e in document.entities},
                "interpretation_approval_ids": [str(a.revision_id) for a in view.interpretation_approvals
                    if a.request.document_id == document.document_id],
            },
        )

    return query


async def prepare_requirements_view(
    manifest: dict, output: Path, *, authoring_client=None
):
    """Read approved owner exports; write a new immutable local release directory."""
    from teoria.domains.goods.authoring_client import GoodsAuthoringClient
    from teoria.domains.goods.data_processing.storage.artifact_store import (
        artifact_store,
        read_uri,
    )

    async def verified(value):
        ref = StandardReference.model_validate(value)
        raw = await read_uri(ref.uri)
        if hashlib.sha256(raw).hexdigest() != ref.sha256:
            raise ValueError("runtime_view_input_checksum_mismatch")
        return json.loads(raw)

    manifest = RequirementsViewInput.model_validate(manifest).model_dump(mode="json")
    extraction_ref = StandardReference.model_validate(manifest["extraction"])
    alignment_ref = StandardReference.model_validate(manifest["alignment"])
    corpus = await verified(manifest["extraction"])
    alignment = await verified(manifest["alignment"])
    if alignment.get("extraction_ref", {}).get("sha256") != extraction_ref.sha256:
        raise ValueError("runtime_view_alignment_extraction_mismatch")

    receipt = await verified(manifest["execution_receipt"])
    if receipt.get("run_id") != manifest["run_id"]:
        raise ValueError("runtime_view_execution_run_mismatch")
    recorded = {(a["uri"], a["sha256"]) for a in receipt.get("artifacts", [])}
    if (
        not {
            (extraction_ref.uri, extraction_ref.sha256),
            (alignment_ref.uri, alignment_ref.sha256),
        }
        <= recorded
    ):
        raise ValueError("runtime_view_inputs_not_in_execution_receipt")
    source_hashes = {d["document_id"]: d["sha256"] for d in receipt.get("sources", [])}
    if any(
        source_hashes.get(d["document_id"]) != d["source"]["sha256"]
        for d in corpus["documents"]
    ):
        raise ValueError("runtime_view_original_source_mismatch")

    async def build(api):
        package = NormalizationPackage.model_validate_json(
            await api.package(manifest["profile_revision_id"])
        )
        if str(package.profile_revision_id) != manifest["profile_revision_id"]:
            raise ValueError("runtime_view_profile_revision_mismatch")
        snapshot = await api.expression_snapshot()
        # The owning publication endpoint rejects Drafts; checksum agreement alone is insufficient.
        publication = await api.ontology_publication(
            package.profile.ontology.version_id
        )
        from teoria.platform.ontology.authoring.publication_contracts import (
            PublishedOntology,
        )

        published = PublishedOntology.model_validate(publication)
        if published.ontology != package.profile.ontology:
            raise ValueError("runtime_view_authoritative_publication_mismatch")
        interpretations = []
        if len(set(manifest['interpretation_revision_ids'])) != len(manifest['interpretation_revision_ids']):
            raise ValueError('duplicate_interpretation_revision')
        for revision_id in manifest['interpretation_revision_ids']:
            approval = ApprovedInterpretation.model_validate(await api.interpretation_approval(revision_id))
            if str(approval.revision_id) != revision_id:
                raise ValueError('interpretation_revision_mismatch')
            result = await verified(approval.request.result.model_dump(mode='json'))
            interpretations.append({'approval': approval, 'source_result': result.get('result', result)})
        return compile_requirements_view(
            version=manifest["version"],
            run_id=manifest["run_id"],
            corpus=corpus,
            alignment=alignment,
            package=package,
            snapshot=snapshot,
            extraction_ref=extraction_ref.model_dump(mode="json"),
            alignment_ref=alignment_ref.model_dump(mode="json"),
            receipt_ref=manifest["execution_receipt"],
            interpretations=interpretations,
        )

    if authoring_client is None:
        async with GoodsAuthoringClient() as api:
            view = await build(api)
    else:
        view = await build(authoring_client)
    raw = (view.model_dump_json() + "\n").encode()
    async with artifact_store(output.resolve().as_uri()) as store:
        ref = await store.put(f"{view.version}/view.json", raw)
    return {
        "artifact": ref.model_dump(mode="json"),
        "view_checksum": view.checksum,
        "version": view.version,
        "documents": len(view.documents),
        "observations": sum(len(d.observations) for d in view.documents),
        "ontology": view.ontology.model_dump(mode="json"),
        "deployment_ready": False,
    }
