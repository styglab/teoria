CREATE TABLE authoring.capability_workspace_audit (
    audit_id bigserial PRIMARY KEY,
    workspace_id uuid NOT NULL REFERENCES authoring.capability_workspaces(workspace_id),
    action text NOT NULL,
    changes jsonb NOT NULL DEFAULT '{}'::jsonb,
    actor text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX capability_workspace_audit_workspace_idx
    ON authoring.capability_workspace_audit (workspace_id, created_at);

COMMENT ON TABLE authoring.capability_workspace_audit IS
    'Append-only actor and change history for human Workspace authoring state.';
