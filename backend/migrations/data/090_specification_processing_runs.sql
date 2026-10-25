-- Only execution metadata and artifact references belong in the Data DB.
-- Extracted text and standard proposals live in object storage, not these tables.
CREATE TABLE public_procurement.specification_processing_runs (
    run_id text PRIMARY KEY CHECK (run_id ~ '^[a-z][a-z0-9_]{0,79}$'),
    input_fingerprint text NOT NULL CHECK (input_fingerprint ~ '^[a-f0-9]{64}$'),
    mode text NOT NULL CHECK (mode IN ('standard_management','document_processing')),
    classification_code text NOT NULL,
    artifact_root text NOT NULL,
    status text NOT NULL CHECK (status IN ('running','completed','partial','failed')),
    standard_uri text,
    standard_sha256 text,
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE public_procurement.specification_processing_artifacts (
    run_id text NOT NULL REFERENCES public_procurement.specification_processing_runs(run_id),
    object_key text NOT NULL,
    uri text NOT NULL,
    sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_type text NOT NULL,
    PRIMARY KEY (run_id,object_key)
);
CREATE TABLE public_procurement.specification_processing_documents (
    run_id text NOT NULL REFERENCES public_procurement.specification_processing_runs(run_id),
    document_id text NOT NULL,
    notice_number text,
    status text NOT NULL CHECK (status IN ('extracted','partial','failed')),
    source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
    result_summary jsonb NOT NULL,
    PRIMARY KEY (run_id,document_id)
);
GRANT SELECT,INSERT,UPDATE ON public_procurement.specification_processing_runs,
    public_procurement.specification_processing_artifacts,
    public_procurement.specification_processing_documents TO teoria_pipeline;
GRANT SELECT ON public_procurement.specification_processing_runs,
    public_procurement.specification_processing_artifacts,
    public_procurement.specification_processing_documents TO teoria_runtime;
