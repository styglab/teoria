CREATE TABLE public_procurement.procurement_relationship_graph_overviews (
    graph_version timestamptz NOT NULL REFERENCES
        public_procurement.procurement_relationship_graph_versions(graph_version)
        ON DELETE CASCADE,
    period_from_year integer NOT NULL,
    period_to_year integer NOT NULL,
    group_by text NOT NULL CHECK (group_by IN ('total', 'work_type', 'field')),
    cluster_id text NOT NULL,
    work_type text,
    field_code text,
    field_name text,
    large_category text,
    middle_category text,
    organization_count bigint NOT NULL,
    company_count bigint NOT NULL,
    link_count bigint NOT NULL,
    contract_count bigint,
    total_attributed_contract_amount numeric,
    PRIMARY KEY (
        graph_version, period_from_year, period_to_year, group_by, cluster_id
    )
);

CREATE INDEX procurement_relationship_graph_overviews_lookup_idx
    ON public_procurement.procurement_relationship_graph_overviews (
        graph_version, group_by, period_from_year, period_to_year
    );

CREATE OR REPLACE FUNCTION
public_procurement.populate_procurement_relationship_graph_overviews(
    selected_version timestamptz
)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public_procurement, public
AS $$
DECLARE
    graph_period_from integer;
    graph_period_to integer;
    selected_period record;
BEGIN
    SELECT period_from_year,period_to_year
    INTO graph_period_from,graph_period_to
    FROM public_procurement.procurement_relationship_graph_versions
    WHERE graph_version=selected_version;

    IF graph_period_from IS NULL OR graph_period_to IS NULL THEN
        RAISE EXCEPTION 'graph version % has no source period', selected_version;
    END IF;

    FOR selected_period IN
        SELECT DISTINCT period_from_year,graph_period_to AS period_to_year
        FROM (VALUES
            (graph_period_to),
            (greatest(graph_period_from,graph_period_to - 2)),
            (greatest(graph_period_from,graph_period_to - 4)),
            (graph_period_from)
        ) periods(period_from_year)
        ORDER BY period_from_year DESC
    LOOP
        INSERT INTO public_procurement.procurement_relationship_graph_overviews (
            graph_version,period_from_year,period_to_year,group_by,cluster_id,
            organization_count,company_count,link_count
        )
        WITH filtered AS MATERIALIZED (
            SELECT organization_code,company_number
            FROM public_procurement.procurement_relationship_graph_aggregates
            WHERE graph_version=selected_version
              AND contract_year BETWEEN selected_period.period_from_year
                                    AND selected_period.period_to_year
        )
        SELECT selected_version,selected_period.period_from_year,
               selected_period.period_to_year,'total','*',
               (SELECT count(*) FROM (
                    SELECT organization_code FROM filtered GROUP BY organization_code
                ) organizations),
               (SELECT count(*) FROM (
                    SELECT company_number FROM filtered GROUP BY company_number
                ) companies),
               (SELECT count(*) FROM (
                    SELECT organization_code,company_number FROM filtered
                    GROUP BY organization_code,company_number
                ) links)
        ON CONFLICT DO NOTHING;

        INSERT INTO public_procurement.procurement_relationship_graph_overviews (
            graph_version,period_from_year,period_to_year,group_by,cluster_id,
            work_type,field_code,field_name,large_category,middle_category,
            organization_count,company_count,link_count,contract_count,
            total_attributed_contract_amount
        )
        WITH filtered AS MATERIALIZED (
            SELECT cluster_id AS group_key,work_type,field_code,field_name,
                   large_category,middle_category,organization_code,company_number,
                   contract_count,total_attributed_contract_amount
            FROM public_procurement.procurement_relationship_graph_aggregates
            WHERE graph_version=selected_version
              AND contract_year BETWEEN selected_period.period_from_year
                                    AND selected_period.period_to_year
        ), metrics AS (
            SELECT group_key,max(work_type) AS work_type,
                   max(field_code) AS field_code,max(field_name) AS field_name,
                   max(large_category) AS large_category,
                   max(middle_category) AS middle_category,
                   sum(contract_count) AS contract_count,
                   sum(total_attributed_contract_amount)
                     AS total_attributed_contract_amount
            FROM filtered GROUP BY group_key
        ), organizations AS (
            SELECT group_key,count(*) AS organization_count
            FROM (SELECT group_key,organization_code FROM filtered
                  GROUP BY group_key,organization_code) grouped
            GROUP BY group_key
        ), companies AS (
            SELECT group_key,count(*) AS company_count
            FROM (SELECT group_key,company_number FROM filtered
                  GROUP BY group_key,company_number) grouped
            GROUP BY group_key
        ), links AS (
            SELECT group_key,count(*) AS link_count
            FROM (SELECT group_key,organization_code,company_number FROM filtered
                  GROUP BY group_key,organization_code,company_number) grouped
            GROUP BY group_key
        )
        SELECT selected_version,selected_period.period_from_year,
               selected_period.period_to_year,'field',metrics.group_key,
               metrics.work_type,metrics.field_code,metrics.field_name,
               metrics.large_category,metrics.middle_category,
               organizations.organization_count,companies.company_count,
               links.link_count,metrics.contract_count,
               metrics.total_attributed_contract_amount
        FROM metrics JOIN organizations USING (group_key)
        JOIN companies USING (group_key) JOIN links USING (group_key)
        ON CONFLICT DO NOTHING;

        INSERT INTO public_procurement.procurement_relationship_graph_overviews (
            graph_version,period_from_year,period_to_year,group_by,cluster_id,
            work_type,organization_count,company_count,link_count,contract_count,
            total_attributed_contract_amount
        )
        WITH filtered AS MATERIALIZED (
            SELECT work_type AS group_key,organization_code,company_number,
                   contract_count,total_attributed_contract_amount
            FROM public_procurement.procurement_relationship_graph_aggregates
            WHERE graph_version=selected_version
              AND contract_year BETWEEN selected_period.period_from_year
                                    AND selected_period.period_to_year
        ), metrics AS (
            SELECT group_key,sum(contract_count) AS contract_count,
                   sum(total_attributed_contract_amount)
                     AS total_attributed_contract_amount
            FROM filtered GROUP BY group_key
        ), organizations AS (
            SELECT group_key,count(*) AS organization_count
            FROM (SELECT group_key,organization_code FROM filtered
                  GROUP BY group_key,organization_code) grouped
            GROUP BY group_key
        ), companies AS (
            SELECT group_key,count(*) AS company_count
            FROM (SELECT group_key,company_number FROM filtered
                  GROUP BY group_key,company_number) grouped
            GROUP BY group_key
        ), links AS (
            SELECT group_key,count(*) AS link_count
            FROM (SELECT group_key,organization_code,company_number FROM filtered
                  GROUP BY group_key,organization_code,company_number) grouped
            GROUP BY group_key
        )
        SELECT selected_version,selected_period.period_from_year,
               selected_period.period_to_year,'work_type',metrics.group_key,
               metrics.group_key,organizations.organization_count,
               companies.company_count,links.link_count,metrics.contract_count,
               metrics.total_attributed_contract_amount
        FROM metrics JOIN organizations USING (group_key)
        JOIN companies USING (group_key) JOIN links USING (group_key)
        ON CONFLICT DO NOTHING;
    END LOOP;
END;
$$;

ALTER FUNCTION public_procurement.publish_procurement_relationship_graph()
    RENAME TO build_procurement_relationship_graph_snapshot;

REVOKE EXECUTE ON FUNCTION
    public_procurement.build_procurement_relationship_graph_snapshot()
    FROM teoria_pipeline;
REVOKE ALL ON FUNCTION
    public_procurement.build_procurement_relationship_graph_snapshot()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION
    public_procurement.populate_procurement_relationship_graph_overviews(timestamptz)
    FROM PUBLIC;

CREATE FUNCTION public_procurement.publish_procurement_relationship_graph()
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
    RETURN published_version;
END;
$$;

GRANT SELECT ON public_procurement.procurement_relationship_graph_overviews
    TO teoria_runtime;
GRANT EXECUTE ON FUNCTION public_procurement.publish_procurement_relationship_graph()
    TO teoria_pipeline;

SELECT public_procurement.populate_procurement_relationship_graph_overviews(
    graph_version
)
FROM public_procurement.procurement_relationship_graph_versions
WHERE status='published'
ORDER BY graph_version DESC
LIMIT 1;

ANALYZE public_procurement.procurement_relationship_graph_overviews;
