"""Data DB statements owned by this market-analysis feature."""

_PROCUREMENT_OUTCOME_AWARDS_QUERY = """
WITH scoped_awards AS MATERIALIZED (
  SELECT a.*
  FROM public_procurement.runtime_bid_awards a
  WHERE a.demand_organization_code=%(organization_code)s
    AND COALESCE(a.final_award_date,a.opening_at::date) >= %(period_from)s
    AND COALESCE(a.final_award_date,a.opening_at::date) < %(period_to)s
)
SELECT a.award_id,a.bid_notice_id,a.bid_classification_number,a.rebid_number,
       a.notice_name,a.demand_organization_name AS organization_name,
       COALESCE(a.final_award_date,a.opening_at::date) AS award_date,
       a.winner_name,a.winner_business_registration_number,
       a.winning_amount,a.winning_rate,a.work_type,
       a.field_code,a.field_name,a.large_category,a.middle_category,
       n.notice_lineage_id,n.root_bid_notice_id,n.lineage_count,
       CASE WHEN n.is_latest_in_lineage THEN n.bid_notice_id
            ELSE COALESCE(n.superseded_by_bid_notice_id,n.bid_notice_id) END
         AS representative_bid_notice_id
FROM scoped_awards a
LEFT JOIN LATERAL (
  SELECT n.notice_lineage_id,n.root_bid_notice_id,n.lineage_count,
         n.is_latest_in_lineage,n.bid_notice_id,n.superseded_by_bid_notice_id
  FROM public_procurement.runtime_bid_notices n
  WHERE n.notice_number=a.notice_number AND n.notice_order=a.notice_order
  LIMIT 1
) n ON true
ORDER BY COALESCE(a.final_award_date,a.opening_at::date) DESC,a.award_id DESC
"""


_PROCUREMENT_OUTCOME_CONTRACTS_QUERY = """
WITH scoped_contracts AS (
  SELECT
         c.unified_contract_number,c.confirmed_contract_number,
         c.contract_reference_number,c.notice_number,c.contract_name,
         c.concluded_date,c.current_contract_amount,c.is_joint_contract,
         c.contract_type,c.procurement_classification_number,
         c.procurement_classification_name,
         d.organization_code
  FROM public_procurement.contracts c
  JOIN public_procurement.contract_demand_organizations d
    USING (unified_contract_number)
  WHERE d.organization_code=%(organization_code)s
    AND c.concluded_date >= %(period_from)s
    AND c.concluded_date < %(period_to)s
  UNION
  SELECT
         c.unified_contract_number,c.confirmed_contract_number,
         c.contract_reference_number,c.notice_number,c.contract_name,
         c.concluded_date,c.current_contract_amount,c.is_joint_contract,
         c.contract_type,c.procurement_classification_number,
         c.procurement_classification_name,c.contracting_organization_code
  FROM public_procurement.contracts c
  WHERE c.contracting_organization_code=%(organization_code)s
    AND c.concluded_date >= %(period_from)s
    AND c.concluded_date < %(period_to)s
    AND NOT EXISTS (
      SELECT 1
      FROM public_procurement.contract_demand_organizations d
      WHERE d.unified_contract_number=c.unified_contract_number
        AND d.organization_code IS NOT NULL
    )
), classification_codes AS (
  SELECT DISTINCT procurement_classification_number
  FROM scoped_contracts
  WHERE procurement_classification_number IS NOT NULL
), classification_hierarchy AS (
  SELECT code.procurement_classification_number,
         hierarchy.procurement_large_classification_name,
         hierarchy.procurement_middle_classification_name
  FROM classification_codes code
  LEFT JOIN LATERAL (
    SELECT n.procurement_large_classification_name,
           n.procurement_middle_classification_name
    FROM public_procurement.bid_notices n
    WHERE n.procurement_classification_number=code.procurement_classification_number
      AND (n.procurement_large_classification_name IS NOT NULL
        OR n.procurement_middle_classification_name IS NOT NULL)
    ORDER BY n.notice_published_at DESC
    LIMIT 1
  ) hierarchy ON true
)
SELECT DISTINCT
       COALESCE(NULLIF(c.confirmed_contract_number,''),
                NULLIF(c.contract_reference_number,''),c.unified_contract_number)
           AS contract_event_id,
       c.unified_contract_number,
       CASE
         WHEN COALESCE(c.notice_number,'')='' THEN NULL
         WHEN c.notice_number LIKE '%%:%%' THEN c.notice_number
         WHEN c.notice_number~'^[0-9]{13}$' AND right(c.notice_number,2)='00'
           THEN left(c.notice_number,length(c.notice_number)-2)||':000'
         ELSE c.notice_number||':000'
       END AS bid_notice_id,
       c.contract_name AS notice_name,
       o.organization_name,
       c.concluded_date AS contract_date,
       c.current_contract_amount AS contract_amount,
       c.is_joint_contract,
       CASE WHEN c.contract_type='foreign_procurement' THEN 'foreign'
            ELSE c.contract_type END AS work_type,
       c.procurement_classification_number AS field_code,
       c.procurement_classification_name AS field_name,
       CASE WHEN c.contract_type='construction'
              THEN c.procurement_classification_name
            ELSE h.procurement_large_classification_name END AS large_category,
       CASE WHEN c.contract_type='construction' THEN NULL
            ELSE h.procurement_middle_classification_name END AS middle_category,
       cs.supplier_sequence,cs.business_registration_number,cs.supplier_name,
       cs.supplier_role_name,cs.participation_share_rate
FROM scoped_contracts c
LEFT JOIN classification_hierarchy h
  USING (procurement_classification_number)
LEFT JOIN public_procurement.public_organizations o
  ON o.organization_code=c.organization_code
LEFT JOIN public_procurement.contract_suppliers cs
  USING (unified_contract_number)
ORDER BY c.concluded_date DESC,c.unified_contract_number,cs.supplier_sequence
"""
