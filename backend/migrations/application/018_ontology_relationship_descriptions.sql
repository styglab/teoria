-- Preserve durable relationship meaning during authoring, cloning and publishing.
-- Previously published JSON artifacts remain immutable.
ALTER TABLE ontology.relationship_types
  ADD COLUMN description text NOT NULL DEFAULT '';
