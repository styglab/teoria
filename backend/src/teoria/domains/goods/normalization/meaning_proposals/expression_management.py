"""Collect grounded review proposals and dispatch historical v1 compatibility explicitly."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from teoria.domains.goods.authoring_client import GoodsAuthoringClient
from teoria.domains.goods.data_processing.storage.artifact_store import (
    artifact_store,
    read_uri,
)
from teoria.domains.goods.data_processing.storage.run_repository import (
    SpecificationRepository,
)
from teoria.domains.goods.expression_links.snapshot_contracts import (
    approved_dictionary_snapshot,
    parse_dictionary_snapshot,
    resolve_snapshot,
)
from teoria.domains.goods.normalization.meaning_proposals.expression_candidates import (
    register_corpus,
)
from teoria.domains.goods.normalization.meaning_proposals.expression_context import (
    observation_context,
)


async def collect_ontology_candidates(
    baseline, corpus, candidates, decisions, *, artifact_root, prefix
):
    snapshot = approved_dictionary_snapshot(baseline)
    by_key = {c.candidate_key: c for c in candidates}
    contexts = {
        c["candidate"]["candidate_key"]: c
        for c in observation_context(corpus, candidates)
    }
    codes = {
        d["document_id"]: d.get("classification_code")
        or corpus.get("classification_code")
        for d in corpus["documents"]
    }
    unresolved = []
    for decision in decisions:
        candidate = by_key[decision["candidate_key"]]
        source = decision.get("entry_id")
        meaning = (
            resolve_snapshot(
                snapshot, [source], codes[candidate.evidence[0].document_id]
            )["items"][0]
            if source
            else {"status": "unresolved", "reason": "source_not_registered"}
        )
        if meaning["status"] != "resolved":
            unresolved.append(
                {
                    "source_entry_id": source,
                    "status": "proposed",
                    "reason": meaning["reason"],
                    "classification_code": codes[candidate.evidence[0].document_id],
                    **contexts[candidate.candidate_key],
                }
            )
    report = {
        "schema_version": 1,
        "artifact_kind": "goods_ontology_review_candidates",
        "authority": "suggestion",
        "reason": "ontology_review_required",
        "auto_approve": False,
        "candidates": unresolved,
    }
    async with artifact_store(artifact_root) as store:
        artifacts = []
        for name, body in [
            ("ontology_candidates.json", report),
            ("dictionary_release.json", snapshot.model_dump(mode="json")),
        ]:
            ref = await store.put(
                prefix + name,
                (json.dumps(body, ensure_ascii=False, indent=2) + "\n").encode(),
            )
            artifacts.append(ref.model_dump(mode="json"))
            if name == "dictionary_release.json":
                release = {"uri": ref.uri, "sha256": ref.sha256}
    return {
        "status": "proposed" if unresolved else "reused",
        "reason": "ontology_review_required"
        if unresolved
        else "approved_ontology_links",
        "summary": dict(Counter(c["status"] for c in unresolved)),
        "auto_applied": False,
        "dictionary_standard": release,
        "artifacts": artifacts,
        "held_source_ids": [],
        "candidate_count": len(unresolved),
        "blocked_source_ids": [],
    }


async def collect_expression_proposals(
    request, corpus, extraction_ref, *, api=None, repository=None, runner=None
):
    if api is None:
        async with GoodsAuthoringClient() as owned:
            return await collect_expression_proposals(
                request,
                corpus,
                extraction_ref,
                api=owned,
                repository=repository,
                runner=runner,
            )
    repo = repository or SpecificationRepository.from_environment()
    await repo.register_extraction(request.run_id, extraction_ref, corpus)
    current = await api.dictionary_meaning("GET", "/snapshot")
    if current.get("schema_version", 1) == 1:
        from teoria.domains.goods.normalization.legacy_dictionary.incremental import (
            update_standard_dictionary as update_legacy,
        )

        return await update_legacy(
            request,
            corpus,
            extraction_ref,
            api=api,
            repository=repo,
            runner=runner,
            current_snapshot=current,
        )
    baseline = parse_dictionary_snapshot(current)
    prefix = "specification_processing/" + request.run_id + "/"
    result = None
    if request.dictionary_baseline:
        raw = await read_uri(request.dictionary_baseline.uri)
        if hashlib.sha256(raw).hexdigest() != request.dictionary_baseline.sha256:
            raise ValueError("baseline dictionary checksum mismatch")
        if (
            approved_dictionary_snapshot(parse_dictionary_snapshot(raw)).checksum
            != approved_dictionary_snapshot(baseline).checksum
        ):
            result = {
                "status": "held",
                "reason": "baseline_dictionary_changed",
                "blocked_source_ids": [],
            }
    if result is None:
        candidates, decisions = await register_corpus(
            api,
            corpus,
            "dictionary_" + request.run_id + "_scan",
            auto_approve=request.dictionary_auto_approve,
        )
        result = await collect_ontology_candidates(
            baseline,
            corpus,
            candidates,
            decisions,
            artifact_root=request.artifact_root,
            prefix=prefix,
        )
    artifacts = result.get("artifacts", [])
    async with artifact_store(request.artifact_root) as store:
        reference = await store.put(
            prefix + "dictionary_incremental.json",
            (
                json.dumps(
                    {k: v for k, v in result.items() if k != "artifacts"},
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
                + "\n"
            ).encode(),
        )
    return {**result, "artifacts": [*artifacts, reference.model_dump()]}
