ALTER TABLE public_procurement.bid_eligibility_extractions
    ADD COLUMN completeness text NOT NULL DEFAULT 'complete'
        CHECK (completeness IN ('complete', 'partial', 'api_only')),
    ADD COLUMN requires_review boolean NOT NULL DEFAULT false,
    ADD COLUMN total_document_count integer NOT NULL DEFAULT 0,
    ADD COLUMN parsed_document_count integer NOT NULL DEFAULT 0,
    ADD COLUMN unavailable_document_count integer NOT NULL DEFAULT 0,
    ADD COLUMN unavailable_documents jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN structured_requirement_count integer NOT NULL DEFAULT 0;
