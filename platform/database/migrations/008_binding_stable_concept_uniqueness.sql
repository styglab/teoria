DROP INDEX binding.one_active_binding_per_target;

CREATE UNIQUE INDEX one_active_binding_per_stable_concept_target
    ON binding.ontology_bindings (
        ontology_concept_id,
        target_type,
        target_locator
    )
    WHERE status IN ('draft','approved');

COMMENT ON INDEX binding.one_active_binding_per_stable_concept_target IS
    'Prevents duplicate active semantic bindings across ontology revisions.';
