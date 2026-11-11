-- Execution settings and import state only; Registry/MLflow retain their authority.
CREATE TABLE mlops.configurations (
    id text PRIMARY KEY,
    revision integer NOT NULL CHECK (revision > 0),
    specification jsonb NOT NULL,
    created_by text NOT NULL,
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE mlops.image_imports (
    id uuid PRIMARY KEY,
    repository text NOT NULL,
    tag text NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    sha256 text,
    archive_uri text,
    status text NOT NULL CHECK (status IN ('created','uploading','uploaded','queued','importing','ready','failed')),
    attempt integer NOT NULL DEFAULT 0,
    image text,
    prefect_run_id text,
    error text,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
