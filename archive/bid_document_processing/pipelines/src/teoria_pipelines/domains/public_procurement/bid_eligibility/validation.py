from __future__ import annotations

from teoria_pipelines.domains.public_procurement.bid_eligibility.normalization import _citation_text


def _validate_citations(result: dict, inputs: dict) -> None:
    blocks = {}
    for document in inputs["documents"]:
        for block in document["content"]["blocks"]:
            blocks[(document["document_id"], block["block_id"])] = (document, block)
    structured = {item["source_id"]: item for item in inputs["structured_requirements"]}
    for evidence in _iter_result_evidence(result):
        if evidence["source_type"] == "document":
            source = blocks.get((evidence["document_id"], evidence["block_id"]))
            if source is None:
                raise ValueError("invalid_document_evidence")
            document, block = source
            if (
                evidence["source_id"] != document["document_id"]
                or evidence["page"] != block.get("page")
                or evidence["section"] != block.get("section")
                or _citation_text(evidence["excerpt"]) not in _citation_text(block["text"])
            ):
                raise ValueError("invalid_document_evidence")
        else:
            record = structured.get(evidence["source_id"])
            if record is None or not _structured_excerpt_matches(evidence["excerpt"], record):
                raise ValueError("invalid_structured_evidence")


def _structured_excerpt_matches(excerpt: str, record: dict) -> bool:
    normalized = _citation_text(excerpt)
    values = [str(value) for key, value in record.items()
              if key != "source_hash" and value not in (None, "", [], {})]
    candidates = {*values, "/".join(values), " ".join(values)}
    candidates.update(f"{left}/{right}" for left in values for right in values if left != right)
    return any(normalized == _citation_text(candidate) for candidate in candidates)


def _iter_result_evidence(result: dict):
    for requirement in result["requirements"]:
        yield from requirement["evidence"]
        for proof in requirement.get("proof_requirements", []):
            yield from proof["evidence"]
    for finding in result.get("participation_findings", []):
        yield from finding["evidence"]


def _validate_participation_findings(result: dict) -> None:
    seen: set[tuple[str, str, str]] = set()
    for finding in result.get("participation_findings", []):
        if finding["category"] == "competition_risk_signal":
            if not str(finding.get("competitive_effect") or "").strip():
                raise ValueError("competition_risk_missing_effect")
        elif finding.get("competitive_effect") is not None:
            raise ValueError("non_competition_finding_has_competitive_effect")
        key = (finding["category"], finding["type"], finding["description"])
        if key in seen:
            raise ValueError("duplicate_participation_finding")
        seen.add(key)
