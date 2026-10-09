_PROCUREMENT_PROFILE_NOTICES_QUERY = """
SELECT n.bid_notice_id,
       n.notice_name,n.notice_published_at::date AS notice_published_date,
       n.allocated_budget,n.estimated_price,NULL::numeric AS base_amount,
       n.field_code AS procurement_classification_number,
       n.field_name AS procurement_classification_name,
       n.large_category AS procurement_large_classification_name,
       n.middle_category AS procurement_middle_classification_name,
       raw.purchase_items,n.work_type,n.notice_kind,n.notice_lineage_id,
       n.root_bid_notice_id,n.is_latest_in_lineage,n.lineage_count,n.lineage_notices
FROM public_procurement.runtime_bid_notices n
JOIN public_procurement.bid_notices raw USING (notice_number,notice_order)
WHERE n.demand_organization_code=%(organization_code)s
  AND n.notice_published_at >= %(period_from)s
  AND n.notice_published_at < %(period_to)s
"""

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


_PROCUREMENT_PROFILE_ACTIVITIES_QUERY = """
WITH scoped_contract_numbers AS MATERIALIZED (
    SELECT DISTINCT scoped_supplier.unified_contract_number,d.organization_code
    FROM public_procurement.contract_suppliers scoped_supplier
    JOIN public_procurement.contract_demand_organizations d
      USING (unified_contract_number)
    WHERE cardinality(%(company_numbers)s::text[])>0
      AND scoped_supplier.business_registration_number=ANY(%(company_numbers)s::text[])
      AND (%(organization_code)s::text IS NULL OR d.organization_code=%(organization_code)s)
    UNION ALL
    SELECT d.unified_contract_number,d.organization_code
    FROM public_procurement.contract_demand_organizations d
    WHERE cardinality(%(company_numbers)s::text[])=0
      AND (%(organization_code)s::text IS NULL OR d.organization_code=%(organization_code)s)
), participation AS (
    SELECT 'participation'::text AS activity_type,
           bp.notice_number||':'||bp.notice_order AS event_key,
           bp.notice_number||':'||bp.notice_order AS bid_notice_id,
           n.notice_name,n.demand_organization_code AS organization_code,
           n.demand_organization_name AS organization_name,
           n.procurement_classification_number,n.procurement_classification_name,
           n.procurement_large_classification_name,
           n.procurement_middle_classification_name,
           n.purchase_items,
           n.work_type,n.notice_published_at::date AS notice_published_date,
           n.contract_method_name,
           bp.business_registration_number AS company_number,bp.participant_name AS company_name,
           n.notice_published_at::date AS activity_date,
           bp.bid_amount AS event_amount,NULL::numeric AS attributed_contract_amount,
           'unknown'::text AS amount_completeness,
           'notice_published_at'::text AS attribution_date_basis,
           NULL::date AS first_contract_date,
           NULL::date AS latest_contract_version_date,
           NULL::integer AS contract_version_count,
           NULL::date[] AS contract_version_dates,
           (a.notice_number IS NOT NULL) AS result_confirmed,
           (a.winner_business_registration_number=bp.business_registration_number)
             AS participation_successful
    FROM public_procurement.bid_opening_participants bp
    JOIN public_procurement.bid_notices n
      ON n.notice_number=bp.notice_number AND n.notice_order=bp.notice_order
    LEFT JOIN public_procurement.bid_awards a
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
    WHERE (%(organization_code)s::text IS NULL OR n.demand_organization_code=%(organization_code)s)
      AND (cardinality(%(company_numbers)s::text[])=0
           OR bp.business_registration_number=ANY(%(company_numbers)s::text[]))
      AND n.notice_published_at >= %(period_from)s
      AND n.notice_published_at < %(period_to)s
), awards AS (
    SELECT 'award'::text AS activity_type,
           concat_ws(':',a.notice_number,a.notice_order,a.bid_classification_number,a.rebid_number)
             AS event_key,
           a.notice_number||':'||a.notice_order AS bid_notice_id,
           COALESCE(n.notice_name,a.notice_name) AS notice_name,
           a.demand_organization_code AS organization_code,
           a.demand_organization_name AS organization_name,
           n.procurement_classification_number,n.procurement_classification_name,
           n.procurement_large_classification_name,
           n.procurement_middle_classification_name,
           n.purchase_items,
           n.work_type,n.notice_published_at::date AS notice_published_date,
           n.contract_method_name,
           a.winner_business_registration_number AS company_number,a.winner_name AS company_name,
           COALESCE(a.final_award_date,a.opening_at::date) AS activity_date,
           a.winning_amount AS event_amount,NULL::numeric AS attributed_contract_amount,
           'unknown'::text AS amount_completeness,
           'final_award_date_or_opening_at'::text AS attribution_date_basis,
           NULL::date AS first_contract_date,
           NULL::date AS latest_contract_version_date,
           NULL::integer AS contract_version_count,
           NULL::date[] AS contract_version_dates,
           true AS result_confirmed,true AS participation_successful
    FROM public_procurement.bid_awards a
    LEFT JOIN public_procurement.bid_notices n
      ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
    WHERE (%(organization_code)s::text IS NULL OR a.demand_organization_code=%(organization_code)s)
      AND (cardinality(%(company_numbers)s::text[])=0
           OR a.winner_business_registration_number=ANY(%(company_numbers)s::text[]))
      AND COALESCE(a.final_award_date,a.opening_at::date) >= %(period_from)s
      AND COALESCE(a.final_award_date,a.opening_at::date) < %(period_to)s
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
           count(DISTINCT unified_contract_number)::integer AS contract_version_count,
           array_agg(DISTINCT concluded_date ORDER BY concluded_date) AS contract_version_dates
    FROM contract_versions
    GROUP BY organization_code,contract_event_key
), latest_contract_versions AS (
    SELECT DISTINCT ON (v.organization_code,v.contract_event_key)
           v.*,g.first_contract_date,g.latest_contract_version_date,
           g.contract_version_count,g.contract_version_dates
    FROM contract_versions v
    JOIN contract_groups g USING (organization_code,contract_event_key)
    ORDER BY v.organization_code,v.contract_event_key,
             v.concluded_date DESC NULLS LAST,v.updated_at DESC,
             v.unified_contract_number DESC
), latest_contracts AS (
    SELECT
           'contract'::text AS activity_type,
           c.contract_event_key AS event_key,
           CASE WHEN c.normalized_notice_number IS NOT NULL
                THEN c.normalized_notice_number||':'||COALESCE(n.notice_order,'000')
                ELSE 'contract:'||c.unified_contract_number END AS bid_notice_id,
           COALESCE(n.notice_name,c.contract_name) AS notice_name,
           c.organization_code,o.organization_name,
           COALESCE(n.procurement_classification_number,c.procurement_classification_number)
             AS procurement_classification_number,
           COALESCE(n.procurement_classification_name,c.procurement_classification_name)
             AS procurement_classification_name,
           n.procurement_large_classification_name,
           n.procurement_middle_classification_name,n.purchase_items,
           COALESCE(n.work_type,CASE WHEN c.contract_type='foreign_procurement' THEN 'foreign'
                                    ELSE c.contract_type END) AS work_type,
           n.notice_published_at::date AS notice_published_date,
           COALESCE(c.contract_method_name,n.contract_method_name) AS contract_method_name,
           cs.business_registration_number AS company_number,cs.supplier_name AS company_name,
           c.first_contract_date AS activity_date,
           c.current_contract_amount AS event_amount,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW'
                     OR c.current_contract_amount IS NULL THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                  THEN c.current_contract_amount*cs.participation_share_rate/100
                WHEN supplier_count.count=1 THEN c.current_contract_amount END
             AS attributed_contract_amount,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW'
                     OR c.current_contract_amount IS NULL THEN 'unknown'
                WHEN cs.participation_share_rate IS NOT NULL OR supplier_count.count=1
                  THEN 'complete' ELSE 'partial' END AS amount_completeness,
           'first_contract_date'::text AS attribution_date_basis,
           c.first_contract_date,c.latest_contract_version_date,
           c.contract_version_count,c.contract_version_dates,
           true AS result_confirmed,true AS participation_successful
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
    CROSS JOIN LATERAL (
      SELECT count(*) FROM public_procurement.contract_suppliers all_cs
      WHERE all_cs.unified_contract_number=c.unified_contract_number
    ) supplier_count
    WHERE (cardinality(%(company_numbers)s::text[])=0
           OR cs.business_registration_number=ANY(%(company_numbers)s::text[]))
      AND (
        c.first_contract_date IS NULL
        OR (
          c.first_contract_date >= %(period_from)s
          AND c.first_contract_date < %(period_to)s
        )
      )
)
SELECT * FROM participation
UNION ALL SELECT * FROM awards
UNION ALL SELECT * FROM latest_contracts
ORDER BY activity_date DESC,activity_type,event_key
"""


_ORGANIZATION_COMPANY_FIRST_AWARD_OR_CONTRACT_QUERY = """
WITH contract_versions AS MATERIALIZED (
    SELECT c.*,
           COALESCE(NULLIF(c.confirmed_contract_number,''),
                    NULLIF(c.contract_reference_number,''),c.unified_contract_number)
             AS contract_event_key,
           CASE WHEN c.notice_number~'^[0-9]{13}$' AND right(c.notice_number,2)='00'
                THEN left(c.notice_number,length(c.notice_number)-2)
                ELSE NULLIF(c.notice_number,'') END AS normalized_notice_number
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.runtime_contracts c USING (unified_contract_number)
    WHERE d.organization_code=%(organization_code)s
      AND c.concluded_date < %(history_to)s
), contract_groups AS (
    SELECT contract_event_key,min(concluded_date) AS first_contract_date
    FROM contract_versions
    GROUP BY contract_event_key
), relationship_events AS (
    SELECT cs.business_registration_number AS company_number,
           COALESCE(n.notice_published_at::date,g.first_contract_date)
             AS activity_date
    FROM contract_versions c
    JOIN contract_groups g USING (contract_event_key)
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    LEFT JOIN LATERAL (
      SELECT notice.notice_published_at
      FROM public_procurement.bid_notices notice
      WHERE notice.notice_number=CASE
        WHEN c.notice_number~'^[0-9]{13}$' AND right(c.notice_number,2)='00'
          THEN left(c.notice_number,length(c.notice_number)-2)
        ELSE NULLIF(c.notice_number,'') END
      ORDER BY (notice.notice_order='000') DESC,notice.notice_order DESC
      LIMIT 1
    ) n ON true
    WHERE cs.business_registration_number IS NOT NULL
      AND COALESCE(n.notice_published_at::date,g.first_contract_date)
            >= %(history_from)s
      AND COALESCE(n.notice_published_at::date,g.first_contract_date)
            < %(history_to)s
      AND (%(work_type)s::text IS NULL OR c.work_type=%(work_type)s)
      AND (%(large_category)s::text IS NULL OR c.large_category=%(large_category)s)
      AND (%(middle_category)s::text IS NULL OR c.middle_category=%(middle_category)s)
      AND (%(field_code)s::text IS NULL OR c.field_code=%(field_code)s)
)
SELECT company_number,min(activity_date) AS first_activity_date
FROM relationship_events
WHERE activity_date IS NOT NULL
GROUP BY company_number
"""
