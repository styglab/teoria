-- Retain legacy snapshots for evidence and Runtime bundle rollback. New Capability
-- versions select goods.* property keys; earlier versions still select computer_server.*.
CREATE OR REPLACE VIEW public_procurement.server_requirement_observations AS
    SELECT observations.*, runs.status AS run_status
      FROM public_procurement.specification_requirement_observations observations
      JOIN public_procurement.specification_processing_runs runs USING (run_id)
     WHERE runs.status IN ('completed', 'partial')
       AND runs.classification_code = '4321150102'
       AND (
           (observations.ontology_namespace = 'goods'
            AND observations.owner_concept_key = 'goods.server')
           OR
           (observations.ontology_namespace = 'computer_server'
            AND observations.owner_concept_key = 'computer_server.server')
       );
