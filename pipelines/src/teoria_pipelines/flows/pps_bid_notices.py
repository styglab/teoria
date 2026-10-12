"""Compatibility imports for existing Prefect deployment entrypoints."""

from teoria_pipelines.domains.public_procurement.bid_notices.flows import (
    sync_pps_bid_notice_window,
    sync_pps_bid_notices,
    sync_pps_bid_notice_backfill,
    sync_pps_bid_notice_enrichment_backfill,
    sync_pps_bid_documents,
    purge_expired_pps_bid_documents,
)

__all__ = ['sync_pps_bid_notice_window', 'sync_pps_bid_notices', 'sync_pps_bid_notice_backfill', 'sync_pps_bid_notice_enrichment_backfill', 'sync_pps_bid_documents', 'purge_expired_pps_bid_documents']
