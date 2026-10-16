"""Data DB statements owned by this market-analysis feature."""

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


_ORGANIZATION_RELATIONSHIP_ACTIVITIES_QUERY = """
WITH participation_activities AS (
    SELECT bp.business_registration_number AS company_number,
           bp.notice_number || ':' || bp.notice_order AS bid_notice_id,
           n.notice_name, n.notice_published_at::date AS notice_published_date,
           bp.bid_classification_number, bp.rebid_number,
           bp.opening_rank, bp.bid_amount,
           CASE WHEN a.award_id IS NULL THEN 'participation_only'
                WHEN a.winner_business_registration_number=bp.business_registration_number
                THEN 'awarded' ELSE 'not_awarded' END AS result,
           COALESCE(bp.bid_at, a.opening_at, bp.created_at)::date AS activity_date,
           NULL::text AS unified_contract_number
    FROM public_procurement.bid_opening_participants bp
    JOIN public_procurement.bid_notices n
      ON n.notice_number=bp.notice_number AND n.notice_order=bp.notice_order
    LEFT JOIN public_procurement.bid_awards a
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
    WHERE n.demand_organization_code=%(organization_code)s
      AND bp.business_registration_number=ANY(%(company_numbers)s)
      AND COALESCE(bp.bid_at, a.opening_at, bp.created_at) < %(as_of)s
), award_only_activities AS (
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
      AND NOT EXISTS (
        SELECT 1 FROM public_procurement.bid_opening_participants bp
        WHERE bp.notice_number=a.notice_number AND bp.notice_order=a.notice_order
          AND bp.bid_classification_number=a.bid_classification_number
          AND bp.rebid_number=a.rebid_number
          AND bp.business_registration_number=a.winner_business_registration_number
      )
), organization_contract_activities AS (
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
SELECT * FROM participation_activities
UNION ALL SELECT * FROM award_only_activities
UNION ALL SELECT * FROM organization_contract_activities
ORDER BY company_number, activity_date DESC NULLS LAST, bid_notice_id,
         bid_classification_number NULLS LAST, rebid_number NULLS LAST
"""
