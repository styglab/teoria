ALTER TABLE ingestion.bid_opening_enrichment_queue
    ADD COLUMN priority_date date;

UPDATE ingestion.bid_opening_enrichment_queue queue
SET priority_date = award.final_award_date
FROM public_procurement.bid_awards award
WHERE (award.notice_number, award.notice_order, award.bid_classification_number,
       award.rebid_number) =
      (queue.notice_number, queue.notice_order, queue.bid_classification_number,
       queue.rebid_number);

CREATE INDEX bid_opening_enrichment_queue_fresh_priority_idx
    ON ingestion.bid_opening_enrichment_queue
       (queue_class, priority_date DESC, updated_at)
    WHERE status IN ('pending', 'processing');

CREATE INDEX bid_opening_enrichment_queue_retry_priority_idx
    ON ingestion.bid_opening_enrichment_queue
       (next_retry_at, priority_date DESC, updated_at)
    WHERE status IN ('retry_wait', 'partial_completed');
