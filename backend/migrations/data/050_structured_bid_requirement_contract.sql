CREATE TABLE ingestion.bid_notice_requirement_collection_status (
    notice_number text NOT NULL,
    notice_order text NOT NULL,
    category text NOT NULL CHECK (category IN ('region', 'industry_license')),
    status text NOT NULL CHECK (status IN ('pending', 'completed', 'failed')),
    record_count integer CHECK (record_count IS NULL OR record_count >= 0),
    execution_id uuid REFERENCES ingestion.pipeline_runs(execution_id),
    error_code text,
    checked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (notice_number, notice_order, category),
    FOREIGN KEY (notice_number, notice_order)
        REFERENCES public_procurement.bid_notices(notice_number, notice_order)
        ON DELETE CASCADE
);

INSERT INTO ingestion.bid_notice_requirement_collection_status (
    notice_number, notice_order, category, status, record_count, checked_at
)
SELECT n.notice_number, n.notice_order, category, 'completed',
       CASE category
           WHEN 'industry_license' THEN (
               SELECT count(*) FROM public_procurement.bid_notice_license_restrictions l
               WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order
           )
           ELSE (
               SELECT count(*) FROM public_procurement.bid_notice_participation_regions r
               WHERE r.notice_number=n.notice_number AND r.notice_order=n.notice_order
           )
       END,
       n.enrichment_checked_at
FROM public_procurement.bid_notices n
CROSS JOIN (VALUES ('region'), ('industry_license')) categories(category)
WHERE n.enrichment_checked_at IS NOT NULL;

CREATE INDEX bid_notice_requirement_collection_status_checked_idx
    ON ingestion.bid_notice_requirement_collection_status (status, checked_at DESC);

CREATE OR REPLACE VIEW public_procurement.runtime_bid_requirements AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number, notice_order, extraction_id
    FROM public_procurement.bid_eligibility_extractions
    WHERE status='completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), extracted AS (
    SELECT
        r.requirement_id::text AS requirement_id,
        r.notice_number || ':' || r.notice_order AS bid_notice_id,
        r.notice_number, r.notice_order, n.notice_name, n.bid_deadline_at,
        r.local_id, r.requirement_type, r.operator, r.value::text AS value_text,
        r.original_text, r.holder_scope, r.reference_date_type, r.mandatory,
        r.review_status, r.confidence,
        string_agg(DISTINCT concat_ws(' | ', e.source_type, e.source_id, d.file_name,
            CASE WHEN e.page_number IS NOT NULL THEN 'page ' || e.page_number END,
            e.section, e.excerpt), E'\n') AS evidence_summary,
        r.assessment_stage, r.failure_effect, r.comparison_mode,
        string_agg(DISTINCT concat_ws(' | ', p.document_type, p.submission_stage,
            p.deadline_text, pe.excerpt), E'\n') AS proof_summary,
        r.proposition_text, r.proposition_start, r.proposition_end,
        r.standard_rule_id, r.standard_rule_version, r.rule_arguments::text AS rule_arguments_text,
        NULL::text AS title,
        NULL::text AS industry_code,
        'applicable'::text AS applicability,
        'document_extraction'::text AS source_kind
    FROM latest_extraction le
    JOIN public_procurement.bid_eligibility_requirements r ON r.extraction_id=le.extraction_id
    JOIN public_procurement.bid_notices n
      ON n.notice_number=r.notice_number AND n.notice_order=r.notice_order
    LEFT JOIN public_procurement.bid_eligibility_requirement_evidence e
      ON e.requirement_id=r.requirement_id
    LEFT JOIN public_procurement.bid_notice_documents d ON d.document_id=e.document_id
    LEFT JOIN public_procurement.bid_eligibility_requirement_proofs p
      ON p.requirement_id=r.requirement_id
    LEFT JOIN public_procurement.bid_eligibility_requirement_proof_evidence pe
      ON pe.proof_id=p.proof_id
    GROUP BY r.requirement_id, r.notice_number, r.notice_order, n.notice_name,
             n.bid_deadline_at, r.local_id, r.requirement_type, r.operator, r.value,
             r.original_text, r.holder_scope, r.reference_date_type, r.mandatory,
             r.review_status, r.confidence, r.assessment_stage, r.failure_effect,
             r.comparison_mode, r.proposition_text, r.proposition_start,
             r.proposition_end, r.standard_rule_id, r.standard_rule_version,
             r.rule_arguments
), structured_licenses AS (
    SELECT
        concat('pps-license:', l.notice_number, ':', l.notice_order, ':',
               l.restriction_group_number, ':', l.restriction_sequence) AS requirement_id,
        l.notice_number || ':' || l.notice_order AS bid_notice_id,
        l.notice_number, l.notice_order, n.notice_name, n.bid_deadline_at,
        concat('api_license_', l.restriction_group_number, '_', l.restriction_sequence) AS local_id,
        'industry_license'::text AS requirement_type,
        'equals'::text AS operator,
        jsonb_build_object(
            'industry_code', substring(l.license_restriction_name FROM '/([0-9]{4})$'),
            'industry_name', regexp_replace(l.license_restriction_name, '/[0-9]{4}$', '')
        )::text AS value_text,
        l.license_restriction_name AS original_text,
        'bidder'::text AS holder_scope,
        'bid_deadline'::text AS reference_date_type,
        true AS mandatory,
        'extracted'::text AS review_status,
        1.0::numeric AS confidence,
        concat_ws(' | ', 'pps_structured_api', 'list_license_restrictions',
                  l.license_restriction_name) AS evidence_summary,
        'bid_entry'::text AS assessment_stage,
        'ineligible'::text AS failure_effect,
        'all'::text AS comparison_mode,
        NULL::text AS proof_summary,
        l.license_restriction_name AS proposition_text,
        0::integer AS proposition_start,
        char_length(l.license_restriction_name) AS proposition_end,
        'has_registered_industry'::text AS standard_rule_id,
        '1.0.0'::text AS standard_rule_version,
        jsonb_build_object(
            'industry_code', substring(l.license_restriction_name FROM '/([0-9]{4})$'),
            'industry_name', regexp_replace(l.license_restriction_name, '/[0-9]{4}$', '')
        )::text AS rule_arguments_text,
        regexp_replace(l.license_restriction_name, '/[0-9]{4}$', '') AS title,
        substring(l.license_restriction_name FROM '/([0-9]{4})$') AS industry_code,
        'applicable'::text AS applicability,
        'pps_structured_api'::text AS source_kind
    FROM public_procurement.bid_notice_license_restrictions l
    JOIN public_procurement.bid_notices n
      ON n.notice_number=l.notice_number AND n.notice_order=l.notice_order
)
SELECT * FROM extracted
UNION ALL
SELECT * FROM structured_licenses;

CREATE VIEW public_procurement.runtime_bid_requirement_sets AS
WITH latest_extraction AS (
    SELECT DISTINCT ON (notice_number, notice_order)
        notice_number, notice_order, extraction_id, completeness, requires_review
    FROM public_procurement.bid_eligibility_extractions
    WHERE status='completed'
    ORDER BY notice_number, notice_order, finished_at DESC NULLS LAST, started_at DESC
), document_sets AS (
    SELECT le.notice_number, le.notice_order, le.completeness, le.requires_review,
           rs.expression
    FROM latest_extraction le
    LEFT JOIN public_procurement.bid_eligibility_requirement_sets rs
      ON rs.extraction_id=le.extraction_id
), license_groups AS (
    SELECT l.notice_number, l.notice_order, l.restriction_group_number,
           jsonb_agg(
               jsonb_build_object(
                   'requirement_id', concat('pps-license:', l.notice_number, ':', l.notice_order,
                                            ':', l.restriction_group_number, ':', l.restriction_sequence)
               ) ORDER BY l.restriction_sequence
           ) AS conditions
    FROM public_procurement.bid_notice_license_restrictions l
    GROUP BY l.notice_number, l.notice_order, l.restriction_group_number
), license_expressions AS (
    SELECT notice_number, notice_order,
           CASE WHEN count(*)=1 THEN (jsonb_agg(
                    jsonb_build_object('operator','all','conditions',conditions)
                    ORDER BY restriction_group_number
                ))->0
                ELSE jsonb_build_object(
                    'operator','any',
                    'conditions',jsonb_agg(
                        jsonb_build_object('operator','all','conditions',conditions)
                        ORDER BY restriction_group_number
                    )
                )
           END AS expression
    FROM license_groups
    GROUP BY notice_number, notice_order
), category_status AS (
    SELECT n.notice_number, n.notice_order,
           CASE
             WHEN EXISTS (SELECT 1 FROM public_procurement.bid_notice_participation_regions r
                          WHERE r.notice_number=n.notice_number AND r.notice_order=n.notice_order
                            AND COALESCE(r.participation_region_code,'') NOT IN ('','00'))
               THEN 'applicable'
             WHEN region.status='completed' THEN 'not_applicable'
             ELSE 'unknown'
           END AS region_applicability,
           CASE WHEN region.status='completed' THEN 'complete' ELSE 'partial' END AS region_completeness,
           CASE
             WHEN EXISTS (SELECT 1 FROM public_procurement.bid_notice_license_restrictions l
                          WHERE l.notice_number=n.notice_number AND l.notice_order=n.notice_order)
               THEN 'applicable'
             WHEN industry.status='completed' THEN 'not_applicable'
             ELSE 'unknown'
           END AS industry_applicability,
           CASE WHEN industry.status='completed' THEN 'complete' ELSE 'partial' END AS industry_completeness
    FROM public_procurement.bid_notices n
    LEFT JOIN ingestion.bid_notice_requirement_collection_status region
      ON region.notice_number=n.notice_number AND region.notice_order=n.notice_order
     AND region.category='region'
    LEFT JOIN ingestion.bid_notice_requirement_collection_status industry
      ON industry.notice_number=n.notice_number AND industry.notice_order=n.notice_order
     AND industry.category='industry_license'
)
SELECT
    n.notice_number || ':' || n.notice_order AS requirement_set_id,
    n.notice_number || ':' || n.notice_order AS bid_notice_id,
    n.notice_number, n.notice_order,
    CASE
      WHEN ds.expression IS NOT NULL AND lx.expression IS NOT NULL THEN
        jsonb_build_object('operator','all','conditions',jsonb_build_array(ds.expression,lx.expression))
      ELSE COALESCE(ds.expression,lx.expression)
    END::text AS requirement_expression,
    jsonb_build_object(
      'region',jsonb_build_object('applicability',cs.region_applicability,
                                  'completeness',cs.region_completeness),
      'industry_license',jsonb_build_object('applicability',cs.industry_applicability,
                                            'completeness',cs.industry_completeness)
    )::text AS requirement_categories,
    cs.region_applicability AS region_requirement_status,
    cs.industry_applicability AS industry_license_requirement_status,
    CASE
      WHEN cs.region_completeness='complete'
       AND cs.industry_completeness='complete'
       AND COALESCE(ds.completeness,'')='complete' THEN 'complete'
      WHEN cs.region_completeness='complete' OR cs.industry_completeness='complete'
        OR ds.completeness IS NOT NULL THEN 'partial'
      ELSE 'unknown'
    END AS requirement_extraction_status,
    COALESCE(ds.requires_review,false) AS requires_review
FROM public_procurement.bid_notices n
JOIN category_status cs USING (notice_number,notice_order)
LEFT JOIN document_sets ds USING (notice_number,notice_order)
LEFT JOIN license_expressions lx USING (notice_number,notice_order);

ALTER VIEW public_procurement.runtime_bid_notices RENAME TO runtime_bid_notices_base;

CREATE VIEW public_procurement.runtime_bid_notices AS
SELECT base.*,
       sets.region_requirement_status,
       sets.industry_license_requirement_status,
       sets.requirement_extraction_status,
       sets.requirement_categories
FROM (
    SELECT * FROM public_procurement.runtime_bid_notices_base
) base
JOIN public_procurement.runtime_bid_requirement_sets sets USING (bid_notice_id);

GRANT SELECT ON public_procurement.runtime_bid_notices TO teoria_runtime;
GRANT SELECT ON public_procurement.runtime_bid_requirements TO teoria_runtime;
GRANT SELECT ON public_procurement.runtime_bid_requirement_sets TO teoria_runtime;
