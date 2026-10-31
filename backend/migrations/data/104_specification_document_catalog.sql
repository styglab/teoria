-- Document input metadata only. Bodies and normalized observations stay in object storage.
CREATE TABLE public_procurement.specification_processing_inputs (
    run_id text NOT NULL REFERENCES public_procurement.specification_processing_runs(run_id),
    document_id text NOT NULL,
    filename text,
    source_uri text,
    source_sha256 text CHECK (source_sha256 IS NULL OR source_sha256 ~ '^[a-f0-9]{64}$'),
    notice_number text,
    PRIMARY KEY (run_id, document_id)
);
INSERT INTO public_procurement.specification_processing_inputs
(run_id, document_id, source_sha256, notice_number)
SELECT run_id, document_id, source_sha256, notice_number
FROM public_procurement.specification_processing_documents;
CREATE INDEX specification_inputs_source ON public_procurement.specification_processing_inputs
(source_sha256, notice_number, run_id);
CREATE INDEX specification_runs_classification_date ON public_procurement.specification_processing_runs
(classification_code, started_at DESC, run_id);
GRANT SELECT, INSERT, UPDATE ON public_procurement.specification_processing_inputs TO teoria_pipeline;
GRANT SELECT ON public_procurement.specification_processing_inputs TO teoria_runtime;
