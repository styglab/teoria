"""Pinned authoring definitions for review only; never a publication contract."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from teoria.features.semantic_modeling.ontology.publication_contracts import publication_checksum


class OntologyReviewRef(BaseModel):
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    version_id: UUID
    namespace: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: Literal['draft', 'published']
    content_checksum: str = Field(pattern=r'^[a-f0-9]{64}$')


class OntologyReviewSnapshot(BaseModel):
    """A checksum pins a mutable Draft observation; it grants no execution authority."""
    model_config = ConfigDict(extra='forbid', hide_input_in_errors=True)
    context: OntologyReviewRef
    content: dict

    @model_validator(mode='after')
    def verify_context(self):
        expected = (str(self.context.version_id), self.context.namespace,
                    self.context.version, self.context.status)
        actual = (str(self.content.get('ontology_version_id')), self.content.get('namespace'),
                  self.content.get('version'), self.content.get('status'))
        if actual != expected:
            raise ValueError('ontology_review_identity_mismatch')
        if publication_checksum(self.content) != self.context.content_checksum:
            raise ValueError('ontology_review_content_changed')
        return self

    def concept_catalog(self):
        """Expose Stable Concept owners, keeping revision row IDs inside this owner."""
        catalog = {}
        for obj in self.content['objects']:
            rows = [(obj, 'object', None)] + [
                (prop, 'property', str(obj['concept_id'])) for prop in obj['properties']]
            for row, kind, owner in rows:
                identifier = str(UUID(str(row['concept_id'])))
                if identifier in catalog:
                    raise ValueError('ambiguous_ontology_review_concept')
                catalog[identifier] = {
                    'concept_id': identifier, 'stable_key': row['stable_key'],
                    'kind': kind, 'name': row['name'], 'definition': row.get('description', ''),
                    'owner_concept_id': owner, 'value_type': row.get('value_type'),
                    'unit': row.get('unit'), 'allowed_units': row.get('allowed_units', []),
                }
        return catalog
