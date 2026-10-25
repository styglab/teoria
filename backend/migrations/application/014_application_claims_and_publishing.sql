-- Never silently resolve conflicting publication history.
CREATE UNIQUE INDEX ontology_single_published_version_idx
    ON ontology.ontology_versions (ontology_id) WHERE status = 'published';

ALTER TABLE intelligence.change_applications
    ADD COLUMN claim_token uuid,
    ADD COLUMN lease_until timestamptz,
    ADD COLUMN effect_started_at timestamptz,
    ADD COLUMN effect_succeeded_at timestamptz,
    ADD COLUMN attempts integer NOT NULL DEFAULT 0;

-- Existing interrupted/failed applications may already have changed their target.
UPDATE intelligence.change_applications
   SET effect_started_at = COALESCE(attempted_at, now())
 WHERE status IN ('applying', 'failed');

CREATE TABLE intelligence.application_attempts (
    attempt_id uuid PRIMARY KEY,
    change_application_id uuid NOT NULL REFERENCES intelligence.change_applications(change_application_id),
    actor text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    outcome text CHECK (outcome IN ('applied', 'failed', 'superseded', 'reconciled')),
    error_code text
);
