ALTER TABLE public_procurement.bid_eligibility_requirements
    ADD COLUMN standard_rule_id text,
    ADD COLUMN standard_rule_version text,
    ADD COLUMN rule_arguments jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD CONSTRAINT bid_eligibility_requirements_rule_binding_check CHECK (
        (standard_rule_id IS NULL AND standard_rule_version IS NULL)
        OR (standard_rule_id IS NOT NULL AND standard_rule_version IS NOT NULL)
    );

COMMENT ON COLUMN public_procurement.bid_eligibility_requirements.standard_rule_id IS
    'Eligibility Rule Registry의 표준 판정 Rule ID';
COMMENT ON COLUMN public_procurement.bid_eligibility_requirements.standard_rule_version IS
    '추출 결과가 바인딩된 표준 Rule 버전';
COMMENT ON COLUMN public_procurement.bid_eligibility_requirements.rule_arguments IS
    '공고별 표준 Rule 인수';

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
    r.notice_number, r.notice_order, n.notice_name, n.bid_deadline_at,
    r.local_id, r.requirement_type, r.operator, r.value::text AS value_text,
    r.original_text, r.holder_scope, r.reference_date_type, r.mandatory,
    r.review_status, r.confidence,
    string_agg(DISTINCT concat_ws(' | ', e.source_type, e.source_id, d.file_name,
        CASE WHEN e.page_number IS NOT NULL THEN 'page ' || e.page_number END,
        e.section, e.excerpt), E'\n') AS evidence_summary,
    r.assessment_stage, r.failure_effect, r.comparison_mode,
    string_agg(DISTINCT concat_ws(' | ', p.document_type, p.submission_stage,
        p.deadline_text, pe.excerpt), E'\n') AS proof_summary,
    r.proposition_text, r.proposition_start, r.proposition_end,
    r.standard_rule_id, r.standard_rule_version,
    r.rule_arguments::text AS rule_arguments_text
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
    n.bid_deadline_at, r.local_id, r.requirement_type, r.operator, r.value,
    r.original_text, r.holder_scope, r.reference_date_type, r.mandatory,
    r.review_status, r.confidence, r.assessment_stage, r.failure_effect,
    r.comparison_mode, r.proposition_text, r.proposition_start, r.proposition_end,
    r.standard_rule_id, r.standard_rule_version, r.rule_arguments;
