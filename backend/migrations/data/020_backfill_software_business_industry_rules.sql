-- Normalize explicit software-business registration requirements to the same
-- 나라장터 registered-industry rule used by structured PPS license records.
WITH latest AS (
    SELECT DISTINCT ON (notice_number, notice_order) extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), candidates AS (
    SELECT r.requirement_id,
           substring(
               coalesce(r.proposition_text, r.original_text, '')
               FROM '업종[[:space:]]*코드[[:space:]]*[:：]?[[:space:]]*\[?[[:space:]]*([0-9]{4})'
           ) AS industry_code
    FROM public_procurement.bid_eligibility_requirements r
    JOIN latest l USING (extraction_id)
    WHERE r.review_status = 'extracted'
      AND r.requirement_type IN (
          'industry_license', 'business_status', 'certificate', 'legal_qualification', 'custom'
      )
      AND coalesce(r.proposition_text, r.original_text, '') ~ '소프트웨어[[:space:]]*사업자'
)
UPDATE public_procurement.bid_eligibility_requirements r
SET requirement_type = 'industry_license',
    value = jsonb_set(
        coalesce(r.value, '{}'::jsonb),
        '{attributes}',
        (
            SELECT coalesce(jsonb_agg(a), '[]'::jsonb)
            FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') <> 'industry_code'
        ) || CASE WHEN c.industry_code IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(
            jsonb_build_object('name', 'industry_code', 'value', c.industry_code)
        ) END
    ),
    standard_rule_id = 'has_registered_industry',
    standard_rule_version = '1.1.0',
    rule_arguments = jsonb_build_object(
        'expected_value', coalesce(c.industry_code, '소프트웨어사업자')
    )
FROM candidates c
WHERE r.requirement_id = c.requirement_id;

UPDATE public_procurement.bid_eligibility_requirements
SET standard_rule_version = '1.1.0'
WHERE standard_rule_id = 'has_registered_industry';
