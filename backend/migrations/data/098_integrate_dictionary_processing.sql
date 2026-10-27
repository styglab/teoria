-- Classification is optional for source-only processing in the original two modes.
-- The historical dictionary_authoring row and migration remain audit history;
-- the active request contract no longer accepts that mode.
ALTER TABLE public_procurement.specification_processing_runs
    DROP CONSTRAINT specification_processing_runs_classification_scope_check;
ALTER TABLE public_procurement.specification_processing_runs
    ADD CONSTRAINT specification_processing_runs_classification_scope_check
    CHECK (classification_code IS NULL OR classification_code ~ '^[0-9]{10}$');
