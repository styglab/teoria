from copy import deepcopy
from pathlib import Path
import hashlib
import json

import pytest

from backend.tests.fixtures.server_specifications import corpus, synthetic_package
from teoria.features.specification_processing.normalization.profile_application import (
    apply_profile,
)
from teoria.features.specification_processing.storage.query_observations import (
    build_query_observations,
    snapshot_id,
)
from teoria.features.goods_querying.comparison import compare_requirements
from teoria.features.runtime.capability.binder import CapabilityBinder
from teoria.features.semantic_modeling.registry.loader import RegistryLoader
from teoria.features.runtime.capability.handlers import CapabilityHandlers
from teoria.features.runtime.capability.runner import CapabilityRunner
from teoria.features.runtime.capability.contracts import CapabilityExecutionError
from teoria.features.goods_querying.capabilities import register_server_capabilities


def observations(tmp_path):
    source = corpus()
    package = synthetic_package()
    normalized, _ = apply_profile(source, package, run_id="server_case")
    refs = []
    for name, body in [("extracted", source), ("normalized", normalized)]:
        path = tmp_path / f"{name}.json"
        raw = json.dumps(body, ensure_ascii=False).encode()
        path.write_bytes(raw)
        refs.append({"uri": path.as_uri(), "sha256": hashlib.sha256(raw).hexdigest()})
    return build_query_observations(source, normalized, package, *refs)


def test_memory_search_filters_role_scope_predicate_and_unit_before_pagination():
    catalog = RegistryLoader(Path("backend/contracts/runtime")).load()
    capability = catalog.capabilities["search_server_specifications"]
    query = CapabilityBinder().bind(
        catalog, capability, capability.steps[0], {"memory_min": 64}
    )
    assert query["filters"] == [
        {"field": "value_decimal", "operator": "gte", "value": 64},
        {"field": "role", "operator": "eq", "value": "requirement_candidate"},
        {"field": "semantic_scope", "operator": "eq", "value": "system_total"},
        {"field": "unit", "operator": "eq", "value": "GB"},
        {"field": "operator", "operator": "in", "value": ["eq", "gte", "gt"]},
        {
            "field": "property_stable_key",
            "operator": "in",
            "value": [
                "computer_server.server.memory_capacity",
                "computer_server.memory.capacity",
            ],
        },
    ]
    assert query["pagination"]["count_distinct"] is False


def test_projection_preserves_values_roles_source_and_versions(tmp_path):
    rows = observations(tmp_path)
    assert len(rows) == 8
    assert {r["role"] for r in rows} == {
        "requirement_candidate",
        "supported_capability",
        "existing_reference",
    }
    assert (
        next(r for r in rows if r["role"] == "supported_capability")["value_decimal"]
        == 1000
    )
    assert all(
        r["ontology_checksum"] and r["package_checksum"] and r["extraction_sha256"]
        for r in rows
    )
    assert all("text" not in r and "quote" not in r for r in rows)
    assert len({r["snapshot_id"] for r in rows}) == 2


def test_changed_normalized_value_cannot_be_materialized(tmp_path):
    source, package = corpus(), synthetic_package()
    normalized, _ = apply_profile(source, package, run_id="case")
    normalized["documents"][0]["requirements"][0]["value"]["decimal"] = "999"
    with pytest.raises(ValueError, match="pinned profile"):
        build_query_observations(source, normalized, package, {}, {})


@pytest.mark.parametrize(
    "mismatch",
    [
        "unit",
        "role",
        "semantic_scope",
        "ontology_checksum",
        "package_checksum",
        "operator",
        "qualifiers_raw",
        "duplicate",
    ],
)
def test_comparison_refuses_incomparable_requirements(tmp_path, mismatch):
    rows = observations(tmp_path)
    left, right = [rows[0]], [deepcopy(rows[4])]
    if mismatch == "duplicate":
        right.append(deepcopy(right[0]))
    elif mismatch == "qualifiers_raw":
        right[0][mismatch] = ["optional"]
    else:
        right[0][mismatch] = "different"
    result = compare_requirements(left, right)
    assert result["comparable_count"] == 0
    assert result["not_comparable_count"] >= 1


async def test_compare_and_checksum_verified_evidence_use_normal_runtime_mapping(
    tmp_path,
):
    rows = observations(tmp_path)

    class Database:
        async def execute(self, catalog, source, relation, query):
            from teoria.features.runtime.source.database import DatabaseQueryResult

            filters = {f["field"]: f["value"] for f in query["filters"]}
            selected = [r for r in rows if all(r[k] == v for k, v in filters.items())]
            return DatabaseQueryResult(
                selected,
                {
                    "page": 1,
                    "page_size": 100,
                    "total_items": len(selected),
                    "total_pages": 1,
                },
            )

    catalog = RegistryLoader(Path("backend/contracts/runtime")).load()
    handlers = CapabilityHandlers()
    register_server_capabilities(handlers)
    runner = CapabilityRunner(database_executor=Database(), handlers=handlers)
    compared = await runner.run(
        catalog,
        "compare_server_specifications",
        {
            "left_snapshot_id": snapshot_id("server_case", "server_a"),
            "right_snapshot_id": snapshot_id("server_case", "server_b"),
        },
    )
    assert compared.outcome["comparable_count"] == 4
    assert compared.outcome["comparisons"][0]["status"] in {"equal", "different"}
    evidence_inputs = {
        "snapshot_id": rows[0]["snapshot_id"],
        "observation_id": rows[0]["observation_id"],
    }
    evidence = await runner.run(
        catalog, "get_server_requirement_evidence", evidence_inputs
    )
    assert evidence.outcome["status"] == "verified"
    assert evidence.outcome["quote"] == "총 메모리 64 GB 이상"
    (tmp_path / "extracted.json").write_text("tampered")
    with pytest.raises(CapabilityExecutionError) as exc:
        await runner.run(catalog, "get_server_requirement_evidence", evidence_inputs)
    assert exc.value.code == "evidence_verification_failed"


@pytest.mark.parametrize("basis", ["explicit", "interpreted", "missing", "ambiguous"])
def test_original_gpu_server_memory_requires_an_explicit_unique_owner(tmp_path, basis):
    import yaml
    from uuid import UUID
    from teoria.features.goods_normalization.profiles.compiler import (
        resolve_profile_template,
        compile_package,
    )

    case = json.loads(
        (
            Path(__file__).with_name("fixtures") / "gpu_server_memory_source.json"
        ).read_text()
    )
    doc = case["document"]
    assert case["label_status"] == "silver"
    source = {
        "classification_code": "4321150102",
        "documents": [doc],
        "unavailable_documents": [],
    }
    # Stable concept IDs are synthetic test identities; source text and owner relation are frozen from the original.
    ontology = {
        "namespace": "computer_server",
        "version": "0.1.0",
        "objects": [
            {
                "business_object_id": str(UUID(int=10)),
                "concept_id": str(UUID(int=1)),
                "stable_key": "computer_server.server",
                "properties": [
                    {
                        "concept_id": str(UUID(int=2)),
                        "stable_key": "computer_server.server.memory_capacity",
                        "value_type": "decimal",
                        "unit": "GB",
                    }
                ],
            },
            {
                "business_object_id": str(UUID(int=11)),
                "concept_id": str(UUID(int=5)),
                "stable_key": "computer_server.memory",
                "properties": [
                    {
                        "concept_id": str(UUID(int=6)),
                        "stable_key": "computer_server.memory.capacity",
                        "value_type": "decimal",
                        "unit": "GB",
                    }
                ],
            },
        ],
        "relationships": [
            {
                "concept_id": str(UUID(int=7)),
                "stable_key": "computer_server.has_memory",
                "source_object_id": str(UUID(int=10)),
                "target_object_id": str(UUID(int=11)),
            }
        ],
    }
    template = yaml.safe_load(
        Path(
            "backend/authoring/normalization_profiles/computer_server_memory.yaml"
        ).read_text()
    )
    profile = resolve_profile_template(template, ontology, version_id=UUID(int=3))
    package = compile_package(
        profile, ontology, revision_id=UUID(int=4), approval_actor="test:reviewer"
    )
    if basis == "missing":
        doc["relations"] = []
    elif basis == "ambiguous":
        owner = deepcopy(
            next(
                e
                for e in doc["entities"]
                if e["id"] == doc["relations"][0]["target_id"]
            )
        )
        owner["id"] = "other_server"
        doc["entities"].append(owner)
        relation = deepcopy(doc["relations"][0])
        relation.update(id="other_relation", target_id=owner["id"])
        doc["relations"].append(relation)
    else:
        doc["relations"][0]["basis"] = basis
    normalized, _ = apply_profile(source, package, run_id="source_case")
    refs = {"uri": (tmp_path / "source.json").as_uri(), "sha256": "a" * 64}
    rows = build_query_observations(source, normalized, package, refs, refs)
    assert len(rows) == 1
    assert (
        rows[0]["value_decimal"] == 512 and rows[0]["semantic_scope"] == "system_total"
    )
    assert rows[0]["subject_concept_key"] == "computer_server.memory"
    assert rows[0]["property_stable_key"] == "computer_server.memory.capacity"
    assert bool(rows[0]["owner_observation_id"]) == (basis == "explicit")
    if basis == "explicit":
        assert rows[0]["owner_concept_key"] == "computer_server.server"
        assert rows[0]["subject_observation_id"] != rows[0]["owner_observation_id"]


def test_binary_memory_units_keep_raw_value_and_exact_conversion(tmp_path):
    source = corpus()
    attribute = source["documents"][0]["attributes"][0]
    attribute["unit_raw"] = "GiB"
    source["documents"][0]["parsed_document"]["nodes"][1]["text"] = (
        "총 메모리 64 GiB 이상"
    )
    package = synthetic_package()
    normalized, _ = apply_profile(source, package, run_id="binary_case")
    refs = {"uri": (tmp_path / "source.json").as_uri(), "sha256": "a" * 64}
    rows = build_query_observations(source, normalized, package, refs, refs)
    assert str(rows[0]["value_decimal"]) == "68.719476736"
    assert (
        rows[0]["unit"] == "GB"
        and rows[0]["unit_raw"] == "GiB"
        and rows[0]["value_raw"] == "64"
    )
