-- Desired and observed serving references; MLflow remains authoritative for model versions.
CREATE SCHEMA IF NOT EXISTS mlops;
CREATE TABLE mlops.deployments (
    deployment_id text PRIMARY KEY,
    backend text NOT NULL CHECK (backend IN ('docker', 'kubernetes')),
    specification jsonb NOT NULL,
    previous_specification jsonb,
    status text NOT NULL CHECK (status IN ('ready', 'stopped', 'failed')),
    endpoint text NOT NULL,
    requested_by text NOT NULL,
    prefect_run_id text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
