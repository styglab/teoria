"""Item boundaries, immutable observations and staged execution over saved parses."""
import asyncio
import copy
import json

import pytest

from teoria_pipelines.domains.public_procurement.specification_intelligence import semantic_batch as batch
from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import (
    DocumentAnalysis, DocumentValidation, IdentityLink, Integration, ItemExtraction, ItemInventory, ResolutionProposal,
    apply_resolution, validate_analysis, validate_integration, validate_inventory, validate_resolved,
)


@pytest.fixture
def prepared(tmp_path):
    source = tmp_path / "original.txt"
    source.write_text("서버 2대 모델 X100\nCPU 16Core 이상\nRAM 128GB 이상\n전체 장비 보증 3년")
    native = tmp_path / "native.json"
    native.write_text(json.dumps({"success": True, "blocks": [
        {"type": "paragraph", "text": line} for line in source.read_text().splitlines()]}))
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"document_id": "server", "parser": "fixture", "version": "1", "status": "success",
                                 "options": {"ocr": False, "formulaOcr": False}}))
    entry = {"document_id": "server", "notice_number": "notice_01"}
    for kind, path in (("source", source), ("native", native), ("parse_record", record)):
        entry[f"{kind}_path"], entry[f"{kind}_sha256"] = path, batch.digest(path)
    root = tmp_path / "batch"
    batch.prepare(batch.BatchInput(batch_id="fixture", documents=[entry]), root)
    return root


def evidence(doc, index):
    node = doc.nodes[index]
    return [{"document_id": doc.document_id, "node_id": node.node_id, "quote": node.text}]


def inventory(root):
    doc = batch.documents(root)[0]
    return ItemInventory(document_id=doc.document_id, native_sha256=doc.native_sha256, purchase_summary="장비 구매", scope_evidence=evidence(doc, 0), entries=[{
        "entity": {"entity_id": "server_a", "label_raw": "서버", "meaning": "납품 서버",
                   "roles": ["delivery_target"], "owner_item_id": None, "evidence": evidence(doc, 0)},
        "category": "delivery_item", "parent": None, "status": "supported", "node_ids": [n.node_id for n in doc.nodes[:3]], "reason": "납품 범위와 규격"}],
        shared_node_ids=[doc.nodes[3].node_id], unresolved_node_ids=[], issues=[])


def extraction(root, task):
    doc = batch.documents(root)[0]
    rows, entities = [], []
    if task["task_id"] == "shared":
        rows.append({"requirement_id": "shared_warranty", "subject_id": None, "item_ids": [], "scope": "common",
            "kind": "service", "property_raw": "보증", "meaning": "보증 기간", "dimension": "time",
            "value_text": "3", "unit_raw": "년", "operator": "eq", "operator_raw": None,
            "modality": "required", "qualifiers": {"aggregation": "not_applicable", "configuration": "not_applicable",
                "measurement_basis": "기간"}, "evidence": evidence(doc, 3)})
    else:
        for i, label, prop, value, unit, dimension in ((1, "CPU", "cores", "16", "Core", "count"),
                                                     (2, "RAM", "capacity", "128", "GB", "data_size")):
            entity_id = task["new_id_prefix"] + label.lower()
            entities.append({"entity_id": entity_id, "label_raw": label, "meaning": label,
                "roles": ["specification_subject"], "owner_item_id": task["item_id"], "evidence": evidence(doc, i)})
            rows.append({"requirement_id": task["new_id_prefix"] + prop, "subject_id": entity_id,
                "item_ids": [task["item_id"]], "scope": "item", "kind": "property", "property_raw": label,
                "meaning": prop, "dimension": dimension, "value_text": value, "unit_raw": unit,
                "operator": "ge", "operator_raw": "이상", "modality": "required",
                "qualifiers": {"aggregation": "unknown", "configuration": "installed", "measurement_basis": prop},
                "evidence": evidence(doc, i)})
    return ItemExtraction(document_id=doc.document_id, native_sha256=doc.native_sha256, task_id=task["task_id"],
        entities=entities, requirements=rows, relations=[], groups=[], coverage=[{
            "node_id": ref, "status": "observed" if any(e["node_id"] == ref for r in rows for e in r["evidence"]) else "non_requirement",
            "requirement_ids": [r["requirement_id"] for r in rows if any(e["node_id"] == ref for e in r["evidence"])],
            "reason": "원문 대조"} for ref in task["source_node_ids"]], issues=[])


def batch_require(row):
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import Requirement
    return Requirement.model_validate(row)


def resolution(graph):
    return ResolutionProposal(document_id=graph.document_id, native_sha256=graph.native_sha256,
                              identities=[], assignments=[], relations=graph.relations, issues=[])


def integration(graph):
    definitions, mappings = [], []
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import observations
    for ref, (kind, row) in observations([graph]).items():
        key = ref.split("/")[1]
        excluded = kind == "property" and row.kind != "property"
        if not excluded:
            definitions.append({"concept_id": key, "kind": kind, "name": key, "definition": "검증용 의미",
                "dimension": row.dimension if kind == "property" else None,
                "applicable_entity_concept_ids": [row.subject_id] if kind == "property" else [],
                "aliases": [], "distinction": "문맥 검토", "predicate": row.predicate if kind == "relation" else None})
        mappings.append({"observation_ref": ref, "decision": "exclude" if excluded else "map",
                         "concept_id": None if excluded else key, "reason": "의미 검토"})
    return Integration(definitions=definitions, mappings=mappings, concept_relations=[], issues=[])


def accept_structure_review(root, findings=None):
    payload = batch.context(root, "review_structure", "server")
    batch.accept(root, "review_structure", {"graph_sha256": payload["graph_sha256"],
        "checked_item_ids": payload["required_item_ids"], "findings": findings or [], "limitations": ["모델 검토"]}, "server")


def populate(root, *, findings=None, with_group=False):
    batch.accept(root, "identify", inventory(root).model_dump(), "server")
    accept_structure_review(root)
    payload = batch.context(root, "extract", "server")
    parts = [extraction(root, t).model_dump() for t in payload["tasks"]]
    if with_group:
        parts[0]["groups"] = [{"group_id": "item_000_logic", "logic": "and", "members": ["item_000_cores", "item_000_capacity"],
                               "evidence": parts[0]["requirements"][0]["evidence"], "antecedents": []}]
    batch.accept(root, "extract", {"parts": parts}, "server")
    graph = DocumentAnalysis.model_validate(batch.accepted(root, "extract", "server"))
    batch.accept(root, "resolve", resolution(graph).model_dump(), "server")
    payload = batch.context(root, "validate", "server")
    batch.accept(root, "validate", {"graph_sha256": payload["graph_sha256"],
        "checked_item_ids": payload["required_item_ids"], "findings": findings or [], "limitations": ["모델 검토"]}, "server")
    return graph


def test_complete_item_first_flow_preserves_common_conditions_without_publishing(prepared, tmp_path):
    graph = populate(prepared)
    batch.accept(prepared, "integrate", integration(graph).model_dump())
    summary = batch.finalize(prepared, tmp_path / "result")
    assert summary["status"] == "needs_review"
    assert summary["human_reviewed"] is False and summary["published"] is False
    assert graph.requirements[-1].scope == "common" and graph.requirements[-1].item_ids == []
    assert batch.load(tmp_path / "result/dictionary.json")["status"] == "suggestion"


def test_identify_is_required_before_extraction_and_old_graph_submission_is_rejected(prepared):
    with pytest.raises(FileNotFoundError):
        batch.context(prepared, "extract", "server")
    batch.accept(prepared, "identify", inventory(prepared).model_dump(), "server")
    accept_structure_review(prepared)
    with pytest.raises(ValueError, match="per-item parts"):
        batch.accept(prepared, "extract", {"entities": []}, "server")


def test_inventory_cannot_drop_unassigned_source(prepared):
    found = inventory(prepared)
    found.shared_node_ids = []
    with pytest.raises(ValueError, match="every text node"):
        validate_inventory(found, batch.documents(prepared)[0])


def test_inventory_separates_deliverables_bundles_existing_and_spare_cpu():
    from teoria_pipelines.domains.public_procurement.specification_intelligence.document_evidence import build_document_evidence
    labels = ["서버", "랙", "모니터", "키보드", "교체용 CPU", "시스템", "기보유 스위치"]
    doc = build_document_evidence({"success": True, "blocks": [{"type": "paragraph", "text": s} for s in labels]},
        document_id="multi", parse_run_id="fixture", native_sha256="a" * 64)
    found = ItemInventory(document_id="multi", native_sha256=doc.native_sha256, purchase_summary="장비 구매", scope_evidence=evidence(doc, 0), entries=[{
        "entity": {"entity_id": f"target_{i}", "label_raw": label, "meaning": label,
                   "roles": ["delivery_target" if i < 5 else "delivery_group" if i == 5 else "existing"],
                   "owner_item_id": None, "evidence": evidence(doc, i)}, "status": "supported",
        "category": "delivery_item" if i < 5 else "bundle" if i == 5 else "existing", "parent": None, "node_ids": [doc.nodes[i].node_id], "reason": "원문 역할"} for i, label in enumerate(labels)],
        shared_node_ids=[], unresolved_node_ids=[], issues=[])
    validate_inventory(found, doc)
    tasks = batch.extraction_tasks(found)
    assert [t["item_id"] for t in tasks] == [f"target_{i}" for i in range(5)] + [None]
    assert tasks[-1]["source_node_ids"] == ["n00005", "n00006"]


@pytest.mark.parametrize("field,value", [("value_text", "28"), ("unit_raw", "MB"), ("operator", "le"), ("dimension", "frequency")])
def test_source_values_cannot_be_changed(prepared, field, value):
    graph = populate(prepared)
    setattr(graph.requirements[1], field, value)
    with pytest.raises(ValueError):
        validate_analysis(graph, batch.documents(prepared)[0])


def test_per_item_extraction_rejects_foreign_evidence_and_new_delivery_items(prepared):
    batch.accept(prepared, "identify", inventory(prepared).model_dump(), "server")
    accept_structure_review(prepared)
    payload = batch.context(prepared, "extract", "server")["tasks"][0]
    part = extraction(prepared, payload)
    part.requirements[0].evidence = batch_require({**part.requirements[0].model_dump(), "evidence": evidence(batch.documents(prepared)[0], 3)}).evidence
    with pytest.raises(ValueError, match="outside extraction region"):
        batch.validate_extraction(part, payload, batch.documents(prepared)[0])
    part = extraction(prepared, payload)
    part.entities[0].roles = ["delivery_target"]
    with pytest.raises(ValueError, match="identify revision"):
        batch.validate_extraction(part, payload, batch.documents(prepared)[0])


def test_wrong_item_ownership_is_rejected_even_when_values_and_quotes_are_valid(prepared):
    graph = populate(prepared)
    other = graph.entities[0].model_copy(deep=True)
    other.entity_id = "server_b"
    graph.entities.append(other)
    graph.requirements[0].item_ids = ["server_b"]
    with pytest.raises(ValueError, match="different item's scope"):
        validate_analysis(graph, batch.documents(prepared)[0])


def test_identity_resolution_preserves_model_observations_and_canonicalizes_subject(prepared):
    graph = populate(prepared)
    alias = graph.entities[0].model_copy(deep=True)
    alias.entity_id, alias.label_raw = "server_model", "X100"
    graph.entities.append(alias)
    graph.requirements[0].subject_id = "server_model"
    patch = resolution(graph)
    patch.identities = [IdentityLink(**{"alias_id": "server_model", "canonical_id": "server_a", "reason": "동일 서버",
                         "evidence": evidence(batch.documents(prepared)[0], 0)})]
    patch = ResolutionProposal.model_validate(patch.model_dump())
    resolved = apply_resolution(graph, patch)
    validate_resolved(graph, resolved)
    validate_analysis(resolved, batch.documents(prepared)[0])
    assert resolved.requirements[0].subject_id == "server_a"
    assert resolved.entities == graph.entities and len(resolved.entities) == 4
    resolved.requirements[0].value_text = "32"
    with pytest.raises(ValueError, match="source observations"):
        validate_resolved(graph, resolved)


def test_cannot_merge_internal_scope_with_delivery_item_or_other_items_scope(prepared):
    graph = populate(prepared)
    patch = resolution(graph)
    patch.identities = [IdentityLink(**{"alias_id": "item_000_cpu", "canonical_id": "server_a", "reason": "잘못된 병합",
                         "evidence": [*evidence(batch.documents(prepared)[0], 0), *evidence(batch.documents(prepared)[0], 1)]})]
    with pytest.raises(ValueError, match="component cannot own itself|delivery item with an internal scope"):
        validate_analysis(apply_resolution(graph, ResolutionProposal.model_validate(patch.model_dump())), batch.documents(prepared)[0])


def test_validation_errors_block_integration(prepared):
    populate(prepared, findings=[{"item_id": "items/completeness", "category": "item_missing", "severity": "error",
                                  "description": "납품 품목 누락"}])
    with pytest.raises(ValueError, match="errors block integration"):
        batch.context(prepared, "integrate")


def test_validation_requires_complete_checks_and_current_graph(prepared):
    populate(prepared)
    path = prepared / "validate/server.json"
    path.unlink()
    path.with_suffix(".accepted.json").unlink()
    ctx = batch.context(prepared, "validate", "server")
    check = {"graph_sha256": ctx["graph_sha256"], "checked_item_ids": [], "findings": [], "limitations": ["검토"]}
    with pytest.raises(ValueError, match="every required item"):
        batch.accept(prepared, "validate", check, "server")
    check.update(checked_item_ids=ctx["required_item_ids"], graph_sha256="a" * 64)
    with pytest.raises(ValueError, match="stale graph"):
        batch.accept(prepared, "validate", check, "server")


def test_input_and_upstream_result_tampering_invalidates_resume(prepared):
    populate(prepared)
    path = prepared / "identify/server.json"
    changed = batch.load(path)
    changed["entries"][0]["status"] = "candidate"
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="accepted result changed"):
        batch.analyses(prepared)


def test_mapping_rejects_wrong_dimension_unresolved_subject_and_fake_alias(prepared):
    graph = populate(prepared)
    draft = integration(graph)
    draft.definitions[-1].dimension = "frequency"
    with pytest.raises(ValueError, match="dimension mismatch"):
        validate_integration(draft, [graph])
    draft = integration(graph)
    draft.definitions[0].aliases = ["not in source"]
    with pytest.raises(ValueError, match="alias absent"):
        validate_integration(draft, [graph])
    graph.requirements[0].subject_id = None
    with pytest.raises(ValueError, match="unresolved property"):
        validate_integration(integration(populate_copy(graph)), [graph])


def populate_copy(graph):
    result = graph.model_copy(deep=True)
    result.requirements[0].subject_id = "item_000_cpu"
    return result


@pytest.mark.asyncio
async def test_actual_orchestration_calls_identification_then_item_and_shared_extraction(prepared, tmp_path):
    calls = []
    class Runner:
        async def generate(self, instruction, payload, output):
            title = payload["schema"]["title"]
            calls.append((title, payload.get("task_id")))
            if title == "ItemInventory":
                return inventory(prepared).model_dump()
            if title == "ItemExtraction":
                return extraction(prepared, payload).model_dump()
            if title == "ResolutionProposal":
                return resolution(DocumentAnalysis.model_validate(payload["observations"])).model_dump()
            if title == "DocumentValidation":
                return {"graph_sha256": payload["graph_sha256"], "checked_item_ids": payload["required_item_ids"],
                        "findings": [], "limitations": ["검토"]}
            return integration(DocumentAnalysis.model_validate(payload["graphs"][0])).model_dump()
    for stage in batch.PROMPTS:
        await batch.run_stage(prepared, stage, Runner(), concurrency=2)
    assert calls == [("ItemInventory", None), ("DocumentValidation", None), ("ItemExtraction", "item_000"), ("ItemExtraction", "shared"),
                     ("ResolutionProposal", None), ("DocumentValidation", None), ("Integration", None)]
    before = len(calls)
    for stage in batch.PROMPTS:
        await batch.run_stage(prepared, stage, Runner())
    assert len(calls) == before
    batch.finalize(prepared, tmp_path / "result")


@pytest.mark.asyncio
async def test_timeout_records_stage_failure_and_never_fabricates_output(prepared):
    class Runner:
        async def generate(self, *args):
            raise TimeoutError("fixture timeout")
    with pytest.raises(RuntimeError, match="identify failed: TimeoutError"):
        await batch.run_stage(prepared, "identify", Runner())
    failures = list((prepared / "failures").glob("*.json"))
    assert len(failures) == 1 and batch.load(failures[0])["manual_fallback"] is False
    assert not (prepared / "identify/server.json").exists()


def test_relation_kinds_keep_bundle_membership_separate_from_internal_structure(prepared):
    graph = populate(prepared)
    bundle = graph.entities[0].model_copy(deep=True)
    bundle.entity_id, bundle.roles = "system_bundle", ["delivery_group"]
    graph.entities.append(bundle)
    graph.relations = [{"relation_id": "server_in_bundle", "subject_id": "server_a",
        "predicate": "delivery_member_of", "object_id": "system_bundle", "basis": "interpreted",
        "reason": "발주 묶음", "evidence": evidence(batch.documents(prepared)[0], 0)},
        {"relation_id": "cpu_in_server", "subject_id": "item_000_cpu", "predicate": "physical_part_of",
         "object_id": "server_a", "basis": "interpreted", "reason": "서버 구성",
         "evidence": evidence(batch.documents(prepared)[0], 1)}]
    graph = DocumentAnalysis.model_validate(graph.model_dump(warnings=False))
    validate_analysis(graph, batch.documents(prepared)[0])
    graph.relations[0].object_id = "server_a"
    with pytest.raises(ValueError, match="self relation|requires a bundle"):
        validate_analysis(graph, batch.documents(prepared)[0])


def test_identity_and_condition_cycles_are_rejected_without_changing_observations(prepared):
    graph = populate(prepared)
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import ConditionGroup
    graph.groups = [ConditionGroup(group_id="choice", logic="or",
        members=["item_000_cores", "item_000_capacity"], evidence=graph.requirements[0].evidence)]
    validate_analysis(graph, batch.documents(prepared)[0])
    graph.groups[0].members = ["choice", "item_000_capacity"]
    with pytest.raises(ValueError, match="cycle"):
        validate_analysis(graph, batch.documents(prepared)[0])
    graph.groups = []
    graph.identities = [IdentityLink(alias_id="item_000_cpu", canonical_id="item_000_ram", reason="순환 1",
        evidence=graph.requirements[0].evidence), IdentityLink(alias_id="item_000_ram", canonical_id="item_000_cpu",
        reason="순환 2", evidence=graph.requirements[1].evidence)]
    with pytest.raises(ValueError, match="cycle"):
        validate_analysis(graph, batch.documents(prepared)[0])


def test_partial_coverage_cannot_become_complete_when_regions_overlap(prepared):
    found = inventory(prepared)
    found.shared_node_ids.append("n00001")
    batch.accept(prepared, "identify", found.model_dump(), "server")
    accept_structure_review(prepared)
    tasks = batch.context(prepared, "extract", "server")["tasks"]
    parts = [extraction(prepared, task) for task in tasks]
    shared = parts[-1]
    shared.coverage[0].status = "partial"
    graph = batch.assemble(found, parts, batch.documents(prepared)[0])
    row = next(c for c in graph.coverage if c.node_id == "n00001")
    assert row.status == "partial" and row.requirement_ids == ["item_000_cores"]


def test_resolution_can_add_cross_task_logic_without_rewriting_existing_conditions(prepared):
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import ConditionGroup
    graph = populate(prepared)
    patch = resolution(graph)
    patch.cross_task_groups = [ConditionGroup(group_id="resolved_joint_condition", logic="and",
        members=["item_000_cores", "shared_warranty"],
        evidence=[*graph.requirements[0].evidence, *graph.requirements[-1].evidence])]
    resolved = apply_resolution(graph, patch)
    validate_resolved(graph, resolved)
    validate_analysis(resolved, batch.documents(prepared)[0])
    assert graph.groups == [] and len(resolved.groups) == 1


def test_repair_feedback_reports_all_raw_labels_and_relation_errors_together(prepared):
    graph = populate(prepared)
    graph.requirements[0].property_raw = "코어 수"
    graph.requirements[1].property_raw = "용량"
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import Relation
    graph.relations = [Relation(relation_id="wrong_membership", subject_id="item_000_cpu",
        predicate="delivery_member_of", object_id="server_a", basis="interpreted", reason="잘못된 구성 관계",
        evidence=graph.requirements[0].evidence)]
    with pytest.raises(ValueError) as error:
        validate_analysis(graph, batch.documents(prepared)[0])
    assert all(ref in str(error.value) for ref in
               ("item_000_cores/property_raw", "item_000_capacity/property_raw", "wrong_membership"))


def test_validation_receives_prior_task_and_repair_history_and_pins_it(prepared):
    populate(prepared)
    found = inventory(prepared).model_dump()
    found["entries"][0]["entity"]["roles"] = ["physical_component"]
    batch.save(prepared / "inference/identify/server.json", found)
    batch.save(prepared / "inference/identify/server_repair.json", inventory(prepared).model_dump())
    payload = batch.context(prepared, "validate", "server")
    history = payload["processing_history"]
    assert history["identify"]["repair_response_recorded"] is True
    assert "roles" in history["identify"]["initial_response_recheck_error"]
    assert history["extract_tasks"][0]["source_node_ids"] == ["n00000", "n00001", "n00002"]
    with pytest.raises(ValueError, match="stale dependencies"):
        batch.accepted(prepared, "validate", "server")


def test_integration_has_exact_mapping_targets_and_reports_extraneous_logic_group(prepared):
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import Mapping
    graph = populate(prepared, with_group=True)
    payload = batch.context(prepared, "integrate")
    assert "server/item_000_logic" not in payload["required_observation_refs"]
    assert "server/item_000_cores" in payload["required_observation_refs"]
    assert payload["graphs"][0]["groups"][0]["group_id"] == "item_000_logic"
    draft = integration(graph)
    draft.mappings.append(Mapping(observation_ref="server/item_000_logic", decision="exclude", concept_id=None, reason="잘못된 추가"))
    with pytest.raises(ValueError, match="extra=.*server/item_000_logic"):
        validate_integration(draft, [graph])


def test_recursive_composition_keeps_descendant_regions_and_attribute_subjects():
    from teoria_pipelines.domains.public_procurement.specification_intelligence.document_evidence import build_document_evidence
    labels = ["분석시험장치", "주행성능 측정장치", "모션캡처 시스템", "카메라"]
    doc = build_document_evidence({"success": True, "blocks": [{"type": "paragraph", "text": label} for label in labels]},
        document_id="system", parse_run_id="fixture", native_sha256="b" * 64)
    rows = []
    for index, label in enumerate(labels):
        rows.append({"entity": {"entity_id": f"part_{index}", "label_raw": label, "meaning": label,
            "roles": ["component"] if index else ["delivery_target"],
            "owner_item_id": "part_0" if index else None, "evidence": evidence(doc, index)},
            "category": "component" if index else "delivery_item", "status": "supported",
            "parent": {"parent_id": f"part_{index-1}", "predicate": "component_of", "basis": "explicit",
                       "reason": "구성 근거", "evidence": evidence(doc, index)} if index else None,
            "node_ids": [doc.nodes[index].node_id], "reason": "구성 근거"})
    found = ItemInventory(document_id="system", native_sha256=doc.native_sha256, purchase_summary="통합 분석시험장치 구매",
        scope_evidence=evidence(doc, 0), entries=rows, shared_node_ids=[], unresolved_node_ids=[], issues=[])
    validate_inventory(found, doc)
    tasks = batch.extraction_tasks(found)
    assert len(tasks) == 1 and tasks[0]["source_node_ids"] == [n.node_id for n in doc.nodes]
    assert [(r.subject_id, r.object_id) for r in batch.structure_relations(found)] == [
        ("part_1", "part_0"), ("part_2", "part_1"), ("part_3", "part_2")]
    found.entries[-1].parent.parent_id = "part_3"
    with pytest.raises(ValueError, match="cycle"):
        validate_inventory(found, doc)


def test_structure_review_blocks_attributes_for_flattened_integrated_system(prepared):
    batch.accept(prepared, "identify", inventory(prepared).model_dump(), "server")
    accept_structure_review(prepared, [{"item_id": "entity/server_a", "category": "item_split",
        "severity": "error", "description": "통합 구성품을 독립 품목으로 오인"}])
    with pytest.raises(ValueError, match="structure errors block"):
        batch.context(prepared, "extract", "server")


def test_inventory_schema_rejects_contextual_roles_and_document_headings(prepared):
    from pydantic import ValidationError
    raw = inventory(prepared).model_dump()
    raw["entries"][0]["entity"]["roles"].append("specification_subject")
    with pytest.raises(ValidationError):
        ItemInventory.model_validate(raw)
    raw["entries"][0]["entity"]["roles"] = ["document_group"]
    with pytest.raises(ValidationError):
        ItemInventory.model_validate(raw)


def test_resolution_cannot_erase_reviewed_parent_link(prepared):
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import Relation
    graph = populate(prepared)
    graph.relations.append(Relation(relation_id="structure_cpu", subject_id="item_000_cpu", predicate="component_of",
        object_id="server_a", basis="interpreted", reason="서버 CPU 구성", evidence=graph.entities[1].evidence))
    proposal = resolution(graph)
    proposal.relations = []
    with pytest.raises(ValueError, match="reviewed composition"):
        validate_resolved(graph, apply_resolution(graph, proposal))


def test_bundle_does_not_replace_nearest_delivery_owner(prepared):
    found = inventory(prepared)
    doc = batch.documents(prepared)[0]
    root = found.entries[0]
    bundle = root.model_copy(deep=True)
    bundle.category, bundle.entity.roles = "bundle", ["delivery_group"]
    bundle.entity.entity_id = "package"
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import ParentLink
    root.parent = ParentLink(parent_id="package", predicate="delivery_member_of", basis="explicit",
                             evidence=evidence(doc, 0), reason="묶음 납품")
    cpu = root.model_copy(deep=True)
    cpu.category, cpu.entity.roles = "component", ["component"]
    cpu.entity.entity_id, cpu.entity.label_raw, cpu.entity.owner_item_id = "cpu", "CPU", "server_a"
    cpu.entity.evidence = [type(root.entity.evidence[0]).model_validate(evidence(doc, 1)[0])]
    cpu.node_ids = [doc.nodes[1].node_id]
    cpu.parent = ParentLink(parent_id="server_a", predicate="component_of", basis="explicit",
                            evidence=evidence(doc, 1), reason="서버 CPU 구성")
    found.entries.extend([bundle, cpu])
    validate_inventory(found, doc)


def test_uncertain_component_owner_stays_unknown_and_service_can_target_existing_asset(prepared):
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import ParentLink
    found = inventory(prepared)
    doc = batch.documents(prepared)[0]
    root = found.entries[0]
    cpu = root.model_copy(deep=True)
    cpu.category, cpu.entity.roles, cpu.status = "component", ["component"], "candidate"
    cpu.entity.entity_id, cpu.entity.label_raw = "cpu", "CPU"
    cpu.entity.evidence = [type(root.entity.evidence[0]).model_validate(evidence(doc, 1)[0])]
    cpu.node_ids = [doc.nodes[1].node_id]
    cpu.parent = ParentLink(parent_id="server_a", predicate="component_of", basis="ambiguous",
                            evidence=evidence(doc, 1), reason="소속 불명")
    existing = root.model_copy(deep=True)
    existing.category, existing.entity.roles, existing.entity.entity_id = "existing", ["existing"], "existing_server"
    service = root.model_copy(deep=True)
    service.category, service.entity.roles, service.entity.entity_id = "service", ["service"], "repair"
    service.entity.label_raw, service.entity.owner_item_id = "보증", "server_a"
    service.entity.evidence = [type(root.entity.evidence[0]).model_validate(evidence(doc, 3)[0])]
    service.node_ids = [doc.nodes[3].node_id]
    service.parent = ParentLink(parent_id="existing_server", predicate="service_for", basis="explicit",
                                evidence=evidence(doc, 3), reason="기보유 장비 대상 서비스")
    found.entries.extend([cpu, existing, service])
    validate_inventory(found, doc)
    assert cpu.entity.owner_item_id is None


def test_revision_feedback_is_frozen_and_separate_from_source(prepared, tmp_path):
    request = batch.verify(prepared)
    request.structure_feedback = {"server": [batch.Finding(item_id="entity/server_a", category="item_missing",
        severity="error", description="이전 모델의 누락 지적이며 원문 대조가 필요함")]}
    request = batch.BatchInput.model_validate(request.model_dump())
    revised = tmp_path / "revised"
    batch.prepare(request, revised)
    payload = batch.context(revised, "identify", "server")
    assert payload["structure_feedback"][0]["category"] == "item_missing"
    assert payload["document"] == batch.context(prepared, "identify", "server")["document"]
    raw = batch.load(revised / "manifest.json")
    raw["structure_feedback"]["server"][0]["description"] = "변조된 검토"
    (revised / "manifest.json").write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="frozen batch changed"):
        batch.verify(revised)


def test_item_extraction_receives_quantity_unit_from_related_table_header(prepared, tmp_path):
    request = batch.verify(prepared)
    entry = request.documents[0]
    source = tmp_path / "table_source.txt"
    source.write_text("품목 | 개수(식)\n서버 | 8")
    native = tmp_path / "table_native.json"
    native.write_text(json.dumps({"success": True, "blocks": [{"type": "table", "table": {"cells": [
        [{"text": "품목"}, {"text": "개수(식)"}], [{"text": "서버"}, {"text": "8"}]]}}]}))
    entry = entry.model_copy(update={"source_path": source, "source_sha256": batch.digest(source),
                                    "native_path": native, "native_sha256": batch.digest(native)})
    root = tmp_path / "table_batch"
    batch.prepare(batch.BatchInput(batch_id="table_fixture", documents=[entry]), root)
    doc = batch.documents(root)[0]
    refs = {n.text: n.node_id for n in doc.nodes if n.text}
    found = ItemInventory(document_id="server", native_sha256=doc.native_sha256,
        purchase_summary="서버 구매", scope_evidence=[{"document_id": "server", "node_id": refs["서버"], "quote": "서버"}],
        entries=[{"category": "delivery_item", "parent": None, "status": "supported", "reason": "공급 행",
            "node_ids": [refs["서버"], refs["8"]], "entity": {"entity_id": "server_a", "label_raw": "서버",
            "meaning": "납품 서버", "roles": ["delivery_target"], "owner_item_id": None,
            "evidence": [{"document_id": "server", "node_id": refs["서버"], "quote": "서버"}]}}],
        shared_node_ids=[refs["품목"], refs["개수(식)"]], unresolved_node_ids=[], issues=[])
    batch.accept(root, "identify", found.model_dump(), "server")
    accept_structure_review(root)
    payload = batch.extraction_context(root, "server", "item_000")
    assert refs["개수(식)"] in payload["supporting_node_ids"]
    assert refs["개수(식)"] in payload["source_node_ids"]
    assert any(n["text"] == "개수(식)" for n in payload["document"]["nodes"])
    assert batch.inventory(root, "server").entries[0].node_ids == [refs["서버"], refs["8"]]


def test_subtree_partition_keeps_sibling_entity_scopes_disjoint(prepared):
    found = inventory(prepared)
    doc = batch.documents(prepared)[0]
    root = found.entries[0]
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import ParentLink
    for key, label, index, parent in [("cpu", "CPU", 1, "server_a"), ("cpu_detail", "CPU", 1, "cpu"),
                                      ("ram", "RAM", 2, "server_a")]:
        row = root.model_copy(deep=True)
        row.category, row.entity.roles = "component", ["component"]
        row.entity.entity_id, row.entity.label_raw, row.entity.owner_item_id = key, label, "server_a"
        row.entity.evidence = [type(root.entity.evidence[0]).model_validate(evidence(doc, index)[0])]
        row.node_ids = [doc.nodes[index].node_id]
        row.parent = ParentLink(parent_id=parent, predicate="component_of", basis="interpreted",
                                evidence=evidence(doc, index), reason="구성 요구")
        found.entries.append(row)
    validate_inventory(found, doc)
    tasks = batch.partition_composition_tasks(found, batch.extraction_tasks(found))
    branch = next(t for t in tasks if t.get("branch_root_id") == "cpu")
    remainder = next(t for t in tasks if t["task_id"] == "item_000")
    assert set(branch["entity_scope_ids"]) == {"cpu", "cpu_detail"}
    assert set(remainder["entity_scope_ids"]) == {"server_a", "ram"}
    assert not set(branch["entity_scope_ids"]) & set(remainder["entity_scope_ids"])
    assert {ref for t in tasks for ref in t["source_node_ids"]} == batch.text_node_ids(doc)


@pytest.mark.asyncio
async def test_parallel_subtree_generation_is_bounded_and_keeps_result_order(prepared):
    batch.accept(prepared, "identify", inventory(prepared).model_dump(), "server")
    accept_structure_review(prepared)
    active = peak = 0
    both_started = asyncio.Event()
    class Runner:
        async def generate(self, instruction, payload, output):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                both_started.set()
            try:
                await asyncio.wait_for(both_started.wait(), 2)
                return extraction(prepared, payload).model_dump()
            finally:
                active -= 1
    await batch.run_stage(prepared, "extract", Runner(), concurrency=2)
    assert peak == 2
    graph = batch.DocumentAnalysis.model_validate(batch.accepted(prepared, "extract", "server"))
    assert graph.requirements[0].requirement_id == "item_000_cores"
    assert graph.requirements[-1].requirement_id == "shared_warranty"


def test_attribute_cannot_move_to_sibling_subtree_even_with_same_delivery_owner(prepared):
    from teoria_pipelines.domains.public_procurement.specification_intelligence.semantic_ir import InventoryEntry
    batch.accept(prepared, "identify", inventory(prepared).model_dump(), "server")
    accept_structure_review(prepared)
    payload = batch.extraction_context(prepared, "server", "item_000")
    part = extraction(prepared, payload)
    found = ItemInventory.model_validate(payload["inventory"])
    for entity in part.entities:
        raw = entity.model_dump()
        raw["roles"] = ["component"]
        found.entries.append(InventoryEntry(entity=raw, category="component", status="supported",
            parent={"parent_id": "server_a", "predicate": "component_of", "basis": "interpreted",
                    "evidence": raw["evidence"], "reason": "서버 구성"},
            node_ids=[e.node_id for e in entity.evidence], reason="구성 규격"))
    payload["inventory"] = found.model_dump()
    payload["entity_scope_ids"] = ["item_000_cpu"]
    part.entities = []
    with pytest.raises(ValueError, match="outside assigned component subtree"):
        batch.validate_extraction(part, payload, batch.documents(prepared)[0])
