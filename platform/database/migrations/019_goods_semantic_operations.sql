-- Durable authoring suggestions/checkpoints; no raw document corpus is replicated.
CREATE TABLE goods.semantic_operations (
    operation_id text PRIMARY KEY CHECK (operation_id ~ '^[a-z][a-z0-9_]{0,79}$'),
    input_checksum text NOT NULL,
    actor text NOT NULL,
    status text NOT NULL CHECK (status IN ('running','awaiting_approval','approved','held','rejected','failed')),
    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
