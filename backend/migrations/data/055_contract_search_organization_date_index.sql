CREATE INDEX IF NOT EXISTS contracts_organization_concluded_search_idx
    ON public_procurement.contracts (
        contracting_organization_code,
        concluded_date DESC NULLS LAST,
        unified_contract_number DESC
    )
    WHERE contracting_organization_code IS NOT NULL;
