CREATE TABLE public_procurement.contract_event_company_ledger (
    organization_code text NOT NULL,
    organization_name text,
    contract_event_id text NOT NULL,
    unified_contract_number text NOT NULL,
    contract_name text,
    first_contract_date date NOT NULL,
    latest_contract_version_date date NOT NULL,
    contract_version_count integer NOT NULL,
    work_type text NOT NULL,
    field_code text NOT NULL,
    field_name text,
    large_category text,
    middle_category text,
    company_number text NOT NULL,
    company_name text,
    company_role text,
    share_percent numeric,
    attributed_contract_amount numeric,
    amount_completeness text NOT NULL,
    contract_amount numeric,
    normalized_notice_number text,
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_code, contract_event_id, company_number)
);

CREATE INDEX contract_event_company_ledger_scope_idx
    ON public_procurement.contract_event_company_ledger (
        work_type, field_code, first_contract_date, organization_code
    );

CREATE INDEX contract_event_company_ledger_company_idx
    ON public_procurement.contract_event_company_ledger (
        organization_code, company_number, field_code, first_contract_date
    );

CREATE TABLE ingestion.contract_event_ledger_refresh_status (
    field_code text PRIMARY KEY,
    refreshed_at timestamptz NOT NULL,
    row_count bigint NOT NULL,
    source_max_updated_at timestamptz
);

CREATE OR REPLACE FUNCTION public_procurement.refresh_contract_event_company_ledger(
    requested_field_code text
) RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public_procurement, ingestion, public
AS $$
DECLARE
    loaded bigint;
BEGIN
    IF requested_field_code IS NULL OR btrim(requested_field_code) = '' THEN
        RAISE EXCEPTION 'field_code is required for an incremental ledger refresh';
    END IF;

    CREATE TEMP TABLE refreshed_contract_events ON COMMIT DROP AS
    WITH versions AS MATERIALIZED (
        SELECT d.organization_code, c.*,
               COALESCE(NULLIF(c.confirmed_contract_number, ''),
                        NULLIF(c.contract_reference_number, ''),
                        c.unified_contract_number) AS event_id,
               CASE WHEN c.notice_number ~ '^[0-9]{13}$' AND right(c.notice_number, 2) = '00'
                    THEN left(c.notice_number, length(c.notice_number) - 2)
                    ELSE NULLIF(c.notice_number, '') END AS normalized_notice
        FROM public_procurement.contracts c
        JOIN public_procurement.contract_demand_organizations d
          USING (unified_contract_number)
        WHERE c.procurement_classification_number = requested_field_code
    ), event_groups AS (
        SELECT organization_code, event_id,
               min(concluded_date) AS first_contract_date,
               max(concluded_date) AS latest_contract_version_date,
               count(DISTINCT unified_contract_number)::integer AS contract_version_count
        FROM versions
        GROUP BY organization_code, event_id
    ), latest AS (
        SELECT DISTINCT ON (v.organization_code, v.event_id)
               v.*, g.first_contract_date, g.latest_contract_version_date,
               g.contract_version_count
        FROM versions v
        JOIN event_groups g USING (organization_code, event_id)
        ORDER BY v.organization_code, v.event_id, v.concluded_date DESC,
                 v.updated_at DESC, v.unified_contract_number DESC
    ), supplier_counts AS (
        SELECT s.unified_contract_number, count(*)::integer AS supplier_count
        FROM public_procurement.contract_suppliers s
        JOIN (SELECT DISTINCT unified_contract_number FROM latest) scope
          USING (unified_contract_number)
        GROUP BY s.unified_contract_number
    ), classification AS (
        SELECT DISTINCT ON (procurement_classification_number)
               procurement_classification_number,
               procurement_large_classification_name AS large_category,
               procurement_middle_classification_name AS middle_category
        FROM public_procurement.bid_notices
        WHERE procurement_classification_number = requested_field_code
        ORDER BY procurement_classification_number, notice_published_at DESC
    )
    SELECT l.organization_code, o.organization_name, l.event_id AS contract_event_id,
           l.unified_contract_number, l.contract_name, l.first_contract_date,
           l.latest_contract_version_date, l.contract_version_count,
           CASE WHEN l.contract_type = 'foreign_procurement' THEN 'foreign'
                ELSE l.contract_type END AS work_type,
           l.procurement_classification_number AS field_code,
           l.procurement_classification_name AS field_name,
           CASE WHEN l.contract_type = 'construction' THEN l.procurement_classification_name
                ELSE cls.large_category END AS large_category,
           CASE WHEN l.contract_type = 'construction' THEN NULL
                ELSE cls.middle_category END AS middle_category,
           s.business_registration_number AS company_number, s.supplier_name AS company_name,
           s.supplier_role_name AS company_role, s.participation_share_rate AS share_percent,
           CASE WHEN COALESCE(l.current_contract_amount_currency, 'KRW') <> 'KRW'
                     OR l.current_contract_amount IS NULL THEN NULL
                WHEN s.participation_share_rate IS NOT NULL
                  THEN l.current_contract_amount * s.participation_share_rate / 100
                WHEN counts.supplier_count = 1 THEN l.current_contract_amount END
             AS attributed_contract_amount,
           CASE WHEN COALESCE(l.current_contract_amount_currency, 'KRW') <> 'KRW'
                     OR l.current_contract_amount IS NULL THEN 'unknown'
                WHEN s.participation_share_rate IS NOT NULL OR counts.supplier_count = 1
                  THEN 'complete' ELSE 'partial' END AS amount_completeness,
           l.current_contract_amount AS contract_amount,
           l.normalized_notice AS normalized_notice_number,
           now() AS refreshed_at
    FROM latest l
    JOIN public_procurement.contract_suppliers s USING (unified_contract_number)
    JOIN supplier_counts counts USING (unified_contract_number)
    LEFT JOIN public_procurement.public_organizations o USING (organization_code)
    LEFT JOIN classification cls
      ON cls.procurement_classification_number = l.procurement_classification_number
    WHERE s.business_registration_number IS NOT NULL;

    DELETE FROM public_procurement.contract_event_company_ledger
    WHERE field_code = requested_field_code;

    INSERT INTO public_procurement.contract_event_company_ledger
    SELECT * FROM refreshed_contract_events;
    GET DIAGNOSTICS loaded = ROW_COUNT;

    INSERT INTO ingestion.contract_event_ledger_refresh_status (
        field_code, refreshed_at, row_count, source_max_updated_at
    ) VALUES (
        requested_field_code, now(), loaded,
        (SELECT max(updated_at) FROM public_procurement.contracts
         WHERE procurement_classification_number = requested_field_code)
    ) ON CONFLICT (field_code) DO UPDATE SET
        refreshed_at = EXCLUDED.refreshed_at,
        row_count = EXCLUDED.row_count,
        source_max_updated_at = EXCLUDED.source_max_updated_at;
    RETURN loaded;
END;
$$;

GRANT SELECT ON public_procurement.contract_event_company_ledger TO teoria_runtime;
GRANT SELECT ON ingestion.contract_event_ledger_refresh_status TO teoria_runtime;
GRANT EXECUTE ON FUNCTION public_procurement.refresh_contract_event_company_ledger(text)
    TO teoria_pipeline;
