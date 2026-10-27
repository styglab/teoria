-- Explicit operator reset authorized by the user on 2026-10-27.
-- psql -v apply=false performs the same guarded deletion with a final ROLLBACK.
\set ON_ERROR_STOP on
BEGIN ISOLATION LEVEL REPEATABLE READ;
CREATE TEMP TABLE reset_ontologies ON COMMIT DROP AS
 SELECT ontology_id FROM ontology.ontologies WHERE namespace IN ('goods','computer_server');
SELECT ontology_id FROM ontology.ontologies WHERE ontology_id IN (SELECT ontology_id FROM reset_ontologies) FOR UPDATE;
CREATE TEMP TABLE reset_versions ON COMMIT DROP AS SELECT ontology_version_id FROM ontology.ontology_versions WHERE ontology_id IN (SELECT ontology_id FROM reset_ontologies);
CREATE TEMP TABLE reset_concepts ON COMMIT DROP AS SELECT concept_id FROM ontology.concepts WHERE ontology_id IN (SELECT ontology_id FROM reset_ontologies);
CREATE TEMP TABLE reset_objects ON COMMIT DROP AS SELECT business_object_id FROM ontology.business_objects WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions);
CREATE TEMP TABLE reset_profiles ON COMMIT DROP AS SELECT revision_id FROM goods.normalization_profile_revisions WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions);
CREATE TEMP TABLE reset_operations ON COMMIT DROP AS SELECT operation_id FROM goods.semantic_operations WHERE checkpoint->>'ontology_draft_id' IN (SELECT ontology_version_id::text FROM reset_versions) OR checkpoint->>'profile_revision_id' IN (SELECT revision_id::text FROM reset_profiles);
CREATE TEMP TABLE reset_bindings ON COMMIT DROP AS SELECT binding_id,capability_target_id FROM binding.ontology_bindings WHERE ontology_concept_id IN (SELECT concept_id FROM reset_concepts);
DO $$ BEGIN
 IF (SELECT count(*) FROM reset_ontologies)<>2 OR (SELECT count(*) FROM reset_versions)<>3
    OR (SELECT count(*) FROM reset_concepts)<>160 OR (SELECT count(*) FROM reset_profiles)<>3
    OR (SELECT count(*) FROM reset_operations)<>1 OR (SELECT count(*) FROM reset_bindings)<>10 THEN
  RAISE EXCEPTION 'Legacy goods inventory changed; inspect and back up the new scope before reset';
 END IF;
 IF EXISTS (SELECT 1 FROM ontology.relationship_types r WHERE r.ontology_version_id NOT IN (SELECT ontology_version_id FROM reset_versions) AND (r.source_object_id IN (SELECT business_object_id FROM reset_objects) OR r.target_object_id IN (SELECT business_object_id FROM reset_objects))) THEN
  RAISE EXCEPTION 'A protected Ontology refers to a reset object';
 END IF;
END $$;
CREATE FUNCTION pg_temp.rows_hash(query_text text) RETURNS text LANGUAGE plpgsql AS $$
DECLARE result text;
BEGIN
 EXECUTE 'SELECT md5(coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text)::text,''[]'')) FROM ('||query_text||') r' INTO result;
 RETURN result;
END $$;
CREATE TEMP TABLE protected_queries(label text PRIMARY KEY, query_text text) ON COMMIT DROP;
INSERT INTO protected_queries VALUES
 ('ontologies','SELECT * FROM ontology.ontologies t WHERE NOT EXISTS (SELECT 1 FROM reset_ontologies r WHERE r.ontology_id=t.ontology_id)'),
 ('versions','SELECT * FROM ontology.ontology_versions t WHERE NOT EXISTS (SELECT 1 FROM reset_versions r WHERE r.ontology_version_id=t.ontology_version_id)'),
 ('concepts','SELECT * FROM ontology.concepts t WHERE NOT EXISTS (SELECT 1 FROM reset_concepts r WHERE r.concept_id=t.concept_id)'),
 ('objects','SELECT * FROM ontology.business_objects t WHERE NOT EXISTS (SELECT 1 FROM reset_versions r WHERE r.ontology_version_id=t.ontology_version_id)'),
 ('properties','SELECT * FROM ontology.object_properties t WHERE NOT EXISTS (SELECT 1 FROM reset_objects r WHERE r.business_object_id=t.business_object_id)'),
 ('relationships','SELECT * FROM ontology.relationship_types t WHERE NOT EXISTS (SELECT 1 FROM reset_versions r WHERE r.ontology_version_id=t.ontology_version_id)'),
 ('rules','SELECT * FROM ontology.business_rules t WHERE NOT EXISTS (SELECT 1 FROM reset_versions r WHERE r.ontology_version_id=t.ontology_version_id)'),
 ('metrics','SELECT * FROM ontology.metrics t WHERE NOT EXISTS (SELECT 1 FROM reset_versions r WHERE r.ontology_version_id=t.ontology_version_id)'),
 ('artifacts','SELECT * FROM ontology.runtime_artifacts t WHERE NOT EXISTS (SELECT 1 FROM reset_versions r WHERE r.ontology_version_id=t.ontology_version_id)'),
 ('audits','SELECT * FROM ontology.audit_events t WHERE NOT EXISTS (SELECT 1 FROM reset_versions r WHERE r.ontology_version_id=t.ontology_version_id)'),
 ('reviews','SELECT * FROM ontology.version_reviews t WHERE NOT EXISTS (SELECT 1 FROM reset_versions r WHERE r.ontology_version_id=t.ontology_version_id)'),
 ('profiles','SELECT * FROM goods.normalization_profile_revisions t WHERE NOT EXISTS (SELECT 1 FROM reset_profiles r WHERE r.revision_id=t.revision_id)'),
 ('profile_events','SELECT * FROM goods.normalization_profile_events t WHERE NOT EXISTS (SELECT 1 FROM reset_profiles r WHERE r.revision_id=t.revision_id)'),
 ('operations','SELECT * FROM goods.semantic_operations t WHERE NOT EXISTS (SELECT 1 FROM reset_operations r WHERE r.operation_id=t.operation_id)'),
 ('bindings','SELECT * FROM binding.ontology_bindings t WHERE NOT EXISTS (SELECT 1 FROM reset_bindings r WHERE r.binding_id=t.binding_id)'),
 ('binding_reviews','SELECT * FROM binding.binding_reviews t WHERE NOT EXISTS (SELECT 1 FROM reset_bindings r WHERE r.binding_id=t.binding_id)'),
 ('capability_targets','SELECT * FROM binding.capability_targets t WHERE NOT EXISTS (SELECT 1 FROM reset_bindings r WHERE r.capability_target_id=t.capability_target_id)'),
 ('metadata_targets','SELECT * FROM binding.metadata_targets'),
 ('api_field_targets','SELECT * FROM binding.api_field_targets');
CREATE TEMP TABLE protected_before ON COMMIT DROP AS SELECT label,pg_temp.rows_hash(query_text) AS checksum FROM protected_queries;
CREATE TEMP TABLE deletion_counts(table_name text,deleted bigint) ON COMMIT DROP;
WITH d AS (DELETE FROM binding.ontology_bindings WHERE binding_id IN (SELECT binding_id FROM reset_bindings) RETURNING 1) INSERT INTO deletion_counts SELECT 'bindings',count(*) FROM d;
WITH d AS (DELETE FROM binding.capability_targets t WHERE capability_target_id IN (SELECT capability_target_id FROM reset_bindings) AND NOT EXISTS (SELECT 1 FROM binding.ontology_bindings b WHERE b.capability_target_id=t.capability_target_id) RETURNING 1) INSERT INTO deletion_counts SELECT 'unreferenced_capability_targets',count(*) FROM d;
WITH d AS (DELETE FROM goods.normalization_profile_events WHERE revision_id IN (SELECT revision_id FROM reset_profiles) RETURNING 1) INSERT INTO deletion_counts SELECT 'profile_events',count(*) FROM d;
WITH d AS (DELETE FROM goods.normalization_profile_revisions WHERE revision_id IN (SELECT revision_id FROM reset_profiles) RETURNING 1) INSERT INTO deletion_counts SELECT 'profiles',count(*) FROM d;
WITH d AS (DELETE FROM goods.semantic_operations WHERE operation_id IN (SELECT operation_id FROM reset_operations) RETURNING 1) INSERT INTO deletion_counts SELECT 'semantic_operations',count(*) FROM d;
WITH d AS (DELETE FROM ontology.audit_events WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions) RETURNING 1) INSERT INTO deletion_counts SELECT 'audit_events',count(*) FROM d;
DELETE FROM ontology.version_reviews WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions);
DELETE FROM ontology.runtime_artifacts WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions);
-- Published-row guards are disabled only for this explicit purge transaction.
-- Foreign keys stay enabled; rollback restores these transactional DDL changes.
ALTER TABLE ontology.business_objects DISABLE TRIGGER immutable_business_objects;
ALTER TABLE ontology.object_properties DISABLE TRIGGER immutable_object_properties;
ALTER TABLE ontology.relationship_types DISABLE TRIGGER immutable_relationship_types;
ALTER TABLE ontology.business_rules DISABLE TRIGGER immutable_business_rules;
ALTER TABLE ontology.metrics DISABLE TRIGGER immutable_metrics;
DELETE FROM ontology.relationship_types WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions);
DELETE FROM ontology.business_rules WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions);
DELETE FROM ontology.metrics WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions);
DELETE FROM ontology.object_properties WHERE business_object_id IN (SELECT business_object_id FROM reset_objects);
DELETE FROM ontology.business_objects WHERE business_object_id IN (SELECT business_object_id FROM reset_objects);
ALTER TABLE ontology.business_objects ENABLE TRIGGER immutable_business_objects;
ALTER TABLE ontology.object_properties ENABLE TRIGGER immutable_object_properties;
ALTER TABLE ontology.relationship_types ENABLE TRIGGER immutable_relationship_types;
ALTER TABLE ontology.business_rules ENABLE TRIGGER immutable_business_rules;
ALTER TABLE ontology.metrics ENABLE TRIGGER immutable_metrics;
WITH d AS (DELETE FROM ontology.ontology_versions WHERE ontology_version_id IN (SELECT ontology_version_id FROM reset_versions) RETURNING 1) INSERT INTO deletion_counts SELECT 'versions',count(*) FROM d;
WITH d AS (DELETE FROM ontology.concepts WHERE concept_id IN (SELECT concept_id FROM reset_concepts) RETURNING 1) INSERT INTO deletion_counts SELECT 'concepts',count(*) FROM d;
WITH d AS (DELETE FROM ontology.ontologies WHERE ontology_id IN (SELECT ontology_id FROM reset_ontologies) RETURNING 1) INSERT INTO deletion_counts SELECT 'ontologies',count(*) FROM d;
DO $$ DECLARE q record; BEGIN
 FOR q IN SELECT p.label,p.query_text,b.checksum FROM protected_queries p JOIN protected_before b USING(label) LOOP
  IF pg_temp.rows_hash(q.query_text) IS DISTINCT FROM q.checksum THEN RAISE EXCEPTION 'Protected data changed: %',q.label; END IF;
 END LOOP;
END $$;
SELECT jsonb_build_object('deleted',(SELECT jsonb_object_agg(table_name,deleted) FROM deletion_counts),'protected_datasets',(SELECT count(*) FROM protected_before));
\if :apply
 COMMIT;
\else
 ROLLBACK;
\endif
