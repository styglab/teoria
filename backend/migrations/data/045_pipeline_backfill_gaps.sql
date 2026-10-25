CREATE TABLE ingestion.pipeline_backfill_gaps (
    pipeline_id text NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    operation_id text NOT NULL,
    error_code text NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    next_retry_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pipeline_id, window_start, window_end, operation_id)
);

CREATE INDEX pipeline_backfill_gaps_retry_idx
    ON ingestion.pipeline_backfill_gaps (next_retry_at, window_start)
    WHERE resolved_at IS NULL;
