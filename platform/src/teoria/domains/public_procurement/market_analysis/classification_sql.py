"""Data DB statements owned by this market-analysis feature."""

_PROCUREMENT_CLASSIFICATION_HIERARCHY_QUERY = """
SELECT DISTINCT ON (n.procurement_classification_number)
       n.procurement_classification_number,
       n.procurement_large_classification_name,
       n.procurement_middle_classification_name,n.purchase_items
FROM public_procurement.bid_notices n
WHERE n.procurement_classification_number=ANY(%(classification_numbers)s::text[])
  AND (n.procurement_large_classification_name IS NOT NULL
       OR n.procurement_middle_classification_name IS NOT NULL)
ORDER BY n.procurement_classification_number,n.notice_published_at DESC
"""
