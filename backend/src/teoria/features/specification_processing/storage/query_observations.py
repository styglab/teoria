"""Build query rows from verified profile observations; preserve document bodies in storage."""

from decimal import Decimal
import hashlib
import json

from teoria.features.goods_normalization.contracts import NormalizationPackage
from teoria.features.specification_processing.normalization.profile_application import (
    apply_profile,
)


def snapshot_id(run_id: str, document_id: str) -> str:
    return hashlib.sha256(
        json.dumps([run_id, document_id], separators=(",", ":")).encode()
    ).hexdigest()


def build_query_observations(
    corpus: dict,
    normalized: dict,
    package: NormalizationPackage,
    extraction_ref: dict,
    normalized_ref: dict,
) -> list[dict]:
    expected, _ = apply_profile(corpus, package, run_id=normalized["run_id"])
    if any(normalized.get(key) != value for key, value in expected.items()):
        raise ValueError("normalized observations differ from the pinned profile")
    documents = {d["document_id"]: d for d in corpus["documents"]}
    rows = []
    for document in normalized["documents"]:
        source = documents[document["document_id"]]
        entities = {
            e["observation_id"]: e
            for e in document["entities"]
            if e["status"] == "applied"
        }
        attributes = {a["id"]: a for a in source["attributes"]}
        for fact in document["requirements"]:
            # The first query domain indexes numeric requirements only; other observations stay in the artifact.
            if fact["value"]["kind"] != "number":
                continue
            attribute = attributes[fact["evidence_ref"].split(":", 1)[1]]
            nodes = (
                [fact["evidence"]["node_id"]]
                if "node_id" in fact["evidence"]
                else list(fact["evidence"].get("source_node_ids", []))
            )
            nodes.extend(attribute.get("resolution_evidence_node_ids", []))
            for subject_id in fact["subject_observation_ids"]:
                entity = entities[subject_id]
                owners = (
                    [entity]
                    if entity["concept_key"] == "computer_server.server"
                    else [
                        entities[r["source_observation_id"]]
                        for r in document["relations"]
                        if r["relationship_stable_key"] == "computer_server.has_memory"
                        and r["target_observation_id"] == subject_id
                        and r.get("basis") == "explicit"
                        and entities[r["source_observation_id"]]["concept_key"]
                        == "computer_server.server"
                    ]
                )
                unique_owners = {e["observation_id"]: e for e in owners}
                # No inferred owner, multiple servers, or a specification_for link cannot establish physical ownership.
                owner = (
                    next(iter(unique_owners.values()))
                    if len(unique_owners) == 1
                    else None
                )
                evidence_nodes = set(nodes)
                if owner is not None and owner["observation_id"] != subject_id:
                    for relation in document["relations"]:
                        if (
                            relation["relationship_stable_key"]
                            == "computer_server.has_memory"
                            and relation["source_observation_id"]
                            == owner["observation_id"]
                            and relation["target_observation_id"] == subject_id
                            and relation.get("basis") == "explicit"
                        ):
                            evidence_nodes.update(
                                e["node_id"] for e in relation["evidence"]
                            )
                row = {
                    "observation_id": fact["observation_id"],
                    "snapshot_id": snapshot_id(
                        normalized["run_id"], document["document_id"]
                    ),
                    "run_id": normalized["run_id"],
                    "document_id": document["document_id"],
                    "source_sha256": source["source"]["sha256"],
                    "document_status": source.get("extraction_status", "partial"),
                    "subject_observation_id": subject_id,
                    "subject_name": entity["name_raw"],
                    "subject_concept_id": entity["concept_id"],
                    "subject_concept_key": entity["concept_key"],
                    "owner_observation_id": owner["observation_id"] if owner else "",
                    "owner_name": owner["name_raw"] if owner else "",
                    "owner_concept_key": owner["concept_key"] if owner else "",
                    "property_concept_id": fact["property_concept_id"],
                    "property_stable_key": fact["property_stable_key"],
                    "operator": fact["operator"],
                    "value_decimal": Decimal(fact["value"]["decimal"]),
                    "unit": fact["value"]["unit"],
                    "role": fact["role"],
                    "semantic_scope": fact["semantic_scope"],
                    "value_raw": fact["value_raw"],
                    "unit_raw": fact["unit_raw"],
                    "qualifiers_raw": fact["qualifiers_raw"],
                    "profile_revision_id": str(package.profile_revision_id),
                    "profile_key": package.profile.profile_key,
                    "profile_version": package.profile.version,
                    "package_checksum": package.checksum,
                    "ontology_version_id": str(package.profile.ontology.version_id),
                    "ontology_namespace": package.profile.ontology.namespace,
                    "ontology_version": package.profile.ontology.version,
                    "ontology_checksum": package.profile.ontology.checksum,
                    "extraction_uri": extraction_ref["uri"],
                    "extraction_sha256": extraction_ref["sha256"],
                    "normalized_uri": normalized_ref["uri"],
                    "normalized_sha256": normalized_ref["sha256"],
                    "evidence_ref": fact["evidence_ref"],
                    "evidence_node_ids": sorted(evidence_nodes),
                }
                if not row["value_decimal"].is_finite():
                    raise ValueError("numeric observation must be finite")
                rows.append(row)
    return rows


async def insert_query_observations(connection, run_id: str, rows: list[dict]) -> None:
    from psycopg import sql

    for row in rows:
        if row["run_id"] != run_id:
            raise ValueError("observation belongs to another run")
        columns = list(row)
        await connection.execute(
            sql.SQL(
                "INSERT INTO public_procurement.specification_requirement_observations ({}) VALUES ({})"
            ).format(
                sql.SQL(", ").join(map(sql.Identifier, columns)),
                sql.SQL(", ").join(sql.Placeholder() for _ in columns),
            ),
            [row[key] for key in columns],
        )
