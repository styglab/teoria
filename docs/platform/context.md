# Context의 의미 조회·계획과 실행

Context Engine은 게시된 Ontology와 승인된 Binding을 조회하고,
등록된 업무 query handler의 계획·실행 전후에 정책을 검증하는 기반이다.
현재 물품 검색·비교 handler는 아직 등록하지 않았다.
이전 계약금액·공고 검색 handler와 질문 테스트 UI는 비활성 보관했다.

## 현재 지원 범위

| 기능 | 상태 |
|---|---|
| 게시된 의미·승인된 연결 조회 | 유지 |
| query handler 주입과 계획·실행 정책 검사 | 유지 |
| 기존 계약금액·공고 질문 | 제공 종료 |
| 추출 물품 검색·비교·AI 질문 | 후속 구현 |

현재 `plan`·`execute`에 질문을 제출하면 handler 미구성 오류를 반환한다.
과거 조달 기능으로 fallback하거나 추측한 답을 만들지 않는다.
AI가 추출 결과를 Published Ontology에 자동 등록하는 기능도 제공하지 않는다.

## Admin API 사용

| API | 역할 |
|---|---|
| `GET /v1/admin/context/resolve?term=...` | 게시된 의미와 활성 bundle의 승인 연결 조회 |
| `POST /v1/admin/context/plan` | 등록된 handler의 실행계획 작성 |
| `POST /v1/admin/context/execute` | 질문에서 계획을 다시 만들고 실행 |
| `POST /v1/admin/context/query` | execute의 deprecated 호환 경로 |

plan·execute는 Admin bearer 인증을 사용한다. OPA는 계획과 실행을 각각 검증하며
정책 서비스가 응답하지 않으면 운영 요청을 허용하지 않는다.
`execute`는 앞서 받은 plan JSON이나 plan ID를 재생하는 API가 아니다.

## 새 handler 연결

`platform/src/teoria/context/query.py`의 계약을 구현하고 `context/composition.py`에서 등록한다.
공통 Engine은 의미 조회·정책 검증을, 업무 handler는 질문 해석·입력 구성·결과 처리를 담당한다.
필요한 Capability·Semantic Binding·Mapping을 실제 데이터로 검증한 뒤 [새 Runtime bundle](runtime.md)에 고정한다.
범용 AI planner나 자유로운 객체 편집의 완료로 간주하지 않는다.
