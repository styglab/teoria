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

_PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY = """
SELECT DISTINCT ON (n.procurement_classification_number)
       n.procurement_classification_number,
       n.procurement_large_classification_name,
       n.procurement_middle_classification_name,n.purchase_items
FROM public_procurement.bid_notices n
WHERE n.procurement_classification_number=ANY(%(classification_numbers)s::text[])
  AND (n.procurement_large_classification_name IS NOT NULL
       OR n.procurement_middle_classification_name IS NOT NULL)
ORDER BY n.procurement_classification_number,n.notice_published_at DESC
"""

_COMPANY_PARTICIPATIONS_QUERY = """
SELECT p.bid_notice_id,p.notice_name,
       p.demand_organization_code AS organization_code,
       p.demand_organization_name AS organization_name,
       p.participation_date,p.rank,p.participant_count,p.bid_amount,p.winning_amount,
       p.result,p.result_confirmed,p.work_type,p.field_code,p.field_name,
       p.large_category,p.middle_category,p.classification_source,p.participant_name
FROM public_procurement.runtime_bid_opening_participants p
WHERE p.business_registration_number=%(company_number)s
  AND p.participation_date >= %(period_from)s
  AND p.participation_date < %(period_to)s
"""

_BID_NOTICE_PARTICIPATIONS_QUERY = """
SELECT a.bid_notice_id,a.notice_name,a.bid_classification_number,a.rebid_number,
       a.participant_count AS source_participant_count,
       a.winner_business_registration_number,
       p.participation_id,p.business_registration_number,p.participant_name,
       p.opening_rank,p.bid_amount,p.bid_rate,p.result,p.result_confirmed
FROM public_procurement.runtime_bid_awards a
LEFT JOIN public_procurement.runtime_bid_opening_participants p
  ON p.notice_number=a.notice_number AND p.notice_order=a.notice_order
 AND p.bid_classification_number=a.bid_classification_number
 AND p.rebid_number=a.rebid_number
WHERE a.notice_number=%(notice_number)s AND a.notice_order=%(notice_order)s
ORDER BY a.bid_classification_number,a.rebid_number,p.opening_rank NULLS LAST,
         p.business_registration_number NULLS LAST,p.participation_id NULLS LAST
"""

_COMPANY_COMPETITORS_QUERY = """
SELECT co.business_registration_number AS company_number,
       co.participant_name AS company_name,
       co.bid_notice_id,co.participation_date,
       concat_ws(':',co.notice_number,co.notice_order,
                 co.bid_classification_number,co.rebid_number) AS participation_event_id,
       target.work_type,target.field_code,target.field_name,
       target.large_category,target.middle_category,target.classification_source
FROM public_procurement.runtime_bid_opening_participants target
JOIN public_procurement.runtime_bid_opening_participants co
  ON co.notice_number=target.notice_number AND co.notice_order=target.notice_order
 AND co.bid_classification_number=target.bid_classification_number
 AND co.rebid_number=target.rebid_number
WHERE target.business_registration_number=%(company_number)s
  AND co.business_registration_number<>%(company_number)s
  AND target.participation_date >= %(period_from)s
  AND target.participation_date < %(period_to)s
"""

