WITH matches AS (
    SELECT r.requirement_id, min(i.industry_code) AS industry_code,
           min(i.industry_name) AS industry_name
    FROM public_procurement.bid_eligibility_requirements r
    JOIN public_procurement.procurement_industries i
      ON i.is_active
     AND regexp_replace(lower(i.industry_name), '[^0-9a-z가-힣]+', '', 'g') =
         regexp_replace(lower(coalesce(r.value->>'text','')), '[^0-9a-z가-힣]+', '', 'g')
    WHERE r.requirement_type='industry_license'
      AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(coalesce(r.value->'attributes','[]'::jsonb)) a
          WHERE lower(a->>'name')='industry_code'
      )
    GROUP BY r.requirement_id
    HAVING count(*)=1
)
UPDATE public_procurement.bid_eligibility_requirements r
SET value=jsonb_set(r.value,'{attributes}',coalesce(r.value->'attributes','[]'::jsonb) ||
        jsonb_build_array(
            jsonb_build_object('name','industry_code','value',m.industry_code),
            jsonb_build_object('name','industry_name','value',m.industry_name)
        )),
    standard_rule_id='has_registered_industry',
    standard_rule_version='1.1.0',
    rule_arguments=jsonb_build_object('expected_value',m.industry_code)
FROM matches m WHERE r.requirement_id=m.requirement_id;
