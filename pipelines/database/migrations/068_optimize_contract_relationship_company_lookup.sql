CREATE INDEX contract_event_company_ledger_company_date_idx
    ON public_procurement.contract_event_company_ledger (
        company_number, first_contract_date, organization_code
    );
