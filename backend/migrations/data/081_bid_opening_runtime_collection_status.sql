-- Expose collection readiness without granting Runtime access to ingestion tables.
CREATE VIEW public_procurement.runtime_bid_opening_collection_status AS
SELECT a.notice_number,a.notice_order,a.bid_classification_number,a.rebid_number,
       CASE
         WHEN q.status='completed'
          AND checked.award_source_record_hash=a.source_record_hash
          AND checked.selected_business_numbers IS NOT NULL THEN 'complete'
         WHEN q.status IN ('pending','processing','retry_wait','partial_completed')
           THEN 'collecting'
         WHEN q.status='permanent_failure' THEN 'failed'
         ELSE 'unknown'
       END AS collection_status
FROM public_procurement.bid_awards a
LEFT JOIN ingestion.bid_opening_enrichment_queue q
  USING (notice_number,notice_order,bid_classification_number,rebid_number)
LEFT JOIN ingestion.bid_opening_collection_status checked
  USING (notice_number,notice_order,bid_classification_number,rebid_number);

GRANT SELECT ON public_procurement.runtime_bid_opening_collection_status TO teoria_runtime;
