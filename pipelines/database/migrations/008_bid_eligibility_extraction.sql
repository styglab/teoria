ALTER TABLE public_procurement.bid_notice_documents
    ADD COLUMN parse_status text NOT NULL DEFAULT 'pending'
        CHECK (parse_status IN ('pending', 'processing', 'parsed', 'unsupported', 'failed')),
    ADD COLUMN parse_attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN parse_next_retry_at timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN parse_error_code text,
    ADD COLUMN parser_name text,
    ADD COLUMN parser_version text,
    ADD COLUMN parsed_object_key text,
    ADD COLUMN parsed_at timestamptz;

CREATE INDEX bid_notice_documents_parse_queue_idx
    ON public_procurement.bid_notice_documents
    (parse_status, parse_next_retry_at, downloaded_at)
    WHERE status = 'stored';

CREATE TABLE public_procurement.bid_eligibility_extractions (
    extraction_id uuid PRIMARY KEY,
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    input_fingerprint text NOT NULL,
    schema_version text NOT NULL,
    skill_version text NOT NULL,
    model_name text,
    status text NOT NULL CHECK (status IN ('processing', 'completed', 'failed')),
    raw_output_object_key text,
    error_code text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (notice_number, notice_order, input_fingerprint),
    FOREIGN KEY (notice_number, notice_order)
        REFERENCES public_procurement.bid_notices(notice_number, notice_order) ON DELETE CASCADE
);

CREATE TABLE public_procurement.bid_eligibility_requirement_sets (
    extraction_id uuid PRIMARY KEY,
    expression jsonb NOT NULL,
    unresolved_candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (extraction_id)
        REFERENCES public_procurement.bid_eligibility_extractions(extraction_id) ON DELETE CASCADE
);

CREATE TABLE public_procurement.bid_eligibility_requirements (
    requirement_id uuid PRIMARY KEY,
    extraction_id uuid NOT NULL,
    local_id text NOT NULL,
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    requirement_type text NOT NULL,
    operator text NOT NULL,
    value jsonb,
    original_text text NOT NULL,
    holder_scope text NOT NULL,
    reference_date_type text NOT NULL,
    mandatory boolean NOT NULL,
    review_status text NOT NULL CHECK (review_status IN ('extracted', 'needs_review')),
    confidence numeric NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (extraction_id, local_id),
    FOREIGN KEY (extraction_id)
        REFERENCES public_procurement.bid_eligibility_extractions(extraction_id) ON DELETE CASCADE
);

CREATE TABLE public_procurement.bid_eligibility_requirement_evidence (
    evidence_id uuid PRIMARY KEY,
    requirement_id uuid NOT NULL,
    source_type text NOT NULL CHECK (source_type IN ('document', 'structured_api')),
    source_id text NOT NULL,
    document_id uuid,
    block_id text,
    page_number integer,
    section text,
    excerpt text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (requirement_id)
        REFERENCES public_procurement.bid_eligibility_requirements(requirement_id) ON DELETE CASCADE,
    FOREIGN KEY (document_id)
        REFERENCES public_procurement.bid_notice_documents(document_id) ON DELETE SET NULL
);

CREATE INDEX bid_eligibility_requirements_notice_idx
    ON public_procurement.bid_eligibility_requirements (notice_number, notice_order);
