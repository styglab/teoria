ALTER TABLE ingestion.bid_opening_enrichment_queue
    ADD COLUMN queue_class text NOT NULL DEFAULT 'backfill';

ALTER TABLE ingestion.bid_opening_enrichment_queue
    ADD CONSTRAINT bid_opening_enrichment_queue_class_check
    CHECK (queue_class IN ('incremental', 'backfill'));

ALTER TABLE ingestion.bid_opening_enrichment_queue
    DROP CONSTRAINT IF EXISTS bid_opening_enrichment_queue_status_check;

ALTER TABLE ingestion.bid_opening_enrichment_queue
    ADD CONSTRAINT bid_opening_enrichment_queue_status_check
    CHECK (status IN ('pending', 'processing', 'retry_wait', 'partial_completed',
                      'completed', 'permanent_failure'));

UPDATE ingestion.bid_opening_enrichment_queue queue
SET queue_class = 'incremental'
FROM public_procurement.bid_awards award
WHERE (award.notice_number, award.notice_order, award.bid_classification_number,
       award.rebid_number) =
      (queue.notice_number, queue.notice_order, queue.bid_classification_number,
       queue.rebid_number)
  AND award.final_award_date >= current_date - interval '14 days'
  AND queue.status <> 'completed';

CREATE INDEX bid_opening_enrichment_queue_lane_claim_idx
    ON ingestion.bid_opening_enrichment_queue
       (queue_class, next_retry_at, updated_at)
    WHERE status IN ('pending', 'processing');

CREATE INDEX bid_opening_enrichment_queue_retry_claim_idx
    ON ingestion.bid_opening_enrichment_queue (next_retry_at, updated_at)
    WHERE status IN ('retry_wait', 'partial_completed');
