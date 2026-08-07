"""Thin Prefect flows grouped by data domain."""
from teoria_pipelines.flows.pps_contracts import sync_pps_contract_window, sync_pps_contracts
from teoria_pipelines.flows.pps_bid_notices import sync_pps_bid_documents, sync_pps_bid_notices
from teoria_pipelines.flows.bid_eligibility import parse_pps_bid_documents, extract_pps_bid_eligibility

__all__ = [
    "sync_pps_bid_documents",
    "sync_pps_bid_notices",
    "sync_pps_contract_window",
    "sync_pps_contracts",
    "parse_pps_bid_documents",
    "extract_pps_bid_eligibility",
]
