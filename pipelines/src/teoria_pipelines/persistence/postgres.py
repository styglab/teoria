"""Public facade for the domain-split PostgreSQL persistence store."""

from teoria_pipelines.persistence.postgres_store import (
    BasePostgresStore,
    BidResultStoreMixin,
    ContractStoreMixin,
    DocumentStoreMixin,
    EligibilityStoreMixin,
)
from teoria_pipelines.persistence.postgres_store.support import (
    _filter_covered_unavailable_documents,
    _sanitize_postgres_value,
    _validate_industry_snapshot,
    eligibility_requires_review,
)


class PostgresStore(
    ContractStoreMixin,
    BidResultStoreMixin,
    DocumentStoreMixin,
    EligibilityStoreMixin,
    BasePostgresStore,
):
    """Data DB writer composed from domain-specific persistence mixins."""


__all__ = [
    "PostgresStore",
    "_filter_covered_unavailable_documents",
    "_sanitize_postgres_value",
    "_validate_industry_snapshot",
    "eligibility_requires_review",
]
