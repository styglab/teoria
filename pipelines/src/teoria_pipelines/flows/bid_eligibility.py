"""Compatibility imports for existing Prefect deployment entrypoints."""

from teoria_pipelines.domains.public_procurement.bid_eligibility.flows import (
    parse_pps_bid_documents,
    extract_pps_bid_eligibility,
)

__all__ = ['parse_pps_bid_documents', 'extract_pps_bid_eligibility']
