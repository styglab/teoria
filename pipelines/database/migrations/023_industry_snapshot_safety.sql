ALTER TABLE public_procurement.procurement_industries
    ADD COLUMN missing_snapshot_count integer NOT NULL DEFAULT 0;
