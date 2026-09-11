-- Bid-notice timestamps from PPS are local Asia/Seoul values. Before this
-- migration they were passed to PostgreSQL without timezone information and
-- interpreted as UTC, making the stored instant nine hours later than intended.
UPDATE public_procurement.bid_notices
SET notice_published_at = notice_published_at - interval '9 hours',
    bid_begin_at = bid_begin_at - interval '9 hours',
    bid_deadline_at = bid_deadline_at - interval '9 hours',
    opening_at = opening_at - interval '9 hours',
    source_registered_at = source_registered_at - interval '9 hours',
    source_changed_at = source_changed_at - interval '9 hours',
    updated_at = now();

UPDATE public_procurement.bid_notice_license_restrictions
SET source_registered_at = source_registered_at - interval '9 hours',
    updated_at = now();

UPDATE public_procurement.bid_notice_participation_regions
SET source_registered_at = source_registered_at - interval '9 hours',
    updated_at = now();
