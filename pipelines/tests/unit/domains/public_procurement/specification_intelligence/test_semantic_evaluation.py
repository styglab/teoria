"""Semantic failures that source quoting and JSON validation alone cannot detect."""
import json

import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence.document_evidence import build_document_evidence
from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import Definition, DocumentAnalysis
from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_evaluation import (
    References, ReuseProposal, run, score, validate_reuse,
)
from teoria_pipelines.domains.public_procurement.specification_intelligence import semantic_batch as batch


@pytest.fixture
def sample():
    document = build_document_evidence({"success": True, "blocks": [
        {"type": "paragraph", "text": text} for text in
        ["CPU 16Core", "RAM 64GB", "PSU 2EA", "GPU CUDA 200Core"]]},
        document_id="server", parse_run_id="fixture", native_sha256="a" * 64)
    def evidence(i):
        return [{"document_id": "server", "node_id": document.nodes[i].node_id, "quote": document.nodes[i].text}]
    entities, requirements, definitions, decisions = [], [], [], []
    entity_ids = ["processor", "system_memory", "psu", "gpu"]
    property_ids = ["core_count", "memory_capacity", "quantity", "cuda_core_count"]
    for i, (label, value, unit, dimension) in enumerate([
        ("CPU", "16", "Core", "count"), ("RAM", "64", "GB", "data_size"),
        ("PSU", "2", "EA", "count"), ("GPU", "200", "Core", "count"),
    ]):
        entity, prop = entity_ids[i], property_ids[i]
        entities.append({"entity_id": entity, "label_raw": label, "meaning": entity,
                         "roles": ["delivery_target"], "owner_item_id": None, "evidence": evidence(i)})
        requirements.append({"requirement_id": prop, "subject_id": entity, "item_ids": [entity], "scope": "item", "kind": "property",
            "property_raw": label, "meaning": prop, "dimension": dimension, "value_text": value,
            "unit_raw": unit, "operator": "eq", "operator_raw": None, "modality": "required",
            "qualifiers": {"aggregation": "per_instance", "configuration": "installed", "measurement_basis": prop},
            "evidence": evidence(i)})
        for kind, key in [("entity", entity), ("property", prop)]:
            definitions.append(Definition(concept_id=key, kind=kind, name=key, definition=key,
                dimension=dimension if kind == "property" else None,
                applicable_entity_concept_ids=[entity] if kind == "property" else [], aliases=[], distinction="test"))
            decisions.append({"observation_ref": f"server/{key}", "decision": "reuse", "concept_id": key, "reason": "test"})
    graph = DocumentAnalysis(document_id="server", native_sha256="a" * 64, entities=entities,
        requirements=requirements, relations=[], groups=[], identities=[], coverage=[{
            "node_id": n.node_id, "status": "observed", "requirement_ids": [property_ids[i]], "reason": "fixture"
        } for i, n in enumerate(document.nodes)], issues=[])
    proposal = ReuseProposal(decisions=decisions, issues=[])
    return document, graph, definitions, proposal


def reference(document, *, key="ram", expected=None, forbidden=False):
    return {"check_id": key, "kind": "property", "evidence": {
        "document_id": document.document_id, "node_id": "n00001", "quote": "RAM 64GB"},
        "expected": expected or {"concept_id": "memory_capacity", "value_unit": "64GB",
                                  "subject_concept_id": "system_memory"}, "forbidden": forbidden}


def evaluate(sample, checks):
    document, graph, _, proposal = sample
    return score(References(checks=checks, label_status="silver"), [graph], proposal.decisions, [document])


def test_valid_mapping_and_semantic_checks(sample):
    document, graph, dictionary, proposal = sample
    validate_reuse(proposal, graph, dictionary)
    assert evaluate(sample, [reference(document)])["passed"] == 1


def test_applicability_gap_is_not_a_new_property_or_a_silent_dictionary_edit(sample):
    _, graph, dictionary, proposal = sample
    quantity = next(d for d in dictionary if d.concept_id == "quantity")
    quantity.applicable_entity_concept_ids = ["processor"]
    with pytest.raises(ValueError, match="applicability"):
        validate_reuse(proposal, graph, dictionary)
    row = next(d for d in proposal.decisions if d.observation_ref == "server/quantity")
    row.decision = "applicability_gap"
    validate_reuse(proposal, graph, dictionary)
    assert quantity.applicable_entity_concept_ids == ["processor"]


def test_unresolved_subject_and_missing_decisions_are_rejected(sample):
    _, graph, dictionary, proposal = sample
    graph.requirements[0].subject_id = None
    with pytest.raises(ValueError, match="unresolved subject"):
        validate_reuse(proposal, graph, dictionary)
    proposal.decisions.pop()
    with pytest.raises(ValueError, match="every observation"):
        validate_reuse(proposal, graph, dictionary)


def test_cuda_cpu_core_merge_rejected_even_with_same_dimension_and_valid_quotes(sample):
    _, graph, dictionary, proposal = sample
    proposal.decisions[-1].concept_id = "core_count"
    with pytest.raises(ValueError, match="applicability"):
        validate_reuse(proposal, graph, dictionary)


def test_wrong_subject_is_a_semantic_failure(sample):
    document, graph, _, _ = sample
    graph.requirements[1].subject_id = "processor"
    graph.requirements[1].item_ids = ["processor"]
    result = evaluate(sample, [reference(document)])
    assert result["passed"] == 0
    assert result["checks"][0]["diagnostics"][0]["mismatches"]["subject_concept_id"]["actual"] == "processor"


def test_missing_requirement_is_counted_as_failure(sample):
    document, graph, _, proposal = sample
    graph.requirements.pop(1)
    proposal.decisions = [d for d in proposal.decisions if d.observation_ref != "server/memory_capacity"]
    graph.coverage[1].requirement_ids = []
    graph.coverage[1].status = "partial"
    assert evaluate(sample, [reference(document)])["passed"] == 0


def test_one_prediction_cannot_satisfy_two_expected_observations(sample):
    document = sample[0]
    result = evaluate(sample, [reference(document, key="first"), reference(document, key="second")])
    assert result["passed"] == 1 and result["total"] == 2


def test_installed_supported_and_aggregation_confusion_is_detected(sample):
    document = sample[0]
    result = evaluate(sample, [reference(document, expected={"value_unit": "64GB", "aggregation": "total",
                                                            "configuration": "supported"})])
    assert result["passed"] == 0


def test_forbidden_merge_violation_and_invalid_reference(sample):
    document = sample[0]
    result = evaluate(sample, [reference(document, expected={"concept_id": "memory_capacity"}, forbidden=True)])
    assert result["forbidden_violations"] == 1
    invalid = reference(document)
    invalid["evidence"]["quote"] = "invented source"
    with pytest.raises(ValueError, match="reference evidence"):
        evaluate(sample, [invalid])


def prepare_run(tmp_path, sample):
    document, graph, dictionary, proposal = sample
    source = tmp_path / "source.txt"
    source.write_text("\n".join(n.text for n in document.nodes))
    native = tmp_path / "native.json"
    native.write_text(json.dumps({"success": True, "blocks": [
        {"type": "paragraph", "text": n.text} for n in document.nodes]}))
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"document_id": "server", "parser": "fixture", "version": "1",
        "status": "success", "options": {"ocr": False, "formulaOcr": False}}))
    entry = {"document_id": "server", "notice_number": "fixture"}
    for kind, path in [("source", source), ("native", native), ("parse_record", record)]:
        entry[f"{kind}_path"] = path
        entry[f"{kind}_sha256"] = batch.digest(path)
    root = tmp_path / "batch"
    batch.prepare(batch.BatchInput(batch_id="fixture", documents=[entry]), root)
    graph.native_sha256 = batch.digest(native)
    for i, row in enumerate(graph.requirements):
        before = row.requirement_id
        row.requirement_id = f"item_{i:03}_" + before
        for coverage in graph.coverage:
            coverage.requirement_ids = [row.requirement_id if key == before else key for key in coverage.requirement_ids]
        for decision in proposal.decisions:
            if decision.observation_ref == f"server/{before}":
                decision.observation_ref = f"server/{row.requirement_id}"
    dictionary_path = tmp_path / "dictionary.json"
    batch.save(dictionary_path, {"definitions": [d.model_dump() for d in dictionary]})
    return root, graph, proposal, dictionary_path


@pytest.mark.asyncio
async def test_automatic_stage_order_preserves_dictionary_and_never_exposes_references(tmp_path, sample):
    root, graph, proposal, dictionary_path = prepare_run(tmp_path, sample)
    before = dictionary_path.read_bytes()
    calls = []
    class Runner:
        async def generate(self, instruction, context, output):
            assert "checks" not in context and "expected" not in context and "references" not in context
            title = context["schema"]["title"]
            calls.append(title)
            if title == "ItemInventory":
                return {"document_id": "server", "native_sha256": graph.native_sha256,
                    "purchase_summary": "장비 구매", "scope_evidence": graph.entities[0].model_dump()["evidence"],
                    "entries": [{"entity": e.model_dump(), "category": "delivery_item", "parent": None, "status": "supported", "node_ids": [f"n{i:05}"],
                                 "reason": "납품 대상"} for i, e in enumerate(graph.entities)],
                    "shared_node_ids": [], "unresolved_node_ids": [], "issues": []}
            if title == "ItemExtraction":
                item_id = context["item_id"]
                rows = [r for r in graph.requirements if r.item_ids == [item_id]]
                return {"document_id": "server", "native_sha256": graph.native_sha256,
                    "task_id": context["task_id"], "entities": [], "requirements": [r.model_dump() for r in rows],
                    "relations": [], "groups": [], "coverage": [c.model_dump() for c in graph.coverage
                        if c.node_id in context["source_node_ids"]], "issues": []}
            if title == "ResolutionProposal":
                return {"document_id": "server", "native_sha256": graph.native_sha256,
                        "assignments": [], "identities": [], "relations": [], "issues": []}
            if title == "DocumentValidation":
                return {"graph_sha256": context["graph_sha256"], "checked_item_ids": context["required_item_ids"],
                        "findings": [], "limitations": ["모델 검토"]}
            return proposal.model_dump()
    output = tmp_path / "result"
    summary = await run(root, dictionary_path, output, Runner())
    assert calls == ["ItemInventory", "DocumentValidation", *["ItemExtraction"] * 4, "ResolutionProposal", "DocumentValidation", "ReuseProposal"]
    assert summary["execution"] == "completed" and summary["published"] is False
    assert dictionary_path.read_bytes() == before == (output / "dictionary.json").read_bytes()
    assert (output / "freeze.json").exists()


@pytest.mark.asyncio
async def test_timeout_is_recorded_as_failure_without_manual_prediction_fallback(tmp_path, sample):
    root, _, _, dictionary_path = prepare_run(tmp_path, sample)
    class Runner:
        async def generate(self, instruction, context, output):
            raise TimeoutError("fixture timeout")
    output = tmp_path / "result"
    with pytest.raises(RuntimeError, match="TimeoutError"):
        await run(root, dictionary_path, output, Runner())
    failure = batch.load(output / "failure.json")
    assert failure["stage"] == "identify" and failure["manual_fallback"] is False
    assert not (output / "summary.json").exists()
