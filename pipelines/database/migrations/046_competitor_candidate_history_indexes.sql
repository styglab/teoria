CREATE INDEX contracts_concluded_date_idx
    ON public_procurement.contracts (concluded_date);

CREATE INDEX contract_demand_organizations_organization_contract_idx
    ON public_procurement.contract_demand_organizations (
        organization_code, unified_contract_number
    );

COMMENT ON INDEX public_procurement.contracts_concluded_date_idx IS
    'Bounds contract history by the candidate analysis coverage period.';

COMMENT ON INDEX public_procurement.contract_demand_organizations_organization_contract_idx IS
    'Resolves demand-organization contract history for competitor candidate analysis.';
