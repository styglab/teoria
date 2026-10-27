\set ON_ERROR_STOP on
BEGIN;
DO $$ BEGIN
 IF (SELECT count(*) FROM public_procurement.specification_processing_runs WHERE run_id IN ('server_memory_20261027_01','goods_server_memory_20261027_01') AND status='partial')<>2
    OR (SELECT count(*) FROM public_procurement.specification_standard_workflows WHERE workflow_id='server_rollout_20261027_01' AND status='awaiting_approval')<>1
    OR (SELECT count(*) FROM public_procurement.specification_requirement_observations)<>6
    OR EXISTS(SELECT 1 FROM public_procurement.specification_requirement_observations WHERE run_id NOT IN ('server_memory_20261027_01','goods_server_memory_20261027_01')) THEN
  RAISE EXCEPTION 'Legacy specification inventory changed; inspect before reset';
 END IF;
END $$;
DELETE FROM public_procurement.specification_requirement_observations WHERE run_id IN ('server_memory_20261027_01','goods_server_memory_20261027_01');
DELETE FROM public_procurement.specification_processing_documents WHERE run_id IN ('server_memory_20261027_01','goods_server_memory_20261027_01');
DELETE FROM public_procurement.specification_processing_artifacts WHERE run_id IN ('server_memory_20261027_01','goods_server_memory_20261027_01');
DELETE FROM public_procurement.specification_processing_runs WHERE run_id IN ('server_memory_20261027_01','goods_server_memory_20261027_01');
DELETE FROM public_procurement.specification_standard_workflows WHERE workflow_id='server_rollout_20261027_01';
\if :apply
 COMMIT;
\else
 ROLLBACK;
\endif
