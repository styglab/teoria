CREATE TABLE ingestion.contract_event_ledger_refresh_queue (
    field_code text PRIMARY KEY,
    requested_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0,
    last_error text
);

CREATE INDEX contract_event_ledger_refresh_queue_requested_idx
    ON ingestion.contract_event_ledger_refresh_queue (requested_at, field_code);
