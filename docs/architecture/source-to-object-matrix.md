# Source-to-Object matrix

Status: **baseline for ontology redesign**. 이 문서는 현재 등록된 Source Registry,
Pipeline Connector와 Runtime Mapping을 기준으로 작성했다. `authoritative` 표시는
제공기관의 업무 범위 안에서만 사용하며, 법적 권위가 확인되지 않은 원천은
`preferred observation`으로 둔다.

## 원칙

```text
Provider record
    -> Source observation and provenance
    -> identity resolution
    -> canonical Business Object / Event / Association
    -> derived projection and Capability
```

- Provider object를 그대로 Business Object type으로 만들지 않는다.
- `teoria_public_procurement`는 정규화된 Database Source다. 원 제공기관 자체가 아니다.
- 동일 객체를 여러 Source가 보강할 수 있다.
- 이름만으로 `BusinessEntity`와 `BusinessRegistration`을 확정 연결하지 않는다.
- 현재값과 관찰 이력을 분리한다.
- 원천 충돌은 덮어쓰지 않고 선택 정책과 선택 근거를 남긴다.

## 현재 Source inventory

### Runtime이 직접 사용하는 API/DB Sources

| Source ID | 제공 범위 | Runtime 역할 |
|---|---|---|
| `teoria_public_procurement` | 정규화된 공고·개찰·낙찰·계약·요건·분류 | 분석/검색용 canonical projection |
| `pps_user` | 수요기관·조달업체·업종·공급물품·제재 | 조달 등록 상태 조회 |
| `nts_business_registration` | 사업자등록 상태·진위 | 사업자등록 관찰/검증 |
| `fsc_company_basic` | 법인 개요·계열·종속회사 | 법인 프로필과 관계 관찰 |
| `fsc_company_financial` | 요약재무·재무상태표·손익계산서 | 재무 관찰 |
| `kodma_smpp_certificate` | 직접생산·여성기업·장애인기업 확인 | 자격/확인 관찰 |
| `mss_innobiz_company_lookup` | 이노비즈 확인 | 자격 관찰 |
| `mss_mainbiz_company_lookup` | 메인비즈 확인 | 자격 관찰 |
| `mss_venture_company_disclosure` | 벤처기업 확인 공시 | 자격/공시 관찰 |

### Pipeline-only connectors

| Connector | 수집 범위 | Canonical 도착점 |
|---|---|---|
| `pps_bid_notice_api` | 공고 원문·일정·금액·기관·분류 | `teoria_public_procurement.bid_notices` 등 |
| `pps_bid_result_api` | 개찰 참여·최종 낙찰 | bid award/participation tables |
| `pps_contract_api` | 계약·계약업체·수요기관·변경/차수 | contract/event/party tables |
| `pps_industry_api` | 조달 업종과 근거법규 | procurement industry dictionary |

Pipeline-only 원천은 Runtime Source Registry에 중복 등록하지 않는다. 대신 canonical
row의 provenance가 connector ID, operation ID, raw record ID와 observed time을
가리켜야 한다.

## Source-to-Object matrix

| Source 사실 | Canonical target | 유형 | 식별 기준 | 시간 성격 | 권위/사용 정책 |
|---|---|---|---|---|---|
| PPS 수요기관 | `Organization` | identity/entity | PPS 기관코드 | slowly changing | PPS 조달 문맥의 기관코드에 authoritative |
| PPS 조달업체 | `BusinessRegistration`, 확인 시 `BusinessEntity` | identity observation | 사업자등록번호 | observed profile | 조달등록 사실에 authoritative, 업체 병합에는 evidence 필요 |
| NTS 사업자 상태 | `TaxpayerStatusObservation` -> `BusinessRegistration` | observation | 사업자등록번호 + observedAt | temporal | 세무/사업자 상태에 authoritative |
| NTS 진위 확인 | `RegistrationVerification` -> `BusinessRegistration` | verification event | request hash + observedAt | immutable event | 입력 조합의 검증 결과에 authoritative |
| FSC 기업개요 | 법인 유형 `BusinessEntity` | entity observation | 법인등록번호 | slowly changing | 공개 기업 프로필에 preferred; 법인등기 원장 대체 아님 |
| FSC 계열/종속 | `BusinessEntityRelationship` | temporal association | 기준 법인 + 상대 법인 + 기준일 | temporal | FSC 공개 관계 관찰에 preferred |
| FSC 재무정보 | `FinancialStatement`, `FinancialFact` | observation | BusinessEntity + 회계연도 + 보고서 구분 | period observation | 해당 공공 API가 제공한 재무 관찰에 preferred |
| MSS 이노비즈/메인비즈 | `QualificationObservation` | observation | 식별 가능한 사업자 + 자격종류 + 유효기간 | temporal | 해당 제도 조회 결과에 authoritative/preferred, 식별 수준에 따라 결정 |
| MSS 벤처 공시 | `VentureCompanyDisclosure` | disclosure event | 공시 식별자 | temporal | 공시 사실에 authoritative |
| KODMA 직접생산 | `DirectProductionConfirmation` | qualification | 사업자 + 세부품명 + 유효기간 | temporal | 직접생산 확인에 authoritative |
| KODMA 여성/장애인기업 | `QualificationObservation` | qualification | 사업자 + 자격종류 + 유효기간 | temporal | 해당 확인서에 authoritative |
| PPS 공고 | `BidNotice` | event/entity | 공고번호 + 차수 + 재입찰/분류 식별자 | temporal lifecycle | 공고 사실에 authoritative |
| PPS 공고 계보 | `ProcurementCase`, `SUPERSEDES` | identity/link assertion | 원천 참조번호 우선 | temporal | 원천 관계는 confirmed; 추론은 candidate |
| PPS 개찰 참여 | `BidParticipation` | association event | 공고 사건 + 사업자 + 재입찰/분류 | immutable event | 개찰 참여 사실에 authoritative |
| PPS 최종낙찰 | `Award`, `AwardRecipient` | decision/association event | 공고 사건 + 낙찰 식별자 | temporal event | 낙찰 결과에 authoritative |
| PPS 계약 | `Contract`, `ContractVersion`, `ContractParty` | entity/version/association | 원계약·통합계약번호와 업체번호 | temporal version | 계약 사실에 authoritative |
| PPS 업종 사전 | `IndustryLicense` | classification | 업종코드 | versioned reference | 조달 업종 의미에 authoritative |
| Teoria 요건 추출 | `BidRequirementSet`, `BidRequirement`, `Evidence` | derived assertion | 공고 + extraction version + local ID | versioned derived | Teoria-derived, evidence/confidence 필수 |
| Teoria 참여 finding | `ParticipationFinding`, `Evidence` | derived assertion | 공고 + finding ID + extraction version | versioned derived | Teoria-derived, 사용자 검토 상태 보존 |
| Teoria 집계/profile | Runtime Contract only | derived projection | 요청/필터/processor version | computed | Business Object로 승격하지 않음 |

## Identity model

### BusinessEntity와 BusinessRegistration

- `BusinessEntity`의 canonical key는 Teoria 내부 안정 ID다.
- 법인등록번호는 법인 유형 BusinessEntity의 강한 외부 식별자지만 모든 업체에
  존재하지 않는다.
- 하나의 BusinessEntity는 복수의 BusinessRegistration을 가질 수 있다.
- BusinessRegistration의 canonical key는 정규화된 사업자등록번호다.
- 이름, 대표자, 주소는 identity key가 아니다.
- PPS, NTS, KODMA, MSS는 등록 단위 또는 상위 업체에 서로 다른 관찰을 제공한다.
- 폐업/휴업은 BusinessEntity 삭제가 아니라 해당 BusinessRegistration의
  `TaxpayerStatusObservation`이다.

### 업체 통합

- FSC 결과는 법인 유형 BusinessEntity의 프로필을 제공한다.
- BusinessRegistration과 BusinessEntity 연결은 `IdentityAssertion`으로 관리한다.
- 정확한 식별자 근거가 없으면 `candidate`이며 재무·기업관계를 사업자등록 실적과
  합치지 않는다.
- 조달 사건은 BusinessRegistration에 연결하고, 업체 통합 분석만 확정된
  BusinessEntity Link를 따라 집계한다.

### Organization

- PPS 기관코드는 조달 문맥의 external identifier다.
- 향후 ERP나 다른 기관 사전이 별도 코드를 제공할 수 있으므로
  `Organization.externalIdentifiers[]` 의미를 지원한다.
- 서로 다른 코드 체계의 병합은 이름 유사도가 아니라 검증된 identifier assertion을
  사용한다.

## 필요한 provenance support model

다음은 사용자가 주로 탐색하는 Business Object라기보다 platform support model이다.
Palantir의 non-semantic technical type 지침처럼 기본 탐색에서는 숨길 수 있다.

### `SourceObservationRef`

```text
source_id
operation_id
connector_id
raw_record_id
database_asset_ref
observed_at
source_updated_at
content_hash
```

### `IdentityAssertion`

```text
subject_ref
identifier_type
identifier_value
status: confirmed | candidate | rejected | superseded
match_method
confidence
evidence[]
valid_from / valid_to
reviewed_by / reviewed_at
```

### `FactAssertion`

```text
subject_ref
property_ref or relationship_ref
value
authority
confidence
source_observation_ref
valid_from / valid_to
```

이 support model 때문에 OpenMetadata entity를 Teoria DB에 복제하지 않는다.
OpenMetadata asset은 reference로만 가리키고, 업무 사실의 provenance와 identity
resolution은 Teoria가 소유한다.

## 속성 충돌 정책

모든 속성에 하나의 전역 Source 순서를 사용하지 않는다. `property purpose`별로
정책을 둔다.

| 속성/관계 | 우선 정책 |
|---|---|
| 사업자 상태 | 최신 유효 NTS 관찰 |
| 법인 기본 프로필 | 확인된 법인번호의 최신 FSC 관찰; 법인등기 원장 Source 추가 시 재평가 |
| 조달 공고/낙찰/계약 | PPS 원천 사실; Teoria DB는 canonical projection |
| 조달업체 등록·업종·공급물품 | PPS 사용자정보의 유효 관찰 |
| 자격/확인 | 해당 제도의 발급·공시 Source별 판단, 서로 다른 자격을 덮어쓰지 않음 |
| 재무 값 | 법인 + 회계연도 + statement type + accounting basis별 병존 |
| 업체명 표시 | 문맥별 표시정책. identity 판정에는 사용하지 않음 |

충돌 결과에는 최소한 `selected_value`, `selection_policy`, `candidate_values`,
`source_refs`, `selected_at`이 필요하다. 값이 다르다는 이유만으로 최신 row가 항상
이기는 것은 아니다.

## 현재 Mapping의 주요 문제

1. `teoria_public_procurement`를 읽을 때 원 PPS connector/operation provenance가
   Runtime object까지 이어지는지 명시적 계약이 부족하다.
2. `procurement.Company`가 사업자등록번호 정체성을 소유해
   `company.BusinessRegistration`과 중복된다. 전자는 BusinessEntity로 교체한다.
3. 현재 `Company` 이름은 법인, 사업자등록, 조달업체의 범위를 혼동시킨다.
4. `ContractParticipation`은 객체라기보다 역할·지분을 가진 association event이며
   `ContractParty`가 더 정확하다.
5. 자격의 “현재 유효” 값과 시점별 관찰이 일부 모델에서 섞일 수 있다.
6. FSC가 제공하지 않는 법인-사업자 연결을 이름으로 보완해서는 안 된다.
7. source authority, conflict policy, observation time이 Binding 자체만으로는 충분히
   표현되지 않는다.

## Ontology Draft 전에 수행할 profiling

| 검증 | 결과물 |
|---|---|
| 사업자번호별 Source 출현과 이름 불일치율 | identity collision report |
| 사업자번호-법인번호 확정/후보/미해결 비율 | identity resolution coverage |
| 기관코드별 명칭·코드체계 중복 | organization identity report |
| 공고-낙찰-계약 linkage completeness | lifecycle linkage report |
| 원계약별 version 수와 날짜/금액 변화 | contract version report |
| 공동수급 지분·역할 누락률 | party attribution completeness |
| 공고 공식 분류와 미분류 비율 | classification coverage |
| canonical row의 raw provenance 보존율 | provenance coverage |

이 결과 없이 cardinality, required property, authority를 확정하지 않는다.

첫 운영 측정 결과는
[Ontology source profile — 2026-10-06](ontology-source-profile-2026-10-06.md)에
기록한다.

## 결정 순서

1. shared operational ontology 안의 identity context와 cross-module Link 규칙 확정
2. identity/provenance support model 설계
3. profiling 수행
4. Object/Property/Link cardinality 확정
5. 새 Ontology Draft 생성
6. Source/Data Asset/API Field Binding 재작성
7. Capability Binding 재작성
8. 기존 Published Artifact와 shadow validation
