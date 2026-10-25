-- A refresh acknowledges only the request version it actually processed.
ALTER TABLE ingestion.contract_event_ledger_refresh_queue
    ADD COLUMN request_version bigint NOT NULL DEFAULT 1;
