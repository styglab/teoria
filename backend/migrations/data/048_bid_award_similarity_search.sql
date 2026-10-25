CREATE INDEX bid_awards_similarity_title_gist_idx
    ON public_procurement.bid_awards
    USING gist (public_procurement.normalize_bid_notice_title(notice_name) gist_trgm_ops);
