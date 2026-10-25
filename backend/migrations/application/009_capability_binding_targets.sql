CREATE TABLE binding.capability_targets (
    capability_target_id uuid PRIMARY KEY,
    capability_id text NOT NULL,
    target_scope text NOT NULL CHECK (target_scope IN ('capability','input','output')),
    field_path text,
    contract_version text,
    registry_version text NOT NULL,
    last_verified_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (capability_id, target_scope, field_path, contract_version)
);

ALTER TABLE binding.ontology_bindings
    ADD COLUMN capability_target_id uuid REFERENCES binding.capability_targets(capability_target_id);

ALTER TABLE binding.ontology_bindings
    ADD CONSTRAINT ontology_binding_target_reference CHECK (
        (target_type IN ('glossary_term','data_asset') AND metadata_target_id IS NOT NULL AND capability_target_id IS NULL)
        OR
        (target_type IN ('capability','capability_input','capability_output') AND capability_target_id IS NOT NULL AND metadata_target_id IS NULL)
        OR
        (target_type = 'api_field' AND metadata_target_id IS NULL AND capability_target_id IS NULL)
    ) NOT VALID;

CREATE INDEX capability_targets_capability_idx
    ON binding.capability_targets (capability_id, target_scope);
