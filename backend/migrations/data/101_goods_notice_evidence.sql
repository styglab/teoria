-- Goods-only recovery evidence. No collector, download queue or Runtime exposure.
SET LOCAL lock_timeout = '5s';

CREATE TABLE public_procurement.goods_notice_import_batches (
    batch_id uuid PRIMARY KEY,
    backup_label text NOT NULL CHECK (backup_label <> ''),
    archive_sha256 text NOT NULL CHECK (archive_sha256 ~ '^[0-9a-f]{64}$'),
    subset_sha256 text NOT NULL UNIQUE CHECK (subset_sha256 ~ '^[0-9a-f]{64}$'),
    notice_count bigint NOT NULL CHECK (notice_count >= 0),
    attachment_count bigint NOT NULL CHECK (attachment_count >= 0),
    recorded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public_procurement.goods_notice_versions (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    source_record_hash text NOT NULL CHECK (source_record_hash ~ '^[0-9a-f]{64}$'),
    source_payload jsonb NOT NULL CHECK (jsonb_typeof(source_payload) = 'object'),
    PRIMARY KEY (notice_number, notice_order, source_record_hash),
    FOREIGN KEY (notice_number, notice_order)
        REFERENCES public_procurement.bid_notices (notice_number, notice_order),
    CHECK ((source_payload->>'bidNtceNo') IS NOT DISTINCT FROM notice_number),
    CHECK ((source_payload->>'bidNtceOrd') IS NOT DISTINCT FROM notice_order)
);

CREATE TABLE public_procurement.goods_notice_observations (
    observation_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    source_record_hash text NOT NULL,
    observation_kind text NOT NULL CHECK (observation_kind IN ('backup_import', 'api_fetch')),
    import_batch_id uuid REFERENCES public_procurement.goods_notice_import_batches (batch_id),
    execution_id uuid REFERENCES ingestion.pipeline_runs (execution_id),
    source_observed_at timestamptz,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (notice_number, notice_order, source_record_hash)
        REFERENCES public_procurement.goods_notice_versions
            (notice_number, notice_order, source_record_hash),
    UNIQUE (import_batch_id, notice_number, notice_order, source_record_hash),
    UNIQUE (execution_id, notice_number, notice_order, source_record_hash),
    CHECK (
        (observation_kind = 'backup_import' AND import_batch_id IS NOT NULL
            AND execution_id IS NULL AND source_observed_at IS NULL)
        OR (observation_kind = 'api_fetch' AND import_batch_id IS NULL
            AND execution_id IS NOT NULL AND source_observed_at IS NOT NULL)
    )
);
CREATE INDEX goods_notice_observations_history_idx
    ON public_procurement.goods_notice_observations
        (notice_number, notice_order, recorded_at, observation_id);

CREATE TABLE public_procurement.goods_notice_attachment_refs (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    source_record_hash text NOT NULL,
    document_slot smallint NOT NULL CHECK (document_slot BETWEEN 1 AND 10),
    source_url text NOT NULL CHECK (btrim(source_url) <> ''),
    file_name text,
    PRIMARY KEY (notice_number, notice_order, source_record_hash, document_slot),
    FOREIGN KEY (notice_number, notice_order, source_record_hash)
        REFERENCES public_procurement.goods_notice_versions
            (notice_number, notice_order, source_record_hash)
);

CREATE FUNCTION public_procurement.check_goods_notice_version_parent()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM 1 FROM public_procurement.bid_notices
    WHERE notice_number = NEW.notice_number AND notice_order = NEW.notice_order
        AND work_type = 'goods' FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Goods evidence requires a goods notice parent';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER goods_notice_versions_require_goods
BEFORE INSERT ON public_procurement.goods_notice_versions
FOR EACH ROW EXECUTE FUNCTION public_procurement.check_goods_notice_version_parent();

CREATE FUNCTION public_procurement.reject_goods_notice_evidence_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Goods notice evidence is append-only';
END $$;

CREATE TRIGGER goods_notice_versions_immutable
BEFORE UPDATE OR DELETE ON public_procurement.goods_notice_versions
FOR EACH ROW EXECUTE FUNCTION public_procurement.reject_goods_notice_evidence_mutation();
CREATE TRIGGER goods_notice_observations_immutable
BEFORE UPDATE OR DELETE ON public_procurement.goods_notice_observations
FOR EACH ROW EXECUTE FUNCTION public_procurement.reject_goods_notice_evidence_mutation();
CREATE TRIGGER goods_notice_attachment_refs_immutable
BEFORE UPDATE OR DELETE ON public_procurement.goods_notice_attachment_refs
FOR EACH ROW EXECUTE FUNCTION public_procurement.reject_goods_notice_evidence_mutation();
CREATE TRIGGER goods_notice_import_batches_immutable
BEFORE UPDATE OR DELETE ON public_procurement.goods_notice_import_batches
FOR EACH ROW EXECUTE FUNCTION public_procurement.reject_goods_notice_evidence_mutation();

COMMENT ON TABLE public_procurement.goods_notice_versions IS
    'Immutable hash-addressed goods notice payload versions; no inferred past revisions.';
COMMENT ON TABLE public_procurement.goods_notice_observations IS
    'Recorded recovery evidence or actual API observations; backup imports have no invented fetch time.';
COMMENT ON TABLE public_procurement.goods_notice_attachment_refs IS
    'Original URL and filename per payload version and slot; existence does not imply download success.';
