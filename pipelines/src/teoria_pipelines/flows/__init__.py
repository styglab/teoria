"""Thin Prefect flows grouped by data domain."""
from teoria_pipelines.flows.pps_contracts import sync_pps_contract_window, sync_pps_contracts

__all__ = ["sync_pps_contract_window", "sync_pps_contracts"]
