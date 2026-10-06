from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.rows import dict_row


class OntologyAuthoringRepository:
    """Authoring boundary; published runtime artifacts are immutable snapshots."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def list_versions(self, namespace: str) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
                """SELECT v.* FROM ontology.ontology_versions v
                     JOIN ontology.ontologies o USING (ontology_id)
                    WHERE o.namespace=%s ORDER BY v.created_at DESC""", (namespace,),
            ).fetchall()
        return [_jsonable(dict(row)) for row in rows]

    def list_ontologies(self) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
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
            ).fetchall()
        return [_jsonable(dict(row)) for row in rows]

    def create_ontology(self, *, namespace: str, name: str, description: str, version: str, actor: str) -> dict[str, Any]:
        with psycopg.connect(self.database_url,row_factory=dict_row) as conn:
            if conn.execute("SELECT 1 FROM ontology.ontologies WHERE namespace=%s",(namespace,)).fetchone():
                raise ValueError(f"Ontology already exists: {namespace}")
            ontology_id,version_id=uuid4(),uuid4()
            conn.execute("INSERT INTO ontology.ontologies (ontology_id,namespace,name,description) VALUES (%s,%s,%s,%s)",(ontology_id,namespace,name,description))
            row=conn.execute("""INSERT INTO ontology.ontology_versions
              (ontology_version_id,ontology_id,version,status,created_by)
              VALUES (%s,%s,%s,'draft',%s) RETURNING *""",(version_id,ontology_id,version,actor)).fetchone()
            self._audit(conn,version_id,None,"ontology_created",actor,None,{"namespace":namespace,"version":version})
        return _jsonable(dict(row))

    def list_concepts(self, namespace: str, *, published_only: bool = True) -> list[dict[str, Any]]:
        status_clause = "AND v.status='published'" if published_only else ""
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute(
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
                      ORDER BY c.stable_key""", (namespace,),
            ).fetchall()
        return [_jsonable(dict(row)) for row in rows]

    def create_draft(self, namespace: str, *, version: str, actor: str, based_on_version_id: UUID | None = None) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            ontology = conn.execute("SELECT * FROM ontology.ontologies WHERE namespace=%s", (namespace,)).fetchone()
            if ontology is None:
                raise KeyError(namespace)
            base = conn.execute(
                "SELECT * FROM ontology.ontology_versions WHERE ontology_version_id=%s AND ontology_id=%s"
                if based_on_version_id else
                "SELECT * FROM ontology.ontology_versions WHERE ontology_id=%s AND status='published'",
                (based_on_version_id, ontology["ontology_id"]) if based_on_version_id else (ontology["ontology_id"],),
            ).fetchone()
            if base is None:
                raise ValueError("A valid base version is required")
            new_id = uuid4()
            row = conn.execute(
                """INSERT INTO ontology.ontology_versions
                       (ontology_version_id,ontology_id,version,status,based_on_version_id,created_by)
                     VALUES (%s,%s,%s,'draft',%s,%s) RETURNING *""",
                (new_id, ontology["ontology_id"], version, base["ontology_version_id"], actor),
            ).fetchone()
            object_map: dict[UUID, UUID] = {}
            for item in conn.execute("SELECT * FROM ontology.business_objects WHERE ontology_version_id=%s", (base["ontology_version_id"],)).fetchall():
                replacement = uuid4(); object_map[item["business_object_id"]] = replacement
                conn.execute(
                    """INSERT INTO ontology.business_objects
                       (business_object_id,ontology_version_id,code,name,description,identity_policy,status,concept_id)
                       VALUES (%s,%s,%s,%s,%s,%s,'draft',%s)""",
                    (replacement,new_id,item["code"],item["name"],item["description"],json.dumps(item["identity_policy"]),item["concept_id"]),
                )
            for old_object, new_object in object_map.items():
                for item in conn.execute("SELECT * FROM ontology.object_properties WHERE business_object_id=%s", (old_object,)).fetchall():
                    conn.execute(
                        """INSERT INTO ontology.object_properties
                           (property_id,business_object_id,code,name,description,value_type,cardinality,unit,temporal,status,concept_id)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
                        (uuid4(),new_object,item["code"],item["name"],item["description"],item["value_type"],item["cardinality"],item["unit"],item["temporal"],item["concept_id"]),
                    )
            for table, id_col in (("relationship_types","relationship_type_id"),("business_rules","business_rule_id"),("metrics","metric_id")):
                for item in conn.execute(f"SELECT * FROM ontology.{table} WHERE ontology_version_id=%s", (base["ontology_version_id"],)).fetchall():
                    self._clone_complex(conn, table, id_col, item, new_id, object_map)
            self._audit(conn, new_id, None, "draft_created", actor, None, {"based_on": str(base["ontology_version_id"]), "version": version})
        return _jsonable(dict(row))

    def _clone_complex(self, conn, table: str, id_col: str, item: dict, new_id: UUID, object_map: dict[UUID, UUID]) -> None:
        if table == "relationship_types":
            conn.execute("""INSERT INTO ontology.relationship_types
              (relationship_type_id,ontology_version_id,code,name,source_object_id,target_object_id,source_cardinality,target_cardinality,temporal,transitive,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
              (uuid4(),new_id,item["code"],item["name"],object_map[item["source_object_id"]],object_map[item["target_object_id"]],item["source_cardinality"],item["target_cardinality"],item["temporal"],item["transitive"],item["concept_id"]))
        elif table == "business_rules":
            conn.execute("""INSERT INTO ontology.business_rules
              (business_rule_id,ontology_version_id,code,name,description,subject_object_id,expression_language,expression,evaluator_key,rule_version,effective_from,effective_to,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
              (uuid4(),new_id,item["code"],item["name"],item["description"],object_map[item["subject_object_id"]],item["expression_language"],json.dumps(item["expression"]),item["evaluator_key"],item["rule_version"],item["effective_from"],item["effective_to"],item["concept_id"]))
        else:
            conn.execute("""INSERT INTO ontology.metrics
              (metric_id,ontology_version_id,code,name,description,subject_object_id,formula,aggregation,grain,dimensions,unit,time_basis,metric_version,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s)""",
              (uuid4(),new_id,item["code"],item["name"],item["description"],object_map[item["subject_object_id"]],json.dumps(item["formula"]),item["aggregation"],json.dumps(item["grain"]),json.dumps(item["dimensions"]),item["unit"],item["time_basis"],item["metric_version"],item["concept_id"]))

    def get_version(self, version_id: UUID) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            version = conn.execute("SELECT v.*,o.namespace,o.name AS ontology_name FROM ontology.ontology_versions v JOIN ontology.ontologies o USING (ontology_id) WHERE ontology_version_id=%s", (version_id,)).fetchone()
            if version is None: raise KeyError(str(version_id))
            objects = conn.execute("""SELECT bo.*,c.stable_key FROM ontology.business_objects bo
              JOIN ontology.concepts c USING (concept_id)
              WHERE bo.ontology_version_id=%s ORDER BY bo.code""", (version_id,)).fetchall()
            result = _jsonable(dict(version)); result["objects"] = []
            for raw in objects:
                item = _jsonable(dict(raw))
                item["properties"] = [_jsonable(dict(p)) for p in conn.execute("""SELECT p.*,c.stable_key
                  FROM ontology.object_properties p JOIN ontology.concepts c USING (concept_id)
                  WHERE p.business_object_id=%s ORDER BY p.code""", (raw["business_object_id"],)).fetchall()]
                result["objects"].append(item)
            for key, table in (("relationships","relationship_types"),("rules","business_rules"),("metrics","metrics")):
                result[key] = [_jsonable(dict(x)) for x in conn.execute(f"""SELECT x.*,c.stable_key
                  FROM ontology.{table} x JOIN ontology.concepts c USING (concept_id)
                  WHERE x.ontology_version_id=%s ORDER BY x.code""", (version_id,)).fetchall()]
            return result

    def add_item(self, version_id: UUID, *, kind: str, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            version = conn.execute("SELECT v.*,o.namespace FROM ontology.ontology_versions v JOIN ontology.ontologies o USING (ontology_id) WHERE ontology_version_id=%s FOR UPDATE",(version_id,)).fetchone()
            if version is None: raise KeyError(str(version_id))
            if version["status"] != "draft": raise ValueError("Only draft ontology versions are editable")
            stable_key = payload.get("stable_key") or f"{version['namespace']}.{payload['code']}"
            concept = conn.execute("SELECT * FROM ontology.concepts WHERE ontology_id=%s AND stable_key=%s",(version["ontology_id"],stable_key)).fetchone()
            concept_id = concept["concept_id"] if concept else uuid4()
            if concept is None:
                conn.execute("INSERT INTO ontology.concepts (concept_id,ontology_id,concept_kind,stable_key) VALUES (%s,%s,%s,%s)",(concept_id,version["ontology_id"],kind,stable_key))
            elif concept["concept_kind"] != kind:
                raise ValueError("Stable key already belongs to a different concept kind")
            row = self._insert_item(conn, version_id, kind, concept_id, payload)
            self._audit(conn,version_id,concept_id,f"{kind}_created",actor,None,payload)
        return _jsonable(dict(row))

    def update_item(self, version_id: UUID, *, kind: str, concept_id: UUID, changes: dict[str, Any], actor: str) -> dict[str, Any]:
        table, id_col, allowed = {
            "object": ("business_objects","business_object_id",{"code","name","description","identity_policy"}),
            "property": ("object_properties","property_id",{"code","name","description","value_type","cardinality","unit","temporal"}),
            "relationship": ("relationship_types","relationship_type_id",{"code","name","source_cardinality","target_cardinality","temporal","transitive"}),
            "rule": ("business_rules","business_rule_id",{"code","name","description","expression_language","expression","evaluator_key","rule_version","effective_from","effective_to"}),
            "metric": ("metrics","metric_id",{"code","name","description","formula","aggregation","grain","dimensions","unit","time_basis","metric_version"}),
        }[kind]
        invalid=set(changes)-allowed
        if invalid or not changes: raise ValueError(f"Invalid {kind} changes: {sorted(invalid)}")
        with psycopg.connect(self.database_url,row_factory=dict_row) as conn:
            self._require_draft(conn,version_id)
            if kind == "property":
                current=conn.execute("SELECT p.* FROM ontology.object_properties p JOIN ontology.business_objects b USING (business_object_id) WHERE b.ontology_version_id=%s AND p.concept_id=%s",(version_id,concept_id)).fetchone()
            else:
                current=conn.execute(f"SELECT * FROM ontology.{table} WHERE ontology_version_id=%s AND concept_id=%s",(version_id,concept_id)).fetchone()
            if current is None: raise KeyError(str(concept_id))
            values=[]; assignments=[]
            for key,value in changes.items():
                assignments.append(f"{key}=%s")
                values.append(json.dumps(value) if key in {"identity_policy","expression","formula","grain","dimensions"} else value)
            values.append(current[id_col])
            row=conn.execute(f"UPDATE ontology.{table} SET {','.join(assignments)} WHERE {id_col}=%s RETURNING *",tuple(values)).fetchone()
            self._audit(conn,version_id,concept_id,f"{kind}_updated",actor,_jsonable(dict(current)),changes)
        return _jsonable(dict(row))

    def delete_item(self, version_id: UUID, *, kind: str, concept_id: UUID, actor: str) -> None:
        table,id_col={"object":("business_objects","business_object_id"),"property":("object_properties","property_id"),"relationship":("relationship_types","relationship_type_id"),"rule":("business_rules","business_rule_id"),"metric":("metrics","metric_id")}[kind]
        with psycopg.connect(self.database_url,row_factory=dict_row) as conn:
            self._require_draft(conn,version_id)
            if kind == "property":
                current=conn.execute("SELECT p.* FROM ontology.object_properties p JOIN ontology.business_objects b USING (business_object_id) WHERE b.ontology_version_id=%s AND p.concept_id=%s",(version_id,concept_id)).fetchone()
            else:
                current=conn.execute(f"SELECT * FROM ontology.{table} WHERE ontology_version_id=%s AND concept_id=%s",(version_id,concept_id)).fetchone()
            if current is None: raise KeyError(str(concept_id))
            conn.execute(f"DELETE FROM ontology.{table} WHERE {id_col}=%s",(current[id_col],))
            self._audit(conn,version_id,concept_id,f"{kind}_removed",actor,_jsonable(dict(current)),None)

    @staticmethod
    def _require_draft(conn, version_id: UUID) -> None:
        row=conn.execute("SELECT status FROM ontology.ontology_versions WHERE ontology_version_id=%s",(version_id,)).fetchone()
        if row is None: raise KeyError(str(version_id))
        if row["status"] != "draft": raise ValueError("Only draft ontology versions are editable")

    def _object_revision_id(self, conn, version_id: UUID, concept_id: UUID) -> UUID:
        row=conn.execute("SELECT business_object_id FROM ontology.business_objects WHERE ontology_version_id=%s AND concept_id=%s",(version_id,concept_id)).fetchone()
        if row is None: raise ValueError(f"Object concept is not a member of this version: {concept_id}")
        return row["business_object_id"]

    def _insert_item(self, conn, version_id: UUID, kind: str, concept_id: UUID, p: dict[str, Any]):
        if kind == "object":
            return conn.execute("""INSERT INTO ontology.business_objects
              (business_object_id,ontology_version_id,code,name,description,identity_policy,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s::jsonb,'draft',%s) RETURNING *""",
              (uuid4(),version_id,p["code"],p["name"],p.get("description",""),json.dumps(p.get("identity_policy",{})),concept_id)).fetchone()
        if kind == "property":
            owner=self._object_revision_id(conn,version_id,UUID(str(p["object_concept_id"])))
            return conn.execute("""INSERT INTO ontology.object_properties
              (property_id,business_object_id,code,name,description,value_type,cardinality,unit,temporal,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING *""",
              (uuid4(),owner,p["code"],p["name"],p.get("description",""),p["value_type"],p.get("cardinality","optional"),p.get("unit"),p.get("temporal",False),concept_id)).fetchone()
        subject=self._object_revision_id(conn,version_id,UUID(str(p.get("subject_object_concept_id") or p.get("source_object_concept_id"))))
        if kind == "relationship":
            target=self._object_revision_id(conn,version_id,UUID(str(p["target_object_concept_id"])))
            return conn.execute("""INSERT INTO ontology.relationship_types
              (relationship_type_id,ontology_version_id,code,name,source_object_id,target_object_id,source_cardinality,target_cardinality,temporal,transitive,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft',%s) RETURNING *""",
              (uuid4(),version_id,p["code"],p["name"],subject,target,p.get("source_cardinality","many"),p.get("target_cardinality","many"),p.get("temporal",False),p.get("transitive",False),concept_id)).fetchone()
        if kind == "rule":
            return conn.execute("""INSERT INTO ontology.business_rules
              (business_rule_id,ontology_version_id,code,name,description,subject_object_id,expression_language,expression,evaluator_key,rule_version,effective_from,effective_to,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,'draft',%s) RETURNING *""",
              (uuid4(),version_id,p["code"],p["name"],p.get("description",""),subject,p["expression_language"],json.dumps(p["expression"]),p.get("evaluator_key"),p.get("rule_version","1.0"),p.get("effective_from"),p.get("effective_to"),concept_id)).fetchone()
        if kind == "metric":
            return conn.execute("""INSERT INTO ontology.metrics
              (metric_id,ontology_version_id,code,name,description,subject_object_id,formula,aggregation,grain,dimensions,unit,time_basis,metric_version,status,concept_id)
              VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb,%s::jsonb,%s,%s,%s,'draft',%s) RETURNING *""",
              (uuid4(),version_id,p["code"],p["name"],p.get("description",""),subject,json.dumps(p["formula"]),p["aggregation"],json.dumps(p.get("grain",[])),json.dumps(p.get("dimensions",[])),p.get("unit"),p.get("time_basis"),p.get("metric_version","1.0"),concept_id)).fetchone()
        raise ValueError(f"Unsupported ontology item kind: {kind}")

    def validate(self, version_id: UUID) -> dict[str, Any]:
        version = self.get_version(version_id)
        diagnostics: list[dict[str, str]] = []
        object_ids = {x["business_object_id"] for x in version["objects"]}
        for rel in version["relationships"]:
            if rel["source_object_id"] not in object_ids or rel["target_object_id"] not in object_ids:
                diagnostics.append({"code":"relationship_endpoint_missing","path":rel["code"]})
        for obj in version["objects"]:
            if not obj["properties"]:
                diagnostics.append({"code":"object_has_no_properties","path":obj["code"],"severity":"warning"})
        impact = self.binding_impact(version_id)
        diagnostics.extend({"code":"bound_concept_missing","path":x["stable_key"],"severity":"error"} for x in impact["incompatible_bindings"])
        errors = [x for x in diagnostics if x.get("severity", "error") == "error"]
        return {"status":"valid" if not errors else "invalid","diagnostic_count":len(diagnostics),"diagnostics":diagnostics,"binding_impact":impact}

    def binding_impact(self, version_id: UUID) -> dict[str, Any]:
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            rows = conn.execute("""WITH selected_ontology AS (
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
              WHERE ob.status='approved' AND m.concept_id IS NULL""", (version_id,)*6).fetchall()
        return {"compatible":not rows,"incompatible_binding_count":len(rows),"incompatible_bindings":[_jsonable(dict(x)) for x in rows]}

    def transition(self, version_id: UUID, *, action: str, actor: str, comment: str | None = None) -> dict[str, Any]:
        transitions = {
            ("draft", "submit"): "in_review",
            ("in_review", "request_changes"): "draft",
            ("in_review", "approve"): "approved",
            ("approved", "revoke"): "draft",
            ("published", "deprecate"): "deprecated",
        }
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            current = conn.execute("SELECT * FROM ontology.ontology_versions WHERE ontology_version_id=%s FOR UPDATE", (version_id,)).fetchone()
            if current is None: raise KeyError(str(version_id))
            next_status = transitions.get((current["status"], action))
            if next_status is None: raise ValueError(f"Cannot {action} version in {current['status']} status")
            if action in {"submit","approve"} and self.validate(version_id)["status"] != "valid": raise ValueError("Ontology version validation failed")
            if action == "deprecate":
                active_bindings = conn.execute(
                    """SELECT count(*) AS count
                         FROM binding.ontology_bindings ob
                         JOIN ontology.concepts c ON c.concept_id=ob.ontology_concept_id
                        WHERE c.ontology_id=%s AND ob.status='approved'""",
                    (current["ontology_id"],),
                ).fetchone()["count"]
                if active_bindings:
                    raise ValueError(
                        f"Cannot deprecate ontology with {active_bindings} approved bindings"
                    )
            if action in {"approve","request_changes"}:
                conn.execute("INSERT INTO ontology.version_reviews VALUES (%s,%s,%s,%s,%s,now())", (uuid4(),version_id,"approve" if action=="approve" else "request_changes",actor,comment))
            row = conn.execute("UPDATE ontology.ontology_versions SET status=%s WHERE ontology_version_id=%s RETURNING *", (next_status,version_id)).fetchone()
            self._audit(conn,version_id,None,action,actor,{"status":current["status"]},{"status":next_status},comment)
        return _jsonable(dict(row))

    def publish(self, version_id: UUID, *, actor: str) -> dict[str, Any]:
        validation = self.validate(version_id)
        if validation["status"] != "valid": raise ValueError("Ontology version validation failed")
        content = self.get_version(version_id)
        artifact_body = {key:content[key] for key in ("namespace","version","objects","relationships","rules","metrics")}
        encoded = json.dumps(artifact_body, ensure_ascii=False, sort_keys=True, separators=(",",":"), default=str)
        checksum = hashlib.sha256(encoded.encode()).hexdigest()
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            current = conn.execute("SELECT * FROM ontology.ontology_versions WHERE ontology_version_id=%s FOR UPDATE", (version_id,)).fetchone()
            if current is None: raise KeyError(str(version_id))
            if current["status"] != "approved": raise ValueError("Only approved ontology versions can be published")
            conn.execute("UPDATE ontology.ontology_versions SET status='deprecated' WHERE ontology_id=%s AND status='published'", (current["ontology_id"],))
            row = conn.execute("UPDATE ontology.ontology_versions SET status='published',published_at=now() WHERE ontology_version_id=%s RETURNING *", (version_id,)).fetchone()
            artifact = conn.execute("INSERT INTO ontology.runtime_artifacts VALUES (%s,%s,'json','1.0',%s,%s::jsonb,%s,now()) RETURNING artifact_id,checksum,schema_version,created_at", (uuid4(),version_id,checksum,encoded,actor)).fetchone()
            self._audit(conn,version_id,None,"published",actor,{"status":"approved"},{"status":"published","checksum":checksum})
        result=_jsonable(dict(row)); result["artifact"]=_jsonable(dict(artifact)); return result

    def diff(self, version_id: UUID, against: UUID) -> dict[str, Any]:
        left, right = self.get_version(against), self.get_version(version_id)
        def flatten(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
            items: dict[str, dict[str, Any]] = {}
            object_concepts = {obj["business_object_id"]: obj["concept_id"] for obj in value["objects"]}
            for obj in value["objects"]:
                items[f"object:{obj['concept_id']}"]={k:v for k,v in obj.items() if k != "properties"}
                for prop in obj["properties"]: items[f"property:{prop['concept_id']}"]=prop
            for kind,key in (("relationship","relationships"),("rule","rules"),("metric","metrics")):
                for item in value[key]:
                    normalized=dict(item)
                    for field in ("source_object_id","target_object_id","subject_object_id"):
                        if field in normalized: normalized[field.replace("_id","_concept_id")]=object_concepts.get(normalized.pop(field))
                    items[f"{kind}:{item['concept_id']}"]=normalized
            return items
        a,b=flatten(left),flatten(right)
        return {"added":sorted(set(b)-set(a)),"removed":sorted(set(a)-set(b)),"changed":sorted(k for k in set(a)&set(b) if _semantic(a[k]) != _semantic(b[k]))}

    def audit(self, version_id: UUID) -> list[dict[str, Any]]:
        with psycopg.connect(self.database_url,row_factory=dict_row) as conn:
            rows=conn.execute("SELECT * FROM ontology.audit_events WHERE ontology_version_id=%s ORDER BY created_at",(version_id,)).fetchall()
        return [_jsonable(dict(x)) for x in rows]

    @staticmethod
    def _audit(conn, version_id, concept_id, event_type, actor, before, after, reason=None):
        conn.execute("INSERT INTO ontology.audit_events VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,now())",(uuid4(),version_id,concept_id,event_type,actor,json.dumps(before) if before is not None else None,json.dumps(after) if after is not None else None,reason))


def _semantic(value: dict[str, Any]) -> str:
    ignored={"business_object_id","property_id","relationship_type_id","business_rule_id","metric_id","ontology_version_id","status","concept_id"}
    return json.dumps({k:v for k,v in value.items() if k not in ignored},sort_keys=True,default=str)


def _jsonable(value: dict[str, Any]) -> dict[str, Any]:
    for key,item in tuple(value.items()):
        if hasattr(item,"isoformat"): value[key]=item.isoformat()
        elif not isinstance(item,(str,int,float,bool,list,dict,type(None))): value[key]=str(item)
    return value
