ALTER TABLE public_procurement.bid_notices
    ADD COLUMN enrichment_checked_at timestamptz;

CREATE INDEX bid_notices_pending_enrichment_idx
    ON public_procurement.bid_notices (notice_published_at)
    WHERE enrichment_checked_at IS NULL;
