"""Opt-in isolated SQL test: reviewed semantics → profile → Data DB → immutable Runtime HTTP."""

import hashlib
import json
import os
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest
import yaml

from backend.tests.fixtures.server_specifications import corpus
from teoria.integrations.application_database import apply_migrations
from teoria.integrations.data_operations.persistence.postgres import PostgresStore
from teoria.features.semantic_modeling.ontology.blueprint import (
    OntologyBlueprint,
    apply_ontology_blueprint,
)
from teoria.features.semantic_modeling.ontology.service import OntologyAuthoringService
from teoria.features.semantic_modeling.registry.release import publish_registry
from teoria.features.semantic_modeling.registry.artifact import RuntimeBundleCompiler
from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.semantic_modeling.binding.capability_manifest import (
    CapabilityBindingManifest,
    apply_capability_binding_manifest,
)
from teoria.features.semantic_modeling.binding.repository import BindingRepository
from teoria.features.goods_normalization.profiles.service import (
    NormalizationProfileService,
)
from teoria.features.specification_processing.models import SpecificationRun
from teoria.features.specification_processing import flows, tasks
from teoria.features.specification_processing.storage.query_observations import (
    snapshot_id,
)
from teoria.entrypoints.runtime_api import create_runtime_app
from teoria.settings import Settings

DATABASE_URL = os.getenv("TEORIA_TEST_SERVER_DATABASE_URL")
RUNTIME_URL = os.getenv("TEORIA_TEST_SERVER_RUNTIME_DATABASE_URL")
OPA_URL = os.getenv("TEORIA_TEST_SERVER_OPA_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not RUNTIME_URL or not OPA_URL,
    reason="isolated server PostgreSQL and OPA URLs required",
)
BACKEND = Path(__file__).resolve().parents[2]


async def test_server_semantics_materialization_and_runtime_http(tmp_path, monkeypatch):
    await apply_migrations(DATABASE_URL, BACKEND / "migrations/application")
    await PostgresStore(DATABASE_URL).apply_migrations(BACKEND / "migrations/data")
    # Real review/publication lifecycle, exclusively in the explicitly configured disposable database.
    ontology = OntologyAuthoringService(DATABASE_URL)
    draft = await apply_ontology_blueprint(
        ontology,
        OntologyBlueprint.load(
            BACKEND / "authoring/ontology_blueprints/computer_server.yaml"
        ),
        actor="test:author",
    )
    vid = UUID(draft["ontology_version_id"])
    await ontology.transition(vid, action="submit", actor="test:author")
    await ontology.transition(vid, action="approve", actor="test:reviewer")
    await ontology.publish(vid, actor="test:publisher")
    published = await ontology.published_artifact(vid)
    profiles = NormalizationProfileService(DATABASE_URL)
    template = yaml.safe_load(
        (
            BACKEND / "authoring/normalization_profiles/computer_server_memory.yaml"
        ).read_text()
    )
    template["profile_key"] = "test_server_" + uuid4().hex
    profile_draft = await profiles.create_from_template(
        vid, template, actor="test:author"
    )
    rid = UUID(profile_draft["revision_id"])
    await profiles.transition(rid, action="submit", actor="test:author")
    await profiles.transition(rid, action="approve", actor="test:reviewer")
    package = await profiles.export(rid)
    standard_path = tmp_path / "package.json"
    standard_path.write_text(package.model_dump_json())
    # Frozen synthetic extraction controls, not a real-model accuracy measurement.
    source_corpus = corpus()
    inputs = []
    for doc in source_corpus["documents"]:
        path = tmp_path / (doc["document_id"] + ".hwpx")
        body = "\n".join(n["text"] for n in doc["parsed_document"]["nodes"]).encode()
        path.write_bytes(body)
        assert hashlib.sha256(body).hexdigest() == doc["source"]["sha256"]
        inputs.append(
            {
                "document_id": doc["document_id"],
                "filename": path.name,
                "source_uri": path.as_uri(),
                "sha256": doc["source"]["sha256"],
            }
        )
    checkpoint = tmp_path / "extracted.json"
    checkpoint.write_text(json.dumps(source_corpus, ensure_ascii=False))
    request = SpecificationRun(
        run_id="test_server_" + uuid4().hex,
        mode="document_processing",
        classification_code="4321150102",
        artifact_root=(tmp_path / "objects").as_uri(),
        documents=inputs,
        standard={
            "uri": standard_path.as_uri(),
            "sha256": hashlib.sha256(standard_path.read_bytes()).hexdigest(),
        },
        extraction_checkpoint={
            "uri": checkpoint.as_uri(),
            "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        },
    )
    monkeypatch.setenv("TEORIA_PIPELINE_DATA_DATABASE_URL", DATABASE_URL)
    monkeypatch.setenv("TEORIA_RUNTIME_DATA_DATABASE_URL", RUNTIME_URL)
    # Exercise operational Task bodies and real transactions without starting a scheduler.
    for name in (
        "stage_original_documents",
        "persist_extraction",
        "select_and_map_standard",
        "persist_report",
        "prepare_query_observations",
    ):
        monkeypatch.setattr(tasks, name, getattr(tasks, name).fn)
    for name in ("start_execution", "complete_execution", "fail_execution"):
        monkeypatch.setattr(flows, name, getattr(flows, name).fn)
    result = await flows.execute_specification_run(request)
    assert result.status == "completed" and result.summary["applied"] == 8
    assert (
        await flows.execute_specification_run(request)
    ).model_dump() == result.model_dump()
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        assert (
            await (
                await connection.execute(
                    "SELECT count(*) FROM public_procurement.specification_requirement_observations WHERE run_id=%s",
                    (request.run_id,),
                )
            ).fetchone()
        )[0] == 8
    # A failure after the first observation insert rolls back rows and the completion checkpoint together.
    from psycopg.rows import dict_row
    from teoria.features.specification_processing.storage.run_repository import (
        SpecificationRepository,
    )

    repository = SpecificationRepository(DATABASE_URL)
    atomic_request = request.model_copy(
        update={"run_id": "atomic_server_" + uuid4().hex}
    )
    await repository.start(atomic_request, atomic_request.input_fingerprint())
    async with await psycopg.AsyncConnection.connect(
        DATABASE_URL, row_factory=dict_row
    ) as connection:
        first = dict(
            await (
                await connection.execute(
                    "SELECT * FROM public_procurement.specification_requirement_observations WHERE run_id=%s LIMIT 1",
                    (request.run_id,),
                )
            ).fetchone()
        )
    first.update(run_id=atomic_request.run_id, observation_id="atomic_" + uuid4().hex)
    with pytest.raises(psycopg.errors.UniqueViolation):
        await repository.complete(
            result.model_copy(update={"run_id": atomic_request.run_id}),
            observations=[first, first],
        )
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as connection:
        assert (
            await (
                await connection.execute(
                    "SELECT count(*) FROM public_procurement.specification_requirement_observations WHERE run_id=%s",
                    (atomic_request.run_id,),
                )
            ).fetchone()
        )[0] == 0
        assert (
            await (
                await connection.execute(
                    "SELECT status FROM public_procurement.specification_processing_runs WHERE run_id=%s",
                    (atomic_request.run_id,),
                )
            ).fetchone()
        )[0] == "running"
    await repository.fail(atomic_request.run_id, "synthetic_atomic_failure")
    # Runtime credentials can read the view but cannot write observations.
    async with await psycopg.AsyncConnection.connect(RUNTIME_URL) as connection:
        assert (
            await (
                await connection.execute(
                    "SELECT count(*) FROM public_procurement.server_requirement_observations"
                )
            ).fetchone()
        )[0] == 8
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        async with await psycopg.AsyncConnection.connect(RUNTIME_URL) as connection:
            await connection.execute(
                "DELETE FROM public_procurement.specification_requirement_observations"
            )
    # Actual release, semantic bindings, checksum-validated bundle; no raw Registry production loading.
    release_root = tmp_path / "releases"
    release = publish_registry(
        BACKEND / "contracts/runtime",
        version="2026.10.26.90",
        output=release_root,
        git_commit="isolated-server-verification",
    )
    catalog = RegistryLoader(BACKEND / "contracts/runtime").load()
    catalog.release = release
    binding_repo = BindingRepository(DATABASE_URL)
    binding_manifest = CapabilityBindingManifest.load(
        BACKEND
        / "authoring/ontology_migrations/pending/2026_10_server_specifications/capability_bindings.yaml"
    )
    await apply_capability_binding_manifest(
        binding_repo, catalog, binding_manifest, actor="test:reviewer", approve=True
    )
    bindings = await binding_repo.list_bindings(status="approved")
    bundle_root = tmp_path / "bundles"
    RuntimeBundleCompiler().compile(
        release_root / release.version,
        ontologies=[published],
        bindings=bindings,
        output=bundle_root,
    )
    settings = Settings(
        environment="production",
        runtime_api_token="test-runtime",
        registry_require_published=True,
        runtime_artifact_path=bundle_root / release.version,
        policy_mode="opa",
        opa_url=OPA_URL,
    )
    app = create_runtime_app(settings=settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://runtime.test"
        ) as client:
            assert (await client.get("/v1/capabilities")).status_code == 401
            headers = {"Authorization": "Bearer test-runtime"}
            discovered = (await client.get("/v1/capabilities", headers=headers)).json()[
                "capabilities"
            ]
            assert {c["id"] for c in discovered} == {
                "search_server_specifications",
                "compare_server_specifications",
                "get_server_requirement_evidence",
            }

            async def execute(capability, inputs):
                response = await client.post(
                    f"/v1/capabilities/{capability}:execute",
                    headers=headers,
                    json={"inputs": inputs},
                )
                assert response.status_code == 200, response.text
                return response.json()

            searched = await execute("search_server_specifications", {"memory_min": 64})
            assert searched["pagination"]["total_items"] == 2
            properties = [o["properties"] for o in searched["objects"]]
            assert {p["document_id"] for p in properties} == {"server_a", "server_b"}
            assert all(
                p["semantic_scope"] == "system_total"
                and p["role"] == "requirement_candidate"
                for p in properties
            )
            assert searched["runtime_artifact"]["bundle_checksum"]
            paged = await execute(
                "search_server_specifications",
                {"memory_min": 64, "page_size": 1, "page": 2},
            )
            assert (
                len(paged["objects"]) == 1 and paged["pagination"]["total_items"] == 2
            )
            supported = await execute(
                "search_server_specifications",
                {
                    "memory_min": 64,
                    "role": "supported_capability",
                    "scope": "support_limit",
                },
            )
            # Upper bounds are never silently selected as lower-bound requirements.
            assert supported["pagination"]["total_items"] == 0
            compared = await execute(
                "compare_server_specifications",
                {
                    "left_snapshot_id": snapshot_id(request.run_id, "server_a"),
                    "right_snapshot_id": snapshot_id(request.run_id, "server_b"),
                },
            )
            assert compared["outcome"]["comparable_count"] == 4
            assert any(
                c.get("right_minus_left") == "64"
                for c in compared["outcome"]["comparisons"]
            )
            row = next(p for p in properties if p["document_id"] == "server_a")
            evidence_inputs = {
                "snapshot_id": row["snapshot_id"],
                "observation_id": row["observation_id"],
            }
            evidence = await execute("get_server_requirement_evidence", evidence_inputs)
            assert evidence["outcome"]["quote"] == "총 메모리 64 GB 이상"
            # Optional local original: replays a previously exposed, frozen real extraction;
            # it is never reported as independent model accuracy.
            source_case = json.loads(
                (
                    BACKEND
                    / "tests/features/goods_querying/fixtures/gpu_server_memory_source.json"
                ).read_text()
            )["document"]
            original = (
                BACKEND.parent
                / ".artifacts/old_20261025/server_standard_management/holdout_repaired_01"
                / source_case["source"]["path"]
            )
            if original.is_file():
                assert (
                    hashlib.sha256(original.read_bytes()).hexdigest()
                    == source_case["source"]["sha256"]
                )
                actual_checkpoint = tmp_path / "actual_extraction.json"
                actual_checkpoint.write_text(
                    json.dumps(
                        {
                            "classification_code": "4321150102",
                            "documents": [source_case],
                            "unavailable_documents": [],
                        },
                        ensure_ascii=False,
                    )
                )
                actual = request.model_copy(
                    update={
                        "run_id": "original_server_" + uuid4().hex,
                        "documents": [
                            type(request.documents[0])(
                                document_id=source_case["document_id"],
                                filename=original.name,
                                source_uri=original.as_uri(),
                                sha256=source_case["source"]["sha256"],
                            )
                        ],
                        "extraction_checkpoint": type(request.extraction_checkpoint)(
                            uri=actual_checkpoint.as_uri(),
                            sha256=hashlib.sha256(
                                actual_checkpoint.read_bytes()
                            ).hexdigest(),
                        ),
                    }
                )
                actual_result = await flows.execute_specification_run(actual)
                assert (
                    actual_result.status == "partial"
                    and actual_result.summary["applied"] == 1
                )
                original_result = await execute(
                    "search_server_specifications",
                    {
                        "memory_min": 64,
                        "snapshot_id": snapshot_id(
                            actual.run_id, source_case["document_id"]
                        ),
                    },
                )
                assert original_result["pagination"]["total_items"] == 1
                original_row = original_result["objects"][0]["properties"]
                assert original_row["value_decimal"] == "512"
                assert (
                    original_row["document_status"]
                    == original_row["run_status"]
                    == "partial"
                )
                assert original_row["subject_concept_key"] == "computer_server.memory"
                assert original_row["owner_concept_key"] == "computer_server.server"
                original_evidence = await execute(
                    "get_server_requirement_evidence",
                    {
                        "snapshot_id": original_row["snapshot_id"],
                        "observation_id": original_row["observation_id"],
                    },
                )
                assert "512" in original_evidence["outcome"]["quote"]
            extraction = Path(row["extraction_uri"].removeprefix("file://"))
            extraction.write_text("tampered")
            invalid = await client.post(
                "/v1/capabilities/get_server_requirement_evidence:execute",
                headers=headers,
                json={"inputs": evidence_inputs},
            )
            assert invalid.status_code == 502
            assert invalid.json()["detail"]["code"] == "evidence_verification_failed"
