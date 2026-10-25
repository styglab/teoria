CREATE TABLE public_procurement.procurement_industries (
    industry_code text PRIMARY KEY,
    industry_name text NOT NULL,
    classification_code text NOT NULL,
    classification_name text NOT NULL,
    base_law_name text,
    base_law_article text,
    base_law_url text,
    related_regulation_contents text,
    included_license_text text,
    source_use_yn text,
    source_registered_at timestamptz NOT NULL,
    source_changed_at timestamptz,
    first_seen_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL,
    is_active boolean NOT NULL,
    source_record_hash text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX procurement_industries_name_idx
    ON public_procurement.procurement_industries (industry_name);
