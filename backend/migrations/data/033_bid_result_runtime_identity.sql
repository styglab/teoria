ALTER TABLE public_procurement.bid_awards
    ADD COLUMN award_id text GENERATED ALWAYS AS (
        notice_number || ':' || notice_order || ':' || bid_classification_number || ':' || rebid_number
    ) STORED,
    ADD COLUMN bid_notice_id text GENERATED ALWAYS AS (
        notice_number || ':' || notice_order
    ) STORED;

ALTER TABLE public_procurement.bid_opening_participants
    ADD COLUMN award_id text GENERATED ALWAYS AS (
        notice_number || ':' || notice_order || ':' || bid_classification_number || ':' || rebid_number
    ) STORED,
    ADD COLUMN bid_notice_id text GENERATED ALWAYS AS (
        notice_number || ':' || notice_order
    ) STORED,
    ADD COLUMN participation_id text GENERATED ALWAYS AS (
        notice_number || ':' || notice_order || ':' || bid_classification_number || ':' ||
        rebid_number || ':' || business_registration_number
    ) STORED;

CREATE UNIQUE INDEX bid_awards_award_id_idx
    ON public_procurement.bid_awards (award_id);
CREATE UNIQUE INDEX bid_opening_participants_participation_id_idx
    ON public_procurement.bid_opening_participants (participation_id);

GRANT SELECT ON public_procurement.bid_awards TO teoria_runtime;
GRANT SELECT ON public_procurement.bid_opening_participants TO teoria_runtime;
