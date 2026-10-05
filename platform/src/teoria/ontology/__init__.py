"""Business Ontology v2 domain model.

These definitions are independent of OpenMetadata entities and runtime response DTOs.
"""

from teoria.ontology.models import (
    BusinessObject,
    BusinessObjectId,
    BusinessRule,
    Metric,
    OntologyProperty,
    OntologyPropertyId,
    OntologyStatus,
    OntologyVersion,
    Relationship,
)

__all__ = [
    "BusinessObject", "BusinessObjectId", "BusinessRule", "Metric",
    "OntologyProperty", "OntologyPropertyId", "OntologyStatus",
    "OntologyVersion", "Relationship",
]
