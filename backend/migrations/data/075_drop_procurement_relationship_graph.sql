DROP VIEW IF EXISTS public_procurement.procurement_relationship_graph_latest;

DROP FUNCTION IF EXISTS
    public_procurement.publish_procurement_relationship_graph();
DROP FUNCTION IF EXISTS
    public_procurement.build_procurement_relationship_graph_snapshot();
DROP FUNCTION IF EXISTS
    public_procurement.populate_procurement_relationship_graph_overviews(timestamptz);
DROP FUNCTION IF EXISTS
    public_procurement.prune_procurement_relationship_graph_versions(
        timestamptz, interval, interval
    );

DROP TABLE IF EXISTS
    public_procurement.procurement_relationship_graph_overviews;
DROP TABLE IF EXISTS
    public_procurement.procurement_relationship_graph_nodes;
DROP TABLE IF EXISTS
    public_procurement.procurement_relationship_graph_aggregates;
DROP TABLE IF EXISTS
    public_procurement.procurement_relationship_graph_versions;
