-- Operational maintenance for the top-10-plus-winner bid-check coverage policy.
--
-- Run each DELETE repeatedly in a transaction until it returns DELETE 0.  They
-- are deliberately not migrations: tens of millions of rows must not be held
-- in one migration transaction.  Pause the bid-result backfill first.

WITH candidates AS (
    SELECT participant.ctid
    FROM public_procurement.bid_opening_participants AS participant
    LEFT JOIN public_procurement.bid_awards AS award
      ON award.notice_number = participant.notice_number
     AND award.notice_order = participant.notice_order
     AND award.bid_classification_number = participant.bid_classification_number
     AND award.rebid_number = participant.rebid_number
    WHERE (participant.opening_rank IS NULL OR participant.opening_rank NOT BETWEEN 1 AND 10)
      AND participant.business_registration_number
          IS DISTINCT FROM award.winner_business_registration_number
    LIMIT 100000
)
DELETE FROM public_procurement.bid_opening_participants AS participant
USING candidates
WHERE participant.ctid = candidates.ctid;

WITH candidates AS (
    SELECT observation.ctid
    FROM ingestion.raw_provider_observations AS observation
    WHERE observation.connector_id = 'pps_bid_result_api'
      AND observation.operation_id = 'list_completed_opening_results'
    LIMIT 100000
)
DELETE FROM ingestion.raw_provider_observations AS observation
USING candidates
WHERE observation.ctid = candidates.ctid;

-- Run only after the opening-result observation DELETE reaches zero; the
-- observation foreign key intentionally prevents premature payload removal.
WITH candidates AS (
    SELECT payload.ctid
    FROM ingestion.raw_provider_payloads AS payload
    WHERE payload.connector_id = 'pps_bid_result_api'
      AND payload.operation_id = 'list_completed_opening_results'
    LIMIT 100000
)
DELETE FROM ingestion.raw_provider_payloads AS payload
USING candidates
WHERE payload.ctid = candidates.ctid;
