-- Remove only empty, retired procurement storage. Keep notice identities and
-- revision tracking for goods restoration, specification runs, law data, and
-- the shared ingestion/checkpoint infrastructure. Existing migrations remain history.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE
    relation_name text;
    relation_id regclass;
    populated boolean;
BEGIN
    -- Lock before checking: a concurrent legacy writer must not add data
    -- between the empty-table check and DROP. Unknown dependencies fail RESTRICT.
    FOREACH relation_name IN ARRAY ARRAY[
        'ingestion.bid_notice_outcome_collection_status',
        'ingestion.bid_notice_requirement_collection_status',
        'ingestion.bid_opening_collection_status',
        'ingestion.bid_opening_enrichment_queue',
        'ingestion.contract_event_ledger_refresh_queue',
        'ingestion.contract_event_ledger_refresh_status',
        'public_procurement.bid_awards',
        'public_procurement.bid_document_purge_runs',
        'public_procurement.bid_eligibility_extractions',
        'public_procurement.bid_eligibility_requirement_evidence',
        'public_procurement.bid_eligibility_requirement_proof_evidence',
        'public_procurement.bid_eligibility_requirement_proofs',
        'public_procurement.bid_eligibility_requirement_sets',
        'public_procurement.bid_eligibility_requirements',
        'public_procurement.bid_notice_documents',
        'public_procurement.bid_notice_license_restrictions',
        'public_procurement.bid_notice_outcomes',
        'public_procurement.bid_notice_participation_regions',
        'public_procurement.bid_opening_participants',
        'public_procurement.bid_participation_finding_evidence',
        'public_procurement.bid_participation_findings',
        'public_procurement.contract_demand_organizations',
        'public_procurement.contract_event_company_ledger',
        'public_procurement.contract_suppliers',
        'public_procurement.contracts',
        'public_procurement.procurement_industries',
        'public_procurement.public_organizations'
    ] LOOP
        relation_id := to_regclass(relation_name);
        IF relation_id IS NOT NULL THEN
            EXECUTE format('LOCK TABLE %s IN ACCESS EXCLUSIVE MODE', relation_id);
            EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s LIMIT 1)', relation_id)
                INTO populated;
            IF populated THEN
                RAISE EXCEPTION 'Retired relation % is not empty; archive/review it before schema cleanup',
                    relation_name;
            END IF;
        END IF;
    END LOOP;
    -- A stale materialized projection may retain rows even after its source
    -- tables were emptied. The locked source tables prevent a concurrent refresh.
    relation_id := to_regclass('public_procurement.procurement_entity_search_index');
    IF relation_id IS NOT NULL THEN
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s LIMIT 1)', relation_id)
            INTO populated;
        IF populated THEN
            RAISE EXCEPTION 'Retired materialized view % is not empty; archive/review it before schema cleanup',
                relation_id;
        END IF;
    END IF;
END $$;

DROP VIEW IF EXISTS
    public_procurement.runtime_asset_collection_status,
    public_procurement.runtime_bid_awards,
    public_procurement.runtime_bid_notices,
    public_procurement.runtime_bid_notices_base,
    public_procurement.runtime_bid_notices_without_current_status,
    public_procurement.runtime_bid_opening_collection_status,
    public_procurement.runtime_bid_opening_participants,
    public_procurement.runtime_bid_participation_finding_evidence,
    public_procurement.runtime_bid_participation_findings,
    public_procurement.runtime_bid_requirement_evidence,
    public_procurement.runtime_bid_requirement_sets,
    public_procurement.runtime_bid_requirements,
    public_procurement.runtime_contracts
RESTRICT;

DROP MATERIALIZED VIEW IF EXISTS public_procurement.procurement_entity_search_index RESTRICT;
DROP FUNCTION IF EXISTS public_procurement.refresh_procurement_entity_search_index() RESTRICT;
DROP FUNCTION IF EXISTS public_procurement.refresh_contract_event_company_ledger(text) RESTRICT;

DROP TABLE IF EXISTS
    ingestion.bid_notice_outcome_collection_status,
    ingestion.bid_notice_requirement_collection_status,
    ingestion.bid_opening_collection_status,
    ingestion.bid_opening_enrichment_queue,
    ingestion.contract_event_ledger_refresh_queue,
    ingestion.contract_event_ledger_refresh_status,
    public_procurement.bid_awards,
    public_procurement.bid_document_purge_runs,
    public_procurement.bid_eligibility_extractions,
    public_procurement.bid_eligibility_requirement_evidence,
    public_procurement.bid_eligibility_requirement_proof_evidence,
    public_procurement.bid_eligibility_requirement_proofs,
    public_procurement.bid_eligibility_requirement_sets,
    public_procurement.bid_eligibility_requirements,
    public_procurement.bid_notice_documents,
    public_procurement.bid_notice_license_restrictions,
    public_procurement.bid_notice_outcomes,
    public_procurement.bid_notice_participation_regions,
    public_procurement.bid_opening_participants,
    public_procurement.bid_participation_finding_evidence,
    public_procurement.bid_participation_findings,
    public_procurement.contract_demand_organizations,
    public_procurement.contract_event_company_ledger,
    public_procurement.contract_suppliers,
    public_procurement.contracts,
    public_procurement.procurement_industries,
    public_procurement.public_organizations
RESTRICT;
