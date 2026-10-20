"""Build reviewable property proposals from development observations only."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from .codex_runner import CodexRunner
from .search_evaluation import RequirementAnswer, save_json
from .search_evaluation import value_in_quote
from .document_evidence import comparable_text


def validate_mapping(proposal: dict, source_groups: list[dict]) -> None:
    expected = {g["group_id"] for g in source_groups}
    assigned = [g for p in proposal["properties"] for g in p["source_groups"]]
    assigned.extend(h["group_id"] for h in proposal["held_groups"])
    if set(assigned) != expected or len(assigned) != len(set(assigned)):
        raise ValueError("dictionary mapping must cover each development group exactly once")
    identifiers = [p["property_id"] for p in proposal["properties"]]
    if len(set(identifiers)) != len(identifiers) or any(not re.fullmatch(r"[a-z][a-z0-9_]*", p) for p in identifiers):
        raise ValueError("unique snake_case property IDs required")
    for property in proposal["properties"]:
        if not property["source_groups"] or any(not isinstance(property.get(k), str) or not property[k].strip()
                                               for k in ("definition", "dimension")):
            raise ValueError("each property requires a definition, dimension and observed source groups")
        if not isinstance(property.get("aliases"), list) or any(not isinstance(a, str) for a in property["aliases"]):
            raise ValueError("property aliases must be a list of strings")
    if any(not isinstance(h.get("reason"), str) or not h["reason"].strip() for h in proposal["held_groups"]):
        raise ValueError("held groups require a reason")


def canonicalize_facts(raw: dict, draft: dict) -> tuple[dict, list[dict]]:
    """Map observed names to proposed stable IDs; preserve values, scope and unknowns."""
    groups = {g["group_id"]: g for g in draft["observation_groups"]}
    exact, aliases = defaultdict(set), defaultdict(set)
    for property in draft["properties"]:
        identity = property["property_id"]
        for alias in [identity, *property["aliases"]]:
            aliases[alias.casefold()].add(identity)
        for group_id in property["source_groups"]:
            group = groups[group_id]
            exact[(group["attribute"], group["unit"], group["configuration"], group["aggregation"])].add(identity)
            aliases[group["attribute"].casefold()].add(identity)
    normalized, mappings = [], []
    for index, fact in enumerate(raw.get("facts", [])):
        if not isinstance(fact, dict) or not isinstance(fact.get("attribute"), str):
            normalized.append(fact)
            mappings.append({"index": index, "status": "invalid_fact"})
            continue
        key = tuple(fact.get(k) for k in ("attribute", "unit", "configuration", "aggregation"))
        matches = exact.get(key) or aliases.get(fact["attribute"].casefold(), set())
        if len(matches) == 1:
            identity = next(iter(matches))
            normalized.append({**fact, "attribute": identity})
            mappings.append({"index": index, "raw_attribute": fact["attribute"], "property_id": identity, "status": "proposed_mapping"})
        else:
            normalized.append(dict(fact))
            mappings.append({"index": index, "raw_attribute": fact["attribute"], "status": "ambiguous" if matches else "unmapped"})
    return {"facts": normalized}, mappings


async def build_dictionary(root: Path, name: str, runner: CodexRunner) -> dict:
    groups = defaultdict(list)
    rejected = []
    paths = ((root / "source_review/development").glob("*/facts_for_dictionary.json") if name == "source_review"
             else (root / "predictions" / name / "development").glob("*/facts.json"))
    for path in sorted(paths):
        source = json.loads((root / "sources/development" / f"{path.parent.name}.json").read_text())["text"]
        for index, raw in enumerate(json.loads(path.read_text()).get("facts", [])):
            try:
                fact = RequirementAnswer.model_validate(raw)
            except ValueError:
                rejected.append({"document_id": path.parent.name, "index": index, "reason": "invalid_fact_contract"})
                continue
            if comparable_text(fact.quote) not in comparable_text(source) or not value_in_quote(fact.value, fact.quote):
                rejected.append({"document_id": path.parent.name, "index": index, "reason": "ungrounded_fact"})
                continue
            key = (fact.attribute, fact.unit, fact.configuration, fact.aggregation)
            groups[key].append({"document_id": path.parent.name, "index": index, **fact.model_dump()})
    source_groups = [{"group_id": f"g{i:04}", "attribute": key[0], "unit": key[1],
                      "configuration": key[2], "aggregation": key[3], "occurrences": len(values),
                      "documents": sorted({v["document_id"] for v in values}), "examples": values}
                     for i, (key, values) in enumerate(sorted(groups.items()))]
    if not source_groups:
        raise ValueError("no development observations for dictionary proposals")
    proposal = await runner.generate(
        "개발 문서 관찰만으로 검토할 표준 속성 사전 후보를 만들어라. 표현이 달라도 같은 의미이면 "
        "합치되 설치/지원 상태, 모듈당/전체 범위를 속성명에 붙여 늘리지 말고 관찰 한정자로 보존한다. "
        "기본/부스트, 점유높이/수용높이 등 측정 의미가 다르면 합치지 않는다. 의미를 확정할 수 없는 "
        "그룹은 held_groups에 둔다. 속성은 {property_id:snake_case,definition,dimension,aliases:[str],"
        "source_groups:[group_id]} 형식이다. 모든 입력 group_id를 properties 또는 held_groups에 "
        "정확히 한 번 배정하라. held_groups는 {group_id,reason} 목록이다. Return JSON "
        "{properties:[...],held_groups:[...]}. 사람 승인이나 게시 상태를 만들지 말라.",
        {"source_groups": source_groups}, root / "dictionary" / "proposal.json",
    )
    proposal = await runner.generate(
        "독립 검토자로 속성 사전 후보를 개발 관찰 근거와 대조해 수정하라. 같은 용량 단위라는 "
        "이유로 서로 다른 측정 의미를 합치지 말고, 표현·설치/지원·전체/개별 차이만으로 "
        "속성을 늘리지 말라. 기본/부스트 클럭은 구별한다. 각 속성에 property_id,definition,"
        "dimension,aliases,source_groups가 필요하다. 모호한 그룹은 held_groups에 group_id와 reason으로 "
        "보류한다. 모든 group_id를 properties 또는 held_groups에 정확히 한 번 배정하라. "
        "Return JSON {properties:[...],held_groups:[...]}. 승인된 의미로 취급하지 말라.",
        {"source_groups": source_groups, "proposal": proposal}, root / "dictionary" / "review.json",
    )
    try:
        validate_mapping(proposal, source_groups)
    except (KeyError, TypeError, ValueError) as error:
        proposal = await runner.generate(
            "속성 사전 후보의 구조 오류를 고쳐라. 모든 group_id를 properties 또는 held_groups에 "
            "정확히 한번 배정하고 unique snake_case property_id, definition, dimension, aliases, "
            "source_groups를 보존하라. 보류 항목은 group_id, reason 필수. Return JSON "
            "{properties:[...],held_groups:[...]}. 원문 없는 의미를 만들지 말라.",
            {"source_groups": source_groups, "proposal": proposal, "validation_error": str(error)},
            root / "dictionary" / "mapping_repair.json",
        )
        validate_mapping(proposal, source_groups)
    result = {"status": "suggestion; unapproved", "source_subset": "development", "prediction_variant": name,
              "observation_groups": source_groups, "invalid_observations": rejected,
              "properties": proposal["properties"], "held_groups": proposal["held_groups"],
              "scope": "property proposals; not a complete ontology; not used as labels or published metadata"}
    save_json(root / "dictionary" / "draft.json", result)
    return result
