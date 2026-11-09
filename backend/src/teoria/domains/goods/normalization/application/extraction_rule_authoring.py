"""Collect, select and apply extraction-standard proposals without Ontology publication."""

from __future__ import annotations

import hashlib
from copy import deepcopy

from teoria.domains.goods.contracts import (
    ContextBinding,
    PropertyBinding,
    StandardArtifact,
)
from teoria.domains.goods.normalization.application.candidate_collection import (
    collect_meaning_candidates,
)
from teoria.domains.goods.normalization.application.extraction_rule_application import (
    binding_signature,
    canonical,
    map_standard,
    signature,
)


def select_definition(
    candidate, document, attribute, rule_set, *, auto_apply_source_literals=False
):
    if rule_set == "server":
        from teoria.domains.goods.normalization.application.legacy_server_rules import (
            select_source_constraint,
            select_typed_definition,
        )

        choice, reason = select_typed_definition(candidate, document, attribute)
        if choice is not None:
            return choice, "typed_definition", reason
        choice, reason = select_source_constraint(candidate, document, attribute)
        return choice, "source_constraint", reason
    if auto_apply_source_literals:
        import hashlib
        import json

        from teoria.domains.goods.data_processing.parsing.document_evidence import (
            attribute_is_grounded,
        )
        from teoria.domains.goods.normalization.application.extraction_rule_application import (
            signature,
        )

        context = signature(document, attribute, rule_set)
        if (
            not attribute["subject_ids"]
            or "unresolved" in context[0]
            or len(context[0]) != 1
            or context[4] == "unknown"
            or context[5] == "unknown"
        ):
            return None, None, "unresolved_source_context"
        if not attribute_is_grounded(document, attribute):
            return None, None, "source_condition_mismatch"
        # This ID denotes a literal extraction contract, never an Ontology concept.
        digest = hashlib.sha256(
            json.dumps(context, ensure_ascii=False).encode()
        ).hexdigest()[:24]
        definition = {
            "id": "source_literal_" + digest,
            "label": attribute.get("property_raw") or attribute["property_key"],
            "definition": "원문 값·단위·연산자·조건을 그대로 보존하는 추출용 규칙.",
            "semantic_maturity": "source_literal",
            "published": False,
            "numeric_ordering_allowed": False,
            "approval_policy": "grounded_source_literal_v1",
        }
        return (
            {"definition": definition},
            "source_literal",
            "grounded_source_literal_policy",
        )
    # A name match does not prove business meaning.
    return None, None, "unresolved_meaning_preserved_as_candidate"


def manage_standard(
    corpus,
    baseline: StandardArtifact | None = None,
    parent_sha256=None,
    *,
    auto_apply_source_literals=False,
):
    baseline = baseline or StandardArtifact(
        version="initial",
        classification_code=corpus["classification_code"],
        definitions=[],
        bindings=[],
    )
    initial = map_standard(corpus, baseline)
    # Candidate collection consumes the still-unmapped universe, not an artificial failure score.
    projection = {
        "attributes": [
            {
                **r,
                "status": "pending_definition"
                if r["status"] == "automatically_deferred"
                else r["status"],
            }
            for r in initial["attributes"]
        ]
    }
    candidates = collect_meaning_candidates(corpus, projection, baseline.model_dump())
    definitions = {d["id"]: deepcopy(d) for d in baseline.definitions}
    bindings = {
        binding_signature(b): b.model_copy(deep=True) for b in baseline.bindings
    }
    observations = {
        (d["document_id"], a["id"]): (d, a)
        for d in corpus["documents"]
        for a in d["attributes"]
    }
    for candidate in candidates["candidates"]:
        adopted = 0
        held = 0
        reasons = {}
        for ref in candidate["observations"]:
            doc, a = observations[(ref["document_id"], ref["attribute_id"])]
            choice, kind, reason = select_definition(
                candidate,
                doc,
                a,
                baseline.rule_set,
                auto_apply_source_literals=auto_apply_source_literals,
            )
            if choice is None:
                held += 1
                reasons[reason] = reasons.get(reason, 0) + 1
                continue
            pid = choice.get("property_id", choice.get("definition", {}).get("id"))
            definition = choice.get("definition")
            if definition is not None:
                if pid in definitions and canonical(definitions[pid]) != canonical(
                    definition
                ):
                    held += 1
                    continue
                definitions[pid] = definition
            context = signature(doc, a, baseline.rule_set)
            binding = ContextBinding(
                target_types=list(context[0]),
                property_key=context[1],
                unit_context=context[2],
                data_type=context[3],
                role=context[4],
                semantic_scope=context[5],
                properties=[
                    PropertyBinding(
                        property_id=pid,
                        rule_kind=kind,
                        candidate={
                            k: candidate[k]
                            for k in [
                                "concept_key",
                                "target_type_candidate",
                                "scope",
                                "role",
                                "decision",
                                "existing_definition_id",
                            ]
                        },
                    )
                ],
            )
            if (
                context in bindings
                and bindings[context].properties != binding.properties
            ):
                held += 1
                continue
            bindings[context] = binding
            adopted += 1
        candidate["automatic_resolution"] = {
            "adopted": adopted,
            "deferred": held,
            "reasons": reasons,
            "human_approval_required": False,
        }
    draft = {
        "rule_set": baseline.rule_set,
        "classification_code": corpus["classification_code"],
        "parent_standard_sha256": parent_sha256,
        "definitions": sorted(definitions.values(), key=lambda d: d["id"]),
        "bindings": [
            b.model_dump() for _, b in sorted(bindings.items(), key=lambda x: str(x[0]))
        ],
    }
    version = "proposal_" + hashlib.sha256(canonical(draft)).hexdigest()[:20]
    standard = StandardArtifact(version=version, **draft)
    candidates["selection_mode"] = "automatic_without_human_gate"
    candidates["source_literal_auto_application"] = auto_apply_source_literals
    return standard, candidates, map_standard(corpus, standard)
