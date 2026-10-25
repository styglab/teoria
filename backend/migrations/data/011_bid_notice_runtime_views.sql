CREATE VIEW public_procurement.runtime_bid_notices AS
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
    le.requires_review
FROM public_procurement.bid_notices n
LEFT JOIN latest_extraction le
    ON le.notice_number = n.notice_number AND le.notice_order = n.notice_order
LEFT JOIN public_procurement.bid_eligibility_requirement_sets rs
    ON rs.extraction_id = le.extraction_id;

CREATE VIEW public_procurement.runtime_bid_requirements AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number,
        notice_order,
        extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
)
SELECT
    r.requirement_id::text AS requirement_id,
    r.notice_number || ':' || r.notice_order AS bid_notice_id,
    r.notice_number,
    r.notice_order,
    n.notice_name,
    n.bid_deadline_at,
    r.local_id,
    r.requirement_type,
    r.operator,
    r.value::text AS value_text,
    r.original_text,
    r.holder_scope,
    r.reference_date_type,
    r.mandatory,
    r.review_status,
    r.confidence,
    string_agg(
        concat_ws(' | ', e.source_type, e.source_id, d.file_name,
                  CASE WHEN e.page_number IS NOT NULL THEN 'page ' || e.page_number END,
                  e.section, e.excerpt),
        E'\n' ORDER BY e.created_at, e.evidence_id
    ) AS evidence_summary
FROM latest_extraction le
JOIN public_procurement.bid_eligibility_requirements r
    ON r.extraction_id = le.extraction_id
JOIN public_procurement.bid_notices n
    ON n.notice_number = r.notice_number AND n.notice_order = r.notice_order
LEFT JOIN public_procurement.bid_eligibility_requirement_evidence e
    ON e.requirement_id = r.requirement_id
LEFT JOIN public_procurement.bid_notice_documents d
    ON d.document_id = e.document_id
GROUP BY r.requirement_id, r.notice_number, r.notice_order, n.notice_name,
         n.bid_deadline_at, r.local_id, r.requirement_type, r.operator,
         r.value, r.original_text, r.holder_scope, r.reference_date_type,
         r.mandatory, r.review_status, r.confidence;

GRANT SELECT ON public_procurement.runtime_bid_notices TO teoria_runtime;
GRANT SELECT ON public_procurement.runtime_bid_requirements TO teoria_runtime;
