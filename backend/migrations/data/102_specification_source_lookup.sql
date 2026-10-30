-- Reverse lookup for standard-management impact review; no document bodies are copied.
CREATE INDEX specification_documents_source_lookup
ON public_procurement.specification_processing_documents(source_sha256,run_id);

-- A digest and revision reference are enough to recognize previously checked contexts.
CREATE TABLE public_procurement.specification_dictionary_contexts (
    run_id text NOT NULL,
    document_id text NOT NULL,
    source_entry_id text NOT NULL,
    context_sha256 text NOT NULL CHECK (context_sha256 ~ '^[a-f0-9]{64}$'),
    definition_revision_id text NOT NULL,
    PRIMARY KEY(run_id,document_id,source_entry_id,context_sha256),
    FOREIGN KEY(run_id,document_id) REFERENCES public_procurement.specification_processing_documents(run_id,document_id)
);
CREATE INDEX specification_dictionary_context_lookup ON public_procurement.specification_dictionary_contexts
(source_entry_id,context_sha256,definition_revision_id);
GRANT SELECT,INSERT ON public_procurement.specification_dictionary_contexts TO teoria_pipeline;
