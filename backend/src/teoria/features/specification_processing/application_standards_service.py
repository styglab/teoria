"""Approve a local application version without publishing an Ontology."""

import hashlib
import json
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5
from pydantic import Field
from teoria.features.specification_processing.models import Record
from teoria.features.semantic_modeling.goods_dictionary.meaning_contracts import (
    approved_dictionary_snapshot,
)
from teoria.features.goods_normalization.contracts import NormalizationPackage
from teoria.features.specification_processing.application_standard_validation import (
    application_standard_readiness, require_application_rules,
)


class ApplicationStandardInput(Record):
    name: str = Field(min_length=1, max_length=120)
    source_run_id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")
    expected_dictionary_checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    rationale: str = Field(min_length=10, max_length=4000)
    idempotency_key: UUID | None = None


class ApplicationStandardsService:
    def __init__(self, repository, processing, meanings, read_artifact, store):
        self.repository = repository
        self.processing = processing
        self.meanings = meanings
        self.read_artifact = read_artifact
        self.store = store

    async def sources(self, offset, limit):
        return await self.processing.standard_candidates(offset, limit)

    async def _read_source(self, source_run_id):
        detail = await self.processing.detail(source_run_id)
        if detail is None:
            raise KeyError(source_run_id)
        run = detail["run"]
        if run["mode"] != "standard_management" or run["status"] not in {
            "completed",
            "partial",
        }:
            raise ValueError("standard_source_run_not_ready")
        reference = next(
            (
                a
                for a in detail["artifacts"]
                if a["uri"] == run["standard_uri"]
                and a["sha256"] == run["standard_sha256"]
            ),
            None,
        )
        if reference is None:
            raise ValueError("registered_standard_artifact_required")
        standard = await self.read_artifact(reference)
        classification = run["classification_code"]
        readiness = application_standard_readiness(standard)
        if readiness['classification_code'] != classification:
            raise ValueError("standard_classification_mismatch")
        return standard, readiness

    async def readiness(self, source_run_id):
        _, readiness = await self._read_source(source_run_id)
        return {'source_run_id': source_run_id, **readiness}

    async def create(self, request, *, actor):
        standard, readiness = await self._read_source(request.source_run_id)
        if not readiness['ready']:
            raise ValueError(readiness['reason'])
        classification = readiness['classification_code']
        kind = readiness['standard_kind']
        snapshot = await self.meanings.snapshot()
        if snapshot["checksum"] != request.expected_dictionary_checksum:
            raise ValueError("dictionary_changed_refresh_before_approval")
        if kind == 'ontology_profile' and snapshot.get('schema_version') == 2:
            package = NormalizationPackage.model_validate(standard)
            reference = package.profile.ontology.model_dump(mode='json')
            if not any(a['ontology'] == reference for a in snapshot['ontologies']):
                raise ValueError('application_ontology_version_mismatch')
        pinned = approved_dictionary_snapshot(snapshot)
        # Stage immutable objects before the short DB transaction. Concurrent authoring
        # cannot mutate the snapshots captured here and there is no HTTP under a DB lock.
        release_id = (uuid5(NAMESPACE_URL, f'teoria:application-standard:{actor}:{request.idempotency_key}')
                      if request.idempotency_key else uuid4())
        prefix = f"specification_processing/application_standards/{release_id}"
        async with self.store() as storage:
            refs = []
            for name, body in [
                ("standard", standard),
                ("dictionary", pinned.model_dump(mode="json")),
            ]:
                raw = json.dumps(
                    body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ).encode()
                ref = await storage.put(f"{prefix}/{name}.json", raw)
                refs.append({"uri": ref.uri, "sha256": ref.sha256})
        content_checksum = hashlib.sha256(
            json.dumps(refs, sort_keys=True).encode()
        ).hexdigest()
        return await self.repository.create(
            {
                "release_id": release_id,
                "name": request.name,
                "source_run_id": request.source_run_id,
                "classification_code": classification,
                "standard_kind": kind,
                "standard_ref": refs[0],
                "dictionary_ref": refs[1],
                "dictionary_checksum": pinned.checksum,
                "content_checksum": content_checksum,
                "approved_by": actor,
                "rationale": request.rationale,
            }
        )

    async def validate_execution(self, manifest):
        row = await self.repository.get(manifest["application_release_id"])
        if row["status"] != "approved" or manifest["mode"] != "document_processing":
            raise ValueError("application_standard_not_available")
        if (
            manifest.get("standard") != row["standard_ref"]
            or manifest.get("dictionary_standard") != row["dictionary_ref"]
            or manifest.get("classification_code") != row["classification_code"]
        ):
            raise ValueError("application_standard_reference_mismatch")
        if manifest.get("dictionary_auto_approve") or manifest.get(
            "dictionary_meaning_auto_approve"
        ):
            raise ValueError("application_standard_is_read_only")
        # Immutable references contain no size. The reader still bounds actual bytes.
        readiness = require_application_rules(await self.read_artifact(
            {'size_bytes': 0, **row['standard_ref']}))
        if (readiness['standard_kind'] != row['standard_kind']
                or readiness['classification_code'] != row['classification_code']):
            raise ValueError('application_standard_reference_mismatch')
        return manifest
