CREATE TABLE public_procurement.procurement_relationship_graph_versions (
    graph_version timestamptz PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('building', 'published')),
    source_ledger_oldest_refreshed_at timestamptz,
    source_ledger_latest_refreshed_at timestamptz,
    period_from_year integer,
    period_to_year integer,
    organization_count bigint NOT NULL DEFAULT 0,
    company_count bigint NOT NULL DEFAULT 0,
    link_count bigint NOT NULL DEFAULT 0,
    aggregate_row_count bigint NOT NULL DEFAULT 0,
    published_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public_procurement.procurement_relationship_graph_aggregates (
    graph_version timestamptz NOT NULL REFERENCES
        public_procurement.procurement_relationship_graph_versions(graph_version)
        ON DELETE CASCADE,
    contract_year integer NOT NULL,
    cluster_id text NOT NULL,
    work_type text NOT NULL,
    field_code text NOT NULL,
    field_name text,
    large_category text,
    middle_category text,
    organization_code text NOT NULL,
    organization_name text,
    company_number text NOT NULL,
    company_name text,
    contract_count bigint NOT NULL,
    total_contract_amount numeric,
    total_attributed_contract_amount numeric,
    known_contract_amount_count bigint NOT NULL,
    known_attributed_amount_count bigint NOT NULL,
    first_contract_date date NOT NULL,
    latest_contract_date date NOT NULL,
    company_roles text[] NOT NULL,
    amount_completeness text NOT NULL,
    PRIMARY KEY (
        graph_version, contract_year, cluster_id,
        organization_code, company_number
    )
);

CREATE TABLE public_procurement.procurement_relationship_graph_nodes (
    graph_version timestamptz NOT NULL REFERENCES
        public_procurement.procurement_relationship_graph_versions(graph_version)
        ON DELETE CASCADE,
    contract_year integer NOT NULL,
    cluster_id text NOT NULL,
    node_type text NOT NULL CHECK (node_type IN ('organization', 'company')),
    node_id text NOT NULL,
    node_name text,
    contract_count bigint NOT NULL,
    total_contract_amount numeric,
    total_attributed_contract_amount numeric,
    known_amount_count bigint NOT NULL,
    first_contract_date date NOT NULL,
    latest_contract_date date NOT NULL,
    amount_completeness text NOT NULL,
    PRIMARY KEY (graph_version, contract_year, cluster_id, node_type, node_id)
);

CREATE INDEX procurement_relationship_graph_cluster_idx
    ON public_procurement.procurement_relationship_graph_aggregates (
        graph_version, cluster_id, contract_year, company_number, organization_code
    );

CREATE INDEX procurement_relationship_graph_overview_idx
    ON public_procurement.procurement_relationship_graph_aggregates (
        graph_version, contract_year, work_type, field_code
    );

CREATE INDEX procurement_relationship_graph_nodes_cluster_idx
    ON public_procurement.procurement_relationship_graph_nodes (
        graph_version, cluster_id, contract_year, node_type, node_id
    );

CREATE OR REPLACE FUNCTION public_procurement.publish_procurement_relationship_graph()
RETURNS timestamptz
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public_procurement, ingestion, public
AS $$
DECLARE
    published_version timestamptz := clock_timestamp();
BEGIN
    INSERT INTO public_procurement.procurement_relationship_graph_versions (
        graph_version, status, source_ledger_oldest_refreshed_at,
        source_ledger_latest_refreshed_at, period_from_year, period_to_year
    )
    SELECT published_version, 'building', min(refreshed_at), max(refreshed_at),
           min(extract(year FROM first_contract_date))::integer,
           max(extract(year FROM first_contract_date))::integer
    FROM public_procurement.contract_event_company_ledger;

    INSERT INTO public_procurement.procurement_relationship_graph_aggregates (
        graph_version, contract_year, cluster_id, work_type, field_code,
        field_name, large_category, middle_category,
        organization_code, organization_name, company_number, company_name,
        contract_count, total_contract_amount, total_attributed_contract_amount,
        known_contract_amount_count, known_attributed_amount_count,
        first_contract_date, latest_contract_date, company_roles, amount_completeness
    )
    SELECT published_version,
           extract(year FROM first_contract_date)::integer AS contract_year,
           work_type || ':' || field_code AS cluster_id,
           work_type, field_code,
           max(field_name), max(large_category), max(middle_category),
           organization_code, max(organization_name),
           company_number, max(company_name),
           count(DISTINCT contract_event_id),
           sum(contract_amount), sum(attributed_contract_amount),
           count(contract_amount), count(attributed_contract_amount),
           min(first_contract_date), max(latest_contract_version_date),
           array_agg(DISTINCT COALESCE(NULLIF(btrim(company_role), ''), 'unknown')
                     ORDER BY COALESCE(NULLIF(btrim(company_role), ''), 'unknown')),
           CASE
             WHEN count(attributed_contract_amount) = count(*) THEN 'complete'
             WHEN count(attributed_contract_amount) = 0 THEN 'unknown'
             ELSE 'partial'
           END
    FROM public_procurement.contract_event_company_ledger
    GROUP BY extract(year FROM first_contract_date)::integer,
             work_type, field_code, organization_code, company_number;

    INSERT INTO public_procurement.procurement_relationship_graph_nodes (
        graph_version, contract_year, cluster_id, node_type, node_id, node_name,
        contract_count, total_contract_amount, total_attributed_contract_amount,
        known_amount_count, first_contract_date, latest_contract_date,
        amount_completeness
    )
    WITH organization_events AS (
        SELECT DISTINCT ON (
                   extract(year FROM first_contract_date)::integer,
                   work_type, field_code, organization_code, contract_event_id
               )
               extract(year FROM first_contract_date)::integer AS contract_year,
               work_type || ':' || field_code AS cluster_id,
               organization_code, organization_name, contract_event_id,
               contract_amount, first_contract_date, latest_contract_version_date
        FROM public_procurement.contract_event_company_ledger
        ORDER BY extract(year FROM first_contract_date)::integer,
                 work_type, field_code, organization_code, contract_event_id,
                 latest_contract_version_date DESC
    ), organization_nodes AS (
        SELECT published_version AS graph_version, contract_year, cluster_id,
               'organization'::text AS node_type, organization_code AS node_id,
               max(organization_name) AS node_name,
               count(*) AS contract_count,
               sum(contract_amount) AS total_contract_amount,
               NULL::numeric AS total_attributed_contract_amount,
               count(contract_amount) AS known_amount_count,
               min(first_contract_date) AS first_contract_date,
               max(latest_contract_version_date) AS latest_contract_date,
               CASE WHEN count(contract_amount)=count(*) THEN 'complete'
                    WHEN count(contract_amount)=0 THEN 'unknown' ELSE 'partial' END
                 AS amount_completeness
        FROM organization_events
        GROUP BY contract_year, cluster_id, organization_code
    ), company_nodes AS (
        SELECT published_version AS graph_version,
               extract(year FROM first_contract_date)::integer AS contract_year,
               work_type || ':' || field_code AS cluster_id,
               'company'::text AS node_type, company_number AS node_id,
               max(company_name) AS node_name,
               count(DISTINCT (organization_code, contract_event_id)) AS contract_count,
               NULL::numeric AS total_contract_amount,
               sum(attributed_contract_amount) AS total_attributed_contract_amount,
               count(attributed_contract_amount) AS known_amount_count,
               min(first_contract_date) AS first_contract_date,
               max(latest_contract_version_date) AS latest_contract_date,
               CASE WHEN count(attributed_contract_amount)=count(*) THEN 'complete'
                    WHEN count(attributed_contract_amount)=0 THEN 'unknown' ELSE 'partial' END
                 AS amount_completeness
        FROM public_procurement.contract_event_company_ledger
        GROUP BY extract(year FROM first_contract_date)::integer,
                 work_type, field_code, company_number
    )
    SELECT * FROM organization_nodes
    UNION ALL
    SELECT * FROM company_nodes;

    UPDATE public_procurement.procurement_relationship_graph_versions version
    SET status='published', published_at=clock_timestamp(),
        organization_count=counts.organization_count,
        company_count=counts.company_count,
        link_count=counts.link_count,
        aggregate_row_count=counts.aggregate_row_count
    FROM (
        SELECT count(DISTINCT organization_code) AS organization_count,
               count(DISTINCT company_number) AS company_count,
               count(DISTINCT (organization_code, company_number)) AS link_count,
               count(*) AS aggregate_row_count
        FROM public_procurement.procurement_relationship_graph_aggregates
        WHERE graph_version=published_version
    ) counts
    WHERE version.graph_version=published_version;

    DELETE FROM public_procurement.procurement_relationship_graph_versions
    WHERE graph_version < published_version - interval '7 days';

    RETURN published_version;
END;
$$;

CREATE VIEW public_procurement.procurement_relationship_graph_latest AS
SELECT aggregate.*
FROM public_procurement.procurement_relationship_graph_aggregates aggregate
WHERE aggregate.graph_version = (
    SELECT max(graph_version)
    FROM public_procurement.procurement_relationship_graph_versions
    WHERE status='published'
);

GRANT SELECT ON public_procurement.procurement_relationship_graph_versions,
                public_procurement.procurement_relationship_graph_aggregates,
                public_procurement.procurement_relationship_graph_nodes,
                public_procurement.procurement_relationship_graph_latest
    TO teoria_runtime;
GRANT EXECUTE ON FUNCTION public_procurement.publish_procurement_relationship_graph()
    TO teoria_pipeline;
