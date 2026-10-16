"""Data DB statements owned by this market-analysis feature."""

_PROCUREMENT_ACTIVITY_NOTICES_QUERY = """
SELECT n.bid_notice_id,n.notice_name,n.notice_published_at AS published_at,
       n.bid_begin_at,n.bid_deadline_at,n.bid_status,n.notice_status,n.notice_kind_name,
       n.current_status,n.current_status_label,n.cancellation_reason,n.cancellation_at,
       n.failure_reason,n.failure_at,n.status_source,n.status_confirmed_at,
       n.original_notice_id,n.current_notice_id,n.revision_number,n.is_latest_revision,
       n.allocated_budget,n.estimated_price,NULL::numeric AS base_amount,
       n.demand_organization_code AS organization_code,
       n.demand_organization_name AS organization_name,
       n.work_type,n.field_code,n.field_name,n.large_category,n.middle_category,
       n.notice_lineage_id,n.root_bid_notice_id,n.lineage_count,n.lineage_notices
FROM public_procurement.runtime_bid_notices n
WHERE n.demand_organization_code=%(organization_code)s
  AND n.notice_published_at >= %(period_from)s
  AND n.notice_published_at < %(period_to)s
  AND n.notice_status <> 'superseded'
  AND n.is_latest_in_lineage
ORDER BY n.notice_published_at DESC,n.bid_notice_id DESC
"""


_PROCUREMENT_ACTIVITY_COMPANY_PARTICIPATION_QUERY = """
SELECT DISTINCT p.bid_notice_id
FROM public_procurement.bid_opening_participants p
JOIN public_procurement.bid_notices n
  ON n.notice_number=p.notice_number AND n.notice_order=p.notice_order
WHERE n.demand_organization_code=%(organization_code)s
  AND n.notice_published_at >= %(period_from)s
  AND n.notice_published_at < %(period_to)s
  AND p.business_registration_number=%(company_number)s
"""


_PROCUREMENT_ACTIVITY_CONTRACTS_QUERY = """
WITH scoped_contract_numbers AS MATERIALIZED (
    SELECT DISTINCT d.unified_contract_number,d.organization_code
    FROM public_procurement.contract_demand_organizations d
    WHERE d.organization_code=%(organization_code)s
), contract_versions AS MATERIALIZED (
    SELECT scoped.organization_code,c.*,
           COALESCE(NULLIF(c.confirmed_contract_number,''),
                    NULLIF(c.contract_reference_number,''),c.unified_contract_number)
             AS contract_event_key,
           CASE WHEN c.notice_number~'^[0-9]{13}$' AND right(c.notice_number,2)='00'
                THEN left(c.notice_number,length(c.notice_number)-2)
                ELSE NULLIF(c.notice_number,'') END AS normalized_notice_number
    FROM scoped_contract_numbers scoped
    JOIN public_procurement.contracts c USING (unified_contract_number)
    WHERE c.concluded_date < %(period_to)s OR c.concluded_date IS NULL
), contract_groups AS (
    SELECT organization_code,contract_event_key,
           min(concluded_date) AS first_contract_date,
           max(concluded_date) AS latest_contract_version_date,
           count(DISTINCT unified_contract_number)::integer AS contract_version_count
    FROM contract_versions
    GROUP BY organization_code,contract_event_key
), latest_contract_versions AS (
    SELECT DISTINCT ON (v.organization_code,v.contract_event_key)
           v.*,g.first_contract_date,g.latest_contract_version_date,
           g.contract_version_count
    FROM contract_versions v
    JOIN contract_groups g USING (organization_code,contract_event_key)
    ORDER BY v.organization_code,v.contract_event_key,
             v.concluded_date DESC NULLS LAST,v.updated_at DESC,
             v.unified_contract_number DESC
)
SELECT c.contract_event_key AS contract_event_id,c.unified_contract_number,
       c.confirmed_contract_number,c.contract_reference_number,c.contract_name,
       c.long_term_continuation_type,c.normalized_notice_number,
       c.request_number,c.contract_detail_url,
       CASE WHEN c.normalized_notice_number IS NOT NULL
            THEN c.normalized_notice_number||':'||COALESCE(n.notice_order,'000')
            ELSE NULL END AS bid_notice_id,
       COALESCE(n.notice_name,c.contract_name) AS notice_name,
       o.organization_name,c.first_contract_date,
       c.latest_contract_version_date AS contract_date,
       c.current_contract_amount AS contract_amount,
       c.current_contract_amount_currency,c.total_amount,
       c.total_amount_currency,c.is_joint_contract,
       c.contract_version_count,
       COALESCE(n.work_type,CASE WHEN c.contract_type='foreign_procurement' THEN 'foreign'
                                ELSE c.contract_type END) AS work_type,
       COALESCE(n.procurement_classification_number,c.procurement_classification_number)
         AS procurement_classification_number,
       COALESCE(n.procurement_classification_name,c.procurement_classification_name)
         AS procurement_classification_name,
       n.procurement_large_classification_name,
       n.procurement_middle_classification_name,n.purchase_items,
       cs.supplier_sequence,cs.business_registration_number,cs.supplier_name,
       cs.supplier_role_name,cs.participation_share_rate
FROM latest_contract_versions c
JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
LEFT JOIN public_procurement.public_organizations o
  ON o.organization_code=c.organization_code
LEFT JOIN LATERAL (
  SELECT notice.*
  FROM public_procurement.bid_notices notice
  WHERE notice.notice_number=c.normalized_notice_number
  ORDER BY (notice.notice_order='000') DESC,notice.notice_order DESC
  LIMIT 1
) n ON true
WHERE c.first_contract_date >= %(period_from)s
  AND c.first_contract_date < %(period_to)s
ORDER BY c.first_contract_date DESC,c.contract_event_key,cs.supplier_sequence
"""
