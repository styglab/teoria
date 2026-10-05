CREATE TABLE ontology.concepts (
    concept_id uuid PRIMARY KEY,
    ontology_id uuid NOT NULL REFERENCES ontology.ontologies(ontology_id),
    concept_kind text NOT NULL CHECK (concept_kind IN ('object','property','relationship','rule','metric')),
    stable_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    retired_at timestamptz,
    UNIQUE (ontology_id, stable_key)
);

ALTER TABLE ontology.business_objects ADD COLUMN concept_id uuid REFERENCES ontology.concepts(concept_id);
ALTER TABLE ontology.object_properties ADD COLUMN concept_id uuid REFERENCES ontology.concepts(concept_id);
ALTER TABLE ontology.relationship_types ADD COLUMN concept_id uuid REFERENCES ontology.concepts(concept_id);
ALTER TABLE ontology.business_rules ADD COLUMN concept_id uuid REFERENCES ontology.concepts(concept_id);
ALTER TABLE ontology.metrics ADD COLUMN concept_id uuid REFERENCES ontology.concepts(concept_id);

INSERT INTO ontology.concepts (concept_id, ontology_id, concept_kind, stable_key)
SELECT gen_random_uuid(), ov.ontology_id, 'object', o.namespace || '.' || bo.code
  FROM ontology.business_objects bo
  JOIN ontology.ontology_versions ov USING (ontology_version_id)
  JOIN ontology.ontologies o USING (ontology_id)
 GROUP BY ov.ontology_id, o.namespace, bo.code;

UPDATE ontology.business_objects bo SET concept_id = c.concept_id
  FROM ontology.ontology_versions ov, ontology.ontologies o, ontology.concepts c
 WHERE bo.ontology_version_id=ov.ontology_version_id AND ov.ontology_id=o.ontology_id
   AND c.ontology_id=ov.ontology_id AND c.stable_key=o.namespace || '.' || bo.code;

INSERT INTO ontology.concepts (concept_id, ontology_id, concept_kind, stable_key)
SELECT gen_random_uuid(), ov.ontology_id, 'property', o.namespace || '.' || bo.code || '.' || p.code
  FROM ontology.object_properties p
  JOIN ontology.business_objects bo USING (business_object_id)
  JOIN ontology.ontology_versions ov USING (ontology_version_id)
  JOIN ontology.ontologies o USING (ontology_id)
 GROUP BY ov.ontology_id, o.namespace, bo.code, p.code;

UPDATE ontology.object_properties p SET concept_id = c.concept_id
  FROM ontology.business_objects bo, ontology.ontology_versions ov, ontology.ontologies o, ontology.concepts c
 WHERE p.business_object_id=bo.business_object_id AND bo.ontology_version_id=ov.ontology_version_id
   AND ov.ontology_id=o.ontology_id AND c.ontology_id=ov.ontology_id
   AND c.stable_key=o.namespace || '.' || bo.code || '.' || p.code;

INSERT INTO ontology.concepts (concept_id, ontology_id, concept_kind, stable_key)
SELECT gen_random_uuid(), ov.ontology_id, 'relationship', o.namespace || '.' || r.code
  FROM ontology.relationship_types r JOIN ontology.ontology_versions ov USING (ontology_version_id)
  JOIN ontology.ontologies o USING (ontology_id)
 GROUP BY ov.ontology_id, o.namespace, r.code;
UPDATE ontology.relationship_types r SET concept_id=c.concept_id
  FROM ontology.ontology_versions ov, ontology.ontologies o, ontology.concepts c
 WHERE r.ontology_version_id=ov.ontology_version_id AND ov.ontology_id=o.ontology_id
   AND c.ontology_id=ov.ontology_id AND c.stable_key=o.namespace || '.' || r.code;

INSERT INTO ontology.concepts (concept_id, ontology_id, concept_kind, stable_key)
SELECT gen_random_uuid(), ov.ontology_id, 'rule', o.namespace || '.' || r.code
  FROM ontology.business_rules r JOIN ontology.ontology_versions ov USING (ontology_version_id)
  JOIN ontology.ontologies o USING (ontology_id)
 GROUP BY ov.ontology_id, o.namespace, r.code;
UPDATE ontology.business_rules r SET concept_id=c.concept_id
  FROM ontology.ontology_versions ov, ontology.ontologies o, ontology.concepts c
 WHERE r.ontology_version_id=ov.ontology_version_id AND ov.ontology_id=o.ontology_id
   AND c.ontology_id=ov.ontology_id AND c.stable_key=o.namespace || '.' || r.code;

INSERT INTO ontology.concepts (concept_id, ontology_id, concept_kind, stable_key)
SELECT gen_random_uuid(), ov.ontology_id, 'metric', o.namespace || '.' || m.code
  FROM ontology.metrics m JOIN ontology.ontology_versions ov USING (ontology_version_id)
  JOIN ontology.ontologies o USING (ontology_id)
 GROUP BY ov.ontology_id, o.namespace, m.code;
UPDATE ontology.metrics m SET concept_id=c.concept_id
  FROM ontology.ontology_versions ov, ontology.ontologies o, ontology.concepts c
 WHERE m.ontology_version_id=ov.ontology_version_id AND ov.ontology_id=o.ontology_id
   AND c.ontology_id=ov.ontology_id AND c.stable_key=o.namespace || '.' || m.code;

ALTER TABLE ontology.business_objects ALTER COLUMN concept_id SET NOT NULL;
ALTER TABLE ontology.object_properties ALTER COLUMN concept_id SET NOT NULL;
ALTER TABLE ontology.relationship_types ALTER COLUMN concept_id SET NOT NULL;
ALTER TABLE ontology.business_rules ALTER COLUMN concept_id SET NOT NULL;
ALTER TABLE ontology.metrics ALTER COLUMN concept_id SET NOT NULL;
ALTER TABLE ontology.business_objects ADD UNIQUE (ontology_version_id, concept_id);
ALTER TABLE ontology.relationship_types ADD UNIQUE (ontology_version_id, concept_id);
ALTER TABLE ontology.business_rules ADD UNIQUE (ontology_version_id, concept_id);
ALTER TABLE ontology.metrics ADD UNIQUE (ontology_version_id, concept_id);

ALTER TABLE ontology.ontology_versions DROP CONSTRAINT ontology_versions_status_check;
ALTER TABLE ontology.ontology_versions ADD CONSTRAINT ontology_versions_status_check
  CHECK (status IN ('draft','in_review','approved','published','deprecated'));

CREATE TABLE ontology.version_reviews (
    review_id uuid PRIMARY KEY,
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions(ontology_version_id),
    decision text NOT NULL CHECK (decision IN ('approve','reject','request_changes')),
    reviewer text NOT NULL,
    comment text,
    reviewed_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ontology.audit_events (
    audit_event_id uuid PRIMARY KEY,
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions(ontology_version_id),
    concept_id uuid REFERENCES ontology.concepts(concept_id),
    event_type text NOT NULL,
    actor text NOT NULL,
    before_value jsonb,
    after_value jsonb,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ontology.runtime_artifacts (
    artifact_id uuid PRIMARY KEY,
    ontology_version_id uuid NOT NULL UNIQUE REFERENCES ontology.ontology_versions(ontology_version_id),
    artifact_format text NOT NULL CHECK (artifact_format IN ('json')),
    schema_version text NOT NULL,
    checksum text NOT NULL,
    content jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE binding.ontology_bindings ADD COLUMN ontology_concept_id uuid REFERENCES ontology.concepts(concept_id);
UPDATE binding.ontology_bindings ob SET ontology_concept_id = CASE ob.ontology_ref_type
  WHEN 'object' THEN (SELECT concept_id FROM ontology.business_objects WHERE business_object_id=ob.ontology_ref_id)
  WHEN 'property' THEN (SELECT concept_id FROM ontology.object_properties WHERE property_id=ob.ontology_ref_id)
  WHEN 'relationship' THEN (SELECT concept_id FROM ontology.relationship_types WHERE relationship_type_id=ob.ontology_ref_id)
  WHEN 'rule' THEN (SELECT concept_id FROM ontology.business_rules WHERE business_rule_id=ob.ontology_ref_id)
  WHEN 'metric' THEN (SELECT concept_id FROM ontology.metrics WHERE metric_id=ob.ontology_ref_id)
END;
ALTER TABLE binding.ontology_bindings ALTER COLUMN ontology_concept_id SET NOT NULL;
CREATE INDEX ontology_bindings_concept_idx ON binding.ontology_bindings (ontology_concept_id, status);

CREATE OR REPLACE FUNCTION ontology.require_draft_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_status text;
BEGIN
  SELECT status INTO version_status FROM ontology.ontology_versions
   WHERE ontology_version_id=COALESCE(NEW.ontology_version_id, OLD.ontology_version_id);
  IF version_status IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'ontology revision is immutable unless version is draft';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;

CREATE TRIGGER immutable_business_objects BEFORE INSERT OR UPDATE OR DELETE ON ontology.business_objects
FOR EACH ROW EXECUTE FUNCTION ontology.require_draft_version();
CREATE TRIGGER immutable_relationship_types BEFORE INSERT OR UPDATE OR DELETE ON ontology.relationship_types
FOR EACH ROW EXECUTE FUNCTION ontology.require_draft_version();
CREATE TRIGGER immutable_business_rules BEFORE INSERT OR UPDATE OR DELETE ON ontology.business_rules
FOR EACH ROW EXECUTE FUNCTION ontology.require_draft_version();
CREATE TRIGGER immutable_metrics BEFORE INSERT OR UPDATE OR DELETE ON ontology.metrics
FOR EACH ROW EXECUTE FUNCTION ontology.require_draft_version();

CREATE OR REPLACE FUNCTION ontology.require_draft_property_version() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_status text;
BEGIN
  SELECT ov.status INTO version_status FROM ontology.business_objects bo
    JOIN ontology.ontology_versions ov USING (ontology_version_id)
   WHERE bo.business_object_id=COALESCE(NEW.business_object_id, OLD.business_object_id);
  IF version_status IS DISTINCT FROM 'draft' THEN
    RAISE EXCEPTION 'ontology property revision is immutable unless version is draft';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER immutable_object_properties BEFORE INSERT OR UPDATE OR DELETE ON ontology.object_properties
FOR EACH ROW EXECUTE FUNCTION ontology.require_draft_property_version();
