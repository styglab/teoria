CREATE INDEX bid_awards_similarity_scope_idx
    ON public_procurement.bid_awards (work_type, opening_at DESC)
    INCLUDE (notice_number, notice_order, notice_name, winner_business_registration_number,
             winner_name, winning_amount, winning_rate, final_award_date);
