CREATE VIEW public_procurement.runtime_bid_requirement_evidence AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number, notice_order, extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
)
SELECT
    e.evidence_id::text AS evidence_id,
    e.requirement_id::text AS requirement_id,
    r.notice_number,
    r.notice_order,
    e.source_type,
    e.source_id,
    e.document_id::text AS document_id,
    d.file_name AS source_document,
    e.page_number AS source_page,
    e.section AS source_clause,
    e.excerpt AS source_excerpt,
    d.source_url
FROM latest_extraction le
JOIN public_procurement.bid_eligibility_requirements r
    ON r.extraction_id = le.extraction_id
JOIN public_procurement.bid_eligibility_requirement_evidence e
    ON e.requirement_id = r.requirement_id
LEFT JOIN public_procurement.bid_notice_documents d
    ON d.document_id = e.document_id;

GRANT SELECT ON public_procurement.runtime_bid_requirement_evidence TO teoria_runtime;
