from __future__ import annotations

import json
from typing import Any
from uuid import NAMESPACE_URL, uuid5
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row


class BindingRepository:
    """Persistence boundary for Teoria-owned ontology bindings.

    OpenMetadata entities remain external. Only their stable reference and the
    reviewed binding are stored in the Teoria application database.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def get_published_concept(
        self, stable_key: str, *, ontology_namespace: str | None = None,
    ) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT c.concept_id,c.concept_kind,c.stable_key
                  FROM ontology.concepts c
                  JOIN ontology.ontologies o USING (ontology_id)
                  JOIN ontology.ontology_versions v ON v.ontology_id=c.ontology_id
             LEFT JOIN ontology.business_objects bo ON bo.concept_id=c.concept_id AND bo.ontology_version_id=v.ontology_version_id
             LEFT JOIN ontology.object_properties p ON p.concept_id=c.concept_id
             LEFT JOIN ontology.business_objects owner ON owner.business_object_id=p.business_object_id AND owner.ontology_version_id=v.ontology_version_id
             LEFT JOIN ontology.relationship_types r ON r.concept_id=c.concept_id AND r.ontology_version_id=v.ontology_version_id
             LEFT JOIN ontology.business_rules br ON br.concept_id=c.concept_id AND br.ontology_version_id=v.ontology_version_id
             LEFT JOIN ontology.metrics m ON m.concept_id=c.concept_id AND m.ontology_version_id=v.ontology_version_id
                 WHERE c.stable_key=%s AND v.status='published'
                   AND (%s::text IS NULL OR o.namespace=%s)
                   AND (bo.concept_id IS NOT NULL OR owner.business_object_id IS NOT NULL OR r.concept_id IS NOT NULL OR br.concept_id IS NOT NULL OR m.concept_id IS NOT NULL)
                """,
                (stable_key, ontology_namespace, ontology_namespace),
            ).fetchall()
        if len(rows) > 1:
            raise ValueError(
                f"Ambiguous published ontology concept {stable_key}; "
                "ontology_namespace is required"
            )
        return _jsonable(dict(rows[0])) if rows else None

    def list_published_property_concepts(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT c.concept_id,c.concept_kind,c.stable_key,p.code,p.name,p.description,
                       p.value_type,p.cardinality,p.unit,bo.code AS object_code,
                       bo.name AS object_name,o.namespace,v.version
                  FROM ontology.concepts c
                  JOIN ontology.ontologies o USING (ontology_id)
                  JOIN ontology.ontology_versions v USING (ontology_id)
                  JOIN ontology.object_properties p ON p.concept_id=c.concept_id
                  JOIN ontology.business_objects bo ON bo.business_object_id=p.business_object_id
                                                   AND bo.ontology_version_id=v.ontology_version_id
                 WHERE v.status='published' AND c.concept_kind='property'
                 ORDER BY c.stable_key
                """
            ).fetchall()
        return [_jsonable(dict(row)) for row in rows]

    def get_active_binding(self, *, ontology_concept_id: UUID, target_type: str, target_locator: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            row = connection.execute(
                """SELECT * FROM binding.ontology_bindings
                    WHERE ontology_concept_id=%s AND target_type=%s AND target_locator=%s
                      AND status IN ('draft','approved')""",
                (ontology_concept_id, target_type, target_locator),
            ).fetchone()
        return _jsonable(dict(row)) if row else None

    def get_property_context(self, namespace: str, object_code: str, property_code: str) -> dict[str, Any] | None:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            property_row = connection.execute(
                """
                SELECT p.property_id, o.namespace, v.version AS ontology_version,
                       b.code AS object_code, b.name AS object_name,
                       p.code AS property_code, p.name AS property_name,
                       p.description, p.value_type, p.cardinality, p.unit,
                       p.temporal, p.status
                  FROM ontology.object_properties p
                  JOIN ontology.business_objects b ON b.business_object_id = p.business_object_id
                  JOIN ontology.ontology_versions v ON v.ontology_version_id = b.ontology_version_id
                  JOIN ontology.ontologies o ON o.ontology_id = v.ontology_id
                 WHERE o.namespace = %s AND b.code = %s AND p.code = %s
                 ORDER BY (v.status = 'published') DESC, v.created_at DESC
                 LIMIT 1
                """,
                (namespace, object_code, property_code),
            ).fetchone()
            if property_row is None:
                return None
            binding_rows = connection.execute(
                """
                SELECT ob.binding_id, ob.target_type, ob.target_locator,
                       ob.target_version, ob.binding_type, ob.purpose,
                       ob.authority, ob.priority, ob.condition, ob.confidence,
                       ob.status, ob.provenance, ob.created_by, ob.approved_by,
                       mr.system, mr.external_entity_id, mr.entity_type,
                       mr.fully_qualified_name, mr.external_version,
                       mr.last_verified_at,
                       at.source_id AS api_source_id,
                       at.operation_id AS api_operation_id,
                       at.object_id AS api_object_id,
                       at.field_path AS api_field_path,
                       at.contract_version AS api_contract_version,
                       at.registry_version AS api_registry_version,
                       at.last_verified_at AS api_last_verified_at
                  FROM binding.ontology_bindings ob
             LEFT JOIN binding.metadata_targets mr
                    ON mr.metadata_target_id = ob.metadata_target_id
             LEFT JOIN binding.api_field_targets at
                    ON at.api_field_target_id = ob.api_field_target_id
                 WHERE ob.ontology_ref_type = 'property'
                   AND ob.ontology_ref_id = %s
                 ORDER BY ob.priority, ob.target_type, ob.target_locator
                """,
                (property_row["property_id"],),
            ).fetchall()
        result = dict(property_row)
        result["property_id"] = str(result["property_id"])
        result["ontology_ref"] = f"{namespace}.{object_code}.{property_code}"
        result["bindings"] = [_jsonable(dict(row)) for row in binding_rows]
        return result

    def list_bindings(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        where = "WHERE ob.status = %s" if status else ""
        params: tuple[Any, ...] = (status, limit) if status else (limit,)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                f"""
                SELECT ob.*, c.stable_key AS ontology_stable_key,
                       c.concept_kind AS ontology_concept_kind,
                       mt.system, mt.external_entity_id, mt.entity_type,
                       mt.fully_qualified_name, mt.external_version, mt.last_verified_at,
                       ct.capability_id, ct.target_scope AS capability_target_scope,
                       ct.field_path AS capability_field_path,
                       ct.contract_version AS capability_contract_version,
                       ct.registry_version AS capability_registry_version,
                       ct.last_verified_at AS capability_last_verified_at,
                       at.source_id AS api_source_id,
                       at.operation_id AS api_operation_id,
                       at.object_id AS api_object_id,
                       at.field_path AS api_field_path,
                       at.contract_version AS api_contract_version,
                       at.registry_version AS api_registry_version,
                       at.last_verified_at AS api_last_verified_at
                  FROM binding.ontology_bindings ob
                  JOIN ontology.concepts c ON c.concept_id=ob.ontology_concept_id
             LEFT JOIN binding.metadata_targets mt ON mt.metadata_target_id = ob.metadata_target_id
             LEFT JOIN binding.capability_targets ct ON ct.capability_target_id = ob.capability_target_id
             LEFT JOIN binding.api_field_targets at ON at.api_field_target_id = ob.api_field_target_id
                  {where}
                 ORDER BY ob.created_at DESC
                 LIMIT %s
                """,
                params,
            ).fetchall()
        return [_jsonable(dict(row)) for row in rows]

    def list_approved_capability_bindings(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT ct.capability_id,ct.target_scope AS capability_target_scope,
                       ct.field_path AS capability_field_path,ct.contract_version,
                       ct.registry_version,ob.binding_type,ob.purpose,ob.authority,
                       ob.priority,c.stable_key AS ontology_stable_key
                  FROM binding.ontology_bindings ob
                  JOIN binding.capability_targets ct
                    ON ct.capability_target_id=ob.capability_target_id
                  JOIN ontology.concepts c ON c.concept_id=ob.ontology_concept_id
                 WHERE ob.status='approved'
                   AND (ob.valid_from IS NULL OR ob.valid_from <= current_date)
                   AND (ob.valid_to IS NULL OR ob.valid_to >= current_date)
                 ORDER BY ct.capability_id,ct.target_scope,ct.field_path
                """
            ).fetchall()
        return [_jsonable(dict(row)) for row in rows]

    def create_openmetadata_binding(
        self, *, ontology_ref_type: str, ontology_ref_id: UUID | None,
        ontology_concept_id: UUID | None, target_type: str,
        external_entity_id: str, entity_type: str, fully_qualified_name: str,
        external_version: str | None, binding_type: str, purpose: str | None,
        authority: str, priority: int, confidence: float | None,
        provenance: dict[str, Any], created_by: str,
    ) -> dict[str, Any]:
        binding_id, target_id = uuid4(), uuid4()
        locator = f"openmetadata://{entity_type}/{fully_qualified_name}"
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            ref_table, ref_column = {
                "object": ("ontology.business_objects", "business_object_id"),
                "property": ("ontology.object_properties", "property_id"),
                "relationship": ("ontology.relationship_types", "relationship_type_id"),
                "rule": ("ontology.business_rules", "business_rule_id"),
                "metric": ("ontology.metrics", "metric_id"),
            }[ontology_ref_type]
            if ontology_ref_id is not None:
                ontology_row = connection.execute(
                    f"SELECT x.{ref_column} AS revision_id,x.concept_id "
                    f"FROM {ref_table} x {('JOIN ontology.business_objects owner ON owner.business_object_id=x.business_object_id JOIN ontology.ontology_versions v ON v.ontology_version_id=owner.ontology_version_id' if ontology_ref_type == 'property' else 'JOIN ontology.ontology_versions v ON v.ontology_version_id=x.ontology_version_id')} "
                    f"WHERE x.{ref_column}=%s AND v.status IN ('draft','published')",
                    (ontology_ref_id,),
                ).fetchone()
            elif ontology_concept_id is not None:
                version_join = (
                    "JOIN ontology.business_objects owner ON owner.business_object_id=x.business_object_id "
                    "JOIN ontology.ontology_versions v ON v.ontology_version_id=owner.ontology_version_id"
                    if ontology_ref_type == "property" else
                    "JOIN ontology.ontology_versions v ON v.ontology_version_id=x.ontology_version_id"
                )
                ontology_row = connection.execute(
                    f"SELECT x.{ref_column} AS revision_id,x.concept_id FROM {ref_table} x {version_join} WHERE x.concept_id=%s AND v.status='published'",
                    (ontology_concept_id,),
                ).fetchone()
            else:
                ontology_row = None
            if ontology_row is None:
                raise ValueError(f"Unknown published ontology {ontology_ref_type} reference")
            ontology_ref_id = ontology_row["revision_id"]
            target_row = connection.execute(
                """
                INSERT INTO binding.metadata_targets
                    (metadata_target_id, system, external_entity_id, entity_type,
                     fully_qualified_name, external_version, locator, last_verified_at)
                VALUES (%s, 'openmetadata', %s, %s, %s, %s, %s, now())
                ON CONFLICT (system, external_entity_id) DO UPDATE SET
                    entity_type=EXCLUDED.entity_type,
                    fully_qualified_name=EXCLUDED.fully_qualified_name,
                    external_version=EXCLUDED.external_version,
                    locator=EXCLUDED.locator,
                    last_verified_at=now()
                RETURNING metadata_target_id
                """,
                (target_id, external_entity_id, entity_type, fully_qualified_name, external_version, locator),
            ).fetchone()
            row = connection.execute(
                """
                INSERT INTO binding.ontology_bindings
                    (binding_id, ontology_ref_type, ontology_ref_id, ontology_concept_id, target_type,
                     metadata_target_id, target_locator, target_version, binding_type,
                     purpose, authority, priority, confidence, status, provenance, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s::jsonb,%s)
                RETURNING *
                """,
                (binding_id, ontology_ref_type, ontology_ref_id, ontology_row["concept_id"], target_type,
                 target_row["metadata_target_id"], locator, external_version,
                 binding_type, purpose, authority, priority, confidence,
                 json.dumps(provenance), created_by),
            ).fetchone()
        return _jsonable(dict(row))

    def create_capability_binding(
        self,
        *,
        ontology_ref_type: str,
        ontology_ref_id: UUID | None,
        ontology_concept_id: UUID | None,
        capability_id: str,
        target_scope: str,
        field_path: str | None,
        contract_version: str | None,
        registry_version: str,
        binding_type: str,
        purpose: str | None,
        authority: str,
        priority: int,
        confidence: float | None,
        provenance: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        target_type = {
            "capability": "capability",
            "input": "capability_input",
            "output": "capability_output",
        }[target_scope]
        if target_scope == "capability" and field_path is not None:
            raise ValueError("Capability-level bindings cannot declare field_path")
        if target_scope != "capability" and not field_path:
            raise ValueError(f"{target_scope} bindings require field_path")
        locator = f"capability://{capability_id}"
        if field_path:
            locator = f"{locator}/{target_scope}/{field_path}"

        binding_id, target_id = uuid4(), uuid4()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            ontology_row = self._resolve_published_revision(
                connection,
                ontology_ref_type=ontology_ref_type,
                ontology_ref_id=ontology_ref_id,
                ontology_concept_id=ontology_concept_id,
            )
            target_row = connection.execute(
                """
                INSERT INTO binding.capability_targets
                    (capability_target_id, capability_id, target_scope, field_path,
                     contract_version, registry_version, last_verified_at)
                VALUES (%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (capability_id, target_scope, field_path, contract_version)
                DO UPDATE SET registry_version=EXCLUDED.registry_version, last_verified_at=now()
                RETURNING capability_target_id
                """,
                (target_id, capability_id, target_scope, field_path, contract_version, registry_version),
            ).fetchone()
            row = connection.execute(
                """
                INSERT INTO binding.ontology_bindings
                    (binding_id, ontology_ref_type, ontology_ref_id, ontology_concept_id,
                     target_type, capability_target_id, target_locator, target_version,
                     binding_type, purpose, authority, priority, confidence, status,
                     provenance, created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s::jsonb,%s)
                RETURNING *
                """,
                (
                    binding_id, ontology_ref_type, ontology_row["revision_id"],
                    ontology_row["concept_id"], target_type,
                    target_row["capability_target_id"], locator, contract_version,
                    binding_type, purpose, authority, priority, confidence,
                    json.dumps(provenance), created_by,
                ),
            ).fetchone()
        return _jsonable(dict(row))

    def create_api_field_binding(
        self,
        *,
        ontology_ref_type: str,
        ontology_ref_id: UUID | None,
        ontology_concept_id: UUID | None,
        source_id: str,
        operation_id: str,
        object_id: str,
        field_path: str,
        contract_version: str | None,
        registry_version: str,
        binding_type: str,
        purpose: str | None,
        authority: str,
        priority: int,
        confidence: float | None,
        provenance: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        locator = f"provider://{source_id}/{operation_id}/response/{object_id}.{field_path}"
        binding_id, target_id = uuid4(), uuid4()
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            ontology_row = self._resolve_published_revision(
                connection,
                ontology_ref_type=ontology_ref_type,
                ontology_ref_id=ontology_ref_id,
                ontology_concept_id=ontology_concept_id,
            )
            target_row = connection.execute(
                """
                INSERT INTO binding.api_field_targets
                    (api_field_target_id,source_id,operation_id,object_id,field_path,
                     contract_version,registry_version,last_verified_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (source_id,operation_id,object_id,field_path,contract_version)
                DO UPDATE SET registry_version=EXCLUDED.registry_version,last_verified_at=now()
                RETURNING api_field_target_id
                """,
                (target_id, source_id, operation_id, object_id, field_path,
                 contract_version, registry_version),
            ).fetchone()
            row = connection.execute(
                """
                INSERT INTO binding.ontology_bindings
                    (binding_id,ontology_ref_type,ontology_ref_id,ontology_concept_id,
                     target_type,api_field_target_id,target_locator,target_version,
                     binding_type,purpose,authority,priority,confidence,status,
                     provenance,created_by)
                VALUES (%s,%s,%s,%s,'api_field',%s,%s,%s,%s,%s,%s,%s,%s,
                        'draft',%s::jsonb,%s)
                RETURNING *
                """,
                (
                    binding_id, ontology_ref_type, ontology_row["revision_id"],
                    ontology_row["concept_id"], target_row["api_field_target_id"],
                    locator, contract_version, binding_type, purpose, authority,
                    priority, confidence, json.dumps(provenance), created_by,
                ),
            ).fetchone()
        return _jsonable(dict(row))

    @staticmethod
    def _resolve_published_revision(
        connection,
        *,
        ontology_ref_type: str,
        ontology_ref_id: UUID | None,
        ontology_concept_id: UUID | None,
    ):
        ref_table, ref_column = {
            "object": ("ontology.business_objects", "business_object_id"),
            "property": ("ontology.object_properties", "property_id"),
            "relationship": ("ontology.relationship_types", "relationship_type_id"),
            "rule": ("ontology.business_rules", "business_rule_id"),
            "metric": ("ontology.metrics", "metric_id"),
        }[ontology_ref_type]
        version_join = (
            "JOIN ontology.business_objects owner ON owner.business_object_id=x.business_object_id "
            "JOIN ontology.ontology_versions v ON v.ontology_version_id=owner.ontology_version_id"
            if ontology_ref_type == "property"
            else "JOIN ontology.ontology_versions v ON v.ontology_version_id=x.ontology_version_id"
        )
        selector, value = (
            (f"x.{ref_column}=%s", ontology_ref_id)
            if ontology_ref_id is not None
            else ("x.concept_id=%s", ontology_concept_id)
        )
        if value is None:
            raise ValueError("ontology_ref_id or ontology_concept_id is required")
        row = connection.execute(
            f"SELECT x.{ref_column} AS revision_id,x.concept_id FROM {ref_table} x "
            f"{version_join} WHERE {selector} AND v.status='published'",
            (value,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown published ontology {ontology_ref_type} reference")
        return row

    def validate_bindings(self) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT ob.binding_id, ob.status, ob.target_type, ob.target_locator,
                       CASE ob.ontology_ref_type
                         WHEN 'object' THEN EXISTS (SELECT 1 FROM ontology.business_objects x WHERE x.business_object_id=ob.ontology_ref_id)
                         WHEN 'property' THEN EXISTS (SELECT 1 FROM ontology.object_properties x WHERE x.property_id=ob.ontology_ref_id)
                         WHEN 'relationship' THEN EXISTS (SELECT 1 FROM ontology.relationship_types x WHERE x.relationship_type_id=ob.ontology_ref_id)
                         WHEN 'rule' THEN EXISTS (SELECT 1 FROM ontology.business_rules x WHERE x.business_rule_id=ob.ontology_ref_id)
                         WHEN 'metric' THEN EXISTS (SELECT 1 FROM ontology.metrics x WHERE x.metric_id=ob.ontology_ref_id)
                         ELSE false
                       END AS ontology_ref_exists,
                       CASE
                         WHEN ob.target_type IN ('glossary_term','data_asset') THEN mt.metadata_target_id IS NOT NULL
                         WHEN ob.target_type IN ('capability','capability_input','capability_output') THEN ct.capability_target_id IS NOT NULL
                         WHEN ob.target_type = 'api_field' THEN at.api_field_target_id IS NOT NULL
                         ELSE true
                       END AS target_ref_exists,
                       mt.last_verified_at
                  FROM binding.ontology_bindings ob
             LEFT JOIN binding.metadata_targets mt ON mt.metadata_target_id=ob.metadata_target_id
             LEFT JOIN binding.capability_targets ct ON ct.capability_target_id=ob.capability_target_id
             LEFT JOIN binding.api_field_targets at ON at.api_field_target_id=ob.api_field_target_id
                """
            ).fetchall()
        diagnostics = []
        for raw in rows:
            row = _jsonable(dict(raw))
            if not row["ontology_ref_exists"]:
                diagnostics.append({"binding_id": row["binding_id"], "code": "ontology_ref_missing"})
            if not row["target_ref_exists"]:
                diagnostics.append({"binding_id": row["binding_id"], "code": "target_ref_missing"})
        return {
            "status": "valid" if not diagnostics else "invalid",
            "binding_count": len(rows),
            "diagnostic_count": len(diagnostics),
            "diagnostics": diagnostics,
        }

    def review_binding(self, binding_id: UUID, *, decision: str, reviewer: str, comment: str | None) -> dict[str, Any]:
        next_status = {"approve": "approved", "reject": "rejected", "deprecate": "deprecated"}[decision]
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            existing = connection.execute(
                "SELECT status FROM binding.ontology_bindings WHERE binding_id=%s FOR UPDATE", (binding_id,)
            ).fetchone()
            if existing is None:
                raise KeyError(str(binding_id))
            allowed = {"draft": {"approve", "reject"}, "approved": {"deprecate"}}
            if decision not in allowed.get(existing["status"], set()):
                raise ValueError(f"Cannot {decision} binding in {existing['status']} status")
            if decision == "approve":
                published = connection.execute(
                    """SELECT CASE ob.ontology_ref_type
                             WHEN 'property' THEN EXISTS (
                               SELECT 1 FROM ontology.object_properties p
                               JOIN ontology.business_objects bo USING (business_object_id)
                               JOIN ontology.ontology_versions v USING (ontology_version_id)
                               WHERE p.property_id=ob.ontology_ref_id AND v.status='published')
                             ELSE EXISTS (
                               SELECT 1 FROM ontology.ontology_versions v
                               LEFT JOIN ontology.business_objects bo USING (ontology_version_id)
                               LEFT JOIN ontology.relationship_types r USING (ontology_version_id)
                               LEFT JOIN ontology.business_rules br USING (ontology_version_id)
                               LEFT JOIN ontology.metrics m USING (ontology_version_id)
                               WHERE v.status='published' AND
                                 (bo.business_object_id=ob.ontology_ref_id OR r.relationship_type_id=ob.ontology_ref_id OR
                                  br.business_rule_id=ob.ontology_ref_id OR m.metric_id=ob.ontology_ref_id))
                           END AS value
                      FROM binding.ontology_bindings ob WHERE ob.binding_id=%s""",
                    (binding_id,),
                ).fetchone()["value"]
                if not published:
                    raise ValueError("Cannot approve binding until its ontology revision is published")
            connection.execute(
                "INSERT INTO binding.binding_reviews (binding_review_id,binding_id,decision,reviewer,comment) VALUES (%s,%s,%s,%s,%s)",
                (uuid4(), binding_id, decision, reviewer, comment),
            )
            row = connection.execute(
                "UPDATE binding.ontology_bindings SET status=%s, approved_by=CASE WHEN %s='approved' THEN %s ELSE approved_by END WHERE binding_id=%s RETURNING *",
                (next_status, next_status, reviewer, binding_id),
            ).fetchone()
        return _jsonable(dict(row))

    def bind_openmetadata_reference(
        self,
        *,
        namespace: str,
        object_code: str,
        property_code: str,
        target_type: str,
        external_entity_id: str,
        entity_type: str,
        fully_qualified_name: str,
        external_version: str | None,
        locator: str,
        binding_type: str,
        purpose: str | None,
        authority: str,
        priority: int,
        created_by: str,
    ) -> str:
        reference_key = f"openmetadata:{entity_type}:{external_entity_id}"
        binding_key = f"{namespace}.{object_code}.{property_code}:{target_type}:{locator}"
        reference_id = uuid5(NAMESPACE_URL, reference_key)
        binding_id = uuid5(NAMESPACE_URL, binding_key)
        with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
            property_row = connection.execute(
                """
                SELECT p.property_id, p.concept_id
                  FROM ontology.object_properties p
                  JOIN ontology.business_objects b ON b.business_object_id = p.business_object_id
                  JOIN ontology.ontology_versions v ON v.ontology_version_id = b.ontology_version_id
                  JOIN ontology.ontologies o ON o.ontology_id = v.ontology_id
                 WHERE o.namespace = %s AND b.code = %s AND p.code = %s
                   AND v.status = 'published'
                """,
                (namespace, object_code, property_code),
            ).fetchone()
            if property_row is None:
                raise ValueError(f"Unknown published ontology property: {namespace}.{object_code}.{property_code}")
            connection.execute(
                """
                INSERT INTO binding.metadata_targets (
                    metadata_target_id, system, external_entity_id,
                    entity_type, fully_qualified_name, external_version,
                    locator, last_verified_at
                ) VALUES (%s, 'openmetadata', %s, %s, %s, %s, %s, now())
                ON CONFLICT (system, external_entity_id) DO UPDATE SET
                    entity_type = EXCLUDED.entity_type,
                    fully_qualified_name = EXCLUDED.fully_qualified_name,
                    external_version = EXCLUDED.external_version,
                    locator = EXCLUDED.locator,
                    last_verified_at = now()
                """,
                (reference_id, external_entity_id, entity_type, fully_qualified_name, external_version, locator),
            )
            actual_reference = connection.execute(
                "SELECT metadata_target_id FROM binding.metadata_targets WHERE system = 'openmetadata' AND external_entity_id = %s",
                (external_entity_id,),
            ).fetchone()["metadata_target_id"]
            connection.execute(
                """
                INSERT INTO binding.ontology_bindings (
                    binding_id, ontology_ref_type, ontology_ref_id, ontology_concept_id, target_type,
                    metadata_target_id, target_locator, target_version,
                    binding_type, purpose, authority, priority, confidence,
                    status, provenance, created_by, approved_by
                ) VALUES (
                    %s, 'property', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    1.0, 'approved', %s::jsonb, %s, %s
                )
                ON CONFLICT (binding_id) DO UPDATE SET
                    metadata_target_id = EXCLUDED.metadata_target_id,
                    target_version = EXCLUDED.target_version,
                    purpose = EXCLUDED.purpose,
                    authority = EXCLUDED.authority,
                    priority = EXCLUDED.priority,
                    provenance = EXCLUDED.provenance,
                    approved_by = EXCLUDED.approved_by
                """,
                (
                    binding_id, property_row["property_id"], property_row["concept_id"], target_type,
                    actual_reference, locator, external_version, binding_type,
                    purpose, authority, priority,
                    json.dumps({"source": "openmetadata", "resolution": "confirmed"}),
                    created_by, created_by,
                ),
            )
        return str(binding_id)


def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    for key, item in tuple(value.items()):
        if hasattr(item, "isoformat"):
            value[key] = item.isoformat()
        elif not isinstance(item, (str, int, float, bool, list, dict, type(None))):
            value[key] = str(item)
    return value
