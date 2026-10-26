"""Ontology persistence and revision integrity; each mutation keeps one transaction."""

from __future__ import annotations
import json
from typing import Any
from uuid import UUID, uuid4
from psycopg.rows import dict_row
from teoria.integrations.application_database.postgres import connect


class OntologyRepository:
    def transaction(self):
        return connect(self.database_url, row_factory=dict_row)

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    async def list_versions(self, namespace: str) -> list[dict[str, Any]]:
        async with connect(self.database_url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    """SELECT v.* FROM ontology.ontology_versions v
                     JOIN ontology.ontologies o USING (ontology_id)
                    WHERE o.namespace=%s ORDER BY v.created_at DESC""",
                    (namespace,),
                )
            ).fetchall()
        return [serialize_record(dict(row)) for row in rows]

    async def list_ontologies(self) -> list[dict[str, Any]]:
        async with connect(self.database_url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    """SELECT o.namespace,o.name,o.description,count(v.*)::integer AS version_count,
                          latest.version AS latest_version,latest.status AS latest_status
                     FROM ontology.ontologies o
                LEFT JOIN ontology.ontology_versions v USING (ontology_id)
                LEFT JOIN LATERAL (
                          SELECT version,status FROM ontology.ontology_versions x
                           WHERE x.ontology_id=o.ontology_id ORDER BY x.created_at DESC LIMIT 1
                     ) latest ON true
                 GROUP BY o.ontology_id,o.namespace,o.name,o.description,latest.version,latest.status
                 ORDER BY o.namespace"""
                )
            ).fetchall()
        return [serialize_record(dict(row)) for row in rows]

    async def create_ontology(
        self, *, namespace: str, name: str, description: str, version: str, actor: str
    ) -> dict[str, Any]:
        async with connect(self.database_url, row_factory=dict_row) as conn:
            if await (
                await conn.execute(
                    "SELECT 1 FROM ontology.ontologies WHERE namespace=%s", (namespace,)
                )
            ).fetchone():
                raise ValueError(f"Ontology already exists: {namespace}")
            ontology_id, version_id = uuid4(), uuid4()
            await conn.execute(
                "INSERT INTO ontology.ontologies (ontology_id,namespace,name,description) VALUES (%s,%s,%s,%s)",
                (ontology_id, namespace, name, description),
            )
            row = await (
                await conn.execute(
                    """INSERT INTO ontology.ontology_versions
              (ontology_version_id,ontology_id,version,status,created_by)
              VALUES (%s,%s,%s,'draft',%s) RETURNING *""",
                    (version_id, ontology_id, version, actor),
                )
            ).fetchone()
            await self.record_event(
                conn,
                version_id,
                None,
                "ontology_created",
                actor,
                None,
                {"namespace": namespace, "version": version},
            )
        return serialize_record(dict(row))

    async def list_concepts(
        self, namespace: str, *, published_only: bool = True
    ) -> list[dict[str, Any]]:
        status_clause = "AND v.status='published'" if published_only else ""
        async with connect(self.database_url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    f"""SELECT DISTINCT c.concept_id,c.concept_kind,c.stable_key,
                            v.version AS ontology_version,v.status AS version_status
                       FROM ontology.concepts c
                       JOIN ontology.ontologies o USING (ontology_id)
                       JOIN ontology.ontology_versions v USING (ontology_id)
                       LEFT JOIN ontology.business_objects bo ON bo.concept_id=c.concept_id AND bo.ontology_version_id=v.ontology_version_id
                       LEFT JOIN ontology.object_properties p ON p.concept_id=c.concept_id
                       LEFT JOIN ontology.business_objects pbo ON pbo.business_object_id=p.business_object_id AND pbo.ontology_version_id=v.ontology_version_id
                       LEFT JOIN ontology.relationship_types r ON r.concept_id=c.concept_id AND r.ontology_version_id=v.ontology_version_id
                       LEFT JOIN ontology.business_rules br ON br.concept_id=c.concept_id AND br.ontology_version_id=v.ontology_version_id
                       LEFT JOIN ontology.metrics m ON m.concept_id=c.concept_id AND m.ontology_version_id=v.ontology_version_id
                      WHERE o.namespace=%s {status_clause}
                        AND (bo.concept_id IS NOT NULL OR pbo.business_object_id IS NOT NULL OR r.concept_id IS NOT NULL OR br.concept_id IS NOT NULL OR m.concept_id IS NOT NULL)
                      ORDER BY c.stable_key""",
                    (namespace,),
                )
            ).fetchall()
        return [serialize_record(dict(row)) for row in rows]

    async def create_draft(
        self,
        namespace: str,
        *,
        version: str,
        actor: str,
        based_on_version_id: UUID | None = None,
    ) -> dict[str, Any]:
        async with connect(self.database_url, row_factory=dict_row) as conn:
            ontology = await (
                await conn.execute(
                    "SELECT * FROM ontology.ontologies WHERE namespace=%s FOR UPDATE",
                    (namespace,),
                )
            ).fetchone()
            if ontology is None:
                raise KeyError(namespace)
            base = await (
                await conn.execute(
                    "SELECT * FROM ontology.ontology_versions WHERE ontology_version_id=%s AND ontology_id=%s"
                    if based_on_version_id
                    else "SELECT * FROM ontology.ontology_versions WHERE ontology_id=%s AND status='published'",
                    (based_on_version_id, ontology["ontology_id"])
                    if based_on_version_id
                    else (ontology["ontology_id"],),
                )
            ).fetchone()
            if base is None:
                raise ValueError("A valid base version is required")
            if base["status"] not in {"published", "deprecated"}:
                raise ValueError(
                    "Drafts must be based on an immutable published version"
                )
            new_id = uuid4()
            row = await (
                await conn.execute(
                    """INSERT INTO ontology.ontology_versions
                       (ontology_version_id,ontology_id,version,status,based_on_version_id,created_by)
                     VALUES (%s,%s,%s,'draft',%s,%s) RETURNING *""",
                    (
                        new_id,
                        ontology["ontology_id"],
                        version,
                        base["ontology_version_id"],
                        actor,
                    ),
                )
            ).fetchone()
            object_map: dict[UUID, UUID] = {}
            for item in await (
                await conn.execute(
                    "SELECT * FROM ontology.business_objects WHERE ontology_version_id=%s",
                    (base["ontology_version_id"],),
                )
            ).fetchall():
                replacement = uuid4()
                object_map[item["business_object_id"]] = replacement
                await conn.execute(
                    """INSERT INTO ontology.business_objects
                       (business_object_id,ontology_version_id,code,name,description,identity_policy,status,concept_id)
                       VALUES (%s,%s,%s,%s,%s,%s,'draft',%s)""",
                    (
                        replacement,
                        new_id,
                        item["code"],
                        item["name"],
                        item["description"],
                        json.dumps(item["identity_policy"]),
                        item["concept_id"],
                    ),
                )
            for old_object, new_object in object_map.items():
                for item in await (
                    await conn.execute(
                        "SELECT * FROM ontology.object_properties WHERE business_object_id=%s",
                        (old_object,),
                    )
                ).fetchall():
                    await conn.execute(
                        """INSERT INTO ontology.object_properties
                           (property_id,business_object_id,code,name,description,value_type,cardinality,unit,temporal,status,concept_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
                        (
                            uuid4(),
                            new_object,
                            item["code"],
                            item["name"],
                            item["description"],
                            item["value_type"],
                            item["cardinality"],
                            item["unit"],
                            item["temporal"],
                            item["concept_id"],
                        ),
                    )
            for table, id_col in (
                ("relationship_types", "relationship_type_id"),
                ("business_rules", "business_rule_id"),
                ("metrics", "metric_id"),
            ):
                for item in await (
                    await conn.execute(
                        f"SELECT * FROM ontology.{table} WHERE ontology_version_id=%s",
                        (base["ontology_version_id"],),
                    )
                ).fetchall():
                    await self._clone_complex(
                        conn, table, id_col, item, new_id, object_map
                    )
            await self.record_event(
                conn,
                new_id,
                None,
                "draft_created",
                actor,
                None,
                {"based_on": str(base["ontology_version_id"]), "version": version},
            )
        return serialize_record(dict(row))

    async def _clone_complex(
        self,
        conn,
        table: str,
        id_col: str,
        item: dict,
        new_id: UUID,
        object_map: dict[UUID, UUID],
    ) -> None:
        if table == "relationship_types":
            await conn.execute(
                """INSERT INTO ontology.relationship_types
              (relationship_type_id,ontology_version_id,code,name,description,source_object_id,target_object_id,source_cardinality,target_cardinality,temporal,transitive,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
                (
                    uuid4(),
                    new_id,
                    item["code"],
                    item["name"],
                    item.get("description", ""),
                    object_map[item["source_object_id"]],
                    object_map[item["target_object_id"]],
                    item["source_cardinality"],
                    item["target_cardinality"],
                    item["temporal"],
                    item["transitive"],
                    item["concept_id"],
                ),
            )
        elif table == "business_rules":
            await conn.execute(
                """INSERT INTO ontology.business_rules
              (business_rule_id,ontology_version_id,code,name,description,subject_object_id,expression_language,expression,evaluator_key,rule_version,effective_from,effective_to,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
                (
                    uuid4(),
                    new_id,
                    item["code"],
                    item["name"],
                    item["description"],
                    object_map[item["subject_object_id"]],
                    item["expression_language"],
                    json.dumps(item["expression"]),
                    item["evaluator_key"],
                    item["rule_version"],
                    item["effective_from"],
                    item["effective_to"],
                    item["concept_id"],
                ),
            )
        else:
            await conn.execute(
                """INSERT INTO ontology.metrics
              (metric_id,ontology_version_id,code,name,description,subject_object_id,formula,aggregation,grain,dimensions,unit,time_basis,metric_version,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
                (
                    uuid4(),
                    new_id,
                    item["code"],
                    item["name"],
                    item["description"],
                    object_map[item["subject_object_id"]],
                    json.dumps(item["formula"]),
                    item["aggregation"],
                    json.dumps(item["grain"]),
                    json.dumps(item["dimensions"]),
                    item["unit"],
                    item["time_basis"],
                    item["metric_version"],
                    item["concept_id"],
                ),
            )

    async def get_version(self, version_id: UUID) -> dict[str, Any]:
        async with connect(self.database_url, row_factory=dict_row) as conn:
            return await self.read_version(conn, version_id)

    async def read_version(self, conn, version_id: UUID) -> dict[str, Any]:
        version = await (
            await conn.execute(
                "SELECT v.*,o.namespace,o.name AS ontology_name FROM ontology.ontology_versions v JOIN ontology.ontologies o USING (ontology_id) WHERE ontology_version_id=%s",
                (version_id,),
            )
        ).fetchone()
        if version is None:
            raise KeyError(str(version_id))
        objects = await (
            await conn.execute(
                """SELECT bo.*,c.stable_key FROM ontology.business_objects bo
          JOIN ontology.concepts c USING (concept_id)
          WHERE bo.ontology_version_id=%s ORDER BY bo.code""",
                (version_id,),
            )
        ).fetchall()
        result = serialize_record(dict(version))
        result["objects"] = []
        for raw in objects:
            item = serialize_record(dict(raw))
            item["properties"] = [
                serialize_record(dict(p))
                for p in (
                    await (
                        await conn.execute(
                            """SELECT p.*,c.stable_key
              FROM ontology.object_properties p JOIN ontology.concepts c USING (concept_id)
              WHERE p.business_object_id=%s ORDER BY p.code""",
                            (raw["business_object_id"],),
                        )
                    ).fetchall()
                )
            ]
            result["objects"].append(item)
        for key, table in (
            ("relationships", "relationship_types"),
            ("rules", "business_rules"),
            ("metrics", "metrics"),
        ):
            result[key] = [
                serialize_record(dict(x))
                for x in (
                    await (
                        await conn.execute(
                            f"""SELECT x.*,c.stable_key
              FROM ontology.{table} x JOIN ontology.concepts c USING (concept_id)
              WHERE x.ontology_version_id=%s ORDER BY x.code""",
                            (version_id,),
                        )
                    ).fetchall()
                )
            ]
        return result

    async def add_item(
        self, version_id: UUID, *, kind: str, payload: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        async with connect(self.database_url, row_factory=dict_row) as conn:
            version = await self.lock_version(conn, version_id)
            if version is None:
                raise KeyError(str(version_id))
            if version["status"] != "draft":
                raise ValueError("Only draft ontology versions are editable")
            stable_key = (
                payload.get("stable_key") or f"{version['namespace']}.{payload['code']}"
            )
            concept = await (
                await conn.execute(
                    "SELECT * FROM ontology.concepts WHERE ontology_id=%s AND stable_key=%s",
                    (version["ontology_id"], stable_key),
                )
            ).fetchone()
            concept_id = concept["concept_id"] if concept else uuid4()
            if concept is None:
                await conn.execute(
                    "INSERT INTO ontology.concepts (concept_id,ontology_id,concept_kind,stable_key) VALUES (%s,%s,%s,%s)",
                    (concept_id, version["ontology_id"], kind, stable_key),
                )
            elif concept["concept_kind"] != kind:
                raise ValueError(
                    "Stable key already belongs to a different concept kind"
                )
            row = await self._insert_item(conn, version_id, kind, concept_id, payload)
            await self.record_event(
                conn, version_id, concept_id, f"{kind}_created", actor, None, payload
            )
        return serialize_record(dict(row))

    async def update_item(
        self,
        version_id: UUID,
        *,
        kind: str,
        concept_id: UUID,
        changes: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        table, id_col, allowed = {
            "object": (
                "business_objects",
                "business_object_id",
                {"code", "name", "description", "identity_policy"},
            ),
            "property": (
                "object_properties",
                "property_id",
                {
                    "code",
                    "name",
                    "description",
                    "value_type",
                    "cardinality",
                    "unit",
                    "temporal",
                },
            ),
            "relationship": (
                "relationship_types",
                "relationship_type_id",
                {
                    "code",
                    "name",
                    "description",
                    "source_cardinality",
                    "target_cardinality",
                    "temporal",
                    "transitive",
                },
            ),
            "rule": (
                "business_rules",
                "business_rule_id",
                {
                    "code",
                    "name",
                    "description",
                    "expression_language",
                    "expression",
                    "evaluator_key",
                    "rule_version",
                    "effective_from",
                    "effective_to",
                },
            ),
            "metric": (
                "metrics",
                "metric_id",
                {
                    "code",
                    "name",
                    "description",
                    "formula",
                    "aggregation",
                    "grain",
                    "dimensions",
                    "unit",
                    "time_basis",
                    "metric_version",
                },
            ),
        }[kind]
        invalid = set(changes) - allowed
        if invalid or not changes:
            raise ValueError(f"Invalid {kind} changes: {sorted(invalid)}")
        async with connect(self.database_url, row_factory=dict_row) as conn:
            await self._require_draft(conn, version_id)
            if kind == "property":
                current = await (
                    await conn.execute(
                        "SELECT p.* FROM ontology.object_properties p JOIN ontology.business_objects b USING (business_object_id) WHERE b.ontology_version_id=%s AND p.concept_id=%s",
                        (version_id, concept_id),
                    )
                ).fetchone()
            else:
                current = await (
                    await conn.execute(
                        f"SELECT * FROM ontology.{table} WHERE ontology_version_id=%s AND concept_id=%s",
                        (version_id, concept_id),
                    )
                ).fetchone()
            if current is None:
                raise KeyError(str(concept_id))
            values = []
            assignments = []
            for key, value in changes.items():
                assignments.append(f"{key}=%s")
                values.append(
                    json.dumps(value)
                    if key
                    in {
                        "identity_policy",
                        "expression",
                        "formula",
                        "grain",
                        "dimensions",
                    }
                    else value
                )
            values.append(current[id_col])
            row = await (
                await conn.execute(
                    f"UPDATE ontology.{table} SET {','.join(assignments)} WHERE {id_col}=%s RETURNING *",
                    tuple(values),
                )
            ).fetchone()
            await self.record_event(
                conn,
                version_id,
                concept_id,
                f"{kind}_updated",
                actor,
                serialize_record(dict(current)),
                changes,
            )
        return serialize_record(dict(row))

    async def delete_item(
        self, version_id: UUID, *, kind: str, concept_id: UUID, actor: str
    ) -> None:
        table, id_col = {
            "object": ("business_objects", "business_object_id"),
            "property": ("object_properties", "property_id"),
            "relationship": ("relationship_types", "relationship_type_id"),
            "rule": ("business_rules", "business_rule_id"),
            "metric": ("metrics", "metric_id"),
        }[kind]
        async with connect(self.database_url, row_factory=dict_row) as conn:
            await self._require_draft(conn, version_id)
            if kind == "property":
                current = await (
                    await conn.execute(
                        "SELECT p.* FROM ontology.object_properties p JOIN ontology.business_objects b USING (business_object_id) WHERE b.ontology_version_id=%s AND p.concept_id=%s",
                        (version_id, concept_id),
                    )
                ).fetchone()
            else:
                current = await (
                    await conn.execute(
                        f"SELECT * FROM ontology.{table} WHERE ontology_version_id=%s AND concept_id=%s",
                        (version_id, concept_id),
                    )
                ).fetchone()
            if current is None:
                raise KeyError(str(concept_id))
            await conn.execute(
                f"DELETE FROM ontology.{table} WHERE {id_col}=%s", (current[id_col],)
            )
            await self.record_event(
                conn,
                version_id,
                concept_id,
                f"{kind}_removed",
                actor,
                serialize_record(dict(current)),
                None,
            )

    @staticmethod
    async def _require_draft(conn, version_id: UUID) -> None:
        row = await OntologyRepository.lock_version(conn, version_id)
        if row is None:
            raise KeyError(str(version_id))
        if row["status"] != "draft":
            raise ValueError("Only draft ontology versions are editable")

    async def _object_revision_id(
        self, conn, version_id: UUID, concept_id: UUID
    ) -> UUID:
        row = await (
            await conn.execute(
                "SELECT business_object_id FROM ontology.business_objects WHERE ontology_version_id=%s AND concept_id=%s",
                (version_id, concept_id),
            )
        ).fetchone()
        if row is None:
            raise ValueError(
                f"Object concept is not a member of this version: {concept_id}"
            )
        return row["business_object_id"]

    async def _insert_item(
        self, conn, version_id: UUID, kind: str, concept_id: UUID, p: dict[str, Any]
    ):
        if kind == "object":
            return await (
                await conn.execute(
                    """INSERT INTO ontology.business_objects
              (business_object_id,ontology_version_id,code,name,description,identity_policy,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s::jsonb,'draft',%s) RETURNING *""",
                    (
                        uuid4(),
                        version_id,
                        p["code"],
                        p["name"],
                        p.get("description", ""),
                        json.dumps(p.get("identity_policy", {})),
                        concept_id,
                    ),
                )
            ).fetchone()
        if kind == "property":
            owner = await self._object_revision_id(
                conn, version_id, UUID(str(p["object_concept_id"]))
            )
            return await (
                await conn.execute(
                    """INSERT INTO ontology.object_properties
              (property_id,business_object_id,code,name,description,value_type,cardinality,unit,temporal,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING *""",
                    (
                        uuid4(),
                        owner,
                        p["code"],
                        p["name"],
                        p.get("description", ""),
                        p["value_type"],
                        p.get("cardinality", "optional"),
                        p.get("unit"),
                        p.get("temporal", False),
                        concept_id,
                    ),
                )
            ).fetchone()
        subject = await self._object_revision_id(
            conn,
            version_id,
            UUID(
                str(
                    p.get("subject_object_concept_id")
                    or p.get("source_object_concept_id")
                )
            ),
        )
        if kind == "relationship":
            target = await self._object_revision_id(
                conn, version_id, UUID(str(p["target_object_concept_id"]))
            )
            return await (
                await conn.execute(
                    """INSERT INTO ontology.relationship_types
              (relationship_type_id,ontology_version_id,code,name,description,source_object_id,target_object_id,source_cardinality,target_cardinality,temporal,transitive,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING *""",
                    (
                        uuid4(),
                        version_id,
                        p["code"],
                        p["name"],
                        p.get("description", ""),
                        subject,
                        target,
                        p.get("source_cardinality", "many"),
                        p.get("target_cardinality", "many"),
                        p.get("temporal", False),
                        p.get("transitive", False),
                        concept_id,
                    ),
                )
            ).fetchone()
        if kind == "rule":
            return await (
                await conn.execute(
                    """INSERT INTO ontology.business_rules
              (business_rule_id,ontology_version_id,code,name,description,subject_object_id,expression_language,expression,evaluator_key,rule_version,effective_from,effective_to,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,'draft',%s) RETURNING *""",
                    (
                        uuid4(),
                        version_id,
                        p["code"],
                        p["name"],
                        p.get("description", ""),
                        subject,
                        p["expression_language"],
                        json.dumps(p["expression"]),
                        p.get("evaluator_key"),
                        p.get("rule_version", "1.0"),
                        p.get("effective_from"),
                        p.get("effective_to"),
                        concept_id,
                    ),
                )
            ).fetchone()
        if kind == "metric":
            return await (
                await conn.execute(
                    """INSERT INTO ontology.metrics
              (metric_id,ontology_version_id,code,name,description,subject_object_id,formula,aggregation,grain,dimensions,unit,time_basis,metric_version,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'draft',%s) RETURNING *""",
                    (
                        uuid4(),
                        version_id,
                        p["code"],
                        p["name"],
                        p.get("description", ""),
                        subject,
                        json.dumps(p["formula"]),
                        p["aggregation"],
                        json.dumps(p.get("grain", [])),
                        json.dumps(p.get("dimensions", [])),
                        p.get("unit"),
                        p.get("time_basis"),
                        p.get("metric_version", "1.0"),
                        concept_id,
                    ),
                )
            ).fetchone()
        raise ValueError(f"Unsupported ontology item kind: {kind}")

    async def binding_impact(self, version_id: UUID) -> dict[str, Any]:
        async with connect(self.database_url, row_factory=dict_row) as conn:
            return await self.binding_impact_in_transaction(conn, version_id)

    async def binding_impact_in_transaction(
        self, conn, version_id: UUID
    ) -> dict[str, Any]:
        rows = await (
            await conn.execute(
                """WITH selected_ontology AS (
          SELECT ontology_id FROM ontology.ontology_versions WHERE ontology_version_id=%s
        ), members AS (
          SELECT concept_id FROM ontology.business_objects WHERE ontology_version_id=%s UNION
          SELECT p.concept_id FROM ontology.object_properties p JOIN ontology.business_objects b USING (business_object_id) WHERE b.ontology_version_id=%s UNION
          SELECT concept_id FROM ontology.relationship_types WHERE ontology_version_id=%s UNION
          SELECT concept_id FROM ontology.business_rules WHERE ontology_version_id=%s UNION
          SELECT concept_id FROM ontology.metrics WHERE ontology_version_id=%s)
          SELECT DISTINCT ob.binding_id,c.stable_key,ob.status FROM binding.ontology_bindings ob
          JOIN ontology.concepts c ON c.concept_id=ob.ontology_concept_id
          JOIN selected_ontology so ON so.ontology_id=c.ontology_id
          LEFT JOIN members m ON m.concept_id=ob.ontology_concept_id
          WHERE ob.status='approved' AND m.concept_id IS NULL""",
                (version_id,) * 6,
            )
        ).fetchall()
        return {
            "compatible": not rows,
            "incompatible_binding_count": len(rows),
            "incompatible_bindings": [serialize_record(dict(x)) for x in rows],
        }

    @staticmethod
    async def lock_version(conn, version_id: UUID):
        owner = await (
            await conn.execute(
                "SELECT ontology_id FROM ontology.ontology_versions WHERE ontology_version_id=%s",
                (version_id,),
            )
        ).fetchone()
        if owner is None:
            raise KeyError(str(version_id))
        # Serialize different versions of the same ontology before locking a revision.
        await conn.execute(
            "SELECT ontology_id FROM ontology.ontologies WHERE ontology_id=%s FOR UPDATE",
            (owner["ontology_id"],),
        )
        return await (
            await conn.execute(
                "SELECT v.*,o.namespace FROM ontology.ontology_versions v JOIN ontology.ontologies o USING (ontology_id) WHERE ontology_version_id=%s FOR UPDATE OF v",
                (version_id,),
            )
        ).fetchone()

    async def audit(self, version_id: UUID) -> list[dict[str, Any]]:
        async with connect(self.database_url, row_factory=dict_row) as conn:
            rows = await (
                await conn.execute(
                    "SELECT * FROM ontology.audit_events WHERE ontology_version_id=%s ORDER BY created_at",
                    (version_id,),
                )
            ).fetchall()
        return [serialize_record(dict(x)) for x in rows]

    @staticmethod
    async def record_event(
        conn, version_id, concept_id, event_type, actor, before, after, reason=None
    ):
        await conn.execute(
            "INSERT INTO ontology.audit_events VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,now())",
            (
                uuid4(),
                version_id,
                concept_id,
                event_type,
                actor,
                json.dumps(before) if before is not None else None,
                json.dumps(after) if after is not None else None,
                reason,
            ),
        )

    async def set_version_status(self, conn, parameters):
        return await (
            await conn.execute(
                "UPDATE ontology.ontology_versions SET status=%s WHERE ontology_version_id=%s RETURNING *",
                parameters,
            )
        ).fetchone()

    async def deprecate_published_versions(self, conn, parameters):
        await conn.execute(
            "UPDATE ontology.ontology_versions SET status='deprecated' WHERE ontology_id=%s AND status='published'",
            parameters,
        )

    async def mark_published(self, conn, parameters):
        return await (
            await conn.execute(
                "UPDATE ontology.ontology_versions SET status='published',published_at=now() WHERE ontology_version_id=%s RETURNING *",
                parameters,
            )
        ).fetchone()

    async def insert_runtime_artifact(self, conn, parameters):
        return await (
            await conn.execute(
                "INSERT INTO ontology.runtime_artifacts VALUES (%s,%s,'json','1.0',%s,%s::jsonb,%s,now()) RETURNING artifact_id,checksum,schema_version,created_at",
                parameters,
            )
        ).fetchone()

    async def insert_version_review(self, conn, parameters):
        await conn.execute(
            "INSERT INTO ontology.version_reviews VALUES (%s,%s,%s,%s,%s,now())",
            parameters,
        )

    async def count_approved_bindings(self, conn, parameters):
        return await (
            await conn.execute(
                """SELECT count(*) AS count
                                 FROM binding.ontology_bindings ob
                                 JOIN ontology.concepts c ON c.concept_id=ob.ontology_concept_id
                                WHERE c.ontology_id=%s AND ob.status='approved'""",
                parameters,
            )
        ).fetchone()

    async def read_artifact(
        self, conn, version_id, *, statuses, expected_checksum=None, lock=False
    ):
        return await (
            await conn.execute(
                "SELECT a.content,a.checksum,v.status FROM ontology.runtime_artifacts a "
                "JOIN ontology.ontology_versions v USING (ontology_version_id) "
                "WHERE a.ontology_version_id=%s AND v.status=ANY(%s) "
                + ("AND a.checksum=%s " if expected_checksum is not None else "")
                + ("FOR SHARE OF v" if lock else ""),
                (version_id, statuses, expected_checksum)
                if expected_checksum is not None
                else (version_id, statuses),
            )
        ).fetchone()


def serialize_record(value: dict[str, Any]) -> dict[str, Any]:
    for key, item in tuple(value.items()):
        if hasattr(item, "isoformat"):
            value[key] = item.isoformat()
        elif not isinstance(item, (str, int, float, bool, list, dict, type(None))):
            value[key] = str(item)
    return value
