ALTER TABLE ingestion.raw_provider_records
    DROP CONSTRAINT IF EXISTS raw_provider_records_connector_id_operation_id_source_record_hash_key;

ALTER TABLE ingestion.raw_provider_records
    ADD CONSTRAINT raw_provider_records_execution_source_hash_key
    UNIQUE (execution_id, connector_id, operation_id, source_record_hash);

CREATE INDEX IF NOT EXISTS raw_provider_records_source_hash_idx
    ON ingestion.raw_provider_records (connector_id, operation_id, source_record_hash);
