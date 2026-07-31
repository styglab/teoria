CREATE SCHEMA IF NOT EXISTS ingestion;
CREATE SCHEMA IF NOT EXISTS public_procurement;

CREATE TABLE IF NOT EXISTS ingestion.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ingestion.pipeline_runs (
    execution_id uuid PRIMARY KEY,
    pipeline_id text NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    started_at timestamptz NOT NULL,
    finished_at timestamptz,
    status text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    raw_record_count integer NOT NULL DEFAULT 0,
    contract_count integer NOT NULL DEFAULT 0,
    error_code text
);

CREATE TABLE IF NOT EXISTS ingestion.raw_provider_records (
    raw_record_id uuid PRIMARY KEY,
    execution_id uuid NOT NULL REFERENCES ingestion.pipeline_runs(execution_id),
    connector_id text NOT NULL,
    operation_id text NOT NULL,
    window_start date NOT NULL,
    window_end date NOT NULL,
    fetched_at timestamptz NOT NULL,
    source_record_hash text NOT NULL,
    payload jsonb NOT NULL,
    UNIQUE (connector_id, operation_id, source_record_hash)
);

CREATE TABLE IF NOT EXISTS ingestion.pipeline_checkpoints (
    pipeline_id text PRIMARY KEY,
    cursor_date date NOT NULL,
    execution_id uuid NOT NULL REFERENCES ingestion.pipeline_runs(execution_id),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public_procurement.contracts (
    unified_contract_number text PRIMARY KEY,
    contract_type text NOT NULL,
    confirmed_contract_number text,
    contract_reference_number text,
    contract_name text,
    is_joint_contract boolean,
    long_term_continuation_type text,
    concluded_date date,
    contract_date date,
    contract_period_text text,
    basis_law_name text,
    total_amount numeric,
    total_amount_currency text,
    current_contract_amount numeric,
    current_contract_amount_currency text,
    guarantee_deposit_rate numeric,
    payment_method_name text,
    request_number text,
    notice_number text,
    contract_method_name text,
    contracting_organization_code text,
    contracting_department_name text,
    procurement_classification_number text,
    procurement_classification_name text,
    contract_information_url text,
    contract_detail_url text,
    source_registered_at timestamptz,
    source_changed_at timestamptz,
    source_record_hash text NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public_procurement.public_organizations (
    organization_code text PRIMARY KEY,
    organization_name text,
    jurisdiction_type text,
    ingested_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public_procurement.contract_suppliers (
    unified_contract_number text NOT NULL REFERENCES public_procurement.contracts(unified_contract_number) ON DELETE CASCADE,
    supplier_sequence integer NOT NULL,
    supplier_role_name text,
    joint_contract_method_name text,
    business_registration_number text,
    supplier_name text,
    representative_name text,
    nationality_name text,
    participation_share_rate numeric,
    creditor_name text,
    supplier_manager_name text,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (unified_contract_number, supplier_sequence)
);

CREATE TABLE IF NOT EXISTS public_procurement.contract_demand_organizations (
    unified_contract_number text NOT NULL REFERENCES public_procurement.contracts(unified_contract_number) ON DELETE CASCADE,
    demand_organization_sequence integer NOT NULL,
    organization_code text,
    department_name text,
    manager_name text,
    telephone_number text,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (unified_contract_number, demand_organization_sequence)
);

CREATE INDEX IF NOT EXISTS raw_provider_records_execution_idx
    ON ingestion.raw_provider_records (execution_id);
CREATE INDEX IF NOT EXISTS contracts_contract_date_idx
    ON public_procurement.contracts (contract_date);
CREATE INDEX IF NOT EXISTS contract_suppliers_business_number_idx
    ON public_procurement.contract_suppliers (business_registration_number);
