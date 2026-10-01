CREATE VIEW public_procurement.runtime_bid_awards AS
SELECT
    award.*,
    notice.procurement_classification_number AS field_code,
    notice.procurement_classification_name AS field_name,
    CASE
        WHEN award.work_type = 'construction'
            THEN notice.procurement_classification_name
        ELSE notice.procurement_large_classification_name
    END AS large_category,
    CASE
        WHEN award.work_type = 'construction' THEN NULL
        ELSE notice.procurement_middle_classification_name
    END AS middle_category
FROM public_procurement.bid_awards award
LEFT JOIN public_procurement.bid_notices notice
  ON notice.notice_number = award.notice_number
 AND notice.notice_order = award.notice_order;

CREATE VIEW public_procurement.runtime_contracts AS
SELECT
    contract.*,
    CASE
        WHEN contract.contract_type = 'foreign_procurement' THEN 'foreign'
        ELSE contract.contract_type
    END AS work_type,
    contract.procurement_classification_number AS field_code,
    contract.procurement_classification_name AS field_name,
    CASE
        WHEN contract.contract_type = 'construction'
            THEN contract.procurement_classification_name
        ELSE hierarchy.procurement_large_classification_name
    END AS large_category,
    CASE
        WHEN contract.contract_type = 'construction' THEN NULL
        ELSE hierarchy.procurement_middle_classification_name
    END AS middle_category
FROM public_procurement.contracts contract
LEFT JOIN LATERAL (
    SELECT
        notice.procurement_large_classification_name,
        notice.procurement_middle_classification_name
    FROM public_procurement.bid_notices notice
    WHERE notice.procurement_classification_number =
          contract.procurement_classification_number
      AND (
          notice.procurement_large_classification_name IS NOT NULL
          OR notice.procurement_middle_classification_name IS NOT NULL
      )
    ORDER BY notice.notice_published_at DESC
    LIMIT 1
) hierarchy ON true;

CREATE INDEX IF NOT EXISTS contracts_procurement_search_idx
    ON public_procurement.contracts (
        contract_type,
        procurement_classification_number,
        concluded_date DESC
    );

GRANT SELECT ON public_procurement.runtime_bid_awards TO teoria_runtime;
GRANT SELECT ON public_procurement.runtime_contracts TO teoria_runtime;
