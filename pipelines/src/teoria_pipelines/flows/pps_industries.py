"""Keep pps-industry-monthly working until its deployment entrypoint is migrated."""

from teoria_pipelines.domains.public_procurement.industries.flows import (
    sync_pps_industries,
)

__all__ = ['sync_pps_industries']
