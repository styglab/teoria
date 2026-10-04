INSERT INTO ingestion.bid_opening_enrichment_queue (
    notice_number, notice_order, bid_classification_number, rebid_number,
    award_source_record_hash, status, attempts, next_retry_at
)
SELECT award.notice_number, award.notice_order, award.bid_classification_number,
       award.rebid_number, award.source_record_hash, 'pending', 0, now()
FROM public_procurement.bid_awards award
LEFT JOIN public_procurement.bid_opening_participants participant
  USING (notice_number, notice_order, bid_classification_number, rebid_number)
WHERE award.participant_count IS NOT NULL
GROUP BY award.notice_number, award.notice_order, award.bid_classification_number,
         award.rebid_number, award.source_record_hash, award.participant_count
HAVING count(DISTINCT participant.business_registration_number)
       < LEAST(award.participant_count, 10)
ON CONFLICT (notice_number, notice_order, bid_classification_number, rebid_number)
DO UPDATE SET status='pending', attempts=0, next_retry_at=now(), lease_until=NULL,
              completed_at=NULL, last_error_code='stored_participant_count_incomplete',
              updated_at=now();
