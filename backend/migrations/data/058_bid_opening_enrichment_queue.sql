CREATE TABLE ingestion.bid_opening_enrichment_queue (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    bid_classification_number text NOT NULL,
    rebid_number text NOT NULL,
    award_source_record_hash text NOT NULL,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'retry_wait', 'completed', 'permanent_failure')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_retry_at timestamptz NOT NULL DEFAULT now(),
    lease_until timestamptz,
    last_error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    PRIMARY KEY (notice_number, notice_order, bid_classification_number, rebid_number)
);

CREATE INDEX bid_opening_enrichment_queue_claim_idx
    ON ingestion.bid_opening_enrichment_queue (next_retry_at, updated_at)
    WHERE status IN ('pending', 'retry_wait', 'processing');

INSERT INTO ingestion.bid_opening_enrichment_queue (
    notice_number, notice_order, bid_classification_number, rebid_number,
    award_source_record_hash
)
SELECT award.notice_number, award.notice_order, award.bid_classification_number,
       award.rebid_number, award.source_record_hash
FROM public_procurement.bid_awards award
LEFT JOIN ingestion.bid_opening_collection_status completed
  USING (notice_number, notice_order, bid_classification_number, rebid_number)
WHERE completed.notice_number IS NULL
ON CONFLICT DO NOTHING;
