# Procurement Ontology redesign

Status: **proposed**. 이 문서는 다음 Published Procurement Ontology 초안을
만들기 위한 설계 기준이다. 현재 `procurement` 0.5.0을 직접 수정하지 않으며,
검토가 끝난 뒤 새 Draft version으로 구현한다.

## 왜 지금 다시 설계하는가

현재 Ontology는 `Organization`, `Company`, `BidNotice`, `Award`, `Contract`와
참여 객체를 제공하므로 기본 방향은 맞다. 그러나 현행 모델만으로는 다음 질문에
일관되게 답하기 어렵다.

2026-10-06 운영 확인 기준 `procurement` 0.5.0은 57개 concept,
`company` 0.2.0은 35개 concept을 게시하고 있다. 조달 쪽에는
`procurement.Company`, 기업 쪽에는 `company.BusinessRegistration`과
`company.LegalEntity`가 별도로 존재해 identity 경계부터 정리해야 한다. 목표
모델에서는 이를 `party.BusinessEntity`와 그 하위 `BusinessRegistration`으로
통합한다.

- 원공고와 재공고가 같은 조달 사업인가?
- 업체가 공고에 단순 참여했는가, 낙찰됐는가, 계약 구성원이 됐는가?
- 공동수급에서 업체의 역할과 지분은 무엇인가?
- 원계약과 변경·차수계약 중 현재 유효한 계약 상태는 무엇인가?
- 계약 없는 낙찰, 공고 없는 계약, 취소·유찰을 어떻게 표현하는가?
- 하나의 업체가 여러 사업자등록번호를 가질 때 업체와 등록 단위를 어떻게 구분하는가?

Capability response나 특정 제공기관의 데이터 모양을 Ontology에 옮기는 작업이
아니라 현실의 조달·기업 세계를 먼저 모델링해야 한다.

## 다중 원천이 기본 전제다

현재 Teoria가 사용하는 원천은 나라장터 하나가 아니다.

원천별 canonical object, 식별자, 시간 성격과 권위 정책은
[Source-to-Object matrix](source-to-object-matrix.md)에 정리한다.

| Source family | 제공하는 관찰/사실 |
|---|---|
| PPS/G2B | 공고, 참여·개찰, 낙찰, 계약, 조달업종, 조달 공급업체 |
| NTS | 사업자등록 상태와 세무 상태 관찰 |
| FSC/DART 계열 | 법인 기본정보, 재무제표, 기업 관계 |
| MSS | 벤처·이노비즈·메인비즈 확인 정보 |
| 공공구매종합정보망 | 직접생산·여성기업·장애인기업 등 확인서 |
| Teoria Data DB | 여러 원천을 정규화·연결한 canonical/analytical projection |
| 향후 ERP/DW/File/API | 기관 내부 계약·지급·성과 등 추가 사실 |

따라서 `BidNotice`가 PPS 객체이거나 `Company`가 FSC 객체인 구조로 만들지 않는다.
하나의 Business Object에 여러 Source가 서로 다른 속성·관찰을 제공한다.

```text
                         BusinessEntity
                              |
                    HAS_BUSINESS_REGISTRATION
                              |
                       BusinessRegistration
                        /       |         \
                     NTS       PPS        MSS/KODMA
                  tax status  supplier   qualifications
                         \       |       /
                          provenance/evidence

                  corporation-type BusinessEntity
                            /       \
                          FSC      confirmed identity evidence
                    profile/finance        |
                                  BusinessRegistration
```

Source별 객체를 따로 복제하지 않고 각 사실에 `source_ref`, `observed_at`,
`valid_from/to`, `authority`, `confidence`, `evidence`를 보존한다. 서로 충돌하는
값은 덮어쓰지 않고 authority policy로 현재 값을 선택하며 원 관찰은 추적할 수
있어야 한다.

## Palantir에서 채택할 원칙

Teoria가 Foundry를 복제하지는 않지만 다음 공식 설계 원칙은 채택한다.

1. **시스템이 아니라 현실을 모델링한다.** Object type은 테이블이나 API response가
   아니라 현실의 entity 또는 event다.
2. **정체성과 관찰을 분리한다.** 업체와 업체 상태 관찰, 계약과 계약 변경 버전은
   서로 다른 객체다.
3. **객체를 작고 집중되게 유지한다.** 모든 필드를 `BidNotice`나 `Company`에
   누적하지 않는다.
4. **Link type은 업무적으로 이름 붙이고 양방향으로 탐색한다.** 각 방향의 이름과
   cardinality가 명확해야 한다.
5. **Action과 Pipeline을 구분한다.** 사용자의 결정과 승인·변경은 Action 후보지만,
   외부 API 동기화와 자동 정규화는 Prefect/Pipeline 작업이다.
6. **실제 업무 질문으로 검증한다.** 객체 수보다 입찰 검토와 계약 분석 질문을
   정확히 탐색할 수 있는지가 기준이다.

근거는 Palantir 공식 문서의
[Ontology design best practices](https://www.palantir.com/docs/foundry/ontology/ontology-best-practices),
[Ontologies overview](https://www.palantir.com/docs/foundry/ontologies/ontologies-overview),
[Link types](https://www.palantir.com/docs/foundry/object-link-types/link-types-overview),
[Actions and rules](https://www.palantir.com/docs/foundry/action-types/rules),
[Object edits](https://www.palantir.com/docs/foundry/object-edits/overview)를 따른다.

## 권위 경계

```text
Data DB / Provider APIs    observed procurement and company facts
OpenMetadata              physical and governance metadata
Business Ontology         durable business objects, links, states and rules
Runtime Contract          Capability input/output wire shape
Semantic Binding          Ontology <-> metadata/API field/Capability
Prefect                    collection, normalization and synchronization
```

Ontology는 원천 row를 저장하는 새 운영 DB가 아니다. Object instance는 Data DB나
Provider에서 해석되고, Ontology authoring DB에는 type definition과 lifecycle만
저장한다.

## 하나의 shared operational ontology, 여러 bounded context

목표 모델은 하나의 거대한 Procurement 객체 묶음이 아니라 다음 bounded context를
조합한다.

| Context | 소유 개념 |
|---|---|
| `party` 또는 shared core | Organization, BusinessEntity, BusinessRegistration, Address |
| `procurement` | ProcurementCase, BidNotice, Lot, Participation, Award, Contract |
| `qualification` | Qualification, Certificate, IndustryLicense, Sanction |
| `finance` | FinancialStatement, FinancialFact, MarketListing |
| `decision` | Go/No-Go Review, Evidence, Decision 기록 |

Palantir Link type도 서로 다른 Ontology를 직접 잇지 않고 shared Ontology를
권장한다. Teoria의 목표도 **하나의 shared operational ontology version 안에 여러
module/namespace를 두는 방식**으로 확정한다. `party.BusinessRegistration`과
`procurement.BidParticipation`은 같은 Published Artifact 안에서 Link된다.

```text
Operational Ontology 1.x
├── party.*
├── procurement.*
├── qualification.*
├── finance.*
└── decision.*
```

이는 모든 개념을 한 Python module이나 한 UI 화면에 섞는다는 뜻이 아니다. module별
소유권과 권한은 유지하되 version validation/publish와 Link integrity만 공유한다.
현재 `company`와 `procurement` Published Ontology는 migration 동안 유지한다.
새 모델은 하나의 `teoria` Ontology version 안에서 `party.*`, `procurement.*`
Stable Key를 함께 발행한다. 현재 authoring 저장소의 Relationship은 같은 version의
Object만 연결할 수 있으므로 이 단일 publication boundary가 cross-module Link의
정합성을 보장한다. 새 shared Artifact가 검증된 후 기존 Ontology를 deprecate한다. 같은 현실 객체를
`procurement.Company`와 `company.BusinessRegistration`으로 복제하지 않는다.

## 제안하는 핵심 객체

### Identity objects

| Object | 의미 | 정체성 |
|---|---|---|
| `Organization` | 공고를 게시하거나 계약하는 공공기관 | 공식 기관코드 |
| `BusinessEntity` | 사용자에게 업체/Company로 보이는 경제활동 주체 | Teoria 내부 안정 ID |
| `BusinessRegistration` | BusinessEntity가 보유한 사업자등록 단위 | 사업자등록번호 |

`BusinessEntity`는 복수의 `BusinessRegistration`을 가질 수 있고 법인인 경우
법인등록번호를 가질 수 있다. 회사명은 식별자가 아니다. 사용자는
`BusinessEntity`를 업체로 탐색하지만, 조달 사건은 원천에서 확인되는 실제
`BusinessRegistration`에 연결한다.

```text
BusinessEntity 1 ---- 0..N BusinessRegistration
    companyId                 businessRegistrationNumber
    displayName               businessStatus
    entityType                taxType
    corporateRegistrationNumber?
```

사업자등록만 있고 상위 업체가 아직 확인되지 않은 경우 `BusinessRegistration`은
미해결 상태로 먼저 존재할 수 있다. 검증된 `IdentityAssertion`이 생긴 뒤
`BusinessEntity`에 연결한다. 업체 전체 계약 실적은 이 확정 Link를 통해서만
합산한다.

### Procurement lifecycle objects

| Object | 의미 | 주요 속성 |
|---|---|---|
| `ProcurementCase` | 재공고·정정공고를 포괄하는 하나의 조달 사업 | caseId, name, workType, status |
| `BidNotice` | 외부에 게시된 개별 공고 | bidNoticeId, publishedAt, deadlineAt, noticeKind, status |
| `ProcurementLot` | 한 사업 안에서 독립 낙찰·계약 가능한 분할 단위 | lotId, lotNumber, name |
| `BidParticipation` | 특정 사업자등록이 특정 공고/lot에 제출한 입찰 사건 | participationId, bidAmount, bidRate, rank, result |
| `Award` | 공고/lot의 낙찰 결정 사건 | awardEventId, awardedAt, amount, status |
| `AwardRecipient` | 낙찰과 업체 사이의 역할 있는 관계 사건 | recipientId, role, sharePercent, attributedAmount |
| `Contract` | 원계약 단위의 지속 가능한 계약 | contractEventId, contractNumber, firstContractDate, status |
| `ContractVersion` | 최초·변경·차수계약의 관찰 가능한 버전 | versionId, versionDate, versionType, amount |
| `ContractParty` | 계약과 업체 사이의 공동수급 관계 | partyId, role, sharePercent, attributedAmount |

`ProcurementLot`은 원천에서 분할 단위를 식별할 수 있을 때만 생성한다. 모든 공고에
가짜 lot를 만들지 않는다. 반대로 복수 낙찰을 `BidNotice` 하나에 평면 배열로
숨기지 않는다.

### Classification and qualification objects

| Object | 의미 |
|---|---|
| `ProcurementClassification` | 물품·용역의 공식 조달 분류 또는 공사의 공식 공종 분류 |
| `IndustryLicense` | 입찰 참가에 사용되는 업종·면허 정의 |
| `BidRequirementSet` | 요건 논리식의 루트 |
| `BidRequirement` | 개별 참가 요건 |
| `Qualification` | 사업자등록이 보유한 자격·확인 |
| `Sanction` | 사업자등록에 대한 제재 사건 |

`workType`은 분류명이 아니라 독립 속성/값 유형이다. 제목에서 분야를 생성하지
않고 공식 분류와 미분류 상태를 보존한다.

## 핵심 Link types

Link는 개념적으로 양방향이며 아래 표의 역방향 이름도 API 계약에 포함한다.

| Source -> Link -> Target | 역방향 | Cardinality |
|---|---|---|
| `Organization` -> `OWNS_CASE` -> `ProcurementCase` | `OWNED_BY` | 1:N |
| `Organization` -> `PUBLISHES` -> `BidNotice` | `PUBLISHED_BY` | 1:N |
| `BidNotice` -> `ANNOUNCES` -> `ProcurementCase` | `ANNOUNCED_BY` | N:1 |
| `BidNotice` -> `SUPERSEDES` -> `BidNotice` | `SUPERSEDED_BY` | 0..1:0..1 |
| `ProcurementCase` -> `HAS_LOT` -> `ProcurementLot` | `PART_OF_CASE` | 1:N |
| `BidNotice` -> `HAS_PARTICIPATION` -> `BidParticipation` | `PARTICIPATION_IN` | 1:N |
| `BidParticipation` -> `SUBMITTED_BY` -> `BusinessRegistration` | `SUBMITS` | N:1 |
| `BidNotice`/`ProcurementLot` -> `RESULTS_IN` -> `Award` | `AWARD_FOR` | 1:N |
| `Award` -> `HAS_RECIPIENT` -> `AwardRecipient` | `RECIPIENT_OF_AWARD` | 1:N |
| `AwardRecipient` -> `REPRESENTS` -> `BusinessRegistration` | `RECEIVES_AWARD` | N:1 |
| `Award` -> `ESTABLISHES` -> `Contract` | `DERIVED_FROM_AWARD` | 0..N:0..1 |
| `Organization` -> `BUYER_IN` -> `Contract` | `CONTRACTING_ORGANIZATION` | 1:N |
| `Contract` -> `FULFILLS` -> `ProcurementCase` | `FULFILLED_BY` | N:0..1 |
| `Contract` -> `HAS_VERSION` -> `ContractVersion` | `VERSION_OF` | 1:N |
| `Contract` -> `HAS_PARTY` -> `ContractParty` | `PARTY_TO_CONTRACT` | 1:N |
| `ContractParty` -> `REPRESENTS` -> `BusinessRegistration` | `PERFORMS_CONTRACT` | N:1 |
| `BidNotice` -> `USES_CLASSIFICATION` -> `ProcurementClassification` | `CLASSIFIES_NOTICE` | N:M |
| `BidNotice` -> `HAS_REQUIREMENT_SET` -> `BidRequirementSet` | `REQUIREMENTS_FOR` | 1:0..1 |

계약-only 사건은 `Award` link 없이 존재할 수 있고, 공고 연결도 확인되지 않으면
거짓 Link를 생성하지 않는다. 미확인 관계는 후보/evidence로 남기며 확정 Link로
승격하지 않는다.

## 상태와 사건

- `BidNotice.status`: scheduled, open, closed, failed, cancelled, superseded
- `Award.status`: pending, confirmed, revoked
- `Contract.status`: planned, active, completed, terminated, cancelled
- `BidParticipation.result`: unknown, unsuccessful, awarded, contracted

상태는 현재 관찰된 요약값이다. 상태 이력이 업무적으로 필요하면
`StatusObservation` 또는 원천 event object로 분리한다. `ContractVersion`은 단순
상태 이력이 아니라 법적·금액적 버전이므로 독립 객체다.

사용자 노출 단계인 `scheduled/open/closed/award/contract`는 여러 객체를 조합한
**derived lifecycle view**다. 이를 `BidNotice`의 영구 원천 상태 하나로 저장하지
않는다.

## Actions, Functions, Capabilities

Palantir식 Ontology는 명사뿐 아니라 업무 동작을 포함하지만, Teoria가 PPS, NTS,
FSC, MSS 등 외부 권위 원천의 사실을 수정할 권한은 없다.

Action 후보는 `ReviewBidParticipation`, `ApproveOntologyVersion`,
`ApproveSemanticBinding`, `ResolveIdentityCandidate`다. Action은 parameter,
submission criteria, effect, audit event를 가져야 한다.

반면 공고/낙찰/계약·기업정보 수집은 Prefect workflow, 정규화와 중복 제거는
Data transformation, 프로필·검색·분석은 read Capability 또는 Function이다.
Capability는 Ontology Action과 동의어가 아니며 Semantic Binding으로
객체·속성·관계와 연결한다.

## 현재 모델 처리 방침

| 현재 항목 | 판단 | 처리 |
|---|---|---|
| Organization, BidNotice, Award, Contract | KEEP/REFACTOR | stable concept 유지, 속성·링크 보완 |
| procurement.Company | REPLACE | `party.BusinessEntity`로 교체하고 UI 표시명은 업체/Company 유지 |
| company.LegalEntity | MERGE | 법인 유형의 `BusinessEntity`로 통합 |
| company.BusinessRegistration | KEEP/REFACTOR | `BusinessEntity`가 보유한 등록 단위로 유지 |

검토 가능한 최초 Draft 정의는
`platform/ontology-migrations/teoria-business-ontology-v1.yaml`이다. 이 manifest는
기존 Published Artifact를 수정하지 않고 `teoria` 0.1.0 Draft를 생성한다. Draft가
검증되기 전에는 기존 Capability Binding이나 Runtime Contract의 target을 바꾸지 않는다.

```bash
uv run --locked --package teoria-platform teoria apply-ontology-blueprint \
  --manifest platform/ontology-migrations/teoria-business-ontology-v1.yaml
```

전환 순서는 `Draft 생성 → source/data binding 작성 → 기존 capability binding 병행 생성
→ shadow 검증 → review/approve/publish → 구 stable concept binding deprecate`다.

현재 OpenMetadata에서 존재가 확인된 핵심 Column Binding 계획은
`platform/ontology-migrations/teoria-openmetadata-bindings-v1.yaml`에 둔다. Draft
Ontology에 대한 Binding은 `draft`로만 생성할 수 있으며 Ontology가 Published되기
전에는 승인할 수 없다.

```bash
uv run --locked --package teoria-platform teoria plan-openmetadata-bindings \
  --manifest platform/ontology-migrations/teoria-openmetadata-bindings-v1.yaml
```

원천 컬럼 자체가 아닌 사건 식별·최신 버전·귀속금액 정책은
`teoria-business-rules-v1.yaml`의 Business Rule로 관리한다. 운영 DB와의 shadow
검증은 기존 Runtime 값을 변경하지 않는 읽기 전용 명령으로 수행한다.

```bash
uv run --locked --package teoria-platform teoria apply-business-rules
uv run --locked --package teoria-platform teoria validate-ontology-shadow \
  --bid-notice-id R26BK01713978:000
```
| BidParticipation | KEEP/REFACTOR | 공고/업체 사이 association event로 명시 |
| ContractParticipation | RENAME/REFACTOR | `ContractParty`로 의미 명확화 |
| Award -> Company 직접 N:M | REPLACE | `AwardRecipient`를 통한 역할·지분 보존 |
| Contract -> Company 직접 N:M | REPLACE | `ContractParty`를 통한 역할·지분 보존 |
| 재공고 필드 묶음 | REPLACE | ProcurementCase + Notice lineage |
| 변경·차수계약 평탄화 | REPLACE | Contract + ContractVersion |
| 프로필/시장분석 response 객체 | KEEP OUT | Runtime Contract로만 유지 |
| 공식 분류 | REFACTOR | canonical classification 객체와 source/type 보존 |

## 첫 검증 질문

1. 기관이 게시한 현재 열린 공고는 무엇인가?
2. 원공고와 재공고를 하나의 사업으로 탐색할 수 있는가?
3. 특정 업체가 어느 공고에 참여했고 결과는 무엇인가?
4. 특정 낙찰의 모든 공동수급 업체와 역할·귀속금액은 무엇인가?
5. 하나의 원계약에 어떤 변경·차수 버전이 있으며 기준일 현재 금액은 무엇인가?
6. 계약-only 사건이 거짓 공고/낙찰 Link 없이 조회되는가?
7. 같은 기관과 업체의 과거 계약 관계를 원계약 기준으로 계산할 수 있는가?
8. 공식 분야가 동일한 과거 사업을 제목 추론 없이 찾을 수 있는가?

## 구현 순서

1. 현재 0.5.0과 모든 Source/Data DB의 실제 식별자·cardinality·누락률·충돌률을
   profiling한다.
2. `procurement` 새 Draft를 만들고 stable concept 유지/병합/교체 mapping을 작성한다.
3. `ProcurementCase`, `AwardRecipient`, `ContractVersion`, `ContractParty`를 추가한다.
4. Authoring 모델을 shared operational ontology와 namespaced module을 지원하도록
   보완한다. 단순 복제 객체는 만들지 않는다.
5. Data Asset/API Field/Capability Binding은 새 객체 모델이 publish된 뒤 재승인한다.
6. 기존 Capability를 동시에 실행해 object/link population과 집계를 비교한다.
7. Context Engine을 새 Published Artifact로 전환한 다음 0.5.0을 deprecate한다.

Capability Binding 커버리지 확대는 5단계 전까지 보류한다. 잘못된 객체 모델에
바인딩을 많이 만들수록 마이그레이션 비용만 커진다.

## 아직 결정할 사항

- `ProcurementLot`을 어느 원천 식별자까지 확보할 때 생성할지
- `Organization`과 `BusinessEntity`가 공통 `Party` interface를 구현할지
- 공동수급 지분 누락을 `unknown`으로 둘지 별도 observation으로 둘지
- 속성별 authority 우선순위와 원천 충돌 정책을 어디까지 공통화할지
- 읽기 전용 조달 플랫폼에서 Action runtime을 어느 단계에 도입할지

이 결정은 source schema가 아니라 실제 데이터 profiling과 첫 검증 질문의 결과로
확정한다.
