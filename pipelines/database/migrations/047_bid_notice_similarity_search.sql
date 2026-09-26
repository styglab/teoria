CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION public_procurement.normalize_bid_notice_title(value text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
RETURN trim(regexp_replace(
    regexp_replace(
        lower(coalesce(value, '')),
        '(19|20)[0-9]{2}년|\([^)]*(긴급|재공고|변경|취소)[^)]*\)|\[(긴급|재공고|변경|취소)[^]]*\]',
        ' ', 'g'
    ),
    '[^0-9a-z가-힣]+', ' ', 'g'
));

CREATE INDEX bid_notices_similarity_title_gist_idx
    ON public_procurement.bid_notices
    USING gist (public_procurement.normalize_bid_notice_title(notice_name) gist_trgm_ops);

CREATE INDEX bid_notices_similarity_scope_idx
    ON public_procurement.bid_notices
    (work_type, notice_published_at DESC, notice_number, notice_order);

GRANT EXECUTE ON FUNCTION public_procurement.normalize_bid_notice_title(text) TO teoria_runtime;
