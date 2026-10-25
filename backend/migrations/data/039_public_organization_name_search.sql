CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX public_organizations_name_trgm_idx
    ON public_procurement.public_organizations
    USING gin (organization_name gin_trgm_ops);
