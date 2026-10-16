"""Data DB statements owned by this market-analysis feature."""

_BID_CONTEXT_COMPETITION_QUERY = """
SELECT concat_ws(':',a.notice_number,a.notice_order,a.bid_classification_number,a.rebid_number)
         AS competition_event_id,
       n.bid_notice_id,
       n.notice_published_at::date AS notice_published_date,a.participant_count,
       n.field_code AS procurement_classification_number,
       n.field_name AS procurement_classification_name,
       n.large_category AS procurement_large_classification_name,
       n.middle_category AS procurement_middle_classification_name,
       raw.purchase_items,n.work_type,n.notice_lineage_id,n.is_latest_in_lineage
FROM public_procurement.bid_awards a
JOIN public_procurement.runtime_bid_notices n
  ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
JOIN public_procurement.bid_notices raw
  ON raw.notice_number=a.notice_number AND raw.notice_order=a.notice_order
WHERE n.demand_organization_code=%(organization_code)s
  AND n.notice_published_at >= %(period_from)s
  AND n.notice_published_at < %(period_to)s
ORDER BY n.notice_published_at DESC,a.bid_classification_number,a.rebid_number
"""


_BID_CONTEXT_PEER_CONTRACTS_QUERY = """
SELECT ledger.organization_code,ledger.organization_name,
       ledger.contract_event_id AS event_key,ledger.unified_contract_number,
       ledger.contract_name,ledger.first_contract_date,
       ledger.latest_contract_version_date,ledger.contract_version_count,
       ledger.company_number,ledger.company_name,ledger.company_role,ledger.share_percent,
       ledger.attributed_contract_amount,ledger.amount_completeness,ledger.contract_amount,
       ledger.normalized_notice_number,ledger.work_type,ledger.field_code,ledger.field_name,
       ledger.large_category,ledger.middle_category
FROM public_procurement.contract_event_company_ledger ledger
WHERE ledger.first_contract_date >= %(history_from)s AND ledger.first_contract_date < %(period_to)s
  AND ledger.work_type=%(work_type)s
  AND (%(large_category)s::text IS NULL OR ledger.large_category=%(large_category)s)
  AND (%(middle_category)s::text IS NULL OR ledger.middle_category=%(middle_category)s)
  AND (%(field_code)s::text IS NULL OR ledger.field_code=%(field_code)s)
"""


_BID_CONTEXT_PEER_COMPETITION_QUERY = """
SELECT n.demand_organization_code AS organization_code,
       concat_ws(':',a.notice_number,a.notice_order,a.bid_classification_number,a.rebid_number)
         AS competition_event_id,
       a.participant_count
FROM public_procurement.bid_awards a
JOIN public_procurement.runtime_bid_notices n
  ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
WHERE n.notice_published_at >= %(period_from)s AND n.notice_published_at < %(period_to)s
  AND n.work_type=%(work_type)s
  AND (%(large_category)s::text IS NULL OR n.large_category=%(large_category)s)
  AND (%(middle_category)s::text IS NULL OR n.middle_category=%(middle_category)s)
  AND (%(field_code)s::text IS NULL OR n.field_code=%(field_code)s)
"""


_BID_RELATIONSHIP_NOTICE_QUERY = """
SELECT n.notice_number||':'||n.notice_order AS bid_notice_id,n.notice_name,
       n.demand_organization_code AS organization_code,
       n.demand_organization_name AS organization_name,
       n.notice_published_at::date AS notice_published_date,n.work_type,
       n.procurement_classification_number AS field_code,
       n.procurement_classification_name AS field_name,
       CASE WHEN n.work_type='construction' THEN n.procurement_classification_name
            ELSE n.procurement_large_classification_name END AS large_category,
       CASE WHEN n.work_type='construction' THEN NULL
            ELSE n.procurement_middle_classification_name END AS middle_category,
       n.allocated_budget,n.estimated_price,NULL::numeric AS base_amount
FROM public_procurement.bid_notices n
WHERE n.notice_number=%(notice_number)s AND n.notice_order=%(notice_order)s
"""


_BID_RELATIONSHIP_PARTICIPANTS_QUERY = """
WITH participant_base AS (
    SELECT bp.business_registration_number AS company_number,bp.participant_name AS company_name,
           bp.opening_rank,bp.bid_amount,bp.bid_rate,
           a.final_award_date AS award_date,a.winning_amount,a.winning_rate
    FROM public_procurement.bid_opening_participants bp
    LEFT JOIN public_procurement.bid_awards a
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
     AND a.winner_business_registration_number=bp.business_registration_number
    WHERE bp.notice_number=%(notice_number)s AND bp.notice_order=%(notice_order)s
), contract_base AS (
    SELECT DISTINCT ON (cs.business_registration_number)
           cs.business_registration_number AS company_number,cs.supplier_name AS company_name,
           c.concluded_date AS contract_date,c.current_contract_amount AS contract_amount,
           cs.participation_share_rate AS share_percent,cs.supplier_role_name,
           supplier_count.count AS supplier_count,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW'
                     OR c.current_contract_amount IS NULL THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                  THEN c.current_contract_amount*cs.participation_share_rate/100
                WHEN supplier_count.count=1 THEN c.current_contract_amount END
             AS attributed_contract_amount,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW'
                     OR c.current_contract_amount IS NULL THEN 'unknown'
                WHEN cs.participation_share_rate IS NOT NULL OR supplier_count.count=1
                  THEN 'complete' ELSE 'partial' END AS amount_completeness
    FROM public_procurement.contracts c
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    CROSS JOIN LATERAL (
      SELECT count(*) FROM public_procurement.contract_suppliers all_cs
      WHERE all_cs.unified_contract_number=c.unified_contract_number
    ) supplier_count
    WHERE c.notice_number IN (
      %(notice_number)s,
      CASE WHEN %(notice_number)s~'^[0-9]+$' THEN %(notice_number)s||'00' ELSE %(notice_number)s END
    )
    ORDER BY cs.business_registration_number,c.concluded_date DESC,c.updated_at DESC
), companies AS (
    SELECT company_number FROM participant_base
    UNION SELECT company_number FROM contract_base
)
SELECT companies.company_number,COALESCE(p.company_name,c.company_name) AS company_name,
       p.opening_rank,p.bid_amount,p.bid_rate,p.award_date,p.winning_amount,p.winning_rate,
       c.contract_date,c.contract_amount,c.attributed_contract_amount,c.share_percent,
       CASE WHEN c.supplier_count=1 THEN 'sole'
            WHEN c.supplier_role_name IN ('대표사','주계약자','대표업체') THEN 'consortium_lead'
            ELSE 'consortium_member' END AS company_role,
       c.amount_completeness
FROM companies
LEFT JOIN participant_base p USING (company_number)
LEFT JOIN contract_base c USING (company_number)
ORDER BY p.opening_rank NULLS LAST,companies.company_number
"""
