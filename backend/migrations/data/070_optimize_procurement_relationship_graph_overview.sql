CREATE INDEX procurement_relationship_graph_overview_cover_idx
    ON public_procurement.procurement_relationship_graph_aggregates (
        graph_version, contract_year, cluster_id,
        organization_code, company_number
    ) INCLUDE (
        work_type, field_code, field_name, large_category, middle_category,
        contract_count, total_attributed_contract_amount
    );

ANALYZE public_procurement.procurement_relationship_graph_aggregates;
