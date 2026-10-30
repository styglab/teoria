-- Missing classification is not permission to apply a meaning in every classification.
ALTER TABLE goods.concept_mappings ADD COLUMN scope_mode text;
UPDATE goods.concept_mappings SET scope_mode=CASE WHEN classification_code IS NULL THEN 'unclassified' ELSE 'classified' END;
ALTER TABLE goods.concept_mappings ADD CONSTRAINT concept_mapping_scope_mode
 CHECK (scope_mode IS NULL OR (scope_mode='classified' AND classification_code IS NOT NULL)
 OR (scope_mode IN ('unclassified','independent') AND classification_code IS NULL));
