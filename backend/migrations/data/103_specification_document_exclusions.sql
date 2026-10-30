-- A source-only form/notice is excluded by document assessment, not a failed extraction.
ALTER TABLE public_procurement.specification_processing_documents
    DROP CONSTRAINT specification_processing_documents_status_check;
ALTER TABLE public_procurement.specification_processing_documents
    ADD CONSTRAINT specification_processing_documents_status_check
    CHECK (status IN ('extracted', 'partial', 'failed', 'excluded'));
