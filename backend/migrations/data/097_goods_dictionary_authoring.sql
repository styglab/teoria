ALTER TABLE public_procurement.specification_processing_runs
    ALTER COLUMN classification_code DROP NOT NULL;
ALTER TABLE public_procurement.specification_processing_runs
    DROP CONSTRAINT specification_processing_runs_mode_check;
ALTER TABLE public_procurement.specification_processing_runs
    ADD CONSTRAINT specification_processing_runs_mode_check
    CHECK (mode IN ('standard_management','document_processing','dictionary_authoring'));
ALTER TABLE public_procurement.specification_processing_runs
    ADD CONSTRAINT specification_processing_runs_classification_scope_check
    CHECK (mode = 'dictionary_authoring' OR
           (classification_code IS NOT NULL AND classification_code ~ '^[0-9]{10}$'));
