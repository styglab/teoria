CREATE TABLE public_procurement.specification_standard_workflows (
    workflow_id text PRIMARY KEY,
    input_checksum text NOT NULL,
    status text NOT NULL CHECK (status IN ('running','awaiting_approval','completed','failed')),
    checkpoint jsonb NOT NULL DEFAULT '{}'::jsonb,
    lease_id uuid,
    lease_until timestamptz,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
GRANT SELECT,INSERT,UPDATE ON public_procurement.specification_standard_workflows TO teoria_pipeline;
GRANT SELECT ON public_procurement.specification_standard_workflows TO teoria_runtime;
