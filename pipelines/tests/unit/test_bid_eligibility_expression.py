from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

from teoria_pipelines.bid_eligibility_expression import (
    compile_eligibility_facts,
    validate_compiled_expression,
)


FIXTURE = Path(__file__).parents[1] / "fixtures/bid_eligibility_expression_cases.yaml"
FACT_SCHEMA = (Path(__file__).parents[3] / ".agents/skills/extract-bid-eligibility/references/"
               "eligibility-facts.schema.json")


def _requirement(requirement_id: str, placements: list[dict]) -> dict:
    return {
        "id": requirement_id, "type": "custom", "operator": "exists",
        "value": {"text": requirement_id, "number": None, "boolean": True,
                  "items": [], "attributes": []},
        "original_text": requirement_id, "holder_scope": "bidder",
        "reference_date_type": "bid_deadline", "mandatory": True,
        "assessment_stage": "bid_entry", "failure_effect": "cannot_bid",
        "comparison_mode": "structured", "proof_requirements": [],
        "review_status": "extracted", "confidence": 1.0,
        "evidence": [{"source_type": "document", "source_id": "doc",
                      "document_id": "doc", "block_id": "b1", "page": 1,
                      "section": None, "excerpt": requirement_id}],
        "logic": {"placements": placements},
    }


def _compact(node: dict) -> str:
    if node["operator"] == "leaf":
        return node["requirement_id"]
    return f"{node['operator']}({','.join(_compact(item) for item in node['conditions'])})"


@pytest.mark.parametrize("case", yaml.safe_load(FIXTURE.read_text())["cases"],
                         ids=lambda case: case["id"])
def test_golden_expression_cases(case: dict) -> None:
    facts = {
        "schema_version": "1.4.0",
        "requirements": [_requirement(key, value) for key, value in case["placements"].items()],
        "unresolved_candidates": [],
    }

    result = compile_eligibility_facts(facts)

    assert _compact(result["expression"]) == case["expected"]
    assert all("logic" not in item for item in result["requirements"])


def test_compiler_rejects_missing_logic() -> None:
    item = _requirement("r1", [])
    item.pop("logic")
    with pytest.raises(ValueError, match="requirement_logic_missing"):
        compile_eligibility_facts({"requirements": [item], "unresolved_candidates": []})


def test_unconditional_common_placement_subsumes_mode_duplicate() -> None:
    item = _requirement("r1", [
        {"scope": "common", "alternative_group": None, "alternative_branch": None},
        {"scope": "single", "alternative_group": None, "alternative_branch": None},
    ])

    result = compile_eligibility_facts({"requirements": [item], "unresolved_candidates": []})

    assert _compact(result["expression"]) == "r1"


def test_allows_shared_requirement_across_distinct_alternative_branches() -> None:
    shared = _requirement("r1", [
        {"scope": "common", "alternative_group": "g1", "alternative_branch": "a"},
        {"scope": "common", "alternative_group": "g1", "alternative_branch": "b"},
    ])
    first = _requirement("r2", [
        {"scope": "common", "alternative_group": "g1", "alternative_branch": "a"},
    ])
    second = _requirement("r3", [
        {"scope": "common", "alternative_group": "g1", "alternative_branch": "b"},
    ])

    result = compile_eligibility_facts({"requirements": [shared, first, second],
                                        "unresolved_candidates": []})

    assert _compact(result["expression"]) == "any(all(r1,r2),all(r1,r3))"


def test_rejects_unconditional_requirement_also_used_as_alternative() -> None:
    item = _requirement("r1", [
        {"scope": "common", "alternative_group": None, "alternative_branch": None},
        {"scope": "common", "alternative_group": "g1", "alternative_branch": "a"},
    ])

    with pytest.raises(ValueError, match="unconditional_requirement_has_alternative_placement"):
        compile_eligibility_facts({"requirements": [item], "unresolved_candidates": []})


def test_compiler_preserves_stage_and_separate_proof_requirements() -> None:
    item = _requirement("r1", [
        {"scope": "common", "alternative_group": None, "alternative_branch": None},
    ])
    item.update({
        "assessment_stage": "qualification_review",
        "failure_effect": "qualification_rejection",
        "comparison_mode": "document_evidence",
        "proof_requirements": [{
            "id": "p1", "document_type": "장비보유현황증명서",
            "submission_stage": "qualification_review", "deadline_text": "적격심사 시",
            "mandatory": True, "review_status": "extracted",
            "evidence": item["evidence"],
        }],
    })

    result = compile_eligibility_facts({"requirements": [item], "unresolved_candidates": []})

    assert result["schema_version"] == "1.3.0"
    assert result["requirements"][0]["assessment_stage"] == "qualification_review"
    assert result["requirements"][0]["proof_requirements"][0]["document_type"] == "장비보유현황증명서"


def test_fact_schema_is_valid() -> None:
    import json

    Draft202012Validator.check_schema(json.loads(FACT_SCHEMA.read_text()))


def test_fact_schema_rejects_unknown_requirement_vocabulary() -> None:
    import json

    item = _requirement("r1", [
        {"scope": "common", "alternative_group": None, "alternative_branch": None},
    ])
    item["type"] = "invented_type"
    facts = {"schema_version": "1.4.0", "requirements": [item],
             "unresolved_candidates": []}

    errors = list(Draft202012Validator(json.loads(FACT_SCHEMA.read_text())).iter_errors(facts))

    assert errors


def test_invariants_reject_redundant_leaf_across_conjunctive_siblings() -> None:
    result = {
        "requirements": [{"id": "r1"}, {"id": "r2"}],
        "expression": {"operator": "all", "requirement_id": None, "conditions": [
            {"operator": "leaf", "requirement_id": "r1", "conditions": []},
            {"operator": "any", "requirement_id": None, "conditions": [
                {"operator": "leaf", "requirement_id": "r1", "conditions": []},
                {"operator": "leaf", "requirement_id": "r2", "conditions": []},
            ]},
        ]},
    }
    with pytest.raises(ValueError, match="redundant_conjunctive_requirement"):
        validate_compiled_expression(result)
