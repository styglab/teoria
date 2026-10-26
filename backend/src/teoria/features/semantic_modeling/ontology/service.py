"""Ontology validation, review and immutable publication policies."""

from __future__ import annotations
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4
from teoria.features.semantic_modeling.ontology.repository import (
    OntologyRepository,
    serialize_record,
)


class OntologyAuthoringService:
    def __init__(
        self,
        database_url: str | None = None,
        *,
        repository: OntologyRepository | None = None,
    ):
        if repository is None and not database_url:
            raise ValueError("Ontology database configuration is required")
        self.repository = repository or OntologyRepository(database_url)

    async def published_artifact(
        self,
        version_id,
        *,
        allow_deprecated=False,
        expected_checksum=None,
        connection=None,
        lock=False,
    ):
        statuses = ["published", "deprecated"] if allow_deprecated else ["published"]
        if connection is not None:
            return await self.repository.read_artifact(
                connection,
                version_id,
                statuses=statuses,
                expected_checksum=expected_checksum,
                lock=lock,
            )
        async with self.repository.transaction() as conn:
            return await self.repository.read_artifact(
                conn,
                version_id,
                statuses=statuses,
                expected_checksum=expected_checksum,
                lock=lock,
            )

    async def list_versions(self, namespace: str) -> list[dict[str, Any]]:
        return await self.repository.list_versions(namespace)

    async def list_ontologies(self) -> list[dict[str, Any]]:
        return await self.repository.list_ontologies()

    async def create_ontology(
        self, *, namespace: str, name: str, description: str, version: str, actor: str
    ) -> dict[str, Any]:
        return await self.repository.create_ontology(
            namespace=namespace,
            name=name,
            description=description,
            version=version,
            actor=actor,
        )

    async def list_concepts(
        self, namespace: str, *, published_only: bool = True
    ) -> list[dict[str, Any]]:
        return await self.repository.list_concepts(
            namespace, published_only=published_only
        )

    async def create_draft(
        self,
        namespace: str,
        *,
        version: str,
        actor: str,
        based_on_version_id: UUID | None = None,
    ) -> dict[str, Any]:
        return await self.repository.create_draft(
            namespace,
            version=version,
            actor=actor,
            based_on_version_id=based_on_version_id,
        )

    async def get_version(self, version_id: UUID) -> dict[str, Any]:
        return await self.repository.get_version(version_id)

    async def add_item(
        self, version_id: UUID, *, kind: str, payload: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        return await self.repository.add_item(
            version_id, kind=kind, payload=payload, actor=actor
        )

    async def update_item(
        self,
        version_id: UUID,
        *,
        kind: str,
        concept_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        return await self.repository.update_item(
            version_id, kind=kind, concept_id=concept_id, changes=changes, actor=actor
        )

    async def delete_item(
        self, version_id: UUID, *, kind: str, concept_id: UUID, actor: str
    ) -> None:
        return await self.repository.delete_item(
            version_id, kind=kind, concept_id=concept_id, actor=actor
        )

    async def binding_impact(self, version_id: UUID) -> dict[str, Any]:
        return await self.repository.binding_impact(version_id)

    async def audit(self, version_id: UUID) -> list[dict[str, Any]]:
        return await self.repository.audit(version_id)

    async def validate(self, version_id: UUID) -> dict[str, Any]:
        async with self.repository.transaction() as conn:
            await self.repository.lock_version(conn, version_id)
            return await self._validate(conn, version_id)

    async def _validate(self, conn, version_id: UUID) -> dict[str, Any]:
        version = await self.repository.read_version(conn, version_id)
        diagnostics: list[dict[str, str]] = []
        object_ids = {x["business_object_id"] for x in version["objects"]}
        for rel in version["relationships"]:
            if (
                rel["source_object_id"] not in object_ids
                or rel["target_object_id"] not in object_ids
            ):
                diagnostics.append(
                    {"code": "relationship_endpoint_missing", "path": rel["code"]}
                )
        for obj in version["objects"]:
            if not obj["properties"]:
                diagnostics.append(
                    {
                        "code": "object_has_no_properties",
                        "path": obj["code"],
                        "severity": "warning",
                    }
                )
        impact = await self.repository.binding_impact_in_transaction(conn, version_id)
        diagnostics.extend(
            {
                "code": "bound_concept_missing",
                "path": x["stable_key"],
                "severity": "error",
            }
            for x in impact["incompatible_bindings"]
        )
        errors = [x for x in diagnostics if x.get("severity", "error") == "error"]
        return {
            "status": "valid" if not errors else "invalid",
            "diagnostic_count": len(diagnostics),
            "diagnostics": diagnostics,
            "binding_impact": impact,
        }

    async def transition(
        self, version_id: UUID, *, action: str, actor: str, comment: str | None = None
    ) -> dict[str, Any]:
        transitions = {
            ("draft", "submit"): "in_review",
            ("in_review", "request_changes"): "draft",
            ("in_review", "approve"): "approved",
            ("approved", "revoke"): "draft",
            ("published", "deprecate"): "deprecated",
        }
        async with self.repository.transaction() as conn:
            current = await self.repository.lock_version(conn, version_id)
            if current is None:
                raise KeyError(str(version_id))
            next_status = transitions.get((current["status"], action))
            if next_status is None:
                raise ValueError(
                    f"Cannot {action} version in {current['status']} status"
                )
            if (
                action in {"submit", "approve"}
                and (await self._validate(conn, version_id))["status"] != "valid"
            ):
                raise ValueError("Ontology version validation failed")
            if action == "deprecate":
                active_bindings = (
                    await self.repository.count_approved_bindings(
                        conn, (current["ontology_id"],)
                    )
                )["count"]
                if active_bindings:
                    raise ValueError(
                        f"Cannot deprecate ontology with {active_bindings} approved bindings"
                    )
            if action in {"approve", "request_changes"}:
                await self.repository.insert_version_review(
                    conn,
                    (
                        uuid4(),
                        version_id,
                        "approve" if action == "approve" else "request_changes",
                        actor,
                        comment,
                    ),
                )
            row = await self.repository.set_version_status(
                conn, (next_status, version_id)
            )
            await self.repository.record_event(
                conn,
                version_id,
                None,
                action,
                actor,
                {"status": current["status"]},
                {"status": next_status},
                comment,
            )
        return serialize_record(dict(row))

    async def publish(self, version_id: UUID, *, actor: str) -> dict[str, Any]:
        async with self.repository.transaction() as conn:
            current = await self.repository.lock_version(conn, version_id)
            if current["status"] != "approved":
                raise ValueError("Only approved ontology versions can be published")
            if (await self._validate(conn, version_id))["status"] != "valid":
                raise ValueError("Ontology version validation failed")
            content = await self.repository.read_version(conn, version_id)
            artifact_body = {
                key: content[key]
                for key in (
                    "namespace",
                    "version",
                    "objects",
                    "relationships",
                    "rules",
                    "metrics",
                )
            }
            encoded = json.dumps(
                artifact_body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            checksum = hashlib.sha256(encoded.encode()).hexdigest()
            await self.repository.deprecate_published_versions(
                conn, (current["ontology_id"],)
            )
            row = await self.repository.mark_published(conn, (version_id,))
            artifact = await self.repository.insert_runtime_artifact(
                conn, (uuid4(), version_id, checksum, encoded, actor)
            )
            await self.repository.record_event(
                conn,
                version_id,
                None,
                "published",
                actor,
                {"status": "approved"},
                {"status": "published", "checksum": checksum},
            )
        result = serialize_record(dict(row))
        result["artifact"] = serialize_record(dict(artifact))
        return result

    async def diff(self, version_id: UUID, against: UUID) -> dict[str, Any]:
        left, right = (
            (await self.get_version(against)),
            (await self.get_version(version_id)),
        )

        def flatten(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
            items: dict[str, dict[str, Any]] = {}
            object_concepts = {
                obj["business_object_id"]: obj["concept_id"] for obj in value["objects"]
            }
            for obj in value["objects"]:
                items[f"object:{obj['concept_id']}"] = {
                    k: v for k, v in obj.items() if k != "properties"
                }
                for prop in obj["properties"]:
                    items[f"property:{prop['concept_id']}"] = prop
            for kind, key in (
                ("relationship", "relationships"),
                ("rule", "rules"),
                ("metric", "metrics"),
            ):
                for item in value[key]:
                    normalized = dict(item)
                    for field in (
                        "source_object_id",
                        "target_object_id",
                        "subject_object_id",
                    ):
                        if field in normalized:
                            normalized[field.replace("_id", "_concept_id")] = (
                                object_concepts.get(normalized.pop(field))
                            )
                    items[f"{kind}:{item['concept_id']}"] = normalized
            return items

        a, b = flatten(left), flatten(right)
        return {
            "added": sorted(set(b) - set(a)),
            "removed": sorted(set(a) - set(b)),
            "changed": sorted(
                k for k in set(a) & set(b) if _semantic(a[k]) != _semantic(b[k])
            ),
        }


def _semantic(value: dict[str, Any]) -> str:
    ignored = {
        "business_object_id",
        "property_id",
        "relationship_type_id",
        "business_rule_id",
        "metric_id",
        "ontology_version_id",
        "status",
        "concept_id",
    }
    return json.dumps(
        {k: v for k, v in value.items() if k not in ignored},
        sort_keys=True,
        default=str,
    )
