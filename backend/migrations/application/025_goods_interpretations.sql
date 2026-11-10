-- Only approval state and immutable references live here. Document/result bodies stay in object storage.
CREATE TABLE goods.interpretation_revisions (
    revision_id uuid PRIMARY KEY,
    review_id text NOT NULL UNIQUE,
    request_ref jsonb NOT NULL,
    request_checksum text NOT NULL CHECK (request_checksum ~ '^[a-f0-9]{64}$'),
    profile_revision_id uuid NOT NULL REFERENCES goods.normalization_profile_revisions(revision_id),
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions(ontology_version_id),
    ontology_checksum text NOT NULL CHECK (ontology_checksum ~ '^[a-f0-9]{64}$'),
    package_checksum text NOT NULL CHECK (package_checksum ~ '^[a-f0-9]{64}$'),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','in_review','approved','rejected','deprecated')),
    created_by text NOT NULL,
    approved_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (status NOT IN ('approved','deprecated') OR approved_by IS NOT NULL)
);
CREATE TABLE goods.interpretation_events (
    event_id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES goods.interpretation_revisions(revision_id),
    action text NOT NULL CHECK (action IN ('created','submit','approve','reject','deprecate','apply')),
    event_key text NOT NULL DEFAULT '',
    actor text NOT NULL,
    request_checksum text NOT NULL,
    comment text,
    artifact_ref jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (revision_id, action, event_key)
);
