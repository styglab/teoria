-- Numeric observation projections only. Source and extracted bodies remain in object storage.
CREATE TABLE public_procurement.specification_requirement_observations (
    observation_id text NOT NULL,
    snapshot_id text NOT NULL,
    run_id text NOT NULL,
    document_id text NOT NULL,
    source_sha256 text NOT NULL,
    subject_observation_id text NOT NULL,
    subject_name text NOT NULL,
    subject_concept_id text NOT NULL,
    subject_concept_key text NOT NULL,
    property_concept_id text NOT NULL,
    property_stable_key text NOT NULL,
    operator text NOT NULL,
    unit text NOT NULL,
    role text NOT NULL,
    semantic_scope text NOT NULL,
    value_raw text NOT NULL,
    unit_raw text NOT NULL,
    profile_revision_id text NOT NULL,
    profile_key text NOT NULL,
    profile_version text NOT NULL,
    package_checksum text NOT NULL,
    ontology_version_id text NOT NULL,
    ontology_namespace text NOT NULL,
    ontology_version text NOT NULL,
    ontology_checksum text NOT NULL,
    extraction_uri text NOT NULL,
    extraction_sha256 text NOT NULL,
    normalized_uri text NOT NULL,
    normalized_sha256 text NOT NULL,
    evidence_ref text NOT NULL,
    value_decimal numeric NOT NULL,
    evidence_node_ids text[] NOT NULL,
    qualifiers_raw text[] NOT NULL,
    owner_observation_id text NOT NULL,
    owner_name text NOT NULL,
    owner_concept_key text NOT NULL,
    document_status text NOT NULL CHECK (document_status IN ('extracted', 'partial')),
    PRIMARY KEY (observation_id, subject_observation_id),
    FOREIGN KEY (run_id) REFERENCES public_procurement.specification_processing_runs(run_id),
    CHECK (operator IN ('eq','gte','lte','gt','lt')),
    CHECK (value_decimal::text NOT IN ('NaN', 'Infinity', '-Infinity'))
);
CREATE INDEX specification_observations_snapshot_idx
    ON public_procurement.specification_requirement_observations(snapshot_id);
CREATE INDEX specification_observations_memory_idx
    ON public_procurement.specification_requirement_observations
    (property_stable_key, role, semantic_scope, unit, operator, value_decimal);
CREATE VIEW public_procurement.server_requirement_observations AS
    SELECT observations.*, runs.status AS run_status
      FROM public_procurement.specification_requirement_observations observations
      JOIN public_procurement.specification_processing_runs runs USING (run_id)
     WHERE runs.status IN ('completed', 'partial')
       AND runs.classification_code = '4321150102'
       AND observations.owner_concept_key = 'computer_server.server';
GRANT SELECT ON public_procurement.server_requirement_observations TO teoria_runtime;
