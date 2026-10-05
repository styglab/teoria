INSERT INTO ontology.ontologies (
    ontology_id, namespace, name, description
) VALUES (
    '10000000-0000-4000-8000-000000000001',
    'procurement',
    'Procurement',
    '조달 공고, 낙찰, 계약과 참여 주체를 표현하는 Business Ontology'
) ON CONFLICT (namespace) DO NOTHING;

INSERT INTO ontology.ontology_versions (
    ontology_version_id, ontology_id, version, status, created_by, published_at
) VALUES (
    '10000000-0000-4000-8000-000000000002',
    '10000000-0000-4000-8000-000000000001',
    '0.1.0',
    'published',
    'system:bootstrap',
    now()
) ON CONFLICT (ontology_id, version) DO NOTHING;

INSERT INTO ontology.business_objects (
    business_object_id, ontology_version_id, code, name, description,
    identity_policy, status
) VALUES (
    '10000000-0000-4000-8000-000000000003',
    '10000000-0000-4000-8000-000000000002',
    'Contract',
    '계약',
    '기관과 업체 사이에 체결된 조달 계약',
    '{"properties":["contractNumber"]}'::jsonb,
    'published'
) ON CONFLICT (ontology_version_id, code) DO NOTHING;

INSERT INTO ontology.object_properties (
    property_id, business_object_id, code, name, description, value_type,
    cardinality, unit, temporal, status
) VALUES (
    '10000000-0000-4000-8000-000000000004',
    '10000000-0000-4000-8000-000000000003',
    'amount',
    '계약금액',
    '계약 사건에서 확정된 통화 기준 계약금액',
    'decimal',
    'optional',
    'KRW',
    true,
    'published'
) ON CONFLICT (business_object_id, code) DO NOTHING;

INSERT INTO binding.ontology_bindings (
    binding_id, ontology_ref_type, ontology_ref_id, target_type,
    target_locator, binding_type, purpose, authority, priority,
    confidence, status, provenance, created_by, approved_by
) VALUES (
    '10000000-0000-4000-8000-000000000005',
    'property',
    '10000000-0000-4000-8000-000000000004',
    'api_field',
    'provider://pps_contract/get_contract/response/cntrctAmt',
    'represents',
    'realtime',
    'authoritative',
    10,
    1.0,
    'approved',
    '{"source":"provider_contract","note":"Provider field name must be verified against the active PPS Source contract before production use"}'::jsonb,
    'system:bootstrap',
    'system:bootstrap'
) ON CONFLICT (binding_id) DO NOTHING;
