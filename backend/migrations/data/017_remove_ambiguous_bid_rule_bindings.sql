-- These clauses require facts or logic that the bound evaluator does not provide.
-- Keep them as extracted requirements, but force Runtime to return needs_review.
UPDATE public_procurement.bid_eligibility_requirements
SET standard_rule_id = NULL,
    standard_rule_version = NULL,
    rule_arguments = '{}'::jsonb
WHERE standard_rule_id = 'holds_valid_direct_production_confirmation'
  AND regexp_count(coalesce(proposition_text, original_text, ''), '[0-9]{10}') > 1;

UPDATE public_procurement.bid_eligibility_requirements
SET standard_rule_id = NULL,
    standard_rule_version = NULL,
    rule_arguments = '{}'::jsonb
WHERE standard_rule_id = 'has_no_active_procurement_sanction'
  AND coalesce(proposition_text, original_text, '')
      ~ '(종료일|제재[[:space:]·]*종료).{0,30}[0-9]+[[:space:]]*(개월|년)';

UPDATE public_procurement.bid_eligibility_requirements
SET standard_rule_id = NULL,
    standard_rule_version = NULL,
    rule_arguments = '{}'::jsonb
WHERE standard_rule_id = 'is_registered_procurement_supplier'
  AND coalesce(proposition_text, original_text, '') ~ '(전자입찰|나라장터).{0,20}이용자[[:space:]]*등록'
  AND coalesce(proposition_text, original_text, '')
      !~ '(입찰참가자격|입찰참가자).{0,20}등록';
