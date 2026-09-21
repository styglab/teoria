CREATE TABLE ingestion.pipeline_operation_progress (
    pipeline_id text NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    operation_id text NOT NULL,
    execution_id uuid NOT NULL,
    raw_record_count integer NOT NULL DEFAULT 0,
    contract_count integer NOT NULL DEFAULT 0,
    supplier_count integer NOT NULL DEFAULT 0,
    organization_count integer NOT NULL DEFAULT 0,
    demand_organization_count integer NOT NULL DEFAULT 0,
    completed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pipeline_id, window_start, window_end, operation_id)
);

UPDATE public_procurement.contracts
SET contract_date = NULL,
    updated_at = now()
WHERE contract_date < DATE '1900-01-01'
   OR contract_date > current_date + 366;

UPDATE public_procurement.contracts
SET concluded_date = NULL,
    updated_at = now()
WHERE concluded_date < DATE '1900-01-01'
   OR concluded_date > current_date + 366;

UPDATE public_procurement.bid_awards
SET opening_at = NULL,
    updated_at = now()
WHERE opening_at < TIMESTAMPTZ '1900-01-01 00:00:00+00'
   OR opening_at > now() + interval '366 days';

UPDATE public_procurement.bid_awards
SET final_award_date = NULL,
    updated_at = now()
WHERE final_award_date < DATE '1900-01-01'
   OR final_award_date > current_date + 366;

UPDATE ingestion.pipeline_runs
SET status = 'failed',
    finished_at = now(),
    error_code = 'StalePipelineRun'
WHERE status = 'running'
  AND started_at < now() - interval '6 hours';
