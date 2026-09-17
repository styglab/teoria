CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX bid_notices_notice_name_trgm_idx
    ON public_procurement.bid_notices USING gin (notice_name gin_trgm_ops);
CREATE INDEX bid_notices_notice_number_trgm_idx
    ON public_procurement.bid_notices USING gin (notice_number gin_trgm_ops);
CREATE INDEX bid_notices_notice_organization_name_trgm_idx
    ON public_procurement.bid_notices USING gin (notice_organization_name gin_trgm_ops);
CREATE INDEX bid_notices_demand_organization_name_trgm_idx
    ON public_procurement.bid_notices USING gin (demand_organization_name gin_trgm_ops);

CREATE TABLE public_procurement.bid_notice_latest_versions (
    notice_number text PRIMARY KEY,
    notice_order text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (notice_number, notice_order)
        REFERENCES public_procurement.bid_notices(notice_number, notice_order)
        ON UPDATE CASCADE ON DELETE CASCADE
);

INSERT INTO public_procurement.bid_notice_latest_versions (notice_number, notice_order)
SELECT DISTINCT ON (notice_number) notice_number, notice_order
FROM public_procurement.bid_notices
ORDER BY
    notice_number,
    CASE WHEN notice_order ~ '^[0-9]+$' THEN notice_order::numeric END DESC NULLS LAST,
    notice_order DESC,
    notice_published_at DESC NULLS LAST;

CREATE FUNCTION public_procurement.refresh_bid_notice_latest_version(target_notice_number text)
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    latest_order text;
BEGIN
    SELECT notice_order
    INTO latest_order
    FROM public_procurement.bid_notices
    WHERE notice_number = target_notice_number
    ORDER BY
        CASE WHEN notice_order ~ '^[0-9]+$' THEN notice_order::numeric END DESC NULLS LAST,
        notice_order DESC,
        notice_published_at DESC NULLS LAST
    LIMIT 1;

    IF latest_order IS NULL THEN
        DELETE FROM public_procurement.bid_notice_latest_versions
        WHERE notice_number = target_notice_number;
    ELSE
        INSERT INTO public_procurement.bid_notice_latest_versions (
            notice_number, notice_order, updated_at
        ) VALUES (target_notice_number, latest_order, now())
        ON CONFLICT (notice_number) DO UPDATE
        SET notice_order = EXCLUDED.notice_order,
            updated_at = CASE
                WHEN public_procurement.bid_notice_latest_versions.notice_order
                     IS DISTINCT FROM EXCLUDED.notice_order
                THEN now()
                ELSE public_procurement.bid_notice_latest_versions.updated_at
            END;
    END IF;
END;
$$;

CREATE FUNCTION public_procurement.sync_bid_notice_latest_version()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' OR (
        TG_OP = 'UPDATE' AND OLD.notice_number IS DISTINCT FROM NEW.notice_number
    ) THEN
        PERFORM public_procurement.refresh_bid_notice_latest_version(OLD.notice_number);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM public_procurement.refresh_bid_notice_latest_version(NEW.notice_number);
    END IF;
    RETURN NULL;
END;
$$;

CREATE TRIGGER bid_notices_sync_latest_version
AFTER INSERT OR DELETE OR UPDATE OF notice_number, notice_order, notice_published_at
ON public_procurement.bid_notices
FOR EACH ROW
EXECUTE FUNCTION public_procurement.sync_bid_notice_latest_version();

CREATE OR REPLACE VIEW public_procurement.runtime_bid_notices AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number,
        notice_order,
        extraction_id,
        completeness,
        requires_review
    FROM public_procurement.bid_eligibility_extractions
    WHERE status = 'completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
)
SELECT
    n.notice_number || ':' || n.notice_order AS bid_notice_id,
    n.notice_number,
    n.notice_order,
    n.notice_name,
    n.work_type,
    n.notice_kind_name,
    n.is_re_notice,
    n.notice_published_at,
    n.bid_begin_at,
    n.bid_deadline_at,
    n.opening_at,
    CASE
        WHEN n.bid_deadline_at IS NULL
             AND n.opening_at IS NOT NULL
             AND n.opening_at < now() THEN 'closed'
        WHEN n.bid_deadline_at IS NULL THEN 'unknown'
        WHEN n.bid_begin_at IS NOT NULL AND n.bid_begin_at > now() THEN 'scheduled'
        WHEN n.bid_deadline_at >= now() THEN 'open'
        ELSE 'closed'
    END AS bid_status,
    n.notice_organization_code,
    n.notice_organization_name,
    n.demand_organization_code,
    n.demand_organization_name,
    n.bid_method_name,
    n.contract_method_name,
    n.estimated_price,
    n.allocated_budget,
    n.detail_url,
    n.notice_url,
    n.source_changed_at,
    rs.expression::text AS requirement_expression,
    le.completeness AS extraction_completeness,
    le.requires_review,
    CASE
        WHEN latest.notice_order IS DISTINCT FROM n.notice_order THEN 'superseded'
        WHEN n.notice_kind_name = '취소공고' THEN 'cancelled'
        ELSE 'active'
    END AS notice_status
FROM public_procurement.bid_notices n
JOIN public_procurement.bid_notice_latest_versions latest
    ON latest.notice_number = n.notice_number
LEFT JOIN latest_extraction le
    ON le.notice_number = n.notice_number AND le.notice_order = n.notice_order
LEFT JOIN public_procurement.bid_eligibility_requirement_sets rs
    ON rs.extraction_id = le.extraction_id;

GRANT SELECT ON public_procurement.runtime_bid_notices TO teoria_runtime;
