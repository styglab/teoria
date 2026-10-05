"""SQL statements used by market-context database readers.

Keep SQL isolated from capability orchestration and pure policy modules.
"""

_SIMILAR_NOTICE_CANDIDATES_QUERY = """
WITH target AS (
    SELECT public_procurement.normalize_bid_notice_title(notice_name) AS normalized_title
    FROM public_procurement.bid_notices
    WHERE notice_number=%(notice_number)s AND notice_order=%(notice_order)s
), title_candidates AS MATERIALIZED (
    SELECT n.notice_number, n.notice_order
    FROM public_procurement.bid_notices n
    CROSS JOIN target t
    WHERE (n.notice_number,n.notice_order)<>(%(notice_number)s,%(notice_order)s)
      AND n.work_type=%(work_type)s
      AND n.notice_published_at >= date_trunc('year', %(as_of)s::timestamptz)
          - ((%(period_years)s - 1) * interval '1 year')
      AND n.notice_published_at < %(as_of)s::timestamptz
      AND public_procurement.normalize_bid_notice_title(n.notice_name) %% t.normalized_title
    ORDER BY public_procurement.normalize_bid_notice_title(n.notice_name) <-> t.normalized_title
    LIMIT %(candidate_limit)s
), organization_candidates AS MATERIALIZED (
    SELECT n.notice_number, n.notice_order
    FROM public_procurement.bid_notices n
    WHERE (n.notice_number,n.notice_order)<>(%(notice_number)s,%(notice_order)s)
      AND n.work_type=%(work_type)s
      AND n.demand_organization_code=%(organization_code)s
      AND n.notice_published_at >= date_trunc('year', %(as_of)s::timestamptz)
          - ((%(period_years)s - 1) * interval '1 year')
      AND n.notice_published_at < %(as_of)s::timestamptz
    ORDER BY n.notice_published_at DESC
    LIMIT %(candidate_limit)s
), candidate_notices AS (
    SELECT * FROM title_candidates
    UNION
    SELECT * FROM organization_candidates
)
SELECT n.notice_number || ':' || n.notice_order AS bid_notice_id,
       n.notice_number, n.notice_order, n.notice_name, n.work_type,
       n.notice_published_at::date AS notice_published_date,
       n.contract_method_name, n.estimated_price, n.allocated_budget,
       n.demand_organization_code, n.demand_organization_name,
       licenses.industry_codes,
       similarity(public_procurement.normalize_bid_notice_title(a.notice_name),
                  t.normalized_title) AS title_trigram_score,
       a.winner_business_registration_number, a.winner_name,
       a.winning_amount, a.winning_rate,
       COALESCE(a.final_award_date, a.opening_at::date) AS award_date
FROM candidate_notices candidate
JOIN public_procurement.bid_notices n USING (notice_number, notice_order)
JOIN public_procurement.bid_awards a USING (notice_number, notice_order)
CROSS JOIN target t
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
                     ORDER BY substring(l.license_restriction_name FROM '/([0-9]{4})$'))
           AS industry_codes
    FROM public_procurement.bid_notice_license_restrictions l
    WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
      AND l.license_restriction_name ~ '/[0-9]{4}$'
) licenses ON true
WHERE a.work_type=%(work_type)s
  AND a.opening_at >= date_trunc('year', %(as_of)s::timestamptz)
      - ((%(period_years)s - 1) * interval '1 year')
  AND a.opening_at < %(as_of)s::timestamptz
  AND (
    %(include_awarded)s OR (
      %(include_contracted)s AND EXISTS (
        SELECT 1 FROM public_procurement.contracts c
        WHERE c.notice_number=a.notice_number
      )
    )
  )
ORDER BY (n.demand_organization_code=%(organization_code)s) DESC,
         similarity(public_procurement.normalize_bid_notice_title(a.notice_name),
                    t.normalized_title) DESC
LIMIT %(candidate_limit)s
"""

_COMPANY_SIMILAR_PROJECT_REFERENCE_QUERY = """
SELECT n.notice_number || ':' || n.notice_order AS bid_notice_id,
       n.notice_name, n.work_type, n.estimated_price, n.allocated_budget,
       LEAST(now(),COALESCE(n.bid_deadline_at,now())) AS as_of,
       COALESCE(licenses.industry_codes,ARRAY[]::text[]) AS industry_codes,
       COALESCE(licenses.industry_names,'{}'::jsonb) AS industry_names
FROM public_procurement.bid_notices n
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
                     ORDER BY substring(l.license_restriction_name FROM '/([0-9]{4})$'))
             FILTER (WHERE l.license_restriction_name ~ '/[0-9]{4}$') AS industry_codes,
           jsonb_object_agg(
               substring(l.license_restriction_name FROM '/([0-9]{4})$'),
               regexp_replace(l.license_restriction_name,'/[0-9]{4}$','')
           ) FILTER (WHERE l.license_restriction_name ~ '/[0-9]{4}$') AS industry_names
    FROM public_procurement.bid_notice_license_restrictions l
    WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
) licenses ON true
WHERE n.notice_number=%(notice_number)s AND n.notice_order=%(notice_order)s
"""

_COMPANY_SIMILAR_PROJECT_EXPERIENCE_QUERY = """
WITH reference AS (
    SELECT n.work_type,LEAST(now(),COALESCE(n.bid_deadline_at,now())) AS as_of,
           public_procurement.normalize_bid_notice_title(n.notice_name) AS normalized_title,
           ARRAY(
               SELECT DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
               FROM public_procurement.bid_notice_license_restrictions l
               WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
                 AND l.license_restriction_name ~ '/[0-9]{4}$'
           )::text[] AS industry_codes
    FROM public_procurement.bid_notices n
    WHERE n.notice_number=%(notice_number)s AND n.notice_order=%(notice_order)s
), company_awards AS MATERIALIZED (
    SELECT DISTINCT ON (a.notice_number,a.notice_order)
           a.notice_number,a.notice_order,
           COALESCE(a.final_award_date,a.opening_at::date) AS award_date,
           a.winning_amount
    FROM public_procurement.bid_awards a
    WHERE a.winner_business_registration_number=%(company_number)s
    ORDER BY a.notice_number,a.notice_order,
             COALESCE(a.final_award_date,a.opening_at::date) DESC NULLS LAST
), company_contracts AS MATERIALIZED (
    SELECT DISTINCT ON (normalized_notice_number)
           normalized_notice_number,c.concluded_date AS contract_date,
           c.current_contract_amount AS contract_amount,
           cs.participation_share_rate,cs.supplier_role_name,
           (SELECT count(*) FROM public_procurement.contract_suppliers all_cs
            WHERE all_cs.unified_contract_number=c.unified_contract_number) AS supplier_count
    FROM public_procurement.contract_suppliers cs
    JOIN public_procurement.runtime_contracts c USING (unified_contract_number)
    CROSS JOIN LATERAL (
        SELECT CASE
          WHEN c.notice_number ~ '^[0-9]{13}$' AND right(c.notice_number,2)='00'
            THEN left(c.notice_number,length(c.notice_number)-2)
          ELSE c.notice_number
        END AS normalized_notice_number
    ) normalized
    WHERE cs.business_registration_number=%(company_number)s
      AND COALESCE(c.notice_number,'')<>''
    ORDER BY normalized_notice_number,c.concluded_date DESC NULLS LAST
), company_notice_keys AS MATERIALIZED (
    SELECT notice_number,notice_order FROM company_awards
    UNION
    SELECT normalized_notice_number,'000'::text FROM company_contracts
), candidates AS MATERIALIZED (
    SELECT n.*
    FROM company_notice_keys k
    JOIN public_procurement.bid_notices n
      ON n.notice_number=k.notice_number AND n.notice_order=k.notice_order
    CROSS JOIN reference r
    WHERE (n.notice_number,n.notice_order)<>(%(notice_number)s,%(notice_order)s)
      AND n.work_type=r.work_type
      AND n.notice_published_at >= date_trunc('year', r.as_of)
          - ((%(period_years)s - 1) * interval '1 year')
      AND n.notice_published_at < r.as_of
      AND EXISTS (
          SELECT 1 FROM public_procurement.bid_notice_license_restrictions l
          WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
            AND l.license_restriction_name ~ '/[0-9]{4}$'
            AND substring(l.license_restriction_name FROM '/([0-9]{4})$')=ANY(r.industry_codes)
      )
)
SELECT n.notice_number || ':' || n.notice_order AS bid_notice_id,
       n.notice_name, n.notice_published_at::date AS notice_published_date,
       n.work_type, n.estimated_price, n.allocated_budget,
       n.demand_organization_code, n.demand_organization_name,
       licenses.industry_codes,
       award.award_date, award.winning_amount,
       contract.contract_date, contract.contract_amount,
       contract.participation_share_rate, contract.supplier_role_name,
       contract.supplier_count,
       similarity(public_procurement.normalize_bid_notice_title(n.notice_name),
                  r.normalized_title) AS title_trigram_score
FROM candidates n
CROSS JOIN reference r
LEFT JOIN company_awards award USING (notice_number,notice_order)
LEFT JOIN company_contracts contract
  ON contract.normalized_notice_number=n.notice_number
LEFT JOIN LATERAL (
    SELECT array_agg(DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
                     ORDER BY substring(l.license_restriction_name FROM '/([0-9]{4})$'))
           AS industry_codes
    FROM public_procurement.bid_notice_license_restrictions l
    WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
      AND l.license_restriction_name ~ '/[0-9]{4}$'
) licenses ON true
WHERE award.award_date IS NOT NULL OR contract.contract_date IS NOT NULL
ORDER BY COALESCE(contract.contract_date,award.award_date,n.notice_published_at::date) DESC
"""

_COMPANY_SIMILAR_PROJECT_METRICS_QUERY = """
WITH reference AS (
    SELECT n.notice_name AS reference_notice_name,n.work_type,
           LEAST(now(),COALESCE(n.bid_deadline_at,now())) AS as_of,
           COALESCE(n.estimated_price,n.allocated_budget)::numeric AS reference_amount,
           ARRAY(
               SELECT DISTINCT substring(l.license_restriction_name FROM '/([0-9]{4})$')
               FROM public_procurement.bid_notice_license_restrictions l
               WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
                 AND l.license_restriction_name ~ '/[0-9]{4}$'
           )::text[] AS industry_codes
    FROM public_procurement.bid_notices n
    WHERE n.notice_number=%(notice_number)s AND n.notice_order=%(notice_order)s
), company_awards AS MATERIALIZED (
    SELECT DISTINCT ON (a.winner_business_registration_number,a.notice_number,a.notice_order)
           a.winner_business_registration_number AS company_number,
           a.notice_number,a.notice_order,a.winning_amount
    FROM public_procurement.bid_awards a
    CROSS JOIN reference r
    WHERE a.winner_business_registration_number=ANY(%(company_numbers)s)
      AND a.work_type=r.work_type
      AND a.opening_at >= date_trunc('year', r.as_of)
          - ((%(period_years)s - 1) * interval '1 year')
      AND a.opening_at < r.as_of
    ORDER BY a.winner_business_registration_number,a.notice_number,a.notice_order,
             COALESCE(a.final_award_date,a.opening_at::date) DESC NULLS LAST
), company_contracts AS MATERIALIZED (
    SELECT DISTINCT ON (cs.business_registration_number,normalized_notice_number)
           cs.business_registration_number AS company_number,
           normalized_notice_number,c.current_contract_amount AS contract_amount
    FROM public_procurement.contract_suppliers cs
    JOIN public_procurement.contracts c USING (unified_contract_number)
    CROSS JOIN reference r
    CROSS JOIN LATERAL (
        SELECT CASE
          WHEN c.notice_number ~ '^[0-9]{13}$' AND right(c.notice_number,2)='00'
            THEN left(c.notice_number,length(c.notice_number)-2)
          ELSE c.notice_number
        END AS normalized_notice_number
    ) normalized
    WHERE cs.business_registration_number=ANY(%(company_numbers)s)
      AND COALESCE(c.notice_number,'')<>''
      AND c.contract_type=r.work_type
      AND c.concluded_date >= (
          date_trunc('year', r.as_of) - ((%(period_years)s - 1) * interval '1 year')
      )::date
      AND c.concluded_date < r.as_of::date
    ORDER BY cs.business_registration_number,normalized_notice_number,
             c.concluded_date DESC NULLS LAST
), company_notice_keys AS (
    SELECT company_number,notice_number,notice_order FROM company_awards
    UNION
    SELECT company_number,normalized_notice_number,'000'::text FROM company_contracts
), eligible_events AS (
    SELECT k.company_number,n.notice_number,n.notice_order,n.notice_name,
           r.reference_notice_name,
           COALESCE(c.contract_amount,a.winning_amount,n.estimated_price,n.allocated_budget)::numeric
             AS event_amount,r.reference_amount
    FROM company_notice_keys k
    JOIN public_procurement.bid_notices n
      ON n.notice_number=k.notice_number AND n.notice_order=k.notice_order
    CROSS JOIN reference r
    LEFT JOIN company_awards a
      ON a.company_number=k.company_number AND a.notice_number=n.notice_number
     AND a.notice_order=n.notice_order
    LEFT JOIN company_contracts c
      ON c.company_number=k.company_number AND c.normalized_notice_number=n.notice_number
    WHERE (n.notice_number,n.notice_order)<>(%(notice_number)s,%(notice_order)s)
      AND n.work_type=r.work_type
      AND n.notice_published_at >= date_trunc('year', r.as_of)
          - ((%(period_years)s - 1) * interval '1 year')
      AND n.notice_published_at < r.as_of
      AND EXISTS (
          SELECT 1 FROM public_procurement.bid_notice_license_restrictions l
          WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
            AND l.license_restriction_name ~ '/[0-9]{4}$'
            AND substring(l.license_restriction_name FROM '/([0-9]{4})$')=ANY(r.industry_codes)
      )
)
, scored AS (
    SELECT company_number,
           similarity(
               public_procurement.normalize_bid_notice_title(notice_name),
               public_procurement.normalize_bid_notice_title(reference_notice_name)
           ) >= 0.08 AS title_related,
           (
             (reference_notice_name~'(구축|개발|도입)' AND notice_name~'(구축|개발|도입)') OR
             (reference_notice_name~'(개선|고도화|재구축)' AND notice_name~'(개선|고도화|재구축)') OR
             (reference_notice_name~'(유지보수|유지관리|운영)' AND notice_name~'(유지보수|유지관리|운영)') OR
             (reference_notice_name~'(컨설팅|감리|설계)' AND notice_name~'(컨설팅|감리|설계)')
           ) AS project_type_match,
           CASE WHEN reference_amount IS NOT NULL AND reference_amount>0
                  AND event_amount IS NOT NULL AND event_amount>0
                THEN least(reference_amount,event_amount)/greatest(reference_amount,event_amount)>=0.5
                ELSE false END AS is_similar_amount
    FROM eligible_events
)
SELECT company_number,count(*) AS candidate_count,
       count(*) FILTER (WHERE title_related OR project_type_match) AS event_count,
       count(*) FILTER (WHERE title_related AND project_type_match) AS strong_event_count,
       count(*) FILTER (WHERE title_related<>project_type_match) AS limited_event_count,
       count(*) FILTER (WHERE NOT title_related AND NOT project_type_match)
         AS reference_only_event_count,
       count(*) FILTER (
           WHERE (title_related OR project_type_match) AND is_similar_amount
       ) AS similar_amount_event_count
FROM scored
GROUP BY company_number
"""

_RELEVANT_COMPANY_ACTIVITIES_QUERY = """
WITH similar_notices AS (
    SELECT * FROM jsonb_to_recordset(%(similar_notices)s::jsonb)
      AS n(bid_notice_id text, notice_number text, notice_order text)
), participation_activities AS (
    SELECT bp.business_registration_number AS company_number,
           sn.bid_notice_id, bp.bid_classification_number, bp.rebid_number,
           bp.opening_rank, bp.bid_amount,
           a.winning_amount,
           CASE WHEN a.award_id IS NULL THEN 'participation_only'
                WHEN a.winner_business_registration_number=bp.business_registration_number
                THEN 'awarded' ELSE 'not_awarded' END AS result,
           COALESCE(bp.bid_at, a.opening_at, bp.created_at)::date AS activity_date,
           NULL::text AS unified_contract_number
    FROM similar_notices sn
    JOIN public_procurement.bid_opening_participants bp
      ON bp.notice_number=sn.notice_number AND bp.notice_order=sn.notice_order
    LEFT JOIN public_procurement.bid_awards a
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
    WHERE bp.business_registration_number=ANY(%(company_numbers)s)
      AND COALESCE(bp.bid_at, a.opening_at, bp.created_at) < %(as_of)s
), award_only_activities AS (
    SELECT a.winner_business_registration_number AS company_number,
           sn.bid_notice_id, a.bid_classification_number, a.rebid_number,
           NULL::integer AS opening_rank, a.winning_amount AS bid_amount, a.winning_amount,
           'awarded'::text AS result,
           COALESCE(a.final_award_date, a.opening_at::date) AS activity_date,
           NULL::text AS unified_contract_number
    FROM similar_notices sn
    JOIN public_procurement.bid_awards a
      ON a.notice_number=sn.notice_number AND a.notice_order=sn.notice_order
    WHERE a.winner_business_registration_number=ANY(%(company_numbers)s)
      AND a.opening_at < %(as_of)s
      AND NOT EXISTS (
        SELECT 1 FROM public_procurement.bid_opening_participants bp
        WHERE bp.notice_number=a.notice_number AND bp.notice_order=a.notice_order
          AND bp.bid_classification_number=a.bid_classification_number
          AND bp.rebid_number=a.rebid_number
          AND bp.business_registration_number=a.winner_business_registration_number
      )
), contract_activities AS (
    SELECT DISTINCT cs.business_registration_number AS company_number,
           sn.bid_notice_id, NULL::text AS bid_classification_number,
           NULL::text AS rebid_number, NULL::integer AS opening_rank,
           NULL::numeric AS bid_amount, NULL::numeric AS winning_amount,
           'contracted'::text AS result, c.concluded_date AS activity_date,
           c.unified_contract_number
    FROM similar_notices sn
    JOIN public_procurement.contracts c ON c.notice_number=sn.notice_number
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE cs.business_registration_number=ANY(%(company_numbers)s)
      AND c.concluded_date < %(as_of)s::date
)
SELECT * FROM participation_activities
UNION ALL SELECT * FROM award_only_activities
UNION ALL SELECT * FROM contract_activities
ORDER BY company_number, activity_date DESC NULLS LAST, bid_notice_id,
         bid_classification_number NULLS LAST, rebid_number NULLS LAST
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

_PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY = """
SELECT requested.procurement_classification_number,
       hierarchy.procurement_large_classification_name,
       hierarchy.procurement_middle_classification_name,
       hierarchy.purchase_items
FROM unnest(%(classification_numbers)s::text[])
  AS requested(procurement_classification_number)
CROSS JOIN LATERAL (
    SELECT n.procurement_large_classification_name,
           n.procurement_middle_classification_name,n.purchase_items
    FROM public_procurement.bid_notices n
    WHERE n.procurement_classification_number=requested.procurement_classification_number
      AND (n.procurement_large_classification_name IS NOT NULL
           OR n.procurement_middle_classification_name IS NOT NULL)
    ORDER BY n.notice_published_at DESC
    LIMIT 1
) hierarchy
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
           n.notice_published_at::date AS activity_date,
           a.winning_amount AS event_amount,NULL::numeric AS attributed_contract_amount,
           'unknown'::text AS amount_completeness,
           'notice_published_at'::text AS attribution_date_basis,
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
      AND n.notice_published_at >= %(period_from)s
      AND n.notice_published_at < %(period_to)s
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
    WHERE c.concluded_date < %(period_to)s
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
             v.concluded_date DESC,v.updated_at DESC,v.unified_contract_number DESC
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
           COALESCE(n.notice_published_at::date,c.first_contract_date) AS activity_date,
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
           CASE WHEN n.notice_published_at IS NOT NULL THEN 'notice_published_at'
                ELSE 'first_contract_date' END AS attribution_date_basis,
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
      AND COALESCE(n.notice_published_at::date,c.first_contract_date) >= %(period_from)s
      AND COALESCE(n.notice_published_at::date,c.first_contract_date) < %(period_to)s
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


_RELEVANT_COMPANY_QUERY = """
WITH similar_notices AS (
    SELECT * FROM jsonb_to_recordset(%(similar_notices)s::jsonb)
      AS n(bid_notice_id text, notice_number text, notice_order text)
),
params AS (
    SELECT %(organization_code)s::text AS organization_code,
           %(as_of)s::timestamptz AS as_of
),
similar_participations AS (
    SELECT bp.business_registration_number AS company_number,
           max(bp.participant_name) AS company_name,
           count(DISTINCT bp.bid_notice_id) AS participation_count,
           array_agg(DISTINCT sn.bid_notice_id ORDER BY sn.bid_notice_id) AS notice_ids,
           min(COALESCE(bp.bid_at, bp.created_at)::date) AS first_date,
           max(COALESCE(bp.bid_at, bp.created_at)::date) AS latest_date
    FROM similar_notices sn
    JOIN public_procurement.bid_opening_participants bp
      ON bp.notice_number=sn.notice_number AND bp.notice_order=sn.notice_order
    CROSS JOIN params p
    WHERE COALESCE(bp.bid_at, bp.created_at) < p.as_of
    GROUP BY bp.business_registration_number
),
similar_awards AS (
    SELECT a.winner_business_registration_number AS company_number,
           max(a.winner_name) AS company_name,
           count(DISTINCT a.award_id) AS award_count,
           sum(a.winning_amount) AS award_amount,
           array_agg(DISTINCT sn.bid_notice_id ORDER BY sn.bid_notice_id) AS notice_ids,
           min(a.opening_at::date) AS first_date,
           max(a.opening_at::date) AS latest_date
    FROM similar_notices sn
    JOIN public_procurement.bid_awards a
      ON a.notice_number=sn.notice_number AND a.notice_order=sn.notice_order
    CROSS JOIN params p
    WHERE a.winner_business_registration_number IS NOT NULL
      AND a.opening_at < p.as_of
    GROUP BY a.winner_business_registration_number
),
similar_contract_rows AS (
    SELECT cs.business_registration_number AS company_number,
           cs.supplier_name AS company_name, c.unified_contract_number,
           COALESCE(NULLIF(c.confirmed_contract_number,''), c.unified_contract_number)
             AS contract_key,
           sn.bid_notice_id, c.concluded_date,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW' THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                THEN c.current_contract_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.current_contract_amount END AS attributed_amount
    FROM similar_notices sn
    JOIN public_procurement.contracts c ON c.notice_number=sn.notice_number
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    CROSS JOIN params p
    WHERE cs.business_registration_number IS NOT NULL
      AND c.concluded_date < p.as_of::date
),
similar_contract_records AS (
    SELECT company_number, max(company_name) AS company_name, contract_key,
           bid_notice_id,
           count(DISTINCT unified_contract_number) AS unified_contract_count,
           max(attributed_amount) AS attributed_amount,
           bool_and(attributed_amount IS NOT NULL) AS amount_complete,
           min(concluded_date) AS first_date, max(concluded_date) AS latest_date
    FROM similar_contract_rows
    GROUP BY company_number, contract_key, bid_notice_id
),
similar_contracts AS (
    SELECT company_number, max(company_name) AS company_name,
           count(DISTINCT contract_key) AS contract_count,
           sum(unified_contract_count) AS unified_contract_count,
           sum(attributed_amount) AS contract_amount,
           bool_and(amount_complete) AS amount_complete,
           array_agg(DISTINCT bid_notice_id ORDER BY bid_notice_id) AS notice_ids,
           min(first_date) AS first_date, max(latest_date) AS latest_date
    FROM similar_contract_records GROUP BY company_number
),
organization_awards AS (
    SELECT a.winner_business_registration_number AS company_number,
           max(a.winner_name) AS company_name,
           count(DISTINCT a.award_id) AS award_count,
           min(a.opening_at::date) AS first_date, max(a.opening_at::date) AS latest_date
    FROM public_procurement.bid_awards a, params p
    WHERE a.demand_organization_code=p.organization_code
      AND a.opening_at < p.as_of
      AND a.winner_business_registration_number IS NOT NULL
    GROUP BY a.winner_business_registration_number
),
organization_participations AS (
    SELECT bp.business_registration_number AS company_number,
           max(bp.participant_name) AS company_name,
           count(DISTINCT bp.bid_notice_id) AS participation_count,
           min(COALESCE(bp.bid_at,a.opening_at)::date) AS first_date,
           max(COALESCE(bp.bid_at,a.opening_at)::date) AS latest_date
    FROM public_procurement.bid_awards a
    JOIN public_procurement.bid_opening_participants bp
      ON a.notice_number=bp.notice_number AND a.notice_order=bp.notice_order
     AND a.bid_classification_number=bp.bid_classification_number
     AND a.rebid_number=bp.rebid_number
    CROSS JOIN params p
    WHERE a.demand_organization_code=p.organization_code AND a.opening_at < p.as_of
    GROUP BY bp.business_registration_number
),
eligible_contracts AS (
    SELECT DISTINCT c.unified_contract_number, c.confirmed_contract_number,
           c.concluded_date, c.current_contract_amount,
           c.current_contract_amount_currency
    FROM public_procurement.contract_demand_organizations d
    JOIN public_procurement.contracts c USING (unified_contract_number)
    CROSS JOIN params p
    WHERE d.organization_code=p.organization_code AND c.concluded_date < p.as_of::date
),
organization_contract_rows AS (
    SELECT cs.business_registration_number AS company_number, cs.supplier_name,
           c.unified_contract_number,
           COALESCE(NULLIF(c.confirmed_contract_number,''), c.unified_contract_number)
             AS contract_key,
           c.concluded_date,
           CASE WHEN COALESCE(c.current_contract_amount_currency,'KRW')<>'KRW' THEN NULL
                WHEN cs.participation_share_rate IS NOT NULL
                THEN c.current_contract_amount * cs.participation_share_rate / 100
                WHEN count(*) OVER (PARTITION BY c.unified_contract_number)=1
                THEN c.current_contract_amount END AS attributed_amount
    FROM eligible_contracts c
    JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
    WHERE cs.business_registration_number IS NOT NULL
),
organization_contract_records AS (
    SELECT company_number, max(supplier_name) AS supplier_name, contract_key,
           count(DISTINCT unified_contract_number) AS unified_contract_count,
           max(attributed_amount) AS attributed_amount,
           bool_and(attributed_amount IS NOT NULL) AS amount_complete,
           min(concluded_date) AS first_date, max(concluded_date) AS latest_date
    FROM organization_contract_rows
    GROUP BY company_number, contract_key
),
organization_contracts AS (
    SELECT company_number, max(supplier_name) AS company_name,
           count(*) AS contract_count,
           sum(unified_contract_count) AS unified_contract_count,
           sum(attributed_amount) AS contract_amount,
           bool_and(amount_complete) AS amount_complete,
           min(first_date) AS first_date, max(latest_date) AS latest_date
    FROM organization_contract_records GROUP BY company_number
),
candidates AS (
    SELECT company_number FROM similar_participations UNION
    SELECT company_number FROM similar_awards UNION
    SELECT company_number FROM similar_contracts UNION
    SELECT company_number FROM organization_awards UNION
    SELECT company_number FROM organization_contracts
)
SELECT c.company_number,
       COALESCE(op.company_name,oa.company_name,oc.company_name,
                sp.company_name,sa.company_name,sc.company_name) AS company_name,
       COALESCE(sp.participation_count,0) AS similar_participation_count,
       COALESCE(sa.award_count,0) AS similar_award_count,
       COALESCE(sc.contract_count,0) AS similar_contract_count,
       COALESCE(sc.unified_contract_count,0) AS similar_unified_contract_count,
       sa.award_amount AS similar_award_amount,
       sc.contract_amount AS similar_contract_amount,
       COALESCE(sc.amount_complete,false) AS similar_contract_amount_complete,
       sp.notice_ids AS participation_notice_ids,
       sa.notice_ids AS award_notice_ids,
       sc.notice_ids AS contract_notice_ids,
       LEAST(sp.first_date,sa.first_date,sc.first_date) AS similar_first_activity_date,
       GREATEST(sp.latest_date,sa.latest_date,sc.latest_date) AS similar_latest_activity_date,
       COALESCE(op.participation_count,0) AS organization_participation_count,
       COALESCE(oa.award_count,0) AS organization_award_count,
       COALESCE(oc.contract_count,0) AS organization_contract_count,
       COALESCE(oc.unified_contract_count,0) AS organization_unified_contract_count,
       oc.contract_amount AS organization_contract_amount,
       COALESCE(oc.amount_complete,false) AS contract_amount_complete,
       LEAST(op.first_date,oa.first_date,oc.first_date) AS organization_first_activity_date,
       GREATEST(op.latest_date,oa.latest_date,oc.latest_date) AS organization_latest_activity_date
FROM candidates c
LEFT JOIN similar_participations sp USING (company_number)
LEFT JOIN similar_awards sa USING (company_number)
LEFT JOIN similar_contracts sc USING (company_number)
LEFT JOIN organization_participations op USING (company_number)
LEFT JOIN organization_awards oa USING (company_number)
LEFT JOIN organization_contracts oc USING (company_number)
ORDER BY
  ((COALESCE(op.participation_count,0)+COALESCE(oa.award_count,0)+COALESCE(oc.contract_count,0)) > 0) DESC,
  COALESCE(sa.award_count,0) DESC,
  COALESCE(sc.contract_count,0) DESC,
  COALESCE(sp.participation_count,0) DESC,
  GREATEST(op.latest_date,oa.latest_date,oc.latest_date,
           sp.latest_date,sa.latest_date,sc.latest_date) DESC NULLS LAST,
  c.company_number
LIMIT %(limit)s
"""
