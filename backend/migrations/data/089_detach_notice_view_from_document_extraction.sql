-- Stop consulting archived extraction tables. NULL compatibility columns preserve
-- existing dependent views; they are absent from the active Runtime contract.
CREATE OR REPLACE VIEW public_procurement.runtime_bid_notices_base AS
WITH lineage_summary AS (
    SELECT root_number,lineage_count,latest_bid_notice_id,lineage_notices
    FROM public_procurement.bid_notice_lineage_summaries
), latest_versions AS NOT MATERIALIZED (
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
    n.source_changed_at,NULL::text AS requirement_expression,
    NULL::text AS extraction_completeness,NULL::boolean AS requires_review,
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

