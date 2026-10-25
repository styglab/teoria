CREATE SCHEMA IF NOT EXISTS policy;

CREATE TABLE policy.opa_decision_logs (
    decision_id text PRIMARY KEY,
    labels jsonb NOT NULL DEFAULT '{}'::jsonb,
    bundles jsonb NOT NULL DEFAULT '{}'::jsonb,
    decision_path text,
    input_document jsonb,
    result_document jsonb,
    requested_by text,
    decided_at timestamptz,
    event jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX opa_decision_logs_decided_at_idx
    ON policy.opa_decision_logs (decided_at DESC);

CREATE TABLE policy.opa_status_reports (
    instance_id text PRIMARY KEY,
    report jsonb NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE policy.opa_decision_logs IS
    'Append-only OPA decision telemetry; sensitive capability inputs are removed by bundle policy.';
COMMENT ON TABLE policy.opa_status_reports IS
    'Latest OPA bundle, decision-log and plugin status per OPA instance.';
