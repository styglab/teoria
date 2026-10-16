"""Data DB statements owned by this market-analysis feature."""

_CONTRACT_SUPPLIERS_BATCH_QUERY = """
SELECT c.unified_contract_number,c.is_joint_contract,
       cs.supplier_sequence,cs.business_registration_number,cs.supplier_name,
       cs.supplier_role_name,cs.joint_contract_method_name,
       cs.participation_share_rate
FROM public_procurement.contracts c
JOIN public_procurement.contract_suppliers cs USING (unified_contract_number)
WHERE c.unified_contract_number=ANY(%(unified_contract_numbers)s::text[])
ORDER BY array_position(%(unified_contract_numbers)s::text[],c.unified_contract_number),
         CASE WHEN cs.supplier_role_name='주계약업체' THEN 0 ELSE 1 END,
         cs.supplier_sequence
"""
