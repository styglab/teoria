"""Runtime adapters for server comparison and checksum-verified original evidence."""

import hashlib
import json
from urllib.parse import urlsplit

from pydantic_core import to_jsonable_python

from teoria.features.goods_querying.comparison import compare_requirements
from teoria.features.runtime.capability.contracts import (
    CapabilityExecutionError,
    CapabilityResult,
)
from teoria.features.runtime.capability.handlers import CapabilityHandlers
from teoria.features.specification_processing.parsing.document_evidence import (
    source_quote,
)
from teoria.features.specification_processing.storage.artifact_store import read_uri


async def _requirements(runner, catalog, snapshot, capability_id):
    rows = []
    for page in range(1, 11):
        result = await runner.run(
            catalog,
            "get_server_requirements",
            {"snapshot_id": snapshot, "page": page, "page_size": 100},
        )
        rows.extend(obj.properties for obj in result.objects)
        if result.pagination is None or page >= result.pagination["total_pages"]:
            return rows
    raise CapabilityExecutionError(
        "observation_limit_exceeded",
        "snapshot exceeds 1000 observations",
        capability_id=capability_id,
    )


async def compare(runner, catalog, capability_id, inputs):
    left = await _requirements(
        runner, catalog, inputs["left_snapshot_id"], capability_id
    )
    right = await _requirements(
        runner, catalog, inputs["right_snapshot_id"], capability_id
    )
    outcome = compare_requirements(left, right)
    outcome["left_snapshot_id"] = inputs["left_snapshot_id"]
    outcome["right_snapshot_id"] = inputs["right_snapshot_id"]
    outcome["left_found"] = bool(left)
    outcome["right_found"] = bool(right)
    return CapabilityResult(
        capability_id=capability_id, outcome=to_jsonable_python(outcome)
    )


async def evidence(runner, catalog, capability_id, inputs):
    rows = await _requirements(runner, catalog, inputs["snapshot_id"], capability_id)
    rows = [r for r in rows if r["observation_id"] == inputs["observation_id"]]
    if not rows:
        return CapabilityResult(
            capability_id=capability_id, outcome={"status": "not_found", "evidence": []}
        )
    row = rows[0]
    try:
        if urlsplit(row["extraction_uri"]).scheme not in {"file", "s3"}:
            raise ValueError("evidence must refer to controlled artifact storage")
        raw = await read_uri(row["extraction_uri"])
        if hashlib.sha256(raw).hexdigest() != row["extraction_sha256"]:
            raise ValueError("extraction artifact checksum mismatch")
        corpus = json.loads(raw)
        doc = next(
            d for d in corpus["documents"] if d["document_id"] == row["document_id"]
        )
        if doc["source"]["sha256"] != row["source_sha256"]:
            raise ValueError("source checksum mismatch")
        document_id, attribute_id = row["evidence_ref"].split(":", 1)
        if document_id != doc["document_id"]:
            raise ValueError("evidence belongs to another document")
        attribute = next(a for a in doc["attributes"] if a["id"] == attribute_id)
        nodes = {n["node_id"]: n for n in doc["parsed_document"]["nodes"]}
        result = {
            "status": "verified",
            "observation": to_jsonable_python(row),
            "quote": source_quote(doc, attribute),
            "nodes": [nodes[node] for node in row["evidence_node_ids"]],
            "source_sha256": row["source_sha256"],
            "extraction_sha256": row["extraction_sha256"],
        }
    except (ValueError, KeyError, StopIteration, OSError) as exc:
        raise CapabilityExecutionError(
            "evidence_verification_failed",
            "original evidence could not be verified",
            capability_id=capability_id,
        ) from exc
    return CapabilityResult(capability_id=capability_id, outcome=result)


def register_server_capabilities(handlers: CapabilityHandlers) -> None:
    handlers.register_processor("server_specifications.compare", compare)
    handlers.register_processor("server_specifications.evidence", evidence)
