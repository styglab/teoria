-- Keep legacy definitions/mappings and frozen results intact. New links reference
-- published Ontology concepts; this table never stores another business definition.
ALTER TABLE ontology.object_properties
    ADD COLUMN quantity_dimension text,
    ADD COLUMN allowed_units jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(allowed_units) = 'array');

CREATE TABLE goods.dictionary_ontology_mappings (
    mapping_id uuid PRIMARY KEY,
    source_entry_id uuid NOT NULL REFERENCES goods.dictionary_entries(entry_id),
    ontology_version_id uuid NOT NULL REFERENCES ontology.ontology_versions(ontology_version_id),
    ontology_checksum text NOT NULL CHECK (ontology_checksum ~ '^[a-f0-9]{64}$'),
    target_concept_id uuid NOT NULL REFERENCES ontology.concepts(concept_id),
    owner_concept_id uuid REFERENCES ontology.concepts(concept_id),
    classification_code text CHECK (classification_code IS NULL OR classification_code ~ '^[0-9]{10}$'),
    scope_mode text NOT NULL CHECK (scope_mode IN ('classified','unclassified','independent')),
    relation text NOT NULL CHECK (relation IN ('equivalent','related')),
    status text NOT NULL CHECK (status IN ('draft','approved','rejected','deprecated')),
    rationale text NOT NULL,
    evidence jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK ((scope_mode = 'classified') = (classification_code IS NOT NULL))
);
CREATE INDEX dictionary_ontology_mapping_source_idx
    ON goods.dictionary_ontology_mappings(source_entry_id, status);
