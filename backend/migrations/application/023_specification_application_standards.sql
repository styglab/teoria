-- Approved application versions pin both the processing standard and dictionary.
-- These references do not publish Ontology or copy OpenMetadata entity state.
CREATE TABLE goods.application_standards (
    release_id uuid PRIMARY KEY,
    name text NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    source_run_id text NOT NULL,
    classification_code text CHECK (classification_code IS NULL OR classification_code ~ '^[0-9]{10}$'),
    standard_kind text NOT NULL CHECK (standard_kind IN ('extraction_draft','ontology_profile')),
    standard_ref jsonb NOT NULL,
    dictionary_ref jsonb NOT NULL,
    dictionary_checksum text NOT NULL,
    content_checksum text NOT NULL,
    status text NOT NULL DEFAULT 'approved' CHECK (status IN ('approved','deprecated')),
    approved_by text NOT NULL,
    rationale text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX application_standards_created ON goods.application_standards(created_at DESC, release_id);
