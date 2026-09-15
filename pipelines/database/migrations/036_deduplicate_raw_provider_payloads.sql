CREATE TABLE ingestion.raw_provider_payloads (
    connector_id text NOT NULL,
    operation_id text NOT NULL,
    source_record_hash text NOT NULL,
    payload jsonb NOT NULL,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    PRIMARY KEY (connector_id, operation_id, source_record_hash)
);

CREATE TABLE ingestion.raw_provider_observations (
    observation_id uuid PRIMARY KEY,
    execution_id uuid NOT NULL REFERENCES ingestion.pipeline_runs(execution_id),
    connector_id text NOT NULL,
    operation_id text NOT NULL,
    source_record_hash text NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    fetched_at timestamptz NOT NULL,
    UNIQUE (execution_id, connector_id, operation_id, source_record_hash),
    FOREIGN KEY (connector_id, operation_id, source_record_hash)
        REFERENCES ingestion.raw_provider_payloads (
            connector_id, operation_id, source_record_hash
        )
);

CREATE INDEX raw_provider_payloads_last_seen_idx
    ON ingestion.raw_provider_payloads (last_seen_at DESC);

CREATE INDEX raw_provider_observations_execution_idx
    ON ingestion.raw_provider_observations (execution_id);

CREATE INDEX raw_provider_observations_payload_idx
    ON ingestion.raw_provider_observations (
        connector_id, operation_id, source_record_hash
    );

INSERT INTO ingestion.raw_provider_payloads (
    connector_id,
    operation_id,
    source_record_hash,
    payload,
    first_seen_at,
    last_seen_at
)
SELECT DISTINCT ON (connector_id, operation_id, source_record_hash)
    connector_id,
    operation_id,
    source_record_hash,
    payload,
    min(fetched_at) OVER payload_partition,
    max(fetched_at) OVER payload_partition
FROM ingestion.raw_provider_records
WINDOW payload_partition AS (
    PARTITION BY connector_id, operation_id, source_record_hash
)
ORDER BY
    connector_id,
    operation_id,
    source_record_hash,
    fetched_at DESC,
    raw_record_id DESC;

INSERT INTO ingestion.raw_provider_observations (
    observation_id,
    execution_id,
    connector_id,
    operation_id,
    source_record_hash,
    window_start,
    window_end,
    fetched_at
)
SELECT
    raw_record_id,
    execution_id,
    connector_id,
    operation_id,
    source_record_hash,
    window_start,
    window_end,
    fetched_at
FROM ingestion.raw_provider_records;

DO $$
BEGIN
    IF (SELECT count(*) FROM ingestion.raw_provider_observations)
       <> (SELECT count(*) FROM ingestion.raw_provider_records) THEN
        RAISE EXCEPTION 'raw provider observation backfill count mismatch';
    END IF;

    IF (SELECT count(*) FROM ingestion.raw_provider_payloads)
       <> (
           SELECT count(*)
           FROM (
               SELECT DISTINCT connector_id, operation_id, source_record_hash
               FROM ingestion.raw_provider_records
           ) AS legacy_payloads
       ) THEN
        RAISE EXCEPTION 'raw provider payload backfill count mismatch';
    END IF;
END
$$;

COMMENT ON TABLE ingestion.raw_provider_records IS
    'Legacy raw payload observations backfilled by migration 036; dropped by migration 037.';

COMMENT ON TABLE ingestion.raw_provider_payloads IS
    'Content-addressed provider payloads deduplicated by connector, operation and source record hash.';

COMMENT ON TABLE ingestion.raw_provider_observations IS
    'Per-execution observations referencing deduplicated provider payloads.';
