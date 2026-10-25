CREATE INDEX bid_notices_notice_organization_published_idx
    ON public_procurement.bid_notices (
        notice_organization_code, notice_published_at DESC
    );

CREATE INDEX bid_notices_demand_organization_published_idx
    ON public_procurement.bid_notices (
        demand_organization_code, notice_published_at DESC
    );
