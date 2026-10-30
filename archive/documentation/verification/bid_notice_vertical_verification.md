# Bid notice Context vertical 검증 보고서

검증 시각: 2026-10-07 UTC

## 지원 질문과 실제 결과

| 질문 | 실행 입력 | 실제 결과 |
|---|---|---|
| 최근 30일 동안 게시된 용역 입찰공고 | 최근 30일, `work_type=service` | 9,334건 |
| 추정가격 1억 원 이상인 소프트웨어 관련 공고 | 최근 1년 기본 범위, `query=소프트웨어`, `estimated_price_min=100000000` | 435건 |
| 근로복지공단이 게시한 현재 접수 중인 입찰공고 | 최근 1년 기본 범위, 기관 `Z004905`, `bid_status=open` | 1건 |

기간을 말하지 않은 질문에는 무제한 조회 대신 최근 365일을 적용하고
`default_period_applied` 경고를 반환한다. 결과는 첫 20개와 전체 건수를 함께
반환한다.

## 의미와 실행 계약

- Published Ontology: `teoria` 0.1.3
- 추가 속성: `teoria.BidNotice.estimatedPrice`, `teoria.BidNotice.workType`
- Capability: `search_bid_notices`
- 승인된 Capability Binding: 11개
- Runtime bundle: `2026.10.07.8`
- 실제 실행 Registry: `2026.10.07.7` 검증 후 metadata binding을 포함한
  `2026.10.07.8`로 재발행·활성화

OpenMetadata의 `runtime_bid_notices`에서 게시일시, 입찰상태, 추정가격,
업무유형과 공고기관코드 컬럼의 존재를 확인했고 각 컬럼을 Ontology property에
authoritative data asset binding으로 승인했다.

## 데이터 품질 측정

| 조건 | 행 | 고유 ID | 게시일 결측 | 마감일 결측 | 추정가격 결측 |
|---|---:|---:|---:|---:|---:|
| 최근 30일 용역 | 9,334 | 9,334 | 0 | 1,148 | 4 |
| 최근 1년 소프트웨어·1억원 이상 | 435 | 435 | 0 | 57 | 0 |
| 근로복지공단 접수 중 | 1 | 1 | 0 | 0 | 0 |

마감일과 추정가격은 업무적으로 nullable하므로 결과에서 누락을 보존한다.
OpenMetadata 컬럼 description, Glossary Term과 Test Suite는 아직 없으며 quality
상태는 `unavailable`로 반환한다. 이것은 실행 실패가 아니라 metadata governance
후속 작업이다.

## 현재 범위

이 vertical은 정해진 표현을 deterministic parser로 해석한다. 일반 자연어 AI
planner가 아니며, 지원하지 않는 금액 단위·상대기간·복합 논리는 추측하지 않는다.
