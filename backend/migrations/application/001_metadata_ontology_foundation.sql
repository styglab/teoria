CREATE SCHEMA IF NOT EXISTS ontology;
CREATE SCHEMA IF NOT EXISTS binding;
CREATE SCHEMA IF NOT EXISTS intelligence;
CREATE SCHEMA IF NOT EXISTS capability;
CREATE SCHEMA IF NOT EXISTS context;

CREATE TABLE ontology.ontologies (
    ontology_id uuid PRIMARY KEY,
    namespace text NOT NULL UNIQUE,
    name text NOT NULL,
    description text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ontology.ontology_versions (
    ontology_version_id uuid PRIMARY KEY,
    ontology_id uuid NOT NULL REFERENCES ontology.ontologies(ontology_id),
    version text NOT NULL,
    status text NOT NULL CHECK (status IN ('draft','in_review','published','deprecated')),
    based_on_version_id uuid REFERENCES ontology.ontology_versions(ontology_version_id),
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    UNIQUE (ontology_id, version)
);

CREATE UNIQUE INDEX one_published_ontology_version
    ON ontology.ontology_versions (ontology_id) WHERE status = 'published';

CREATE TABLE ontology.business_objects (
    business_object_id uuid PRIMARY KEY,
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions(ontology_version_id) ON DELETE CASCADE,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    identity_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL CHECK (status IN ('draft','in_review','published','deprecated')),
    UNIQUE (ontology_version_id, code)
);

CREATE TABLE ontology.object_properties (
    property_id uuid PRIMARY KEY,
    business_object_id uuid NOT NULL REFERENCES ontology.business_objects(business_object_id) ON DELETE CASCADE,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    value_type text NOT NULL,
    cardinality text NOT NULL CHECK (cardinality IN ('one','optional','many')),
    unit text,
    temporal boolean NOT NULL DEFAULT false,
    status text NOT NULL CHECK (status IN ('draft','in_review','published','deprecated')),
    UNIQUE (business_object_id, code)
);

CREATE TABLE ontology.relationship_types (
    relationship_type_id uuid PRIMARY KEY,
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions(ontology_version_id) ON DELETE CASCADE,
    code text NOT NULL,
    name text NOT NULL,
    source_object_id uuid NOT NULL REFERENCES ontology.business_objects(business_object_id),
    target_object_id uuid NOT NULL REFERENCES ontology.business_objects(business_object_id),
    source_cardinality text NOT NULL,
    target_cardinality text NOT NULL,
    inverse_relationship_type_id uuid REFERENCES ontology.relationship_types(relationship_type_id),
    temporal boolean NOT NULL DEFAULT false,
    transitive boolean NOT NULL DEFAULT false,
    status text NOT NULL CHECK (status IN ('draft','in_review','published','deprecated')),
    UNIQUE (ontology_version_id, code)
);

CREATE TABLE ontology.business_rules (
    business_rule_id uuid PRIMARY KEY,
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions(ontology_version_id) ON DELETE CASCADE,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    subject_object_id uuid NOT NULL REFERENCES ontology.business_objects(business_object_id),
    expression_language text NOT NULL,
    expression jsonb NOT NULL,
    evaluator_key text,
    rule_version text NOT NULL,
    effective_from date,
    effective_to date,
    status text NOT NULL CHECK (status IN ('draft','in_review','published','deprecated')),
    UNIQUE (ontology_version_id, code, rule_version)
);

CREATE TABLE ontology.metrics (
    metric_id uuid PRIMARY KEY,
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions(ontology_version_id) ON DELETE CASCADE,
    code text NOT NULL,
    name text NOT NULL,
    description text NOT NULL,
    subject_object_id uuid NOT NULL REFERENCES ontology.business_objects(business_object_id),
    formula jsonb NOT NULL,
    aggregation text NOT NULL,
    grain jsonb NOT NULL,
    dimensions jsonb NOT NULL DEFAULT '[]'::jsonb,
    unit text,
    time_basis text,
    metric_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('draft','in_review','published','deprecated')),
    UNIQUE (ontology_version_id, code, metric_version)
);

CREATE TABLE binding.metadata_references (
    metadata_reference_id uuid PRIMARY KEY,
    provider text NOT NULL CHECK (provider IN ('openmetadata')),
    external_entity_id text NOT NULL,
    entity_type text NOT NULL,
    fully_qualified_name text,
    external_version text,
    locator text NOT NULL,
    last_verified_at timestamptz,
    UNIQUE (provider, external_entity_id)
);

CREATE TABLE binding.ontology_bindings (
    binding_id uuid PRIMARY KEY,
    ontology_ref_type text NOT NULL CHECK (ontology_ref_type IN ('object','property','relationship','rule','metric')),
    ontology_ref_id uuid NOT NULL,
    target_type text NOT NULL CHECK (target_type IN ('glossary_term','data_asset','api_field','capability','capability_input','capability_output')),
    metadata_reference_id uuid REFERENCES binding.metadata_references(metadata_reference_id),
    target_locator text NOT NULL,
    target_version text,
    binding_type text NOT NULL,
    purpose text,
    authority text NOT NULL CHECK (authority IN ('authoritative','preferred','supplemental')),
    priority integer NOT NULL DEFAULT 100,
    condition jsonb NOT NULL DEFAULT '{}'::jsonb,
    confidence numeric CHECK (confidence BETWEEN 0 AND 1),
    status text NOT NULL CHECK (status IN ('draft','approved','deprecated')),
    valid_from date,
    valid_to date,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by text NOT NULL,
    approved_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE INDEX ontology_bindings_ref_idx ON binding.ontology_bindings (ontology_ref_type, ontology_ref_id);
CREATE INDEX ontology_bindings_target_idx ON binding.ontology_bindings (target_type, target_locator);

CREATE TABLE intelligence.suggestions (
    suggestion_id uuid PRIMARY KEY,
    target_type text NOT NULL,
    target_ref text NOT NULL,
    suggestion_type text NOT NULL,
    proposed_value jsonb NOT NULL,
    confidence numeric NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    rationale text,
    risk_level text NOT NULL CHECK (risk_level IN ('low','medium','high')),
    model_provider text NOT NULL,
    model_name text NOT NULL,
    model_version text,
    policy_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('pending','approved','rejected','changes_requested','applied','failed')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE intelligence.suggestion_evidence (
    evidence_id uuid PRIMARY KEY,
    suggestion_id uuid NOT NULL REFERENCES intelligence.suggestions(suggestion_id) ON DELETE CASCADE,
    evidence_type text NOT NULL,
    source_ref text NOT NULL,
    excerpt text,
    content_hash text,
    observed_at timestamptz NOT NULL,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE intelligence.reviews (
    review_id uuid PRIMARY KEY,
    suggestion_id uuid NOT NULL REFERENCES intelligence.suggestions(suggestion_id),
    decision text NOT NULL CHECK (decision IN ('approve','reject','request_changes','supersede')),
    reviewer text NOT NULL,
    comment text,
    reviewed_at timestamptz NOT NULL DEFAULT now(),
    resulting_change_ref text
);

CREATE TABLE intelligence.change_applications (
    change_application_id uuid PRIMARY KEY,
    suggestion_id uuid NOT NULL REFERENCES intelligence.suggestions(suggestion_id),
    target_system text NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('approved','applying','applied','failed')),
    external_change_ref text,
    error_code text,
    attempted_at timestamptz,
    applied_at timestamptz
);

COMMENT ON SCHEMA ontology IS 'Teoria-owned business ontology definitions; not physical metadata.';
COMMENT ON SCHEMA binding IS 'References and semantic bindings; OpenMetadata entities are not replicated.';
COMMENT ON SCHEMA intelligence IS 'AI suggestions, evidence, reviews, and approved change application state.';
