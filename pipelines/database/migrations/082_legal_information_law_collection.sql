CREATE SCHEMA legal_information;

-- Payload bytes retain the provider XML, with authentication echoes redacted.
CREATE TABLE ingestion.law_raw_payloads (
    operation_id text NOT NULL CHECK (operation_id IN ('list_law_versions', 'get_law_version')),
    source_record_hash text NOT NULL,
    content_type text NOT NULL,
    payload bytea NOT NULL,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    PRIMARY KEY (operation_id, source_record_hash)
);
CREATE TABLE ingestion.law_raw_observations (
    execution_id uuid NOT NULL REFERENCES ingestion.pipeline_runs(execution_id),
    operation_id text NOT NULL,
    source_record_hash text NOT NULL,
    request_hash text NOT NULL,
    request_parameters jsonb NOT NULL,
    fetched_at timestamptz NOT NULL,
    PRIMARY KEY (execution_id, operation_id, source_record_hash, request_hash),
    FOREIGN KEY (operation_id, source_record_hash)
        REFERENCES ingestion.law_raw_payloads(operation_id, source_record_hash)
);

CREATE TABLE legal_information.law (
    law_id text PRIMARY KEY,
    target_id text UNIQUE NOT NULL,
    target_name text NOT NULL,
    first_seen_at timestamptz NOT NULL DEFAULT now(),
    last_catalog_at timestamptz,
    catalog_version_count integer CHECK (catalog_version_count > 0)
);
CREATE TABLE legal_information.law_version (
    law_id text NOT NULL REFERENCES legal_information.law(law_id),
    mst text NOT NULL,
    effective_date date NOT NULL,
    name text NOT NULL,
    promulgation_date date NOT NULL,
    promulgation_number text NOT NULL,
    amendment_type text NOT NULL,
    listing jsonb NOT NULL,
    listing_hash text NOT NULL,
    latest_snapshot_id uuid,
    PRIMARY KEY (law_id, mst, effective_date)
);
CREATE INDEX law_version_effective_idx
    ON legal_information.law_version(law_id, effective_date DESC);
CREATE TABLE legal_information.law_snapshot (
    snapshot_id uuid PRIMARY KEY,
    law_id text NOT NULL,
    mst text NOT NULL,
    effective_date date NOT NULL,
    source_record_hash text NOT NULL,
    operation_id text NOT NULL DEFAULT 'get_law_version' CHECK (operation_id = 'get_law_version'),
    parser_version text NOT NULL,
    source_metadata jsonb NOT NULL,
    listing jsonb NOT NULL,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    UNIQUE (law_id, mst, effective_date, source_record_hash, parser_version),
    UNIQUE (snapshot_id, law_id, mst, effective_date),
    FOREIGN KEY (law_id, mst, effective_date)
        REFERENCES legal_information.law_version(law_id, mst, effective_date),
    FOREIGN KEY (operation_id, source_record_hash)
        REFERENCES ingestion.law_raw_payloads(operation_id, source_record_hash)
);
ALTER TABLE legal_information.law_version
    ADD FOREIGN KEY (latest_snapshot_id, law_id, mst, effective_date)
    REFERENCES legal_information.law_snapshot(snapshot_id, law_id, mst, effective_date);

CREATE TABLE legal_information.law_provision (
    snapshot_id uuid NOT NULL REFERENCES legal_information.law_snapshot(snapshot_id),
    path text NOT NULL,
    parent_path text,
    kind text NOT NULL CHECK (kind IN ('heading','article','paragraph','subparagraph','item','addendum')),
    number text NOT NULL,
    title text NOT NULL,
    content text NOT NULL,
    effective_date date,
    source_xml text NOT NULL,
    PRIMARY KEY (snapshot_id, path),
    FOREIGN KEY (snapshot_id, parent_path) REFERENCES legal_information.law_provision(snapshot_id, path)
);
CREATE INDEX law_provision_number_idx ON legal_information.law_provision(snapshot_id, kind, number);
CREATE TABLE legal_information.law_attachment (
    snapshot_id uuid NOT NULL REFERENCES legal_information.law_snapshot(snapshot_id),
    path text NOT NULL,
    number text NOT NULL,
    branch text NOT NULL,
    kind text NOT NULL,
    title text NOT NULL,
    source_xml text NOT NULL,
    PRIMARY KEY (snapshot_id, path)
);
CREATE TABLE legal_information.law_collection_run (
    execution_id uuid PRIMARY KEY REFERENCES ingestion.pipeline_runs(execution_id),
    reconcile_all boolean NOT NULL,
    target_count integer NOT NULL,
    catalog_version_count integer NOT NULL DEFAULT 0,
    collected_version_count integer NOT NULL DEFAULT 0,
    provision_count integer NOT NULL DEFAULT 0,
    failed_targets jsonb NOT NULL DEFAULT '[]'::jsonb
);
-- No Runtime grant: a Database Source read contract will be introduced only
-- when Runtime consumes legal data. Pipeline migrations own this schema.
