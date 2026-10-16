# Context의 의미 조회·계획과 실행

Context는 업무 표현을 승인된 의미·Capability와 연결하고, 허용된 질문을 실행계획으로
바꾼 뒤 Runtime을 호출한다. 현재 기본 handler는 공공조달의 정해진 질문 형식을
처리한다. 임의 업무 질문을 해석하는 범용 자연어 planner의 완료를 뜻하지 않는다.

## 현재 지원 범위

| 질문 유형 | 처리 |
|---|---|
| 기관의 최근 N년 계약금액 | 기관 식별, 승인된 analytics 경로 선택, 계약 조회·페이지 집계 |
| 공고 검색 | 기간·업무구분·접수 상태·지원 키워드 등을 해석해 `search_bid_notices` 실행 |

예를 들어 `근로복지공단의 최근 5년 계약금액을 알려줘`는 계약금액 질문 형식이다.
기간은 `as_of`와 질문에서 계산한다. 의미·기관·승인 경로를 찾지 못하면 실행하지 않는다.
계약 검색 결과 집계는 프로필의 계약사건 집계와 자동으로 같은 의미가 되지 않으므로
[계약 집계 기준](domains/public_procurement/contract_aggregation.md)과 혼용하지 않는다.

## 요청 처리 순서

```text
질문·기준일 → context.plan 정책 검사 → 의미·기관·실행 경로 조회 → 계획
→ context.execute 정책 검사 → Runtime Capability 실행 → 집계·근거·불확실성 반환
```

계획에는 `schema_version`, 질문·기준일, concept·ontology, Capability ID, inputs와
해석·선택 이유·근거·경고가 들어간다. 계획의 정책 결정과 실행의 정책 결정은 구분한다.
실행 결과는 부분 실패, freshness와 metadata quality 상태를 보존한다.

계획 작성 중 기관 식별·지원 계약 확인을 위해 Runtime 조회를 할 수 있다.
`plan`을 외부 호출이 전혀 없는 순수 계산으로 간주하지 않는다.

## Admin API 사용

| API | 입력과 동작 |
|---|---|
| `GET /v1/admin/context/resolve?term=계약금액&purpose=analytics` | 게시된 의미·승인된 연결과 목적별 경로 조회 |
| `POST /v1/admin/context/plan` | 질문과 선택적 `as_of`로 계획 작성 |
| `POST /v1/admin/context/execute` | 질문으로 계획을 새로 작성하고 정책 검사 후 실행 |
| `POST /v1/admin/context/query` | execute와 같은 동작의 deprecated 호환 경로 |

plan·execute는 관리자 인증을 사용한다. 요청 예는 다음과 같다.

```json
{
  "question": "근로복지공단의 최근 5년 계약금액을 알려줘",
  "as_of": "2026-10-16"
}
```

`execute`는 앞서 받은 plan JSON이나 plan ID를 입력받지 않는다. 같은 질문도 실행 시점의
참조·데이터 상태에 따라 계획이 달라질 수 있다. 저장된 계획의 승인·재실행 계약은 현재
API로 제공하지 않는다. 전체 요청·응답과 인증 조건은 배포된 Admin OpenAPI를 확인한다.

## 준비할 연결과 실패 확인

Admin의 Context repository는 명시한 Runtime bundle path·store를 우선하고, 해당 설정이
없으면 Application DB를 사용한다. 운영 의미·계약을 고정하는 배포는
[Runtime bundle](runtime.md) 안내를 따른다. 질문 실행에는 Runtime URL·service token이
필요하다. OpenMetadata 연결은 근거 조회에 사용하며 entity 본문을 Teoria DB에 복제하지 않는다.

| 상태 | 먼저 확인할 내용 |
|---|---|
| `context_engine_unavailable` | bundle 또는 Application DB 연결 |
| `context_runtime_unavailable` | Runtime client 설정·접속 |
| `context_not_resolved` | 지원 질문 형식·기간·기관·승인된 의미 경로 |
| `policy_denied` | principal·역할과 정책 결정 이유 |
| `policy_unavailable` | OPA 연결·준비 상태 |

운영은 OPA 정책 장애 시 요청을 허용하지 않는다. 기간·최대 페이지·Runtime timeout은
[환경 설정](../deployment/configuration.md)에 설명한다. UI의 질문 테스트 사용법은
[Admin UI](admin_ui.md)를 참고한다.

## 수정할 코드와 검증

`platform/src/teoria/admin/context_api.py`는 HTTP, `context/service.py`는 의미 조회·정책,
`context/query.py`는 handler 계약, `context/runtime_client.py`는 Runtime HTTP 호출을
소유한다. `context/composition.py`가 기본 handler를 조립한다.
`domains/public_procurement/context.py`는 질문 파싱·계획 구성·결과 집계를 담당한다.

Domain 질문을 늘릴 때는 handler를 확장하고 공통 Engine에 Domain별 분기를 추가하지 않는다.
회귀 테스트는 `platform/tests/unit/context/test_context_engine.py`와
`platform/tests/unit/admin/test_context_api.py`에 있다. 코드 변경과 전체 검증은
[Platform 개발](development.md), 시점별 실행 증거는
[Context 검증 기록](../verification/vertical_slice_verification.md)을 참고한다.
