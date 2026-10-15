CREATE TABLE intelligence.asset_assessments (
    assessment_id uuid PRIMARY KEY,
    target_ref jsonb NOT NULL,
    scopes text[] NOT NULL,
    column_names text[] NOT NULL DEFAULT '{}',
    assessment_date date NOT NULL,
    disclosure_context text NOT NULL,
    requested_by text NOT NULL,
    request_key text NOT NULL,
    status text NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued','running','completed','partial','failed')),
    model_name text NOT NULL,
    policy_version text NOT NULL DEFAULT 'asset_assessment_v1',
    attempts integer NOT NULL DEFAULT 0,
    claim_token uuid,
    lease_until timestamptz,
    error_code text,
    findings jsonb NOT NULL DEFAULT '[]',
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);
CREATE UNIQUE INDEX asset_assessments_active_request
    ON intelligence.asset_assessments(request_key)
    WHERE status IN ('queued','running');
CREATE INDEX asset_assessments_claim
    ON intelligence.asset_assessments(created_at) WHERE status IN ('queued','running');
CREATE INDEX asset_assessments_target
    ON intelligence.asset_assessments((target_ref->>'entity_id'),created_at DESC);
CREATE INDEX suggestions_pending_target
    ON intelligence.suggestions(target_ref,suggestion_type) WHERE status='pending';
CREATE TABLE intelligence.asset_assessment_suggestions (
    assessment_id uuid NOT NULL REFERENCES intelligence.asset_assessments,
    suggestion_id uuid NOT NULL REFERENCES intelligence.suggestions,
    PRIMARY KEY (assessment_id,suggestion_id)
);
