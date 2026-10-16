"""Runtime evaluation of ontology-backed assessment objects."""

from teoria.domains.public_procurement.bid_eligibility.assessment import (
    execute_bid_eligibility_assessment,
    execute_bid_eligibility_assessments,
)

__all__ = ["execute_bid_eligibility_assessment", "execute_bid_eligibility_assessments"]
