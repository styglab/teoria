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
