ALTER TABLE public_procurement.bid_notices
    ADD COLUMN IF NOT EXISTS procurement_classification_number text,
    ADD COLUMN IF NOT EXISTS procurement_classification_name text,
    ADD COLUMN IF NOT EXISTS procurement_large_classification_name text,
    ADD COLUMN IF NOT EXISTS procurement_middle_classification_name text,
    ADD COLUMN IF NOT EXISTS purchase_items jsonb;

UPDATE public_procurement.bid_notices
SET procurement_classification_number = NULLIF(source_payload->>'pubPrcrmntClsfcNo', ''),
    procurement_classification_name = NULLIF(source_payload->>'pubPrcrmntClsfcNm', ''),
    procurement_large_classification_name = NULLIF(source_payload->>'pubPrcrmntLrgClsfcNm', ''),
    procurement_middle_classification_name = NULLIF(source_payload->>'pubPrcrmntMidClsfcNm', ''),
    purchase_items = CASE
        WHEN NULLIF(source_payload->>'purchsObjPrdctList', '') IS NULL THEN NULL
        ELSE (
            SELECT jsonb_agg(jsonb_build_object(
                'sequence', NULLIF(split_part(item, '^', 1), ''),
                'code', NULLIF(split_part(item, '^', 2), ''),
                'name', NULLIF(regexp_replace(item, '^[^^]*\^[^^]*\^', ''), '')
            ))
            FROM regexp_split_to_table(
                trim(both '[]' FROM source_payload->>'purchsObjPrdctList'),
                '\s*,\s*'
            ) AS item
        )
    END
WHERE procurement_classification_number IS NULL
   OR procurement_classification_name IS NULL
   OR procurement_large_classification_name IS NULL
   OR procurement_middle_classification_name IS NULL
   OR purchase_items IS NULL;

CREATE INDEX IF NOT EXISTS bid_notices_procurement_classification_idx
    ON public_procurement.bid_notices (
        procurement_classification_number, notice_published_at DESC
    )
    WHERE procurement_classification_number IS NOT NULL;
