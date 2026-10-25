CREATE TABLE public_procurement.bid_notice_lineage_summaries (
    root_number text PRIMARY KEY,
    lineage_count integer NOT NULL,
    latest_bid_notice_id text NOT NULL,
    lineage_notices text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public_procurement.bid_notice_lineage_summaries (
    root_number,lineage_count,latest_bid_notice_id,lineage_notices
)
SELECT COALESCE(lineage_root_notice_number,notice_number),count(*)::integer,
       (array_agg(notice_number||':'||notice_order
          ORDER BY notice_published_at DESC NULLS LAST,notice_number DESC))[1],
       jsonb_agg(jsonb_build_object(
          'bid_notice_id',notice_number||':'||notice_order,
          'notice_kind',CASE WHEN notice_kind_name='재공고' OR is_re_notice THEN 're_notice'
            WHEN notice_kind_name='변경공고' THEN 'correction'
            WHEN notice_kind_name='취소공고' THEN 'cancellation'
            WHEN notice_kind_name='등록공고' THEN 'original' ELSE 'unknown' END,
          'notice_published_at',notice_published_at)
          ORDER BY notice_published_at,notice_number,notice_order)::text
FROM public_procurement.bid_notices
GROUP BY COALESCE(lineage_root_notice_number,notice_number);

CREATE FUNCTION public_procurement.refresh_bid_notice_lineage_summary(root text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM public_procurement.bid_notice_lineage_summaries WHERE root_number=root;
    INSERT INTO public_procurement.bid_notice_lineage_summaries (
        root_number,lineage_count,latest_bid_notice_id,lineage_notices
    )
    SELECT root,count(*)::integer,
           (array_agg(notice_number||':'||notice_order
             ORDER BY notice_published_at DESC NULLS LAST,notice_number DESC))[1],
           jsonb_agg(jsonb_build_object(
             'bid_notice_id',notice_number||':'||notice_order,
             'notice_kind',CASE WHEN notice_kind_name='재공고' OR is_re_notice THEN 're_notice'
               WHEN notice_kind_name='변경공고' THEN 'correction'
               WHEN notice_kind_name='취소공고' THEN 'cancellation'
               WHEN notice_kind_name='등록공고' THEN 'original' ELSE 'unknown' END,
             'notice_published_at',notice_published_at)
             ORDER BY notice_published_at,notice_number,notice_order)::text
    FROM public_procurement.bid_notices
    WHERE COALESCE(lineage_root_notice_number,notice_number)=root
    HAVING count(*)>0;
END $$;

CREATE FUNCTION public_procurement.refresh_bid_notice_lineage_summary_trigger()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM public_procurement.refresh_bid_notice_lineage_summary(
      COALESCE(NEW.lineage_root_notice_number,NEW.notice_number));
    IF TG_OP='UPDATE' AND COALESCE(OLD.lineage_root_notice_number,OLD.notice_number)
       IS DISTINCT FROM COALESCE(NEW.lineage_root_notice_number,NEW.notice_number) THEN
      PERFORM public_procurement.refresh_bid_notice_lineage_summary(
        COALESCE(OLD.lineage_root_notice_number,OLD.notice_number));
    END IF;
    RETURN NULL;
END $$;

CREATE TRIGGER bid_notices_refresh_lineage_summary
AFTER INSERT OR UPDATE OF source_payload,notice_published_at,notice_kind_name,is_re_notice
ON public_procurement.bid_notices
FOR EACH ROW EXECUTE FUNCTION public_procurement.refresh_bid_notice_lineage_summary_trigger();

DO $$
DECLARE definition text; start_at integer; end_at integer;
BEGIN
    SELECT pg_get_viewdef('public_procurement.runtime_bid_notices_base'::regclass,true)
      INTO definition;
    start_at := position('lineage_summary AS (' in definition);
    end_at := position('latest_versions AS (' in definition);
    IF start_at=0 OR end_at=0 OR end_at<=start_at THEN
      RAISE EXCEPTION 'runtime_bid_notices_base lineage CTE was not found';
    END IF;
    definition := substring(definition from 1 for start_at-1)
      || 'lineage_summary AS (SELECT root_number,lineage_count,latest_bid_notice_id,lineage_notices '
      || 'FROM public_procurement.bid_notice_lineage_summaries), '
      || substring(definition from end_at);
    EXECUTE 'CREATE OR REPLACE VIEW public_procurement.runtime_bid_notices_base AS '||definition;
END $$;

GRANT SELECT ON public_procurement.bid_notice_lineage_summaries TO teoria_runtime;
