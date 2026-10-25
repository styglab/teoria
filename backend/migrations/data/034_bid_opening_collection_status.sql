CREATE TABLE ingestion.bid_opening_collection_status (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    bid_classification_number text NOT NULL,
    rebid_number text NOT NULL,
    award_source_record_hash text NOT NULL,
    checked_at timestamptz NOT NULL DEFAULT now(),
    participant_count integer NOT NULL CHECK (participant_count >= 0),
    execution_id uuid NOT NULL REFERENCES ingestion.pipeline_runs(execution_id),
    PRIMARY KEY (
        notice_number, notice_order, bid_classification_number, rebid_number
    )
);

CREATE INDEX bid_opening_collection_status_checked_at_idx
    ON ingestion.bid_opening_collection_status (checked_at);
