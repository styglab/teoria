CREATE OR REPLACE FUNCTION public_procurement.hangul_initials(value text)
RETURNS text
LANGUAGE plpgsql
IMMUTABLE
PARALLEL SAFE
AS $$
DECLARE
    character text;
    codepoint integer;
    initials text[] := ARRAY[
        'ㄱ','ㄲ','ㄴ','ㄷ','ㄸ','ㄹ','ㅁ','ㅂ','ㅃ','ㅅ',
        'ㅆ','ㅇ','ㅈ','ㅉ','ㅊ','ㅋ','ㅌ','ㅍ','ㅎ'
    ];
    result text := '';
BEGIN
    IF value IS NULL THEN
        RETURN '';
    END IF;
    FOREACH character IN ARRAY regexp_split_to_array(value, '') LOOP
        codepoint := ascii(character);
        IF codepoint BETWEEN 44032 AND 55203 THEN
            result := result || initials[((codepoint - 44032) / 588) + 1];
        ELSIF character !~ '\s' THEN
            result := result || lower(character);
        END IF;
    END LOOP;
    RETURN result;
END;
$$;

CREATE MATERIALIZED VIEW public_procurement.procurement_entity_search_index AS
WITH company_names AS (
    SELECT company_number AS entity_id,
           (array_agg(company_name ORDER BY refreshed_at DESC)
             FILTER (WHERE company_name IS NOT NULL))[1] AS display_name,
           max(refreshed_at) AS sort_at
    FROM public_procurement.contract_event_company_ledger
    GROUP BY company_number
), classifications AS (
    SELECT procurement_classification_number AS entity_id,
           max(procurement_classification_name) AS display_name,
           max(updated_at) AS sort_at,
           jsonb_build_object(
               'classification_system','pps_procurement',
               'large_category',max(procurement_large_classification_name),
               'middle_category',max(procurement_middle_classification_name)
           ) AS context
    FROM public_procurement.bid_notices
    WHERE procurement_classification_number IS NOT NULL
    GROUP BY procurement_classification_number
), entities AS (
    SELECT 'bid_notice'::text AS entity_type,
           notice_number||':'||notice_order AS entity_id,
           notice_name AS display_name,notice_number AS display_number,
           notice_published_at AS sort_at,
           jsonb_build_object(
               'notice_organization_code',notice_organization_code,
               'notice_organization_name',notice_organization_name,
               'demand_organization_code',demand_organization_code,
               'demand_organization_name',demand_organization_name,
               'work_type',work_type,
               'field_code',procurement_classification_number,
               'field_name',procurement_classification_name,
               'large_category',procurement_large_classification_name,
               'middle_category',procurement_middle_classification_name,
               'region_basis',CASE WHEN participation_restriction_region_code IS NOT NULL
                 THEN 'participation_restriction' END,
               'region_code',participation_restriction_region_code,
               'region_name',participation_restriction_region_name
           ) AS context
    FROM public_procurement.bid_notices
    UNION ALL
    SELECT 'organization',organization_code,organization_name,organization_code,
           updated_at,jsonb_build_object('jurisdiction_type',jurisdiction_type)
    FROM public_procurement.public_organizations
    UNION ALL
    SELECT 'company',entity_id,display_name,entity_id,sort_at,'{}'::jsonb
    FROM company_names
    UNION ALL
    SELECT 'classification',entity_id,display_name,entity_id,sort_at,context
    FROM classifications
)
SELECT entity_type,entity_id,display_name,display_number,sort_at,context,
       regexp_replace(lower(coalesce(display_name,'')),'[\s-]+','','g') AS normalized_name,
       public_procurement.hangul_initials(display_name) AS initials
FROM entities;

CREATE UNIQUE INDEX procurement_entity_search_identity_idx
    ON public_procurement.procurement_entity_search_index(entity_type,entity_id);
CREATE INDEX procurement_entity_search_name_trgm_idx
    ON public_procurement.procurement_entity_search_index
    USING gin(normalized_name gin_trgm_ops);
CREATE INDEX procurement_entity_search_initials_trgm_idx
    ON public_procurement.procurement_entity_search_index
    USING gin(initials gin_trgm_ops);
CREATE INDEX procurement_entity_search_number_idx
    ON public_procurement.procurement_entity_search_index
    (display_number text_pattern_ops,entity_type);

CREATE OR REPLACE FUNCTION public_procurement.refresh_procurement_entity_search_index()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path=public_procurement,public
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY
        public_procurement.procurement_entity_search_index;
END;
$$;

REVOKE ALL ON FUNCTION public_procurement.refresh_procurement_entity_search_index()
    FROM PUBLIC;
GRANT SELECT ON public_procurement.procurement_entity_search_index TO teoria_runtime;
GRANT EXECUTE ON FUNCTION public_procurement.refresh_procurement_entity_search_index()
    TO teoria_pipeline;

ANALYZE public_procurement.procurement_entity_search_index;
