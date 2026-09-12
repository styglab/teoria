"""Runtime evaluation of ontology-backed assessment objects."""

from teoria.runtime.assessment.processor import (
    execute_bid_eligibility_assessment,
    execute_bid_eligibility_assessments,
)

__all__ = ["execute_bid_eligibility_assessment", "execute_bid_eligibility_assessments"]
