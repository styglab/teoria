DROP VIEW public_procurement.runtime_bid_notices;

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

GRANT SELECT ON public_procurement.runtime_bid_notices TO teoria_runtime;
