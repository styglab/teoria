ALTER TABLE public_procurement.bid_notice_documents
    ADD COLUMN storage_status text NOT NULL DEFAULT 'active'
        CHECK (storage_status IN ('active', 'purging', 'purged', 'purge_failed')),
    ADD COLUMN purge_attempts integer NOT NULL DEFAULT 0,
    ADD COLUMN purge_error_code text,
    ADD COLUMN purged_at timestamptz,
    ADD COLUMN purge_reason text;

ALTER TABLE public_procurement.bid_eligibility_extractions
    ADD COLUMN raw_output_purged_at timestamptz;

CREATE INDEX bid_notice_documents_retention_idx
    ON public_procurement.bid_notice_documents (storage_status, notice_number, notice_order)
    WHERE object_key IS NOT NULL OR parsed_object_key IS NOT NULL;

CREATE TABLE public_procurement.bid_document_purge_runs (
    purge_run_id uuid PRIMARY KEY,
    retention_days integer NOT NULL,
    target_count integer NOT NULL,
    purged_document_count integer NOT NULL,
    deleted_object_count integer NOT NULL,
    failed_document_count integer NOT NULL,
    started_at timestamptz NOT NULL,
    completed_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT ON public_procurement.bid_document_purge_runs TO teoria_runtime;
