"""Business Ontology v2 domain model.

These definitions are independent of OpenMetadata entities and runtime response DTOs.
"""

from teoria.features.semantic_modeling.ontology.models import (
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
