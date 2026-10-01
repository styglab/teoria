CREATE INDEX IF NOT EXISTS bid_notices_classification_published_lookup_idx
    ON public_procurement.bid_notices (
        procurement_classification_number,
        notice_published_at DESC
    )
    WHERE procurement_classification_number IS NOT NULL;
