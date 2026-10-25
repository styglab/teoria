ALTER TABLE intelligence.suggestions
    ADD COLUMN submitted_by text NOT NULL DEFAULT 'system:legacy';

ALTER TABLE intelligence.suggestions
    ALTER COLUMN submitted_by DROP DEFAULT;
