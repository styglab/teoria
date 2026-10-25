-- A terminal partial result must not be reclaimed forever. Legacy rows marked
-- completed before selected_business_numbers was introduced are not verified.
DROP VIEW public_procurement.runtime_bid_opening_collection_status;

UPDATE ingestion.bid_opening_enrichment_queue queue
SET status = 'pending',
    attempts = 0,
    next_retry_at = now(),
    lease_until = NULL,
    completed_at = NULL,
    last_error_code = 'legacy_selection_unverified',
    updated_at = now()
FROM ingestion.bid_opening_collection_status checked
WHERE (checked.notice_number, checked.notice_order,
       checked.bid_classification_number, checked.rebid_number) =
      (queue.notice_number, queue.notice_order,
       queue.bid_classification_number, queue.rebid_number)
  AND queue.status = 'completed'
  AND checked.selected_business_numbers IS NULL;

UPDATE ingestion.bid_opening_enrichment_queue
SET status = 'partial_completed',
    next_retry_at = 'infinity'::timestamptz,
    lease_until = NULL,
    updated_at = now()
WHERE status = 'retry_wait'
  AND last_error_code = 'opening_response_incomplete'
  AND attempts >= 3;

UPDATE ingestion.bid_opening_enrichment_queue
SET status = 'permanent_failure',
    next_retry_at = 'infinity'::timestamptz,
    lease_until = NULL,
    updated_at = now()
WHERE status = 'retry_wait'
  AND last_error_code = 'opening_lookup_failed'
  AND attempts >= 5;

DROP INDEX IF EXISTS ingestion.bid_opening_enrichment_queue_retry_claim_idx;
DROP INDEX IF EXISTS ingestion.bid_opening_enrichment_queue_retry_priority_idx;
CREATE INDEX bid_opening_enrichment_queue_retry_claim_idx
    ON ingestion.bid_opening_enrichment_queue
       (next_retry_at, priority_date DESC, updated_at)
    WHERE status = 'retry_wait';

CREATE VIEW public_procurement.runtime_bid_opening_collection_status AS
SELECT a.notice_number,a.notice_order,a.bid_classification_number,a.rebid_number,
       CASE
         WHEN q.status='completed'
          AND checked.award_source_record_hash=a.source_record_hash
          AND checked.selected_business_numbers IS NOT NULL THEN 'complete'
         WHEN q.status IN ('pending','processing','retry_wait') THEN 'collecting'
         WHEN q.status IN ('partial_completed','permanent_failure') THEN 'failed'
         ELSE 'unknown'
       END AS collection_status
FROM public_procurement.bid_awards a
LEFT JOIN ingestion.bid_opening_enrichment_queue q
  USING (notice_number,notice_order,bid_classification_number,rebid_number)
LEFT JOIN ingestion.bid_opening_collection_status checked
  USING (notice_number,notice_order,bid_classification_number,rebid_number);

GRANT SELECT ON public_procurement.runtime_bid_opening_collection_status TO teoria_runtime;
