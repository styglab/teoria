# Context vertical 검증 보고서

검증 시각: 2026-10-07 UTC

이 문서는 대표 질문 하나를 사용해 Ontology, Semantic Binding, OpenMetadata,
Capability, Runtime과 실제 Data DB가 끝까지 연결되는지 검증한 결과다.

## 검증 질문

> 근로복지공단의 최근 5년 계약금액을 알려줘

기준일은 `2026-10-07`이며 대상 기간은 `2022-01-01`부터
`2026-10-07`까지다.

## 판정

**실제 데이터 실행 경로와 기본 semantic path가 입증됐다.** 컬럼과 Glossary
Term의 연결은 OpenMetadata의 중첩 컬럼 필드를 명시 조회해 확인했고, Teoria의
Suggestion → Review → Application 이력도 남겼다. Metadata quality test는 아직
없으므로 이 vertical은 `실행·의미 연결 검증 완료`, `quality 검증 미완료`로 판정한다.

현재 Registry 원본과 Admin API의 Capability 수는 모두 **46개**다. Runtime API는
이 중 public exposure인 **29개**를 노출한다. 따라서 이전 화면에서 관찰된
52개는 현재 Registry 기준 숫자가 아니며 준비도 판단에 사용하면 안 된다.

| 검증 단계 | 결과 | 관찰된 근거 |
|---|---|---|
| Published Ontology | 통과 | `procurement.Contract.currentAmount`, 단위 `KRW`, artifact checksum `3d912a41...95673` |
| 승인된 Capability Binding | 통과 | analytics route가 `search_public_procurement_contracts`로 선택됨 |
| Capability 실행 계약 | 통과 | 날짜와 기관코드 입력 후 24페이지 실행 |
| 실제 Data DB 대조 | 통과 | API와 DB 모두 계약 2,323건, 결측 0건, 합계 1,257,472,414,585원 |
| Registry provenance | 통과 | Published Registry `2026.10.07.6`, checksum과 Git commit 반환 |
| OpenMetadata asset 존재 | 통과 | 계약 테이블과 `current_contract_amount` 컬럼 조회 성공 |
| OpenMetadata glossary 존재 | 통과 | `Procurement.ContractAmount` 조회 성공 |
| Physical Asset → Glossary Term | 통과 | 컬럼에 `Procurement.ContractAmount`, `Manual/Confirmed` 적용 확인 |
| Review/Application 이력 | 통과 | Suggestion `6bd68784-1427-42e8-9196-40048db1586a`가 `system:admin` 승인 후 applied |
| 실행 시 metadata 조회 | 통과 | Admin 연동 활성화 후 두 entity 모두 `available=true` |
| 데이터 freshness 계약 | 통과 | Runtime object의 `source_registered_at` 최댓값을 실행 검증에 기록 |
| Metadata quality test | **실패** | OpenMetadata table의 `testSuite`가 없음 |

## 실행 증거

Context Engine은 질문을 다음과 같이 해석했다.

```text
업무 개념: procurement.Contract.currentAmount
기관: 근로복지공단본부 (Z004905)
기간: 2022-01-01 ~ 2026-10-07
Capability: search_public_procurement_contracts
금액 필드: current_contract_amount
```

Runtime 결과는 다음과 같다.

```text
상태: complete
고유 계약 수: 2,323
금액 존재 계약 수: 2,323
합계: 1,257,472,414,585 KRW
실행 페이지: 24
실패 페이지: 없음
```

동일 조건으로 `public_procurement.runtime_contracts`를 직접 집계한 결과도
다음과 같았다.

```text
rows: 2,323
distinct unified_contract_number: 2,323
null current_contract_amount: 0
sum(current_contract_amount): 1,257,472,414,585
latest_update: 2026-10-06 17:49:57.861539+00
```

따라서 이 결과는 UI mock이나 Capability 선언만으로 만들어진 값이 아니라 실제
Data DB를 Runtime이 읽어 계산한 값이다.

## 의미 연결 증거와 결손

승인된 Binding에는 아래 두 OpenMetadata reference가 존재한다.

```text
openmetadata://column/
  teoria_postgresql.teoria_data.public_procurement.contracts.current_contract_amount

openmetadata://glossaryTerm/Procurement.ContractAmount
```

OpenMetadata에서 두 entity를 실제 조회할 수 있었고 설명도 존재했다.

- 테이블: 조달 원계약과 변경·차수계약의 최신 계약 상태 및 금액을 관리하는 정규화 테이블
- Glossary Term: 계약 사건에서 확정된 통화 기준 계약금액

`fields=columns`를 포함해 조회한 결과 `current_contract_amount` 컬럼에는
`Procurement.ContractAmount`가 `Manual/Confirmed` 상태로 적용돼 있었다. 기본
조회 응답에서 중첩 tag가 생략되는 것을 tag 부재로 판정하지 않아야 한다.

```text
Physical Column → Procurement.ContractAmount → procurement.Contract.currentAmount
```

Admin 배포의 OpenMetadata 연동을 활성화했고 Context 응답에서 entity 가용성,
metadata 수정 시각과 실제 Runtime object의 source freshness를 구분해 반환한다.

## 다음 완료 조건

이 vertical을 완결하려면 다음 조건을 모두 충족해야 한다.

1. `current_contract_amount`에 대한 OpenMetadata quality test를 정의하고 실행한다.
2. 같은 검증을 대표 질문 3~5개에 반복하고 통과한 Capability만
   `verified`로 구분한다.

이 조건 전에는 전체 Registry가 준비됐다고 표현하지 않고, **한 Context vertical의
실행과 의미 연결은 검증됐으며 quality와 나머지 Capability는 미검증**이라고 표현한다.

## 다음 후보 준비도 감사

대표 후보 5개를 동일한 binding coverage 기준으로 감사했다. 종단 검증을 통과한
것으로 취급하는 것은 첫 항목뿐이다.

| Capability | 현재 상태 | 차단 사유 |
|---|---|---|
| `search_public_procurement_contracts` | vertical 검증 | Context에 필요한 금액 output은 승인됐으나 전체 Capability coverage는 partial |
| `get_bid_notice` | partial | 입력 2개와 관계 output 1개가 미연결 |
| `search_bid_notices` | unbound | 입력 22개와 output 3개가 미연결 |
| `search_public_organizations` | unbound | 입력 6개와 output 1개가 미연결 |
| `search_companies_by_name` | unbound | 입력 1개와 output 5개가 미연결 |

준비도 수치를 억지로 높이기 위해 pagination이나 free-text 같은 기술 입력을 업무
개념에 연결하지 않는다. 다음 vertical 질문을 먼저 정한 뒤 필요한 의미만 승인한다.
