"""Per-document immutable result projections. Source observations remain in object storage."""

import json
import re


def result_kind(normalization):
    if not isinstance(normalization, dict):
        return "source"
    if (normalization.get("artifact_kind") == "goods_normalized_observations"
            and normalization.get("profile_revision_id") and normalization.get("package_checksum")
            and isinstance(normalization.get("ontology"), dict)):
        return "profile"
    return "extraction_standard" if normalization.get("standard_version") else "source"


def document_result(corpus, normalized, document_id, *, definitions=()):
    documents = corpus.get("documents", [])
    failed = corpus.get("unavailable_documents", [])
    document = next((d for d in documents + failed if d.get("document_id") == document_id), None)
    if document is None:
        raise KeyError(document_id)
    extraction = {"documents": [document], "unavailable_documents": []} if document in documents else {
        "documents": [], "unavailable_documents": [document]}
    scoped = None
    if isinstance(normalized, dict):
        scoped = {key: normalized[key] for key in (
            "schema_version", "artifact_kind", "standard_version", "profile_revision_id", "profile_key",
            "package_checksum", "ontology", "classification_code", "standard_ref",
        ) if key in normalized}
        # A standard version alone is not proof that its document-level mappings loaded.
        if not isinstance(normalized.get("attributes"), list):
            raise ValueError("invalid normalization artifact")
        labels = {d["id"]: d["label"] for d in definitions if isinstance(d, dict) and d.get("id") and d.get("label")}
        scoped["attributes"] = []
        for row in normalized["attributes"]:
            if row.get("document_id") != document_id:
                continue
            facts = [{**fact, **({"property_label": labels[fact['property_id']]} if fact.get('property_id') in labels else {})}
                     for fact in row.get("facts", [])]
            scoped["attributes"].append({**row, **({"facts": facts} if "facts" in row else {})})
        scoped["documents"] = [d for d in normalized.get("documents", []) if d.get("document_id") == document_id]
    return {"schema_version": 1, "artifact_kind": "specification_document_result",
            "document_id": document_id, "source_sha256": document.get("source", {}).get("sha256"),
            "result_kind": result_kind(scoped), "extracted": extraction, "normalization": scoped}


async def store_document_results(store, run_id, corpus, normalized, *, definitions=()):
    references = []
    for document in corpus.get("documents", []) + corpus.get("unavailable_documents", []):
        # Source document IDs were validated at the processing boundary.
        document_id = document["document_id"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", document_id):
            raise ValueError("unsafe document ID")
        payload = document_result(corpus, normalized, document_id, definitions=definitions)
        reference = await store.put(f"specification_processing/{run_id}/documents/{document_id}/result.json",
                                    (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode())
        references.append(reference.model_dump())
    return references
