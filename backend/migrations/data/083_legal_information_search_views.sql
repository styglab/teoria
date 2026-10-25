-- Search documents preserve one article/addendum's complete subtree. Raw XML
-- remains in ingestion; readers see only structured legal source text.
CREATE VIEW legal_information.law_search_versions AS
SELECT l.target_id, v.law_id, v.mst, v.name AS law_name, v.effective_date,
       v.promulgation_date, v.amendment_type, l.last_catalog_at,
       v.latest_snapshot_id IS NOT NULL AS available
FROM legal_information.law l
JOIN legal_information.law_version v USING (law_id);

CREATE VIEW legal_information.law_search_documents AS
SELECT l.target_id, v.law_id, v.mst, v.name AS law_name, v.effective_date,
       v.promulgation_date, v.promulgation_number, v.amendment_type,
       v.listing->>'현행연혁코드' AS catalog_status, l.last_catalog_at,
       s.snapshot_id, s.source_record_hash, s.parser_version,
       s.snapshot_id = v.latest_snapshot_id AS is_latest_snapshot,
       p.path, p.kind, p.number, p.title,
       p.effective_date AS provision_effective_date,
       concat_ws(E'\n', NULLIF(p.title,''), NULLIF(p.content,''), children.content) AS content
FROM legal_information.law l
JOIN legal_information.law_version v USING (law_id)
JOIN legal_information.law_snapshot s USING (law_id, mst, effective_date)
JOIN legal_information.law_provision p USING (snapshot_id)
LEFT JOIN LATERAL (
    SELECT string_agg(c.content, E'\n' ORDER BY
        ARRAY(SELECT (m[1])::integer FROM regexp_matches(c.path,'\[(\d+)\]','g') m)) AS content
    FROM legal_information.law_provision c
    WHERE c.snapshot_id = p.snapshot_id AND c.path LIKE p.path || '/%'
) children ON true
WHERE p.kind IN ('article', 'addendum');

GRANT USAGE ON SCHEMA legal_information TO teoria_runtime;
GRANT SELECT ON legal_information.law_search_versions TO teoria_runtime;
GRANT SELECT ON legal_information.law_search_documents TO teoria_runtime;
-- No grant on source tables, sample values, or ingestion payloads.
