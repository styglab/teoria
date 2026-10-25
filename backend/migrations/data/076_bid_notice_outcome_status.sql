ALTER TABLE ingestion.pipeline_runs
    ADD COLUMN notice_outcome_count integer NOT NULL DEFAULT 0;

CREATE TABLE public_procurement.bid_notice_outcomes (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    bid_classification_number text NOT NULL,
    rebid_number text NOT NULL,
    outcome_status text NOT NULL CHECK (outcome_status IN ('failed')),
    reason text,
    status_source text NOT NULL,
    status_confirmed_at timestamptz NOT NULL,
    source_record_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (notice_number, notice_order, bid_classification_number, rebid_number)
);

CREATE INDEX bid_notice_outcomes_notice_idx
    ON public_procurement.bid_notice_outcomes (notice_number, notice_order);

CREATE TABLE ingestion.bid_notice_outcome_collection_status (
    notice_number text PRIMARY KEY,
    notice_source_record_hash text NOT NULL,
    outcome_count integer NOT NULL DEFAULT 0,
    checked_at timestamptz NOT NULL DEFAULT now()
);

ALTER VIEW public_procurement.runtime_bid_notices
    RENAME TO runtime_bid_notices_without_current_status;

CREATE VIEW public_procurement.runtime_bid_notices AS
SELECT base.*,
       CASE
         WHEN base.notice_status='cancelled' THEN 'cancelled'
         WHEN contract_status.confirmed_at IS NOT NULL THEN 'contracted'
         WHEN award_status.confirmed_at IS NOT NULL THEN 'awarded'
         WHEN failed_status.status_confirmed_at IS NOT NULL THEN 'failed'
         WHEN base.bid_status IN ('scheduled','open','closed') THEN base.bid_status
         ELSE 'closed'
       END AS current_status,
       CASE
         WHEN base.notice_status='cancelled' THEN '취소'
         WHEN contract_status.confirmed_at IS NOT NULL THEN '계약'
         WHEN award_status.confirmed_at IS NOT NULL THEN '낙찰'
         WHEN failed_status.status_confirmed_at IS NOT NULL THEN '유찰'
         WHEN base.bid_status='scheduled' THEN '예정'
         WHEN base.bid_status='open' THEN '진행'
         ELSE '마감'
       END AS current_status_label,
       CASE WHEN base.notice_status='cancelled'
            THEN NULLIF(notice_source.source_payload->>'chgNtceRsn','') END
         AS cancellation_reason,
       CASE WHEN base.notice_status='cancelled'
            THEN COALESCE(base.source_changed_at,base.notice_published_at) END
         AS cancellation_at,
       failed_status.reason AS failure_reason,
       CASE WHEN failed_status.status_confirmed_at IS NOT NULL THEN base.opening_at END
         AS failure_at,
       CASE
         WHEN base.notice_status='cancelled' THEN 'pps_bid_notice_api.notice_kind_name'
         WHEN contract_status.confirmed_at IS NOT NULL THEN 'teoria_public_procurement.contracts'
         WHEN award_status.confirmed_at IS NOT NULL THEN 'pps_bid_result_api.final_award'
         WHEN failed_status.status_confirmed_at IS NOT NULL THEN failed_status.status_source
         ELSE 'teoria_runtime.bid_timeline'
       END AS status_source,
       CASE
         WHEN base.notice_status='cancelled'
           THEN COALESCE(base.source_changed_at,base.notice_published_at)
         WHEN contract_status.confirmed_at IS NOT NULL THEN contract_status.confirmed_at
         WHEN award_status.confirmed_at IS NOT NULL THEN award_status.confirmed_at
         WHEN failed_status.status_confirmed_at IS NOT NULL
           THEN failed_status.status_confirmed_at
         ELSE base.source_changed_at
       END AS status_confirmed_at,
       base.root_bid_notice_id AS original_notice_id,
       lineage_current.bid_notice_id AS current_notice_id,
       lineage_current.revision_number,
       base.is_latest_in_lineage AS is_latest_revision
FROM public_procurement.runtime_bid_notices_without_current_status base
LEFT JOIN public_procurement.bid_notices notice_source
  ON notice_source.notice_number=base.notice_number
 AND notice_source.notice_order=base.notice_order
LEFT JOIN LATERAL (
  SELECT outcome.reason,outcome.status_source,outcome.status_confirmed_at
  FROM public_procurement.bid_notice_outcomes outcome
  WHERE outcome.notice_number=base.notice_number
    AND outcome.notice_order=base.notice_order
  ORDER BY outcome.rebid_number DESC,outcome.status_confirmed_at DESC
  LIMIT 1
) failed_status ON true
LEFT JOIN LATERAL (
  SELECT COALESCE(award.final_award_date::timestamptz,award.opening_at,
                  award.source_registered_at,award.updated_at) AS confirmed_at
  FROM public_procurement.bid_awards award
  WHERE award.notice_number=base.notice_number
    AND award.notice_order=base.notice_order
  ORDER BY award.final_award_date DESC NULLS LAST,award.updated_at DESC
  LIMIT 1
) award_status ON true
LEFT JOIN LATERAL (
  SELECT COALESCE(contract.source_changed_at,contract.source_registered_at,
                  contract.concluded_date::timestamptz,contract.updated_at) AS confirmed_at
  FROM public_procurement.contracts contract
  WHERE CASE
    WHEN contract.notice_number~'^[0-9]{13}$' AND right(contract.notice_number,2)='00'
      THEN left(contract.notice_number,length(contract.notice_number)-2)
    ELSE NULLIF(contract.notice_number,'')
  END=base.notice_number
  ORDER BY contract.concluded_date DESC NULLS LAST,contract.updated_at DESC
  LIMIT 1
) contract_status ON true
LEFT JOIN LATERAL (
  SELECT item->>'bid_notice_id' AS bid_notice_id,(position-1)::integer AS revision_number
  FROM jsonb_array_elements(COALESCE(base.lineage_notices,'[]')::jsonb)
       WITH ORDINALITY AS lineage(item,position)
  ORDER BY position DESC
  LIMIT 1
) lineage_current ON true;

GRANT SELECT ON public_procurement.bid_notice_outcomes TO teoria_runtime;
GRANT SELECT ON public_procurement.runtime_bid_notices TO teoria_runtime;
