CREATE INDEX bid_notices_previous_published_idx
    ON public_procurement.bid_notices
       (previous_notice_number, notice_published_at, notice_number, notice_order)
    WHERE previous_notice_number IS NOT NULL;

DO $$
DECLARE definition text;
BEGIN
    SELECT pg_get_viewdef('public_procurement.runtime_bid_notices_base'::regclass,true)
      INTO definition;
    IF position('latest_versions AS (' in definition)=0 THEN
      RAISE EXCEPTION 'runtime_bid_notices_base latest_versions CTE was not found';
    END IF;
    definition := replace(definition,'latest_versions AS (',
                           'latest_versions AS NOT MATERIALIZED (');
    EXECUTE 'CREATE OR REPLACE VIEW public_procurement.runtime_bid_notices_base AS '||definition;
END $$;
