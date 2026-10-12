from __future__ import annotations

from teoria_pipelines.domains.public_procurement.bid_eligibility.normalization import (
    _assign_evidence,
    _citation_similarity,
    _citation_text,
    _ellipsis_fragments_match,
)
from teoria_pipelines.domains.public_procurement.bid_eligibility.validation import (
    _iter_result_evidence,
)


def _reconcile_original_text(result: dict) -> None:
    """Make original_text an exact substring of one retained Evidence excerpt."""
    for requirement in result["requirements"]:
        if any(
            requirement["original_text"] in evidence["excerpt"]
            for evidence in requirement["evidence"]
        ):
            continue
        requirement["original_text"] = min(
            (evidence["excerpt"] for evidence in requirement["evidence"]), key=len
        )


def _reconcile_proposition_spans(result: dict) -> None:
    """Anchor each atomic proposition inside its verbatim requirement citation."""
    for requirement in result["requirements"]:
        original = requirement["original_text"]
        proposition = str(requirement.get("proposition_text") or "").strip()
        if not proposition or proposition not in original:
            normalized = str((requirement.get("value") or {}).get("text") or "").strip()
            proposition = normalized if normalized and normalized in original else original
        start = original.index(proposition)
        requirement["proposition_text"] = proposition
        requirement["proposition_start"] = start
        requirement["proposition_end"] = start + len(proposition)


def _reconcile_document_citations(result: dict, inputs: dict) -> None:
    blocks: list[tuple[dict, dict]] = [
        (document, block)
        for document in inputs["documents"]
        for block in document["content"]["blocks"]
    ]
    by_id = {
        (document["document_id"], block["block_id"]): (document, block)
        for document, block in blocks
    }
    for evidence in _iter_result_evidence(result):
        if evidence["source_type"] != "document":
            continue
        excerpt = _citation_text(evidence["excerpt"])
        pointed = by_id.get((evidence["document_id"], evidence["block_id"]))
        if pointed and excerpt in _citation_text(pointed[1]["text"]):
            _assign_evidence(evidence, *pointed, evidence["excerpt"])
            continue
        exact = next(
            ((document, block) for document, block in blocks
             if excerpt and excerpt in _citation_text(block["text"])),
            None,
        )
        if exact:
            _assign_evidence(evidence, *exact, evidence["excerpt"])
            continue
        # A long citation may be abbreviated with an ellipsis. Accept that
        # abbreviation only when its substantial fragments occur verbatim and
        # in order in the cited block, then persist the actual source text.
        if pointed and _ellipsis_fragments_match(excerpt, pointed[1]["text"]):
            _assign_evidence(evidence, *pointed, pointed[1]["text"])
            continue
        if pointed and _citation_similarity(excerpt, pointed[1]["text"]) >= 0.58:
            _assign_evidence(evidence, *pointed, pointed[1]["text"])
            continue
        best: tuple[float, dict, dict] | None = None
        second_score = 0.0
        for document, block in blocks:
            score = _citation_similarity(excerpt, block["text"])
            if best is None or score > best[0]:
                second_score = best[0] if best else 0.0
                best = (score, document, block)
            elif score > second_score:
                second_score = score
        if best and best[0] >= 0.65 and (best[0] - second_score >= 0.08):
            _assign_evidence(evidence, best[1], best[2], best[2]["text"])

    structured = {item["source_id"]: item for item in inputs["structured_requirements"]}
    for evidence in _iter_result_evidence(result):
        if evidence["source_type"] != "structured_api":
            continue
        record = structured.get(evidence["source_id"])
        if record is None:
            continue
        canonical_excerpt = record.get("name")
        if canonical_excerpt:
            evidence.update({
                "document_id": None, "block_id": None, "page": None, "section": None,
                "excerpt": str(canonical_excerpt),
            })
