-- Rebuild Rule bindings conservatively. A requirement type alone is not enough to
-- select an evaluator: electronic authentication is not supplier registration,
-- and a tax-evasion conviction is not an active procurement restriction.
UPDATE public_procurement.bid_eligibility_requirements
SET standard_rule_id = NULL,
    standard_rule_version = NULL,
    rule_arguments = '{}'::jsonb
WHERE standard_rule_id IN (
    'is_active_business',
    'is_registered_procurement_supplier',
    'has_registered_industry',
    'satisfies_participation_region',
    'is_valid_women_owned_business',
    'is_valid_disabled_owned_business',
    'holds_valid_direct_production_confirmation',
    'has_registered_supply_product',
    'has_no_active_procurement_sanction'
);

-- Add explicit subtypes only to unambiguous legacy clauses in the latest completed
-- extraction for each notice. Ambiguous authentication, representative, conviction,
-- insolvency and restructuring clauses intentionally remain unbound.
WITH latest AS (
    SELECT DISTINCT ON (notice_number, notice_order) extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), candidates AS (
    SELECT r.requirement_id, r.requirement_type,
           coalesce(r.proposition_text, r.original_text, '') AS clause
    FROM public_procurement.bid_eligibility_requirements r
    JOIN latest l USING (extraction_id)
    WHERE r.review_status = 'extracted'
)
UPDATE public_procurement.bid_eligibility_requirements r
SET value = jsonb_set(
    r.value,
    '{attributes}',
    coalesce(r.value->'attributes', '[]'::jsonb) || jsonb_build_array(
        jsonb_build_object(
            'name', CASE c.requirement_type
                WHEN 'procurement_registration' THEN 'procurement_registration_type'
                WHEN 'business_status' THEN 'business_status_type'
                ELSE 'sanction_type'
            END,
            'value', CASE c.requirement_type
                WHEN 'procurement_registration' THEN 'supplier_registration'
                WHEN 'business_status' THEN 'active_business_registration'
                ELSE 'procurement_participation_restriction'
            END
        )
    )
)
FROM candidates c
WHERE r.requirement_id = c.requirement_id
  AND NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
      WHERE a->>'name' IN (
          'procurement_registration_type', 'business_status_type', 'sanction_type'
      )
  )
  AND (
      (
          c.requirement_type = 'procurement_registration'
          AND c.clause ~ '(나라장터|국가종합전자조달|조달청)'
          AND c.clause ~ '(입찰참가자격|입찰참가자|전자입찰[[:space:]]*이용자).{0,20}등록'
          AND c.clause !~ '(개인인증|지문|신원확인|인증서[[:space:]]*차용|대표자|입찰대리인|변경등록)'
      )
      OR (c.requirement_type = 'business_status' AND c.clause ~ '계속사업자')
      OR (
          c.requirement_type = 'sanction'
          AND c.clause ~ '(부정당업자|입찰[[:space:]]*참가[[:space:]]*자격[[:space:]]*제한|입찰참가자격[[:space:]]*제한)'
          AND c.clause !~ '(조세포탈|유죄판결|경영개선|워크아웃|회생절차|청산|휴업|폐업|기술자|대리인)'
      )
  );

-- Direct-production confirmations are safe to automate only when the detailed
-- product code is present. A name-only certificate remains for document review.
WITH latest AS (
    SELECT DISTINCT ON (notice_number, notice_order) extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), candidates AS (
    SELECT r.requirement_id,
           substring(coalesce(r.proposition_text, r.original_text, '') from '([0-9]{10})') AS product_code
    FROM public_procurement.bid_eligibility_requirements r
    JOIN latest l USING (extraction_id)
    WHERE r.requirement_type = 'certificate'
      AND r.review_status = 'extracted'
      AND coalesce(r.proposition_text, r.original_text, '') ~ '직접생산확인'
      AND coalesce(r.proposition_text, r.original_text, '') ~ '[0-9]{10}'
)
UPDATE public_procurement.bid_eligibility_requirements r
SET value = jsonb_set(
    r.value,
    '{attributes}',
    (
        SELECT coalesce(jsonb_agg(a), '[]'::jsonb)
        FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
        WHERE lower(a->>'name') NOT IN ('certificate_type', 'product_code', 'detailed_product_code')
    ) || jsonb_build_array(
        jsonb_build_object('name', 'certificate_type', 'value', 'direct_production_confirmation'),
        jsonb_build_object('name', 'product_code', 'value', c.product_code)
    )
)
FROM candidates c
WHERE r.requirement_id = c.requirement_id;

-- Older extractions sometimes classified an atomic women/disabled-owned company
-- qualification as business_status. Reclassify only the self-contained legal status,
-- excluding references to the similarly named confirmation guideline.
WITH latest AS (
    SELECT DISTINCT ON (notice_number, notice_order) extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), candidates AS (
    SELECT r.requirement_id,
           CASE
               WHEN coalesce(r.proposition_text, r.original_text, '') ~ '여성기업' THEN 'women_owned_business'
               ELSE 'disabled_owned_business'
           END AS qualification_type
    FROM public_procurement.bid_eligibility_requirements r
    JOIN latest l USING (extraction_id)
    WHERE r.requirement_type IN ('business_status', 'certificate')
      AND r.review_status = 'extracted'
      AND coalesce(r.proposition_text, r.original_text, '') ~ '(여성기업지원에 관한 법률|장애인기업활동 촉진법)'
      AND coalesce(r.proposition_text, r.original_text, '') !~ '(확인요령|소기업|소상공인)'
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
    )
FROM candidates c
WHERE r.requirement_id = c.requirement_id;

WITH latest AS (
    SELECT DISTINCT ON (notice_number, notice_order) extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), normalized AS (
    SELECT r.requirement_id, r.requirement_type, r.value,
           (SELECT a->>'value' FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'industry_code' LIMIT 1) AS industry_code,
           (SELECT a->>'value' FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') IN ('product_code', 'detailed_product_code') LIMIT 1) AS product_code,
           (SELECT a->>'value' FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'certificate_type' LIMIT 1) AS certificate_type,
           (SELECT a->>'value' FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'qualification_type' LIMIT 1) AS qualification_type,
           (SELECT a->>'value' FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'procurement_registration_type' LIMIT 1) AS procurement_registration_type,
           (SELECT a->>'value' FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'business_status_type' LIMIT 1) AS business_status_type,
           (SELECT a->>'value' FROM jsonb_array_elements(coalesce(r.value->'attributes', '[]'::jsonb)) a
            WHERE lower(a->>'name') = 'sanction_type' LIMIT 1) AS sanction_type
    FROM public_procurement.bid_eligibility_requirements r
    JOIN latest l USING (extraction_id)
    WHERE r.review_status = 'extracted'
), bindings AS (
    SELECT n.*,
           CASE
               WHEN requirement_type = 'business_status'
                    AND business_status_type = 'active_business_registration'
                   THEN 'is_active_business'
               WHEN requirement_type = 'procurement_registration'
                    AND procurement_registration_type = 'supplier_registration'
                   THEN 'is_registered_procurement_supplier'
               WHEN requirement_type = 'industry_license' THEN 'has_registered_industry'
               WHEN requirement_type = 'participation_region' THEN 'satisfies_participation_region'
               WHEN requirement_type = 'product_registration' THEN 'has_registered_supply_product'
               WHEN requirement_type = 'certificate'
                    AND certificate_type = 'direct_production_confirmation'
                   THEN 'holds_valid_direct_production_confirmation'
               WHEN requirement_type = 'certificate'
                    AND qualification_type = 'women_owned_business'
                   THEN 'is_valid_women_owned_business'
               WHEN requirement_type = 'certificate'
                    AND qualification_type = 'disabled_owned_business'
                   THEN 'is_valid_disabled_owned_business'
               WHEN requirement_type = 'sanction'
                    AND sanction_type = 'procurement_participation_restriction'
                   THEN 'has_no_active_procurement_sanction'
           END AS rule_id,
           CASE
               WHEN requirement_type = 'industry_license' THEN jsonb_build_object(
                   'expected_value', coalesce(
                       to_jsonb(nullif(industry_code, '')),
                       nullif(value->'items', '[]'::jsonb),
                       to_jsonb(nullif(value->>'text', ''))
                   )
               )
               WHEN requirement_type = 'participation_region' THEN jsonb_build_object(
                   'expected_value', coalesce(
                       nullif(value->'items', '[]'::jsonb),
                       to_jsonb(nullif(value->>'text', ''))
                   )
               )
               WHEN requirement_type = 'product_registration' THEN jsonb_build_object(
                   'product_code', coalesce(
                       to_jsonb(nullif(product_code, '')),
                       nullif(value->'items', '[]'::jsonb),
                       to_jsonb(nullif(value->>'text', ''))
                   )
               )
               WHEN requirement_type = 'certificate'
                    AND certificate_type = 'direct_production_confirmation'
                    AND product_code IS NOT NULL
                   THEN jsonb_build_object('product_code', product_code)
               ELSE '{}'::jsonb
           END AS arguments
    FROM normalized n
)
UPDATE public_procurement.bid_eligibility_requirements r
SET standard_rule_id = b.rule_id,
    standard_rule_version = '1.0.0',
    rule_arguments = b.arguments
FROM bindings b
WHERE r.requirement_id = b.requirement_id
  AND b.rule_id IS NOT NULL
  AND (b.rule_id NOT IN ('has_registered_industry', 'satisfies_participation_region')
       OR b.arguments->'expected_value' <> 'null'::jsonb)
  AND (b.rule_id <> 'has_registered_supply_product'
       OR b.arguments->'product_code' <> 'null'::jsonb);
