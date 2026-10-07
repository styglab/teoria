CREATE OR REPLACE FUNCTION
public_procurement.prune_procurement_relationship_graph_versions(
    reference_time timestamptz DEFAULT clock_timestamp(),
    published_retention interval DEFAULT interval '0 seconds',
    building_retention interval DEFAULT interval '1 day'
)
RETURNS TABLE (
    deleted_published_versions bigint,
    deleted_building_versions bigint,
    oldest_retained_version timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public_procurement, public
AS $$
DECLARE
    latest_published_version timestamptz;
BEGIN
    IF published_retention < interval '0 seconds' THEN
        RAISE EXCEPTION 'published_retention must not be negative';
    END IF;
    IF building_retention < interval '1 hour' THEN
        RAISE EXCEPTION 'building_retention must be at least 1 hour';
    END IF;

    SELECT max(graph_version)
    INTO latest_published_version
    FROM public_procurement.procurement_relationship_graph_versions
    WHERE status='published';

    DELETE FROM public_procurement.procurement_relationship_graph_versions
    WHERE status='published'
      AND graph_version < reference_time - published_retention
      AND graph_version IS DISTINCT FROM latest_published_version;
    GET DIAGNOSTICS deleted_published_versions = ROW_COUNT;

    DELETE FROM public_procurement.procurement_relationship_graph_versions
    WHERE status='building'
      AND created_at < reference_time - building_retention;
    GET DIAGNOSTICS deleted_building_versions = ROW_COUNT;

    SELECT min(graph_version)
    INTO oldest_retained_version
    FROM public_procurement.procurement_relationship_graph_versions
    WHERE status='published';

    RETURN NEXT;
END;
$$;

CREATE OR REPLACE FUNCTION public_procurement.publish_procurement_relationship_graph()
RETURNS timestamptz
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public_procurement, public
AS $$
DECLARE
    published_version timestamptz;
BEGIN
    published_version :=
        public_procurement.build_procurement_relationship_graph_snapshot();
    PERFORM public_procurement.populate_procurement_relationship_graph_overviews(
        published_version
    );
    PERFORM public_procurement.prune_procurement_relationship_graph_versions(
        published_version, interval '0 seconds', interval '1 day'
    );
    RETURN published_version;
END;
$$;

GRANT EXECUTE ON FUNCTION
    public_procurement.prune_procurement_relationship_graph_versions(
        timestamptz, interval, interval
    )
    TO teoria_pipeline;
GRANT EXECUTE ON FUNCTION public_procurement.publish_procurement_relationship_graph()
    TO teoria_pipeline;

SELECT *
FROM public_procurement.prune_procurement_relationship_graph_versions(
    clock_timestamp(), interval '0 seconds', interval '1 day'
);
