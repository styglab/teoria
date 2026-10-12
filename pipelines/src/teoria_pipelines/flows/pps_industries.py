"""Compatibility imports for existing Prefect deployment entrypoints."""

from teoria_pipelines.domains.public_procurement.industries.flows import (
    sync_pps_industries,
)

__all__ = ['sync_pps_industries']
