CREATE INDEX bid_awards_work_type_opening_at_idx
    ON public_procurement.bid_awards (work_type, opening_at DESC);

CREATE INDEX bid_awards_demand_organization_opening_at_idx
    ON public_procurement.bid_awards (demand_organization_code, opening_at DESC);

CREATE INDEX bid_awards_winner_business_opening_at_idx
    ON public_procurement.bid_awards (winner_business_registration_number, opening_at DESC);

CREATE INDEX bid_opening_participants_bid_at_idx
    ON public_procurement.bid_opening_participants (bid_at DESC);

CREATE INDEX bid_opening_participants_business_bid_at_idx
    ON public_procurement.bid_opening_participants (business_registration_number, bid_at DESC);

CREATE VIEW public_procurement.runtime_bid_opening_participants AS
SELECT
    participant.*,
    award.work_type,
    award.notice_name,
    award.opening_at,
    award.final_award_date,
    award.demand_organization_code,
    award.demand_organization_name
FROM public_procurement.bid_opening_participants AS participant
LEFT JOIN public_procurement.bid_awards AS award
    ON award.notice_number = participant.notice_number
   AND award.notice_order = participant.notice_order
   AND award.bid_classification_number = participant.bid_classification_number
   AND award.rebid_number = participant.rebid_number;

GRANT SELECT ON public_procurement.runtime_bid_opening_participants TO teoria_runtime;
