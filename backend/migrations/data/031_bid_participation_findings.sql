CREATE TABLE public_procurement.bid_participation_findings (
    finding_id uuid PRIMARY KEY,
    extraction_id uuid NOT NULL,
    local_id text NOT NULL,
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    category text NOT NULL CHECK (category IN (
        'participation_note', 'performance_obligation', 'competition_risk_signal'
    )),
    finding_type text NOT NULL,
    title text NOT NULL,
    subject text NOT NULL,
    stage text NOT NULL,
    description text NOT NULL,
    deadline_text text,
    failure_effect text NOT NULL,
    importance text NOT NULL CHECK (importance IN ('high', 'medium', 'low')),
    competitive_effect text,
    legitimate_justification text,
    review_status text NOT NULL CHECK (review_status IN ('extracted', 'needs_review')),
    confidence numeric NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (extraction_id, local_id),
    FOREIGN KEY (extraction_id)
        REFERENCES public_procurement.bid_eligibility_extractions(extraction_id) ON DELETE CASCADE
);

CREATE TABLE public_procurement.bid_participation_finding_evidence (
    evidence_id uuid PRIMARY KEY,
    finding_id uuid NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('document', 'structured_api')),
    source_id text NOT NULL,
    document_id uuid,
    block_id text,
    page_number integer,
    section text,
    excerpt text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (finding_id)
        REFERENCES public_procurement.bid_participation_findings(finding_id) ON DELETE CASCADE,
    FOREIGN KEY (document_id)
        REFERENCES public_procurement.bid_notice_documents(document_id) ON DELETE SET NULL
);

CREATE INDEX bid_participation_findings_notice_idx
    ON public_procurement.bid_participation_findings (notice_number, notice_order, category);

CREATE VIEW public_procurement.runtime_bid_participation_findings AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number, notice_order, extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
)
SELECT
    f.finding_id::text AS finding_id,
    f.notice_number || ':' || f.notice_order AS bid_notice_id,
    f.notice_number,
    f.notice_order,
    f.category,
    f.finding_type,
    f.title,
    f.subject,
    f.stage,
    f.description,
    f.deadline_text,
    f.failure_effect,
    f.importance,
    f.competitive_effect,
    f.legitimate_justification,
    f.review_status,
    f.confidence
FROM latest_extraction le
JOIN public_procurement.bid_participation_findings f
    ON f.extraction_id = le.extraction_id;

CREATE VIEW public_procurement.runtime_bid_participation_finding_evidence AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number, notice_order, extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
)
SELECT
    e.evidence_id::text AS evidence_id,
    e.finding_id::text AS finding_id,
    f.notice_number,
    f.notice_order,
    e.source_type,
    e.source_id,
    e.document_id::text AS document_id,
    d.file_name AS source_document,
    e.page_number AS source_page,
    e.section AS source_clause,
    e.excerpt AS source_excerpt,
    d.source_url
FROM latest_extraction le
JOIN public_procurement.bid_participation_findings f
    ON f.extraction_id = le.extraction_id
JOIN public_procurement.bid_participation_finding_evidence e
    ON e.finding_id = f.finding_id
LEFT JOIN public_procurement.bid_notice_documents d
    ON d.document_id = e.document_id;

GRANT SELECT ON public_procurement.runtime_bid_participation_findings TO teoria_runtime;
GRANT SELECT ON public_procurement.runtime_bid_participation_finding_evidence TO teoria_runtime;
