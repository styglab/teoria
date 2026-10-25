-- Bind newly supported rules on the latest completed extraction per notice.
-- Company-scale absence remains needs_review at Runtime until an authoritative
-- certificate/API fact exists, so this backfill cannot create a false rejection.
WITH latest AS (
    SELECT DISTINCT ON (notice_number, notice_order) extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), normalized AS (
    SELECT r.requirement_id, r.requirement_type, r.value,
           (SELECT a->>'value'
            FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'qualification_type' LIMIT 1) AS qualification_type,
           (SELECT a->>'value'
            FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'company_scale' LIMIT 1) AS company_scale,
           (SELECT a->>'value'
            FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'participation_mode' LIMIT 1) AS participation_mode
    FROM public_procurement.bid_eligibility_requirements r
    JOIN latest l USING (extraction_id)
    WHERE r.review_status = 'extracted'
)
UPDATE public_procurement.bid_eligibility_requirements r
SET standard_rule_id = CASE
        WHEN n.requirement_type = 'certificate'
             AND n.qualification_type IN ('women_owned_business', 'disabled_owned_business')
            THEN 'holds_valid_company_qualification'
        WHEN n.requirement_type = 'company_scale'
             AND coalesce(n.company_scale, n.value->>'text') IS NOT NULL
            THEN 'has_company_scale_qualification'
        ELSE 'is_consortium_allowed'
    END,
    standard_rule_version = '1.0.0',
    rule_arguments = CASE
        WHEN n.requirement_type = 'certificate' THEN
            jsonb_build_object('qualification_type', n.qualification_type)
        WHEN n.requirement_type = 'company_scale' THEN
            jsonb_build_object('company_scale', coalesce(n.company_scale, n.value->>'text'))
        ELSE jsonb_build_object('consortium_allowed', n.value->'boolean')
    END
FROM normalized n
WHERE r.requirement_id = n.requirement_id
  AND (
      (n.requirement_type = 'certificate'
       AND n.qualification_type IN ('women_owned_business', 'disabled_owned_business'))
      OR (n.requirement_type = 'company_scale'
          AND coalesce(n.company_scale, n.value->>'text') IS NOT NULL)
      OR (n.requirement_type = 'consortium'
          AND n.value->'boolean' IN ('true'::jsonb, 'false'::jsonb)
          AND (n.participation_mode IN ('consortium', 'single_only')
               OR coalesce(r.proposition_text, r.original_text, '') ~ '공동수급|공동도급'))
  );
