-- The common execution model only records raw_record_count. Retired
-- procurement counters and the unused operation-progress table are not used
-- by active flows. Refuse to discard any recorded progress or nonzero counters.
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE
    retired_column text;
    populated boolean;
BEGIN
    LOCK TABLE ingestion.pipeline_runs IN ACCESS EXCLUSIVE MODE;
    IF to_regclass('ingestion.pipeline_operation_progress') IS NOT NULL THEN
        LOCK TABLE ingestion.pipeline_operation_progress IN ACCESS EXCLUSIVE MODE;
        SELECT EXISTS (SELECT 1 FROM ingestion.pipeline_operation_progress)
            INTO populated;
        IF populated THEN
            RAISE EXCEPTION 'Operation progress is not empty; archive/review it before cleanup';
        END IF;
    END IF;

    FOREACH retired_column IN ARRAY ARRAY[
        'contract_count', 'notice_count', 'document_count', 'award_count',
        'opening_participant_count', 'notice_outcome_count'
    ] LOOP
        IF EXISTS (
            SELECT 1 FROM pg_attribute
            WHERE attrelid = 'ingestion.pipeline_runs'::regclass
              AND attname = retired_column AND NOT attisdropped
        ) THEN
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM ingestion.pipeline_runs WHERE %I IS DISTINCT FROM 0)',
                retired_column
            ) INTO populated;
            IF populated THEN
                RAISE EXCEPTION 'Legacy counter % contains information; archive/review it before cleanup',
                    retired_column;
            END IF;
        END IF;
    END LOOP;
END $$;

DROP TABLE IF EXISTS ingestion.pipeline_operation_progress RESTRICT;
ALTER TABLE ingestion.pipeline_runs
    DROP COLUMN IF EXISTS contract_count RESTRICT,
    DROP COLUMN IF EXISTS notice_count RESTRICT,
    DROP COLUMN IF EXISTS document_count RESTRICT,
    DROP COLUMN IF EXISTS award_count RESTRICT,
    DROP COLUMN IF EXISTS opening_participant_count RESTRICT,
    DROP COLUMN IF EXISTS notice_outcome_count RESTRICT;
