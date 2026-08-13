-- Normalize only explicit innovation-company eligibility requirements in the
-- latest completed extraction. The Runtime evaluator still applies each
-- Source's temporal limits, especially current-only venture disclosures.
WITH latest AS (
    SELECT DISTINCT ON (notice_number, notice_order) extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), candidates AS (
    SELECT r.requirement_id,
           CASE
               WHEN coalesce(r.proposition_text, r.original_text, '') ~ '벤처기업'
                   THEN 'venture_business'
               WHEN coalesce(r.proposition_text, r.original_text, '') ~ '(이노비즈|기술혁신형[[:space:]]*중소기업)'
                   THEN 'innobiz'
               WHEN coalesce(r.proposition_text, r.original_text, '') ~ '(메인비즈|경영혁신형[[:space:]]*중소기업)'
                   THEN 'mainbiz'
           END AS qualification_type
    FROM public_procurement.bid_eligibility_requirements r
    JOIN latest l USING (extraction_id)
    WHERE r.review_status = 'extracted'
      AND r.requirement_type IN ('business_status', 'certificate', 'legal_qualification', 'custom')
      AND coalesce(r.proposition_text, r.original_text, '')
          ~ '(벤처기업|이노비즈|기술혁신형[[:space:]]*중소기업|메인비즈|경영혁신형[[:space:]]*중소기업)'
)
UPDATE public_procurement.bid_eligibility_requirements r
SET requirement_type = 'certificate',
    value = jsonb_set(
        r.value,
        '{attributes}',
        (
            SELECT coalesce(jsonb_agg(a), '[]'::jsonb)
            FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') <> 'qualification_type'
        ) || jsonb_build_array(
            jsonb_build_object('name', 'qualification_type', 'value', c.qualification_type)
        )
    ),
    standard_rule_id = 'holds_valid_company_qualification',
    standard_rule_version = '1.1.0',
    rule_arguments = jsonb_build_object('qualification_type', c.qualification_type)
FROM candidates c
WHERE r.requirement_id = c.requirement_id
  AND c.qualification_type IS NOT NULL;

UPDATE public_procurement.bid_eligibility_requirements
SET standard_rule_version = '1.1.0'
WHERE standard_rule_id = 'holds_valid_company_qualification';
