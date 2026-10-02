CREATE OR REPLACE VIEW public_procurement.runtime_bid_opening_participants AS
SELECT
    participant.*,
    award.work_type,
    COALESCE(notice.notice_name, award.notice_name) AS notice_name,
    award.opening_at,
    award.final_award_date,
    COALESCE(notice.demand_organization_code, award.demand_organization_code)
      AS demand_organization_code,
    COALESCE(notice.demand_organization_name, award.demand_organization_name)
      AS demand_organization_name,
    COALESCE(participant.bid_at, award.opening_at) AS participation_date,
    participant.opening_rank AS rank,
    award.participant_count,
    award.winning_amount,
    notice.procurement_classification_number AS field_code,
    notice.procurement_classification_name AS field_name,
    CASE WHEN award.work_type = 'construction'
         THEN notice.procurement_classification_name
         ELSE notice.procurement_large_classification_name END AS large_category,
    CASE WHEN award.work_type = 'construction' THEN NULL
         ELSE notice.procurement_middle_classification_name END AS middle_category,
    CASE WHEN notice.procurement_classification_number IS NULL
         THEN 'unclassified' ELSE 'procurement_classification' END AS classification_source,
    CASE
      WHEN EXISTS (
        SELECT 1
        FROM public_procurement.contracts contract
        JOIN public_procurement.contract_suppliers supplier
          USING (unified_contract_number)
        WHERE supplier.business_registration_number = participant.business_registration_number
          AND (contract.notice_number = participant.notice_number
               OR contract.notice_number = participant.notice_number || '00')
      ) THEN 'contract'
      WHEN award.winner_business_registration_number = participant.business_registration_number
        THEN 'award'
      WHEN award.notice_number IS NOT NULL THEN 'unsuccessful'
      ELSE 'unknown'
    END AS result,
    (award.notice_number IS NOT NULL) AS result_confirmed
FROM public_procurement.bid_opening_participants AS participant
LEFT JOIN public_procurement.bid_awards AS award
  ON award.notice_number = participant.notice_number
 AND award.notice_order = participant.notice_order
 AND award.bid_classification_number = participant.bid_classification_number
 AND award.rebid_number = participant.rebid_number
LEFT JOIN public_procurement.bid_notices AS notice
  ON notice.notice_number = participant.notice_number
 AND notice.notice_order = participant.notice_order;

CREATE INDEX IF NOT EXISTS bid_opening_participants_competitor_lookup_idx
ON public_procurement.bid_opening_participants (
    notice_number, notice_order, bid_classification_number, rebid_number,
    business_registration_number
);

GRANT SELECT ON public_procurement.runtime_bid_opening_participants TO teoria_runtime;
