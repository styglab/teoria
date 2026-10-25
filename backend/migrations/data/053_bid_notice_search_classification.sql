DROP VIEW public_procurement.runtime_bid_notices;
DROP VIEW public_procurement.runtime_bid_notices_base;

CREATE VIEW public_procurement.runtime_bid_notices_base AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number,
        notice_order,
        extraction_id,
        completeness,
        requires_review
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
)
SELECT
    n.notice_number || ':' || n.notice_order AS bid_notice_id,
    n.notice_number,
    n.notice_order,
    n.notice_name,
    n.work_type,
    n.procurement_classification_number AS field_code,
    n.procurement_classification_name AS field_name,
    CASE
        WHEN n.work_type = 'construction' THEN n.procurement_classification_name
        ELSE n.procurement_large_classification_name
    END AS large_category,
    CASE
        WHEN n.work_type = 'construction' THEN NULL
        ELSE n.procurement_middle_classification_name
    END AS middle_category,
    ARRAY(
        SELECT DISTINCT code
        FROM (
            SELECT NULLIF(n.procurement_classification_number, '') AS code
            UNION ALL
            SELECT NULLIF(item->>'code', '')
            FROM jsonb_array_elements(COALESCE(n.purchase_items, '[]'::jsonb)) item
        ) classification_codes
        WHERE code IS NOT NULL
    ) AS field_codes,
    n.notice_kind_name,
    n.is_re_notice,
    n.notice_published_at,
    n.bid_begin_at,
    n.bid_deadline_at,
    n.opening_at,
    CASE
        WHEN n.bid_deadline_at IS NULL
             AND n.opening_at IS NOT NULL
             AND n.opening_at < now() THEN 'closed'
        WHEN n.bid_deadline_at IS NULL THEN 'unknown'
        WHEN n.bid_begin_at IS NOT NULL AND n.bid_begin_at > now() THEN 'scheduled'
        WHEN n.bid_deadline_at >= now() THEN 'open'
        ELSE 'closed'
    END AS bid_status,
    n.notice_organization_code,
    n.notice_organization_name,
    n.demand_organization_code,
    n.demand_organization_name,
    n.bid_method_name,
    n.contract_method_name,
    n.estimated_price,
    n.allocated_budget,
    n.detail_url,
    n.notice_url,
    n.source_changed_at,
    rs.expression::text AS requirement_expression,
    le.completeness AS extraction_completeness,
    le.requires_review,
    CASE
        WHEN latest.notice_order IS DISTINCT FROM n.notice_order THEN 'superseded'
        WHEN n.notice_kind_name = '취소공고' THEN 'cancelled'
        ELSE 'active'
    END AS notice_status
FROM public_procurement.bid_notices n
JOIN public_procurement.bid_notice_latest_versions latest
  ON latest.notice_number = n.notice_number
LEFT JOIN latest_extraction le
  ON le.notice_number = n.notice_number AND le.notice_order = n.notice_order
LEFT JOIN public_procurement.bid_eligibility_requirement_sets rs
  ON rs.extraction_id = le.extraction_id;

CREATE VIEW public_procurement.runtime_bid_notices AS
SELECT
    base.*,
    CASE
      WHEN EXISTS (
        SELECT 1 FROM public_procurement.bid_notice_participation_regions region
        WHERE region.notice_number=base.notice_number
          AND region.notice_order=base.notice_order
          AND COALESCE(region.participation_region_code,'') NOT IN ('','00')
      ) THEN 'applicable'
      WHEN region_status.status='completed' THEN 'not_applicable'
      ELSE 'unknown'
    END AS region_requirement_status,
    CASE
      WHEN EXISTS (
        SELECT 1 FROM public_procurement.bid_notice_license_restrictions license
        WHERE license.notice_number=base.notice_number
          AND license.notice_order=base.notice_order
      ) THEN 'applicable'
      WHEN industry_status.status='completed' THEN 'not_applicable'
      ELSE 'unknown'
    END AS industry_license_requirement_status,
    CASE
      WHEN region_status.status='completed'
       AND industry_status.status='completed'
       AND COALESCE(base.extraction_completeness,'')='complete' THEN 'complete'
      WHEN region_status.status='completed'
        OR industry_status.status='completed'
        OR base.extraction_completeness IS NOT NULL THEN 'partial'
      ELSE 'unknown'
    END AS requirement_extraction_status,
    jsonb_build_object(
      'region', jsonb_build_object(
        'applicability', CASE
          WHEN EXISTS (
            SELECT 1 FROM public_procurement.bid_notice_participation_regions region
            WHERE region.notice_number=base.notice_number
              AND region.notice_order=base.notice_order
              AND COALESCE(region.participation_region_code,'') NOT IN ('','00')
          ) THEN 'applicable'
          WHEN region_status.status='completed' THEN 'not_applicable'
          ELSE 'unknown'
        END,
        'completeness', CASE WHEN region_status.status='completed' THEN 'complete' ELSE 'partial' END
      ),
      'industry_license', jsonb_build_object(
        'applicability', CASE
          WHEN EXISTS (
            SELECT 1 FROM public_procurement.bid_notice_license_restrictions license
            WHERE license.notice_number=base.notice_number
              AND license.notice_order=base.notice_order
          ) THEN 'applicable'
          WHEN industry_status.status='completed' THEN 'not_applicable'
          ELSE 'unknown'
        END,
        'completeness', CASE WHEN industry_status.status='completed' THEN 'complete' ELSE 'partial' END
      )
    )::text AS requirement_categories
FROM public_procurement.runtime_bid_notices_base base
LEFT JOIN ingestion.bid_notice_requirement_collection_status region_status
  ON region_status.notice_number=base.notice_number
 AND region_status.notice_order=base.notice_order
 AND region_status.category='region'
LEFT JOIN ingestion.bid_notice_requirement_collection_status industry_status
  ON industry_status.notice_number=base.notice_number
 AND industry_status.notice_order=base.notice_order
 AND industry_status.category='industry_license';

CREATE INDEX IF NOT EXISTS bid_notices_procurement_hierarchy_idx
    ON public_procurement.bid_notices (
        procurement_large_classification_name,
        procurement_middle_classification_name,
        work_type,
        notice_published_at DESC
    )
    WHERE procurement_large_classification_name IS NOT NULL;

GRANT SELECT ON public_procurement.runtime_bid_notices_base TO teoria_runtime;
GRANT SELECT ON public_procurement.runtime_bid_notices TO teoria_runtime;
