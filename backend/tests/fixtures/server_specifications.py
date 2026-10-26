"""Explicit synthetic source cases; these are pipeline/query controls, not extraction accuracy labels."""

from uuid import UUID
import hashlib

from teoria.features.goods_normalization.contracts import NormalizationProfile, checksum
from teoria.features.goods_normalization.profiles.compiler import compile_package


def synthetic_package():
    ontology = {
        "namespace": "computer_server",
        "version": "0.1.0",
        "objects": [
            {
                "business_object_id": str(UUID(int=10)),
                "concept_id": str(UUID(int=1)),
                "stable_key": "computer_server.server",
                "properties": [
                    {
                        "concept_id": str(UUID(int=2)),
                        "stable_key": "computer_server.server.memory_capacity",
                        "value_type": "decimal",
                        "unit": "GB",
                    }
                ],
            }
        ],
        "relationships": [],
    }
    template = {
        "profile_key": "server_memory",
        "version": "1.0.0",
        "classification_code": "4321150102",
        "entities": [
            {"rule_id": "server", "aliases": ["서버"], "concept_id": str(UUID(int=1))}
        ],
        "requirements": [
            {
                "rule_id": "memory",
                "target_concept_id": str(UUID(int=1)),
                "property_concept_id": str(UUID(int=2)),
                "source_property_keys": ["memory_capacity"],
                "roles": [
                    "requirement_candidate",
                    "supported_capability",
                    "existing_reference",
                ],
                "scopes": ["system_total", "per_module", "support_limit"],
                "value_type": "number",
                "units": [
                    {"source_unit": "GB", "canonical_unit": "GB"},
                    {
                        "source_unit": "GiB",
                        "canonical_unit": "GB",
                        "multiplier": "1.073741824",
                    },
                    {"source_unit": "TB", "canonical_unit": "GB", "multiplier": "1000"},
                ],
            }
        ],
    }
    profile = NormalizationProfile.model_validate(
        {
            **template,
            "ontology": {
                "version_id": str(UUID(int=3)),
                "namespace": ontology["namespace"],
                "version": ontology["version"],
                "checksum": checksum(ontology),
            },
        }
    )
    return compile_package(
        profile, ontology, revision_id=UUID(int=4), approval_actor="test:reviewer"
    )


def corpus():
    docs = []
    for document_id, capacity in [("server_a", "64"), ("server_b", "128")]:
        attributes, nodes = (
            [],
            [{"node_id": "title", "text": "서버", "kind": "heading"}],
        )
        for i, (value, unit, operator, role, scope, text) in enumerate(
            [
                (
                    capacity,
                    "GB",
                    "gte",
                    "requirement_candidate",
                    "system_total",
                    f"총 메모리 {capacity} GB 이상",
                ),
                (
                    "32",
                    "GB",
                    "eq",
                    "requirement_candidate",
                    "per_module",
                    "모듈당 메모리 32 GB",
                ),
                (
                    "1",
                    "TB",
                    "lte",
                    "supported_capability",
                    "support_limit",
                    "최대 1 TB 지원",
                ),
                (
                    "256",
                    "GB",
                    "eq",
                    "existing_reference",
                    "system_total",
                    "기보유 메모리 256 GB",
                ),
            ]
        ):
            nodes.append({"node_id": f"n{i}", "text": text, "kind": "paragraph"})
            attributes.append(
                {
                    "id": f"a{i}",
                    "subject_ids": ["server"],
                    "property_key": "memory_capacity",
                    "data_type": "number",
                    "value_raw": value,
                    "unit_raw": unit,
                    "operator": operator,
                    "operator_raw": "이상" if operator == "gte" else None,
                    "qualifiers_raw": [],
                    "semantic_role": role,
                    "semantic_scope": scope,
                    "evidence": {"node_id": f"n{i}"},
                }
            )
        source = "\n".join(n["text"] for n in nodes).encode()
        docs.append(
            {
                "document_id": document_id,
                "source": {"sha256": hashlib.sha256(source).hexdigest()},
                "parser": {"version": "synthetic"},
                "parsed_document": {"nodes": nodes},
                "entities": [
                    {
                        "id": "server",
                        "name": "서버",
                        "kind": "equipment",
                        "evidence": [{"node_id": "title"}],
                    }
                ],
                "attributes": attributes,
                "relations": [],
                "extraction_status": "extracted",
            }
        )
    return {
        "classification_code": "4321150102",
        "documents": docs,
        "unavailable_documents": [],
    }
