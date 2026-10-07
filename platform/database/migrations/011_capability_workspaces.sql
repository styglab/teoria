CREATE SCHEMA IF NOT EXISTS authoring;

CREATE TABLE authoring.capability_workspaces (
    workspace_id uuid PRIMARY KEY,
    title text NOT NULL CHECK (length(trim(title)) > 0),
    question text NOT NULL CHECK (length(trim(question)) > 0),
    description text,
    capability_id text,
    status text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft','in_progress','in_review','release_ready','released','cancelled')),
    current_stage text NOT NULL DEFAULT 'definition'
        CHECK (current_stage IN ('definition','semantics','data','execution','testing','review','release')),
    created_by text NOT NULL,
    updated_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX capability_workspaces_status_updated_idx
    ON authoring.capability_workspaces (status, updated_at DESC);

COMMENT ON SCHEMA authoring IS
    'Human authoring workflow state; never loaded as a production Runtime contract.';
COMMENT ON TABLE authoring.capability_workspaces IS
    'Capability-centered workspaces that orchestrate authoritative Ontology, Binding, OpenMetadata and Registry changes.';
