CREATE INDEX bid_notices_admin_search_order_idx
    ON public_procurement.bid_notices (
        notice_published_at DESC NULLS LAST,
        notice_number DESC,
        notice_order DESC
    );

CREATE INDEX bid_eligibility_extractions_latest_completed_idx
    ON public_procurement.bid_eligibility_extractions (
        notice_number,
        notice_order,
        finished_at DESC NULLS LAST,
        started_at DESC
    )
    WHERE status = 'completed';
