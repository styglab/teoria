ALTER TABLE public_procurement.bid_notices
    ADD COLUMN previous_notice_number text,
    ADD COLUMN lineage_root_notice_number text;

UPDATE public_procurement.bid_notices
SET previous_notice_number = NULLIF(source_payload->>'befBidBbancNo', ''),
    lineage_root_notice_number = NULLIF(source_payload->>'befBidBbancNo', '')
WHERE is_re_notice IS TRUE
   OR notice_kind_name IN ('재공고', '변경공고', '취소공고');

CREATE INDEX bid_notices_previous_notice_number_idx
    ON public_procurement.bid_notices (previous_notice_number)
    WHERE previous_notice_number IS NOT NULL;
CREATE INDEX bid_notices_lineage_root_idx
    ON public_procurement.bid_notices (lineage_root_notice_number, notice_published_at DESC);

CREATE FUNCTION public_procurement.set_bid_notice_lineage_fields()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE resolved_root text;
BEGIN
    NEW.previous_notice_number := NULLIF(NEW.source_payload->>'befBidBbancNo', '');
    IF NEW.previous_notice_number IS NULL THEN
        NEW.lineage_root_notice_number := NEW.notice_number;
    ELSE
        SELECT COALESCE(lineage_root_notice_number, notice_number)
        INTO resolved_root
        FROM public_procurement.bid_notices
        WHERE notice_number = NEW.previous_notice_number
        ORDER BY notice_order DESC LIMIT 1;
        NEW.lineage_root_notice_number := COALESCE(resolved_root, NEW.previous_notice_number);
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER bid_notices_set_lineage_fields
BEFORE INSERT OR UPDATE OF source_payload ON public_procurement.bid_notices
FOR EACH ROW EXECUTE FUNCTION public_procurement.set_bid_notice_lineage_fields();

DROP VIEW public_procurement.runtime_bid_notices;
DROP VIEW public_procurement.runtime_bid_notices_base;

CREATE VIEW public_procurement.runtime_bid_notices_base AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number, notice_order, extraction_id, completeness, requires_review
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), lineage_summary AS (
    SELECT COALESCE(lineage_root_notice_number, notice_number) AS root_number,
           count(*)::integer AS lineage_count,
           (array_agg(notice_number || ':' || notice_order
              ORDER BY notice_published_at DESC NULLS LAST, notice_number DESC))[1]
              AS latest_bid_notice_id,
           jsonb_agg(jsonb_build_object(
              'bid_notice_id', notice_number || ':' || notice_order,
              'notice_kind', CASE
                WHEN notice_kind_name='재공고' OR is_re_notice THEN 're_notice'
                WHEN notice_kind_name='변경공고' THEN 'correction'
                WHEN notice_kind_name='취소공고' THEN 'cancellation'
                WHEN notice_kind_name='등록공고' THEN 'original' ELSE 'unknown' END,
              'notice_published_at', notice_published_at)
              ORDER BY notice_published_at, notice_number, notice_order)::text AS lineage_notices
    FROM public_procurement.bid_notices
    GROUP BY COALESCE(lineage_root_notice_number, notice_number)
), latest_versions AS (
    SELECT notice_number, notice_order FROM public_procurement.bid_notice_latest_versions
)
SELECT
    n.notice_number || ':' || n.notice_order AS bid_notice_id,
    n.notice_number, n.notice_order, n.notice_name, n.work_type,
    n.procurement_classification_number AS field_code,
    n.procurement_classification_name AS field_name,
    CASE WHEN n.work_type='construction' THEN n.procurement_classification_name
         ELSE n.procurement_large_classification_name END AS large_category,
    CASE WHEN n.work_type='construction' THEN NULL
         ELSE n.procurement_middle_classification_name END AS middle_category,
    ARRAY(SELECT DISTINCT code FROM (
        SELECT NULLIF(n.procurement_classification_number,'') AS code
        UNION ALL SELECT NULLIF(item->>'code','')
        FROM jsonb_array_elements(COALESCE(n.purchase_items,'[]'::jsonb)) item
    ) codes WHERE code IS NOT NULL) AS field_codes,
    n.notice_kind_name, n.is_re_notice, n.notice_published_at, n.bid_begin_at,
    n.bid_deadline_at, n.opening_at,
    CASE WHEN n.bid_deadline_at IS NULL AND n.opening_at IS NOT NULL AND n.opening_at<now() THEN 'closed'
         WHEN n.bid_deadline_at IS NULL THEN 'unknown'
         WHEN n.bid_begin_at IS NOT NULL AND n.bid_begin_at>now() THEN 'scheduled'
         WHEN n.bid_deadline_at>=now() THEN 'open' ELSE 'closed' END AS bid_status,
    n.notice_organization_code,n.notice_organization_name,
    n.demand_organization_code,n.demand_organization_name,n.bid_method_name,
    n.contract_method_name,n.estimated_price,n.allocated_budget,n.detail_url,n.notice_url,
    n.source_changed_at,rs.expression::text AS requirement_expression,
    le.completeness AS extraction_completeness,le.requires_review,
    CASE WHEN latest.notice_order IS DISTINCT FROM n.notice_order THEN 'superseded'
         WHEN n.notice_kind_name='취소공고' THEN 'cancelled' ELSE 'active' END AS notice_status,
    CASE WHEN n.notice_kind_name='재공고' OR n.is_re_notice THEN 're_notice'
         WHEN n.notice_kind_name='변경공고' THEN 'correction'
         WHEN n.notice_kind_name='취소공고' THEN 'cancellation'
         WHEN n.notice_kind_name='등록공고' THEN 'original' ELSE 'unknown' END AS notice_kind,
    COALESCE(n.lineage_root_notice_number,n.notice_number) || ':' || COALESCE(root_latest.notice_order,'000')
      AS notice_lineage_id,
    COALESCE(n.lineage_root_notice_number,n.notice_number) || ':' || COALESCE(root_latest.notice_order,'000')
      AS root_bid_notice_id,
    CASE WHEN n.previous_notice_number IS NULL THEN NULL
         ELSE n.previous_notice_number || ':' || COALESCE(previous_latest.notice_order,'000') END
      AS previous_bid_notice_id,
    successor.bid_notice_id AS superseded_by_bid_notice_id,
    (n.notice_number||':'||n.notice_order)=summary.latest_bid_notice_id AS is_latest_in_lineage,
    CASE WHEN (n.notice_number||':'||n.notice_order)<>summary.latest_bid_notice_id THEN 'superseded'
         WHEN n.notice_kind_name='취소공고' THEN 'cancelled' ELSE 'active' END AS lineage_status,
    CASE WHEN n.previous_notice_number IS NOT NULL OR summary.lineage_count>1
         THEN 'source_confirmed' ELSE 'unknown' END AS lineage_confidence,
    summary.lineage_count,summary.lineage_notices,
    CASE WHEN (n.notice_number||':'||n.notice_order)=summary.latest_bid_notice_id
         THEN ARRAY['all','latest_only','grouped']::text[] ELSE ARRAY['all']::text[] END
      AS lineage_modes
FROM public_procurement.bid_notices n
JOIN latest_versions latest ON latest.notice_number=n.notice_number
LEFT JOIN latest_extraction le
  ON le.notice_number=n.notice_number AND le.notice_order=n.notice_order
LEFT JOIN public_procurement.bid_eligibility_requirement_sets rs ON rs.extraction_id=le.extraction_id
JOIN lineage_summary summary
  ON summary.root_number=COALESCE(n.lineage_root_notice_number,n.notice_number)
LEFT JOIN latest_versions root_latest
  ON root_latest.notice_number=COALESCE(n.lineage_root_notice_number,n.notice_number)
LEFT JOIN latest_versions previous_latest ON previous_latest.notice_number=n.previous_notice_number
LEFT JOIN LATERAL (
    SELECT child.notice_number||':'||child.notice_order AS bid_notice_id
    FROM public_procurement.bid_notices child
    WHERE child.previous_notice_number=n.notice_number
    ORDER BY child.notice_published_at,child.notice_number,child.notice_order LIMIT 1
) successor ON true;

CREATE VIEW public_procurement.runtime_bid_notices AS
SELECT base.*,
  CASE WHEN EXISTS (SELECT 1 FROM public_procurement.bid_notice_participation_regions r
      WHERE r.notice_number=base.notice_number AND r.notice_order=base.notice_order
      AND COALESCE(r.participation_region_code,'') NOT IN ('','00')) THEN 'applicable'
       WHEN region_status.status='completed' THEN 'not_applicable' ELSE 'unknown' END
    AS region_requirement_status,
  CASE WHEN EXISTS (SELECT 1 FROM public_procurement.bid_notice_license_restrictions l
      WHERE l.notice_number=base.notice_number AND l.notice_order=base.notice_order) THEN 'applicable'
       WHEN industry_status.status='completed' THEN 'not_applicable' ELSE 'unknown' END
    AS industry_license_requirement_status,
  CASE WHEN region_status.status='completed' AND industry_status.status='completed'
         AND COALESCE(base.extraction_completeness,'')='complete' THEN 'complete'
       WHEN region_status.status='completed' OR industry_status.status='completed'
         OR base.extraction_completeness IS NOT NULL THEN 'partial' ELSE 'unknown' END
    AS requirement_extraction_status,
  jsonb_build_object(
    'region',jsonb_build_object('applicability',CASE WHEN EXISTS (
      SELECT 1 FROM public_procurement.bid_notice_participation_regions r
      WHERE r.notice_number=base.notice_number AND r.notice_order=base.notice_order
      AND COALESCE(r.participation_region_code,'') NOT IN ('','00')) THEN 'applicable'
      WHEN region_status.status='completed' THEN 'not_applicable' ELSE 'unknown' END,
      'completeness',CASE WHEN region_status.status='completed' THEN 'complete' ELSE 'partial' END),
    'industry_license',jsonb_build_object('applicability',CASE WHEN EXISTS (
      SELECT 1 FROM public_procurement.bid_notice_license_restrictions l
      WHERE l.notice_number=base.notice_number AND l.notice_order=base.notice_order) THEN 'applicable'
      WHEN industry_status.status='completed' THEN 'not_applicable' ELSE 'unknown' END,
      'completeness',CASE WHEN industry_status.status='completed' THEN 'complete' ELSE 'partial' END)
  )::text AS requirement_categories
FROM public_procurement.runtime_bid_notices_base base
LEFT JOIN ingestion.bid_notice_requirement_collection_status region_status
  ON region_status.notice_number=base.notice_number AND region_status.notice_order=base.notice_order
 AND region_status.category='region'
LEFT JOIN ingestion.bid_notice_requirement_collection_status industry_status
  ON industry_status.notice_number=base.notice_number AND industry_status.notice_order=base.notice_order
 AND industry_status.category='industry_license';

GRANT SELECT ON public_procurement.runtime_bid_notices_base TO teoria_runtime;
GRANT SELECT ON public_procurement.runtime_bid_notices TO teoria_runtime;
