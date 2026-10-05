from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any


_TOKEN_RE = re.compile(r"[A-Za-z0-9가-힣]+")


def normalize(value: str | None) -> str:
    if not value:
        return ""
    return "".join(token.lower() for token in _TOKEN_RE.findall(value))


def tokens(value: str | None) -> set[str]:
    if not value:
        return set()
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return {part.lower() for part in _TOKEN_RE.findall(snake)}


@dataclass(frozen=True)
class RankedCandidate:
    concept_id: str
    concept_kind: str
    stable_key: str
    score: float
    evidence: list[dict[str, Any]]


def rank_binding_candidates(
    column: dict[str, Any],
    concepts: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> list[RankedCandidate]:
    column_name = str(column.get("name") or "")
    column_description = str(column.get("description") or "")
    column_tokens = tokens(column_name) | tokens(column_description)
    ranked: list[RankedCandidate] = []
    for concept in concepts:
        if concept["concept_kind"] != "property":
            continue
        concept_name = str(concept.get("name") or concept["stable_key"].rsplit(".", 1)[-1])
        concept_description = str(concept.get("description") or "")
        name_score = SequenceMatcher(None, normalize(column_name), normalize(concept_name)).ratio()
        overlap = column_tokens & (tokens(concept_name) | tokens(concept_description))
        token_score = len(overlap) / max(len(column_tokens), 1)
        datatype_score = _datatype_compatibility(column.get("dataType"), concept.get("value_type"))
        glossary_score = _glossary_match(column.get("tags") or [], concept_name)
        score = 0.45 * name_score + 0.20 * token_score + 0.20 * datatype_score + 0.15 * glossary_score
        evidence = [
            {"type": "normalized_name_similarity", "score": round(name_score, 6)},
            {"type": "token_overlap", "score": round(token_score, 6), "tokens": sorted(overlap)},
            {"type": "datatype_compatibility", "score": round(datatype_score, 6)},
        ]
        if glossary_score:
            evidence.append({"type": "glossary_match", "score": glossary_score})
        ranked.append(RankedCandidate(
            concept_id=str(concept["concept_id"]),
            concept_kind=concept["concept_kind"],
            stable_key=concept["stable_key"],
            score=round(score, 6),
            evidence=evidence,
        ))
    return sorted(ranked, key=lambda item: (-item.score, item.stable_key))[:limit]


def _datatype_compatibility(source: Any, target: Any) -> float:
    source_value = normalize(str(source or ""))
    target_value = normalize(str(target or ""))
    if not source_value or not target_value:
        return 0.5
    groups = [
        {"int", "integer", "bigint", "smallint", "decimal", "numeric", "float", "double", "number"},
        {"string", "text", "varchar", "char"},
        {"date", "datetime", "timestamp", "timestamptz"},
        {"bool", "boolean"},
    ]
    return 1.0 if any(source_value in group and target_value in group for group in groups) else 0.0


def _glossary_match(tags: list[dict[str, Any]], concept_name: str) -> float:
    expected = normalize(concept_name)
    for tag in tags:
        label = tag.get("tagFQN") or tag.get("name") or ""
        if normalize(str(label).rsplit(".", 1)[-1]) == expected:
            return 1.0
    return 0.0
