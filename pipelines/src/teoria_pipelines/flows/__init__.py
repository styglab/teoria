"""Thin Prefect flows grouped by data domain."""
from teoria_pipelines.flows.openmetadata import sync_openmetadata_postgres
from teoria_pipelines.flows.pps_contracts import (
    refresh_pps_contract_event_ledger,
    retry_pps_contract_backfill_gaps,
    sync_pps_contract_window,
    sync_pps_contracts,
)
from teoria_pipelines.flows.pps_bid_results import (
    enrich_pps_bid_opening_participants,
    sync_pps_bid_result_window,
    sync_pps_bid_results_backfill,
    sync_pps_bid_results_incremental,
)
from teoria_pipelines.flows.pps_bid_notices import (
    sync_pps_bid_documents,
    sync_pps_bid_notice_backfill,
    sync_pps_bid_notice_enrichment_backfill,
    sync_pps_bid_notice_window,
    sync_pps_bid_notices,
)
from teoria_pipelines.flows.bid_eligibility import parse_pps_bid_documents, extract_pps_bid_eligibility

__all__ = [
    "sync_openmetadata_postgres",
    "sync_pps_bid_documents",
    "sync_pps_bid_notices",
    "sync_pps_bid_notice_window",
    "sync_pps_bid_notice_backfill",
    "sync_pps_bid_notice_enrichment_backfill",
    "sync_pps_contract_window",
    "sync_pps_contracts",
    "retry_pps_contract_backfill_gaps",
    "refresh_pps_contract_event_ledger",
    "sync_pps_bid_result_window",
    "sync_pps_bid_results_backfill",
    "enrich_pps_bid_opening_participants",
    "sync_pps_bid_results_incremental",
    "parse_pps_bid_documents",
    "extract_pps_bid_eligibility",
]
