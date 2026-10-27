"""Source-backed examples and failures that previously produced false components."""
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError
import yaml

from teoria.features.goods_normalization.contracts.specification_graph import (
    DocumentGoodsGraph, SpecificationValue,
)

ROOT = Path(__file__).resolve().parents[4]
EXAMPLES = ROOT / "authoring/specification_examples/four_sample_graphs.yaml"


def examples():
    return yaml.safe_load(EXAMPLES.read_text())["graphs"]


@pytest.mark.parametrize("index", range(4))
def test_four_documents_have_valid_classification_free_review_graphs(index):
    graph = DocumentGoodsGraph.model_validate(examples()[index])
    assert graph.review_status == "proposed"
    assert graph.classifications == []
    assert DocumentGoodsGraph.model_validate_json(graph.model_dump_json()) == graph


def test_cage_is_external_and_compatibility_is_not_composition():
    graph = DocumentGoodsGraph.model_validate(examples()[3])
    external = next(m for m in graph.memberships if m.subject_id == "external_cage")
    assert external.role == "externally_provided"
    assert not any(c.child_id == "external_cage" for c in graph.compositions)
    compatibility = next(r for r in graph.requirements if r.requirement_id == "rail_compatibility")
    assert set(compatibility.subject_ids) == {"rail", "treatment_table", "external_cage"}
    load = next(p for p in graph.properties if p.statement_id == "table_load")
    assert load.subject_id == "treatment_table" and load.value.number == 200
    assert load.value.unit_raw == "kg" and load.operator == "gte"


def test_pump_quantity_and_supported_board_capacity_remain_distinct():
    graph = DocumentGoodsGraph.model_validate(examples()[1])
    pump = next(c for c in graph.compositions if c.child_id == "pump")
    assert pump.quantity.value == 2 and pump.quantity.unit_raw == "set"
    assert not any(s.name == "아날로그 보드" for s in graph.subjects)
    boards = next(p for p in graph.properties if p.statement_id == "supported_boards")
    assert boards.assertion_role == "supported_capability"
    oven = next(p for p in graph.properties if p.statement_id == "oven_range")
    assert oven.value.arguments[0].kind == "relative"
    assert oven.value.arguments[0].reference == "ambient_temperature"
    assert oven.value.arguments[0].number == -10
    assert next(p for p in graph.properties if p.statement_id == "column_capacity").value.kind == "any"


def test_nested_components_and_shared_requirements_keep_their_context():
    graph = DocumentGoodsGraph.model_validate(examples()[2])
    cameras = next(c for c in graph.compositions if c.child_id == "motion_cameras")
    software = next(c for c in graph.compositions if c.child_id == "motion_software")
    assert cameras.parent_id == software.parent_id == "motion"
    assert cameras.quantity.value == 20 and software.quantity.unit_raw == "COPY"
    assert not any(c.child_id == "agricultural_test_subject" for c in graph.compositions)
    sync = next(r for r in graph.requirements if r.requirement_id == "shared_synchronization")
    assert set(sync.subject_ids) == {"laser", "camera", "power"}
    assert not graph.item_relations  # no invented pairwise synchronization links
    acceptance = next(r for r in graph.requirements if r.requirement_id == "laser_acceptance")
    assert acceptance.verifies == ["laser_rate"]


def test_gases_are_measurement_targets_and_existing_equipment_is_preserved():
    graph = DocumentGoodsGraph.model_validate(examples()[0])
    assert not {s.name for s in graph.subjects} & {"CO", "H2S", "O2", "EX"}
    gas = next(p for p in graph.properties if p.statement_id == "environment_targets")
    assert {v.text for v in gas.value.arguments} == {"CO", "H2S", "O2", "EX"}
    assert next(m for m in graph.memberships if m.subject_id == "existing_transmitter").role == "existing"
    assert next(s for s in graph.subjects if s.subject_id == "upgrade").kind == "service"


def test_standards_and_required_documents_are_requirements_not_completed_work():
    farm = DocumentGoodsGraph.model_validate(examples()[2])
    compliance = next(r for r in farm.requirements if r.requirement_id == "pedestrian_compliance")
    assert compliance.subject_ids == ["pedestrian_targets"]
    assert compliance.standards[0].identifier_raw == "ISO 19206-2"
    assert compliance.standards[0].allows_equivalent
    vehicle = DocumentGoodsGraph.model_validate(examples()[3])
    document = next(s for s in vehicle.subjects if s.subject_id == "wiring_diagram")
    assert document.kind == "deliverable"
    assert next(m for m in vehicle.memberships if m.subject_id == document.subject_id).role == "required_supply"
    assert vehicle.review_status == "proposed"


def test_external_classification_can_be_added_without_reidentifying_the_graph():
    original = DocumentGoodsGraph.model_validate(examples()[3])
    data = original.model_dump(mode="json")
    data["classifications"] = [{
        "assignment_id": "synthetic_classification_claim", "subject_id": "vehicle",
        "raw_code": "synthetic_external_code", "source_kind": "item_metadata",
        "source_ref": "synthetic:item_metadata_row", "resolution_status": "unresolved",
    }]
    enriched = DocumentGoodsGraph.model_validate(data)
    assert enriched.subjects == original.subjects
    assert enriched.compositions == original.compositions
    data["classifications"][0]["resolution_status"] = "verified"
    with pytest.raises(ValidationError, match="catalog reference"):
        DocumentGoodsGraph.model_validate(data)


@pytest.mark.parametrize("mutation,match", [
    ("cycle", "cyclic"), ("self", "itself"), ("target", "missing subject"),
    ("evidence", "unknown evidence"), ("duplicate", "unique"),
    ("service_component", "incorrect subject kind"), ("excluded_component", "contradicts"),
])
def test_invalid_graphs_reject_false_compositions_and_broken_evidence(mutation, match):
    graph = deepcopy(examples()[3])
    edge = graph["compositions"][0]
    if mutation == "cycle":
        graph["compositions"].append({**edge, "composition_id": "cycle", "parent_id": edge["child_id"], "child_id": edge["parent_id"]})
    elif mutation == "self":
        edge["child_id"] = edge["parent_id"]
    elif mutation == "target":
        edge["child_id"] = "other_document_item"
    elif mutation == "evidence":
        edge["evidence_ids"] = ["unknown_source"]
    elif mutation == "duplicate":
        graph["subjects"].append(deepcopy(graph["subjects"][0]))
    elif mutation == "service_component":
        next(s for s in graph["subjects"] if s["subject_id"] == edge["child_id"])["kind"] = "service"
    elif mutation == "excluded_component":
        graph["memberships"].append({
            "membership_id": "excluded_power", "scope_id": "vehicle_supply", "subject_id": edge["child_id"],
            "role": "excluded", "evidence_ids": edge["evidence_ids"],
        })
    with pytest.raises(ValidationError, match=match):
        DocumentGoodsGraph.model_validate(graph)


@pytest.mark.parametrize("value", [
    {"kind": "number", "text": "12"},
    {"kind": "number", "number": "NaN"},
    {"kind": "range", "arguments": [{"kind": "number", "number": 10}, {"kind": "number", "number": 1}]},
    {"kind": "any", "arguments": [{"kind": "text", "text": "only one"}]},
    {"kind": "tolerance", "number": -1},
])
def test_malformed_numeric_or_conditional_values_are_not_silently_coerced(value):
    with pytest.raises(ValidationError):
        SpecificationValue.model_validate(value)


def test_acceptance_must_reference_a_requirement_in_this_document():
    graph = examples()[2]
    acceptance = next(r for r in graph["requirements"] if r["requirement_kind"] == "acceptance")
    acceptance["verifies"] = ["unknown_requirement"]
    with pytest.raises(ValidationError, match="acceptance"):
        DocumentGoodsGraph.model_validate(graph)


def test_graph_validation_cli_is_read_only_and_reports_scope(tmp_path, capsys):
    from argparse import Namespace
    from teoria.features.specification_processing.cli import run_command

    assert run_command(Namespace(specification_command="validate-graph", manifest=EXAMPLES)) == 0
    assert '"validation_scope": "structure_and_references_only"' in capsys.readouterr().out
    invalid = examples()[3]
    invalid["compositions"][0]["child_id"] = "missing"
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump({"purpose": "test rejection", "graphs": [invalid]}))
    assert run_command(Namespace(specification_command="validate-graph", manifest=path)) == 1
    assert '"status": "invalid"' in capsys.readouterr().out


def test_proposed_graphs_do_not_claim_other_source_documents():
    ledger = yaml.safe_load((ROOT.parent / "docs/architecture/examples/goods_four_sample_evidence.yaml").read_text())
    hashes = {d["document_id"]: d["source_sha256"] for d in ledger["documents"]}
    assert {g["document_id"]: g["source_sha256"] for g in examples()} == hashes
