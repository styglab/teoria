-- Explicit output contracts, not inferred from table/flow name similarity.
-- No OpenMetadata entities, samples, raw payloads or provider credentials here.
CREATE INDEX pipeline_runs_pipeline_started_idx
    ON ingestion.pipeline_runs (pipeline_id, started_at DESC);
CREATE VIEW public_procurement.runtime_asset_collection_status AS
WITH outputs(relation_name, pipeline_id) AS (VALUES
    ('contracts', 'pps_contract_incremental'),
    ('contracts', 'pps_contract_backfill_2021_2026'),
    ('contracts', 'pps_contract_ingestion'),
    ('contract_suppliers', 'pps_contract_incremental'),
    ('contract_suppliers', 'pps_contract_backfill_2021_2026'),
    ('contract_suppliers', 'pps_contract_ingestion'),
    ('contract_demand_organizations', 'pps_contract_incremental'),
    ('contract_demand_organizations', 'pps_contract_backfill_2021_2026'),
    ('contract_demand_organizations', 'pps_contract_ingestion'),
    ('public_organizations', 'pps_contract_incremental'),
    ('public_organizations', 'pps_contract_backfill_2021_2026'),
    ('public_organizations', 'pps_contract_ingestion'),
    ('bid_notices', 'pps_bid_notice_ingestion'),
    ('bid_notices', 'pps_bid_notice_backfill_2021_2026'),
    ('bid_notices', 'pps_bid_notice_enrichment_backfill'),
    ('bid_notice_license_restrictions', 'pps_bid_notice_enrichment_backfill'),
    ('bid_notice_participation_regions', 'pps_bid_notice_enrichment_backfill'),
    ('bid_awards', 'pps_bid_result_incremental'),
    ('bid_awards', 'pps_bid_result_backfill_5y'),
    ('bid_awards', 'pps_bid_result_ingestion'),
    ('bid_opening_participants', 'pps_bid_opening_incremental_enrichment'),
    ('bid_opening_participants', 'pps_bid_opening_backfill_enrichment'),
    ('bid_opening_participants', 'pps_bid_opening_retry_enrichment'),
    ('bid_notice_outcomes', 'pps_bid_notice_outcome_enrichment'),
    ('procurement_industries', 'pps_industry_ingestion')
)
SELECT current_database() AS database_name, 'public_procurement'::text AS schema_name,
       o.relation_name, o.pipeline_id, r.execution_id, r.status,
       r.started_at, r.finished_at, r.window_start, r.window_end,
       r.error_code, r.raw_record_count, r.contract_count, r.notice_count,
       r.award_count, r.opening_participant_count, r.notice_outcome_count,
       success.finished_at AS last_success_at, c.cursor_date, c.updated_at AS checkpoint_updated_at
FROM outputs o
LEFT JOIN LATERAL (
    SELECT * FROM ingestion.pipeline_runs r WHERE r.pipeline_id=o.pipeline_id
    ORDER BY r.started_at DESC, r.execution_id DESC LIMIT 1
) r ON true
LEFT JOIN LATERAL (
    SELECT r.finished_at FROM ingestion.pipeline_runs r
    WHERE r.pipeline_id=o.pipeline_id AND r.status='completed'
    ORDER BY r.started_at DESC LIMIT 1
) success ON true
LEFT JOIN ingestion.pipeline_checkpoints c ON c.pipeline_id=o.pipeline_id;
GRANT SELECT ON public_procurement.runtime_asset_collection_status TO teoria_runtime;
