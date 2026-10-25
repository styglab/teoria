ALTER TABLE public_procurement.bid_eligibility_requirements
    ADD CONSTRAINT bid_eligibility_requirements_type_check
        CHECK (requirement_type IN ('business_status', 'procurement_registration',
              'industry_license', 'participation_region', 'company_scale', 'certificate',
              'product_registration', 'sanction', 'past_performance', 'credit_rating',
              'technical_personnel', 'consortium', 'legal_qualification',
              'facility_requirement', 'equipment_ownership', 'manufacturer_status', 'custom')),
    ADD CONSTRAINT bid_eligibility_requirements_operator_check
        CHECK (operator IN ('equals', 'not_equals', 'contains', 'in', 'not_in',
              'greater_than_or_equal', 'less_than_or_equal', 'exists', 'not_exists',
              'valid_on', 'custom')),
    ADD CONSTRAINT bid_eligibility_requirements_reference_date_check
        CHECK (reference_date_type IN ('bid_deadline', 'qualification_registration_deadline',
              'notice_date', 'contract_date', 'explicit_date', 'none')),
    ADD COLUMN assessment_stage text NOT NULL DEFAULT 'bid_entry'
        CHECK (assessment_stage IN ('bid_entry', 'qualification_review', 'contracting')),
    ADD COLUMN failure_effect text NOT NULL DEFAULT 'cannot_bid'
        CHECK (failure_effect IN ('cannot_bid', 'invalid_bid', 'qualification_rejection',
                                  'cannot_contract', 'needs_review')),
    ADD COLUMN comparison_mode text NOT NULL DEFAULT 'manual'
        CHECK (comparison_mode IN ('structured', 'document_evidence', 'manual'));

CREATE TABLE public_procurement.bid_eligibility_requirement_proofs (
    proof_id uuid PRIMARY KEY,
    requirement_id uuid NOT NULL,
    local_id text NOT NULL,
    document_type text NOT NULL,
    submission_stage text NOT NULL
        CHECK (submission_stage IN ('bid_entry', 'qualification_review', 'contracting')),
    deadline_text text,
    mandatory boolean NOT NULL,
    review_status text NOT NULL CHECK (review_status IN ('extracted', 'needs_review')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (requirement_id, local_id),
    FOREIGN KEY (requirement_id)
        REFERENCES public_procurement.bid_eligibility_requirements(requirement_id) ON DELETE CASCADE
);

CREATE TABLE public_procurement.bid_eligibility_requirement_proof_evidence (
    evidence_id uuid PRIMARY KEY,
    proof_id uuid NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('document', 'structured_api')),
    source_id text NOT NULL,
    document_id uuid,
    block_id text,
    page_number integer,
    section text,
    excerpt text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (proof_id)
        REFERENCES public_procurement.bid_eligibility_requirement_proofs(proof_id) ON DELETE CASCADE,
    FOREIGN KEY (document_id)
        REFERENCES public_procurement.bid_notice_documents(document_id) ON DELETE SET NULL
);

CREATE INDEX bid_eligibility_requirement_proofs_requirement_idx
    ON public_procurement.bid_eligibility_requirement_proofs (requirement_id);

CREATE OR REPLACE VIEW public_procurement.runtime_bid_requirements AS
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
        DISTINCT concat_ws(' | ', e.source_type, e.source_id, d.file_name,
                  CASE WHEN e.page_number IS NOT NULL THEN 'page ' || e.page_number END,
                  e.section, e.excerpt),
        E'\n'
    ) AS evidence_summary,
    r.assessment_stage,
    r.failure_effect,
    r.comparison_mode,
    string_agg(
        DISTINCT concat_ws(' | ', p.document_type, p.submission_stage, p.deadline_text,
                           pe.excerpt),
        E'\n'
    ) AS proof_summary
FROM latest_extraction le
JOIN public_procurement.bid_eligibility_requirements r
    ON r.extraction_id = le.extraction_id
JOIN public_procurement.bid_notices n
    ON n.notice_number = r.notice_number AND n.notice_order = r.notice_order
LEFT JOIN public_procurement.bid_eligibility_requirement_evidence e
    ON e.requirement_id = r.requirement_id
LEFT JOIN public_procurement.bid_notice_documents d
    ON d.document_id = e.document_id
LEFT JOIN public_procurement.bid_eligibility_requirement_proofs p
    ON p.requirement_id = r.requirement_id
LEFT JOIN public_procurement.bid_eligibility_requirement_proof_evidence pe
    ON pe.proof_id = p.proof_id
GROUP BY r.requirement_id, r.notice_number, r.notice_order, n.notice_name,
         n.bid_deadline_at, r.local_id, r.requirement_type, r.operator,
         r.value, r.original_text, r.holder_scope, r.reference_date_type,
         r.mandatory, r.review_status, r.confidence, r.assessment_stage,
         r.failure_effect, r.comparison_mode;

GRANT SELECT ON public_procurement.bid_eligibility_requirement_proofs TO teoria_runtime;
GRANT SELECT ON public_procurement.bid_eligibility_requirement_proof_evidence TO teoria_runtime;
