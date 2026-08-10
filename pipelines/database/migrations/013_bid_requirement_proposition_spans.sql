ALTER TABLE public_procurement.bid_eligibility_requirements
    ADD COLUMN proposition_text text,
    ADD COLUMN proposition_start integer,
    ADD COLUMN proposition_end integer,
    ADD CONSTRAINT bid_eligibility_requirements_proposition_span_check CHECK (
        (proposition_text IS NULL AND proposition_start IS NULL AND proposition_end IS NULL)
        OR (
            proposition_text IS NOT NULL
            AND proposition_start IS NOT NULL
            AND proposition_end IS NOT NULL
            AND proposition_start >= 0
            AND proposition_end > proposition_start
        )
    );

COMMENT ON COLUMN public_procurement.bid_eligibility_requirements.proposition_text IS
    '원문 인용 안에서 해당 원자 요건만 나타내는 최소 완결 절';
COMMENT ON COLUMN public_procurement.bid_eligibility_requirements.proposition_start IS
    'original_text 기준 proposition_text 시작 문자 offset';
COMMENT ON COLUMN public_procurement.bid_eligibility_requirements.proposition_end IS
    'original_text 기준 proposition_text 끝 문자 offset(exclusive)';

CREATE OR REPLACE VIEW public_procurement.runtime_bid_requirements AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number, notice_order, extraction_id
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
        DISTINCT concat_ws(' | ', e.source_type, e.source_id, d.file_name,
                  CASE WHEN e.page_number IS NOT NULL THEN 'page ' || e.page_number END,
                  e.section, e.excerpt), E'\n'
    ) AS evidence_summary,
    r.assessment_stage,
    r.failure_effect,
    r.comparison_mode,
    string_agg(
        DISTINCT concat_ws(' | ', p.document_type, p.submission_stage, p.deadline_text,
                           pe.excerpt), E'\n'
    ) AS proof_summary,
    r.proposition_text,
    r.proposition_start,
    r.proposition_end
FROM latest_extraction le
JOIN public_procurement.bid_eligibility_requirements r ON r.extraction_id = le.extraction_id
JOIN public_procurement.bid_notices n
    ON n.notice_number = r.notice_number AND n.notice_order = r.notice_order
LEFT JOIN public_procurement.bid_eligibility_requirement_evidence e
    ON e.requirement_id = r.requirement_id
LEFT JOIN public_procurement.bid_notice_documents d ON d.document_id = e.document_id
LEFT JOIN public_procurement.bid_eligibility_requirement_proofs p
    ON p.requirement_id = r.requirement_id
LEFT JOIN public_procurement.bid_eligibility_requirement_proof_evidence pe
    ON pe.proof_id = p.proof_id
GROUP BY r.requirement_id, r.notice_number, r.notice_order, n.notice_name,
         n.bid_deadline_at, r.local_id, r.requirement_type, r.operator,
         r.value, r.original_text, r.holder_scope, r.reference_date_type,
         r.mandatory, r.review_status, r.confidence, r.assessment_stage,
         r.failure_effect, r.comparison_mode, r.proposition_text,
         r.proposition_start, r.proposition_end;
