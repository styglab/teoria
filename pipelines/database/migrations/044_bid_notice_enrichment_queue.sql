ALTER TABLE public_procurement.bid_notices
    ADD COLUMN enrichment_claimed_at timestamptz;

CREATE INDEX bid_notices_pending_enrichment_queue_idx
    ON public_procurement.bid_notices (notice_published_at DESC, notice_number, notice_order)
    WHERE enrichment_checked_at IS NULL;
