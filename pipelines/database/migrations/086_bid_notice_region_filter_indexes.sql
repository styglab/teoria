CREATE INDEX IF NOT EXISTS bid_notice_participation_regions_region_notice_idx
    ON public_procurement.bid_notice_participation_regions
    (participation_region_code, notice_number, notice_order)
    WHERE COALESCE(participation_region_code, '') NOT IN ('', '00');

CREATE INDEX IF NOT EXISTS contract_event_company_ledger_notice_idx
    ON public_procurement.contract_event_company_ledger
    (normalized_notice_number)
    WHERE normalized_notice_number IS NOT NULL;

ANALYZE public_procurement.bid_notice_participation_regions;
ANALYZE public_procurement.contract_event_company_ledger;
