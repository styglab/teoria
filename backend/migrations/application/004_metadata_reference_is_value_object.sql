ALTER TABLE binding.metadata_references RENAME TO metadata_targets;
ALTER TABLE binding.metadata_targets
    RENAME COLUMN metadata_reference_id TO metadata_target_id;
ALTER TABLE binding.metadata_targets
    RENAME COLUMN provider TO system;
ALTER TABLE binding.ontology_bindings
    RENAME COLUMN metadata_reference_id TO metadata_target_id;

COMMENT ON TABLE binding.metadata_targets IS
    'Non-authoritative value references to external OpenMetadata entities. This table is not a metadata cache or catalog.';
COMMENT ON COLUMN binding.metadata_targets.external_entity_id IS
    'Stable identifier owned by OpenMetadata; Teoria does not own or reproduce the referenced entity.';
