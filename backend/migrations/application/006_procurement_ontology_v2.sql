UPDATE ontology.ontology_versions
   SET status = 'deprecated'
 WHERE ontology_id = '10000000-0000-4000-8000-000000000001'
   AND status = 'published';

INSERT INTO ontology.ontology_versions (
    ontology_version_id, ontology_id, version, status, based_on_version_id,
    created_by, published_at
) VALUES (
    '20000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000001',
    '0.2.0', 'published',
    '10000000-0000-4000-8000-000000000002',
    'system:bootstrap', now()
);

INSERT INTO ontology.business_objects
    (business_object_id, ontology_version_id, code, name, description, identity_policy, status)
VALUES
('20000000-0000-4000-8000-000000000010','20000000-0000-4000-8000-000000000001','Organization','기관','조달 공고를 게시하고 계약을 체결하는 기관','{"properties":["organizationCode"]}','published'),
('20000000-0000-4000-8000-000000000011','20000000-0000-4000-8000-000000000001','Company','업체','조달에 참여하거나 계약을 수행하는 사업자','{"properties":["businessRegistrationNumber"]}','published'),
('20000000-0000-4000-8000-000000000012','20000000-0000-4000-8000-000000000001','BidNotice','입찰공고','기관이 게시한 조달 입찰 공고','{"properties":["bidNoticeId"]}','published'),
('20000000-0000-4000-8000-000000000013','20000000-0000-4000-8000-000000000001','Award','낙찰','입찰공고에 대한 낙찰 결과','{"properties":["awardEventId"]}','published'),
('20000000-0000-4000-8000-000000000014','20000000-0000-4000-8000-000000000001','Contract','계약','기관과 업체 사이에 체결된 조달 계약','{"properties":["contractNumber"]}','published');

INSERT INTO ontology.object_properties
    (property_id, business_object_id, code, name, description, value_type, cardinality, unit, temporal, status)
VALUES
('20000000-0000-4000-8000-000000000020','20000000-0000-4000-8000-000000000010','organizationCode','기관코드','기관을 식별하는 공식 코드','string','one',NULL,false,'published'),
('20000000-0000-4000-8000-000000000021','20000000-0000-4000-8000-000000000011','businessRegistrationNumber','사업자등록번호','업체를 식별하는 사업자등록번호','string','one',NULL,false,'published'),
('20000000-0000-4000-8000-000000000022','20000000-0000-4000-8000-000000000012','bidNoticeId','공고 식별자','공고번호와 차수를 포함하는 식별자','string','one',NULL,false,'published'),
('20000000-0000-4000-8000-000000000023','20000000-0000-4000-8000-000000000013','awardEventId','낙찰 사건 식별자','중복 제거된 낙찰 사건 식별자','string','one',NULL,false,'published'),
('20000000-0000-4000-8000-000000000024','20000000-0000-4000-8000-000000000014','contractNumber','계약번호','원계약 관계를 식별하는 계약번호','string','one',NULL,false,'published'),
('20000000-0000-4000-8000-000000000025','20000000-0000-4000-8000-000000000014','amount','계약금액','계약 사건에서 확정된 통화 기준 계약금액','decimal','optional','KRW',true,'published'),
('20000000-0000-4000-8000-000000000026','20000000-0000-4000-8000-000000000014','contractDate','계약일','원계약 사건의 최초 계약일','date','optional',NULL,true,'published');

INSERT INTO ontology.relationship_types
    (relationship_type_id, ontology_version_id, code, name, source_object_id, target_object_id, source_cardinality, target_cardinality, temporal, transitive, status)
VALUES
('20000000-0000-4000-8000-000000000030','20000000-0000-4000-8000-000000000001','PUBLISHES','공고 게시','20000000-0000-4000-8000-000000000010','20000000-0000-4000-8000-000000000012','one','many',true,false,'published'),
('20000000-0000-4000-8000-000000000031','20000000-0000-4000-8000-000000000001','RESULTS_IN_AWARD','낙찰 결과','20000000-0000-4000-8000-000000000012','20000000-0000-4000-8000-000000000013','one','many',true,false,'published'),
('20000000-0000-4000-8000-000000000032','20000000-0000-4000-8000-000000000001','AWARDED_TO','낙찰 업체','20000000-0000-4000-8000-000000000013','20000000-0000-4000-8000-000000000011','many','many',true,false,'published'),
('20000000-0000-4000-8000-000000000033','20000000-0000-4000-8000-000000000001','RESULTS_IN_CONTRACT','계약 결과','20000000-0000-4000-8000-000000000013','20000000-0000-4000-8000-000000000014','one','many',true,false,'published'),
('20000000-0000-4000-8000-000000000034','20000000-0000-4000-8000-000000000001','SIGNS','계약 체결','20000000-0000-4000-8000-000000000010','20000000-0000-4000-8000-000000000014','one','many',true,false,'published'),
('20000000-0000-4000-8000-000000000035','20000000-0000-4000-8000-000000000001','CONTRACTOR','계약 업체','20000000-0000-4000-8000-000000000014','20000000-0000-4000-8000-000000000011','many','many',true,false,'published');

UPDATE binding.ontology_bindings
   SET ontology_ref_id = '20000000-0000-4000-8000-000000000025'
 WHERE ontology_ref_type = 'property'
   AND ontology_ref_id = '10000000-0000-4000-8000-000000000004';
