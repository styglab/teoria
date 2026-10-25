ALTER TABLE ingestion.pipeline_runs
    ADD COLUMN notice_count integer NOT NULL DEFAULT 0,
    ADD COLUMN document_count integer NOT NULL DEFAULT 0;

CREATE TABLE public_procurement.bid_notices (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    work_type text NOT NULL CHECK (work_type IN ('construction', 'service', 'foreign', 'goods', 'other')),
    notice_name text,
    notice_kind_name text,
    registration_type_name text,
    is_re_notice boolean,
    notice_published_at timestamptz,
    bid_begin_at timestamptz,
    bid_deadline_at timestamptz,
    opening_at timestamptz,
    notice_organization_code text,
    notice_organization_name text,
    demand_organization_code text,
    demand_organization_name text,
    bid_method_name text,
    contract_method_name text,
    estimated_price numeric,
    allocated_budget numeric,
    detail_url text,
    notice_url text,
    standard_document_url text,
    source_registered_at timestamptz,
    source_changed_at timestamptz,
    source_record_hash text NOT NULL,
    source_payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (notice_number, notice_order)
);

CREATE TABLE public_procurement.bid_notice_license_restrictions (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    restriction_group_number text NOT NULL,
    restriction_sequence text NOT NULL,
    license_restriction_name text,
    permitted_industry_list text,
    industry_main_field_list text,
    business_type_name text,
    source_registered_at timestamptz,
    source_record_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (notice_number, notice_order, restriction_group_number, restriction_sequence),
    FOREIGN KEY (notice_number, notice_order)
        REFERENCES public_procurement.bid_notices(notice_number, notice_order) ON DELETE CASCADE
);

CREATE TABLE public_procurement.bid_notice_participation_regions (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    restriction_sequence text NOT NULL,
    participation_region_name text,
    business_type_name text,
    source_registered_at timestamptz,
    source_record_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (notice_number, notice_order, restriction_sequence),
    FOREIGN KEY (notice_number, notice_order)
        REFERENCES public_procurement.bid_notices(notice_number, notice_order) ON DELETE CASCADE
);

CREATE TABLE public_procurement.bid_notice_documents (
    document_id uuid PRIMARY KEY,
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    document_slot text NOT NULL,
    file_name text,
    source_url text NOT NULL,
    media_type text,
    file_size bigint,
    checksum text,
    object_key text,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'stored', 'unsupported', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    next_retry_at timestamptz NOT NULL DEFAULT now(),
    last_error_code text,
    downloaded_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (notice_number, notice_order, document_slot, source_url),
    FOREIGN KEY (notice_number, notice_order)
        REFERENCES public_procurement.bid_notices(notice_number, notice_order) ON DELETE CASCADE
);

CREATE INDEX bid_notices_deadline_idx
    ON public_procurement.bid_notices (bid_deadline_at);
CREATE INDEX bid_notices_published_idx
    ON public_procurement.bid_notices (notice_published_at DESC);
CREATE INDEX bid_notice_documents_pending_idx
    ON public_procurement.bid_notice_documents (status, next_retry_at, created_at);
