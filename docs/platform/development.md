# Platform 개발 안내

Platform은 Ontology·Semantic Binding·Metadata Intelligence와 Source·Mapping·Capability·
Context 실행을 소유한다. 현재 업무는 물품 규격서 결과를 의미 모델에 연결하는 방향으로 재구성했다.
법령 검색은 `domains/legal_information/`에서 활성 운영하며 Admin과 자산 진단에 연결한다.
기존 기업·공고·계약·낙찰 업무 구현은 `archive/procurement_services/`에 비활성 보관했다.
규격서 파싱·추출은 [Pipelines](../pipelines/development.md)의 책임이다.

## 먼저 찾을 위치

| 경로 (`platform/` 기준) | 책임 |
|---|---|
| `src/teoria/entrypoints/`, `cli/` | HTTP·CLI 실행과 조립 |
| `src/teoria/admin/` | 인증된 관리 API·서비스 조립 |
| `src/teoria/ontology/`, `authoring/` | Ontology 작성·검토·게시·artifact |
| `src/teoria/binding/` | Stable Concept와 의미 연결 |
| `src/teoria/metadata/` | OpenMetadata client와 자산 맥락 |
| `src/teoria/intelligence/` | Suggestion·검토·적용과 자산 진단 |
| `src/teoria/runtime/` | Source·Mapping·Capability 실행 |
| `src/teoria/context/`, `policy/` | 의미 조회·계획·실행 정책 |
| `src/teoria/registry/`, `registries/` | 계약 검증·발행·bundle 구성 |
| `ontology_blueprints/goods.yaml` | 물품 Ontology 초기 Draft 모델 |
| `database/migrations/` | Application DB migration |
| `admin_ui/src/features/` | 관리 UI |

## 실행 진입점

`teoria-admin-api`, `teoria-runtime-api`, `teoria-policy-control-plane`을 유지한다.
선택적 `teoria-metadata-assessment-worker`는 모델 gateway를 설정한 경우 사용한다.
`teoria`는 Registry·bundle·Ontology·Binding 관리 명령이다.
현재 활성 Registry는 공통 타입만 포함하며 업무 Capability discovery는 빈 목록이다.

## Domain 기능을 추가하는 방법

새 물품 기능은 이름 있는 Domain 패키지에 두고 공통 Runner에 업무별 분기를 넣지 않는다.
명시적인 processor·query hook은 `runtime/composition.py`에서 등록한다.
선언형 Source·Mapping 조회는 공통 Runner를 그대로 사용할 수 있다.
현재 기본 handler 집합은 비어 있으며 archived Python 모듈을 역으로 import하지 않는다.
Context는 `context/query.py` 계약과 `context/composition.py`의 등록 경계를 따른다.

물품 Ontology의 새 의미는 Draft에서 검토·승인·게시한다.
추출 표준의 자동 채택과 문서별 관찰을 Business Ontology 게시로 혼동하지 않는다.
Source record→Runtime Object의 Mapping과 개념↔자산·용어·Capability의 Binding도 구분한다.

## I/O와 동시 실행

HTTP·DB 호출은 API→Service→Repository까지 native async로 연결한다.
PostgreSQL은 `persistence/postgres.py`의 `connect()`를 사용하고 transaction 순서를 보존한다.
`TEORIA_DATABASE_CONCURRENCY_LIMIT`는 event loop별·접속 URL별 연결 상한이다.
계산·검증은 일반 함수로, 불가피한 동기 I/O는 제한된 별도 실행으로 둔다.
인증된 principal을 Admin 쓰기의 actor로 기록한다.

## 개발 실행과 검증

```bash
uv run --locked --package teoria-platform teoria-admin-api
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-platform teoria validate platform/registries
```

Application DB 통합 검사는 운영과 분리한 `TEORIA_TEST_APP_DATABASE_URL`을 사용한다.
미설정 시 DB 의존 검사는 건너뛸 수 있다. 적용 SQL·Published revision·artifact는 수정하지 않는다.
새 migration을 추가하면 전체 Platform 테스트와 Compose 설정 검사를 수행한다.

## 작업별 상세 안내

- [Ontology와 Binding](ontology.md), [Runtime bundle](runtime.md), [Context](context.md)
- [Registry](registry/guide.md), [Source 작성](registry/source_authoring.md), [Mapping](registry/mappings.md), [Capability](registry/capabilities.md)
- [Admin UI](admin_ui.md), [자산 맥락](metadata/asset_context.md), [자산 진단](metadata/asset_assessment.md), [제안 처리](metadata/suggestions.md)
