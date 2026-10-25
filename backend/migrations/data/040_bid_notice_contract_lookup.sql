CREATE INDEX contracts_notice_number_concluded_idx
    ON public_procurement.contracts (
        notice_number, concluded_date DESC, unified_contract_number DESC
    );
