CREATE OR REPLACE VIEW public_procurement.runtime_bid_notices AS
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
),
ranked_notices AS (
    SELECT
        n.*,
        row_number() OVER (
            PARTITION BY n.notice_number
            ORDER BY
                CASE
                    WHEN n.notice_order ~ '^[0-9]+$' THEN n.notice_order::numeric
                END DESC NULLS LAST,
                n.notice_order DESC,
                n.notice_published_at DESC NULLS LAST
        ) AS lifecycle_rank
    FROM public_procurement.bid_notices n
)
SELECT
    n.notice_number || ':' || n.notice_order AS bid_notice_id,
    n.notice_number,
    n.notice_order,
    n.notice_name,
    n.work_type,
    n.notice_kind_name,
    n.is_re_notice,
    n.notice_published_at,
    n.bid_begin_at,
    n.bid_deadline_at,
    n.opening_at,
    CASE
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
        WHEN n.lifecycle_rank > 1 THEN 'superseded'
        WHEN n.notice_kind_name = '취소공고' THEN 'cancelled'
        ELSE 'active'
    END AS notice_status
FROM ranked_notices n
LEFT JOIN latest_extraction le
    ON le.notice_number = n.notice_number AND le.notice_order = n.notice_order
LEFT JOIN public_procurement.bid_eligibility_requirement_sets rs
    ON rs.extraction_id = le.extraction_id;

GRANT SELECT ON public_procurement.runtime_bid_notices TO teoria_runtime;
