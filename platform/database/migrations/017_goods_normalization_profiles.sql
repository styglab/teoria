CREATE SCHEMA IF NOT EXISTS goods;

CREATE TABLE goods.normalization_profile_revisions (
    revision_id uuid PRIMARY KEY,
    profile_key text NOT NULL,
    version text NOT NULL,
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions,
    status text NOT NULL DEFAULT 'draft'
      CHECK (status IN ('draft','in_review','approved','rejected','deprecated')),
    content jsonb NOT NULL,
    content_checksum text NOT NULL,
    package jsonb,
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (profile_key,version),
    CHECK (status NOT IN ('approved','deprecated') OR package IS NOT NULL)
);

CREATE TABLE goods.normalization_profile_events (
    event_id uuid PRIMARY KEY,
    revision_id uuid NOT NULL REFERENCES goods.normalization_profile_revisions,
    action text NOT NULL,
    actor text NOT NULL,
    content_checksum text NOT NULL,
    comment text,
    created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE goods.normalization_profile_revisions IS
 'Goods normalization configuration referencing stable published concepts; never a duplicate Ontology or per-document observation store.';
