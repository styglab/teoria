ALTER TABLE binding.ontology_bindings
    DROP CONSTRAINT ontology_bindings_status_check;

ALTER TABLE binding.ontology_bindings
    ADD CONSTRAINT ontology_bindings_status_check
    CHECK (status IN ('draft','approved','rejected','deprecated'));

CREATE TABLE binding.binding_reviews (
    binding_review_id uuid PRIMARY KEY,
    binding_id uuid NOT NULL REFERENCES binding.ontology_bindings(binding_id) ON DELETE CASCADE,
    decision text NOT NULL CHECK (decision IN ('approve','reject','deprecate')),
    reviewer text NOT NULL,
    comment text,
    reviewed_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX binding_reviews_binding_idx
    ON binding.binding_reviews (binding_id, reviewed_at DESC);

CREATE UNIQUE INDEX one_active_binding_per_target
    ON binding.ontology_bindings (ontology_ref_type, ontology_ref_id, target_type, target_locator)
    WHERE status IN ('draft','approved');

