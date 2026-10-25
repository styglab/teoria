CREATE TABLE binding.api_field_targets (
    api_field_target_id uuid PRIMARY KEY,
    source_id text NOT NULL,
    operation_id text NOT NULL,
    object_id text NOT NULL,
    field_path text NOT NULL,
    contract_version text,
    registry_version text NOT NULL,
    last_verified_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, operation_id, object_id, field_path, contract_version)
);

ALTER TABLE binding.ontology_bindings
    ADD COLUMN api_field_target_id uuid REFERENCES binding.api_field_targets(api_field_target_id);

ALTER TABLE binding.ontology_bindings
    DROP CONSTRAINT ontology_binding_target_reference;

ALTER TABLE binding.ontology_bindings
    ADD CONSTRAINT ontology_binding_target_reference CHECK (
        (target_type IN ('glossary_term','data_asset')
            AND metadata_target_id IS NOT NULL
            AND capability_target_id IS NULL
            AND api_field_target_id IS NULL)
        OR
        (target_type IN ('capability','capability_input','capability_output')
            AND capability_target_id IS NOT NULL
            AND metadata_target_id IS NULL
            AND api_field_target_id IS NULL)
        OR
        (target_type = 'api_field'
            AND api_field_target_id IS NOT NULL
            AND metadata_target_id IS NULL
            AND capability_target_id IS NULL)
    );

CREATE INDEX api_field_targets_source_operation_idx
    ON binding.api_field_targets (source_id, operation_id);
