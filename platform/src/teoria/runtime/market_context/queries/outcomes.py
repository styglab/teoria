_PROCUREMENT_OUTCOME_AWARDS_QUERY = """
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
FROM public_procurement.runtime_bid_awards a
LEFT JOIN public_procurement.runtime_bid_notices n
  ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
WHERE a.demand_organization_code=%(organization_code)s
  AND COALESCE(a.final_award_date,a.opening_at::date) >= %(period_from)s
  AND COALESCE(a.final_award_date,a.opening_at::date) < %(period_to)s
ORDER BY COALESCE(a.final_award_date,a.opening_at::date) DESC,a.award_id DESC
"""


_PROCUREMENT_ACTIVITY_NOTICES_QUERY = """
SELECT n.bid_notice_id,n.notice_name,n.notice_published_at AS published_at,
       n.bid_begin_at,n.bid_deadline_at,n.bid_status,n.notice_status,n.notice_kind_name,
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


_CONTRACT_SUPPLIERS_BATCH_QUERY = """
SELECT c.unified_contract_number,c.is_joint_contract,
       cs.supplier_sequence,cs.business_registration_number,cs.supplier_name,
       cs.supplier_role_name,cs.joint_contract_method_name,
       cs.participation_share_rate
FROM public_procurement.contracts c
JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
WHERE c.unified_contract_number=ANY(%(unified_contract_numbers)s::text[])
ORDER BY array_position(%(unified_contract_numbers)s::text[],c.unified_contract_number),
         CASE WHEN cs.supplier_role_name='주계약업체' THEN 0 ELSE 1 END,
         cs.supplier_sequence
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

_ORGANIZATION_AWARD_CONTRACT_ACTIVITIES_QUERY = """
WITH award_activities AS (
    SELECT a.winner_business_registration_number AS company_number,
           a.notice_number || ':' || a.notice_order AS bid_notice_id,
           n.notice_name, n.notice_published_at::date AS notice_published_date,
           a.bid_classification_number, a.rebid_number,
           NULL::integer AS opening_rank, a.winning_amount AS bid_amount,
           'awarded'::text AS result,
           COALESCE(a.final_award_date, a.opening_at::date) AS activity_date,
           NULL::text AS unified_contract_number
    FROM public_procurement.bid_awards a
    JOIN public_procurement.bid_notices n
      ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
    WHERE n.demand_organization_code=%(organization_code)s
      AND a.winner_business_registration_number=ANY(%(company_numbers)s)
      AND a.opening_at < %(as_of)s
), contract_activities AS (
    SELECT cs.business_registration_number AS company_number,
           CASE WHEN COALESCE(c.notice_number,'')<>''
                THEN c.notice_number || ':000'
                ELSE 'contract:' || COALESCE(NULLIF(c.confirmed_contract_number,''),
                                              c.unified_contract_number) END AS bid_notice_id,
           c.contract_name AS notice_name, c.concluded_date AS notice_published_date,
           NULL::text AS bid_classification_number, NULL::text AS rebid_number,
           NULL::integer AS opening_rank,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW' THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                THEN c.current_contract_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.current_contract_amount END AS bid_amount,
           'contracted'::text AS result, c.concluded_date AS activity_date,
           c.unified_contract_number
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE d.organization_code=%(organization_code)s
      AND cs.business_registration_number=ANY(%(company_numbers)s)
      AND c.concluded_date < %(as_of)s::date
)
SELECT * FROM award_activities
UNION ALL SELECT * FROM contract_activities
ORDER BY company_number, activity_date DESC NULLS LAST, bid_notice_id,
         bid_classification_number NULLS LAST, rebid_number NULLS LAST
"""


_ORGANIZATION_FIELD_EVENT_ROWS_QUERY = """
WITH organization_awards AS (
    SELECT 'award'::text AS source_kind,
           a.notice_number, a.notice_order, a.bid_classification_number,
           a.rebid_number, NULL::text AS unified_contract_number,
           NULL::text AS original_contract_number,
           a.notice_number || ':' || a.notice_order AS bid_notice_id,
           COALESCE(n.notice_name,a.notice_name) AS notice_name,
           COALESCE(a.final_award_date,a.opening_at::date) AS event_date,
           a.winning_amount AS event_amount,
           a.winner_business_registration_number AS company_number,
           a.winner_name AS company_name,
           NULL::numeric AS participation_share_rate,
           NULL::text AS supplier_role_name,
           n.notice_published_at::date AS notice_published_date,
           NULL::text AS contract_period_text,
           NULL::numeric AS contract_amount,
           NULL::text AS contract_currency,
           n.notice_published_at::date AS attribution_date,
           'notice_published_at'::text AS attribution_date_basis,
           NULL::date AS first_contract_date,
           NULL::date AS latest_contract_version_date
    FROM public_procurement.runtime_bid_awards a
    LEFT JOIN public_procurement.bid_notices n
      ON n.notice_number=a.notice_number AND n.notice_order=a.notice_order
    WHERE a.demand_organization_code=%(organization_code)s
      AND (%(work_type)s::text IS NULL OR a.work_type=%(work_type)s)
      AND (%(large_category)s::text IS NULL OR a.large_category=%(large_category)s)
      AND (%(middle_category)s::text IS NULL OR a.middle_category=%(middle_category)s)
      AND (%(procurement_field_code)s::text IS NULL
           OR a.field_code=%(procurement_field_code)s)
      AND COALESCE(a.final_award_date,a.opening_at::date)<%(as_of)s::date
      AND a.winner_business_registration_number IS NOT NULL
), organization_contracts AS (
    SELECT 'contract'::text AS source_kind,
           NULLIF(c.notice_number,'') AS notice_number,
           NULL::text AS notice_order, NULL::text AS bid_classification_number,
           NULL::text AS rebid_number, c.unified_contract_number,
           COALESCE(NULLIF(c.confirmed_contract_number,''),
                    NULLIF(c.contract_reference_number,''),c.unified_contract_number)
             AS original_contract_number,
           CASE WHEN COALESCE(c.notice_number,'')<>'' THEN c.notice_number || ':000'
                ELSE 'contract:' || c.unified_contract_number END AS bid_notice_id,
           COALESCE(n.notice_name,c.contract_name) AS notice_name,
           c.concluded_date AS event_date,
           c.current_contract_amount AS event_amount,
           cs.business_registration_number AS company_number,
           cs.supplier_name AS company_name,
           cs.participation_share_rate, cs.supplier_role_name,
           n.notice_published_at::date AS notice_published_date,
           c.contract_period_text,
           c.current_contract_amount AS contract_amount,
           COALESCE(c.current_contract_amount_currency,'KRW') AS contract_currency,
           COALESCE(
             n.notice_published_at::date,
             min(c.concluded_date) OVER (
               PARTITION BY d.organization_code,
                 COALESCE(NULLIF(c.confirmed_contract_number,''),
                          NULLIF(c.contract_reference_number,''),c.unified_contract_number)
             )
           ) AS attribution_date,
           CASE WHEN n.notice_published_at IS NOT NULL THEN 'notice_published_at'
                ELSE 'first_contract_date' END AS attribution_date_basis,
           min(c.concluded_date) OVER (
             PARTITION BY d.organization_code,
               COALESCE(NULLIF(c.confirmed_contract_number,''),
                        NULLIF(c.contract_reference_number,''),c.unified_contract_number)
           ) AS first_contract_date,
           max(c.concluded_date) OVER (
             PARTITION BY d.organization_code,
               COALESCE(NULLIF(c.confirmed_contract_number,''),
                        NULLIF(c.contract_reference_number,''),c.unified_contract_number)
           ) AS latest_contract_version_date
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.runtime_contracts c USING (unified_contract_number)
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    LEFT JOIN LATERAL (
      SELECT notice.notice_name,notice.notice_published_at
      FROM public_procurement.bid_notices notice
      WHERE notice.notice_number=CASE
        WHEN c.notice_number~'^[0-9]{13}$' AND right(c.notice_number,2)='00'
          THEN left(c.notice_number,length(c.notice_number)-2)
        ELSE NULLIF(c.notice_number,'') END
      ORDER BY (notice.notice_order='000') DESC,notice.notice_order DESC
      LIMIT 1
    ) n ON true
    WHERE d.organization_code=%(organization_code)s
      AND (%(work_type)s::text IS NULL OR c.work_type=%(work_type)s)
      AND (%(large_category)s::text IS NULL OR c.large_category=%(large_category)s)
      AND (%(middle_category)s::text IS NULL OR c.middle_category=%(middle_category)s)
      AND (%(procurement_field_code)s::text IS NULL
           OR c.field_code=%(procurement_field_code)s)
      AND c.concluded_date<%(as_of)s::date
      AND cs.business_registration_number IS NOT NULL
)
SELECT * FROM organization_awards
UNION ALL
SELECT * FROM organization_contracts
ORDER BY event_date,source_kind,notice_number,unified_contract_number,company_number
"""
