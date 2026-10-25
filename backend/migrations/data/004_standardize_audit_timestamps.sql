ALTER TABLE ingestion.pipeline_checkpoints
    ADD COLUMN created_at timestamptz;

UPDATE ingestion.pipeline_checkpoints
SET created_at = updated_at;

ALTER TABLE ingestion.pipeline_checkpoints
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL;

ALTER TABLE public_procurement.contracts
    RENAME COLUMN ingested_at TO created_at;
ALTER TABLE public_procurement.contracts
    ADD COLUMN updated_at timestamptz;
UPDATE public_procurement.contracts SET updated_at = created_at;
ALTER TABLE public_procurement.contracts
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE public_procurement.public_organizations
    RENAME COLUMN ingested_at TO created_at;
ALTER TABLE public_procurement.public_organizations
    ADD COLUMN updated_at timestamptz;
UPDATE public_procurement.public_organizations SET updated_at = created_at;
ALTER TABLE public_procurement.public_organizations
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE public_procurement.contract_suppliers
    RENAME COLUMN ingested_at TO created_at;
ALTER TABLE public_procurement.contract_suppliers
    ADD COLUMN updated_at timestamptz;
UPDATE public_procurement.contract_suppliers SET updated_at = created_at;
ALTER TABLE public_procurement.contract_suppliers
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

ALTER TABLE public_procurement.contract_demand_organizations
    RENAME COLUMN ingested_at TO created_at;
ALTER TABLE public_procurement.contract_demand_organizations
    ADD COLUMN updated_at timestamptz;
UPDATE public_procurement.contract_demand_organizations SET updated_at = created_at;
ALTER TABLE public_procurement.contract_demand_organizations
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;
