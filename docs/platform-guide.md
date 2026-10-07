# Teoria platform guide

Teoria는 OpenMetadata가 관리하는 데이터 자산과 Teoria의 Business Ontology 및
Capability를 연결해 검증 가능한 business context를 제공한다. 전체 권위 경계는
[Architecture](architecture/overview.md)를 따른다.

## 저장소

| 경로 | 책임 |
|---|---|
| `platform/` | Ontology, Binding, Intelligence, Runtime, 직접 Source 실행 |
| `pipelines/` | Connector, Prefect, raw·정규 적재, Data DB migration |
| `mcp/` | MCP protocol과 Runtime HTTP client |
| `packages/provider_api/` | Provider wire 계약과 HTTP 실행 |
| `deploy/` | 지원되는 Compose와 실험 단계의 k3s 스캐폴드 |

## 로컬 실행

```bash
cp deploy/compose/.env.example deploy/compose/.env
export TEORIA_ENV_FILE=deploy/compose/.env
uv sync --locked --all-packages --all-groups
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml up --build -d
```

기본 진입점은 다음과 같다.

| 대상 | 주소/명령 |
|---|---|
| Admin UI | `http://localhost:8081/` |
| Admin API | `http://localhost:8081/admin-api/docs` |
| Runtime API | `http://localhost:8081/runtime-api/docs` |
| Prefect | `http://localhost:8081/prefect/` |
| MCP | `uv run --locked --package teoria-mcp teoria-mcp` |

OpenMetadata는 `metadata` profile로 선택 실행한다. 상세한 환경변수는
[Configuration](configuration.md), 서비스 운영은 [Deployment](../deploy/README.md)를
참고한다.

## 주요 작업 흐름

### 데이터 운영자

Connector와 Prefect Flow를 관리하고 raw·정규 적재가 모두 성공한 뒤 checkpoint가
이동하는지 확인한다. [Prefect guide](ingestion/prefect.md)를 따른다.

### Metadata 관리자

OpenMetadata에서 asset, schema, glossary, owner와 lineage를 관리한다. Teoria에는
OpenMetadata entity 본문을 복제하지 않는다.

Metadata Intelligence 제안은 Review Queue에서 승인한 뒤 유형별 application service가
적용한다. description, Glossary Term 생성·할당과 quality test는 OpenMetadata API를
사용하며 적용 전 대상 version을 다시 확인한다. AI가 직접 승인하거나 OpenMetadata를
임의 변경하지 않는다.
[Metadata Asset 분석 Skill](skills/analyze_metadata_asset.md)을 사용하면 현재
OpenMetadata 자산과 Ontology·Binding·Source 근거를 대조하여 Review Queue용 제안을
만들 수 있다.

### Ontology owner와 Binding reviewer

Published version에서 새 Draft를 만들고 review·approval 후 publish한다. Binding과
AI Suggestion은 승인 전까지 권위 정보가 아니다. 상세 계약은
[Ontology](architecture/ontology.md)를 따른다.
Ontology 변경 Suggestion 승인도 새 Draft와 변경 항목만 생성하며, 별도의 Ontology
review·approval·publish 단계를 생략하지 않는다.

### Capability 개발자

Runtime Object, Mapping과 Capability를 Domain Registry에 정의한다. 직접 실행 API는
Source, 지속 수집 API는 Connector로 작성한다. [Registry guide](registry/README.md)와
[Source authoring](registry/source-authoring.md)을 따른다.

기관·업체의 1·2단계 직접 계약관계는
`analyze_procurement_relationship_context`를 사용한다. 이 Capability는 기관 또는
업체를 기준으로 시작하며 단계마다 같은 기간·업무유형·조달분류 필터를 적용한다.
기존 프로필 Capability를 노드별로 반복 호출하지 않고 관계 ledger를 단계별 set query로
조회한다. 업체와 링크 금액은 귀속금액만 사용하며 누락값을 총계약금액으로 대체하지 않는다.
분야 필터가 없는 조회는 분류 코드가 없는 계약이 관계 ledger에 포함되지 않음을
`data_completeness`에 명시한다.

전체 조달관계 탐색은 `summarize_procurement_relationship_graph`로 게시된 스냅샷의
업무유형·분야 군집과 전체 크기를 먼저 조회한 뒤,
`search_procurement_relationship_graph_entities`로 선택한 군집을 페이지 조회한다.
무필터 overview는 snapshot 게시 시 최근 1년·3년·5년·전체 기간과
`work_type`·`field` 그룹을 별도 요약 테이블에 사전 계산한다. Runtime은 지원되는
기간의 overview에서 관계 행을 다시 집계하지 않고 이 요약만 조회한다.
후속 요청은 overview가 반환한 `graph_version`, 기간과 `cluster_id`를 그대로 전달해야
하며 cursor도 이 범위를 검증한다. 페이지는 업체 노드를 기준으로 분할하고 해당 업체의
기관과 모든 링크를 함께 반환한다. 스냅샷은 Pipeline이 매일 생성하며 7일간 보존하므로
Runtime은 화면 요청마다 원본 계약을 다시 집계하지 않는다. 두 응답 모두 분류되지 않은
계약이 관계 ledger에 포함되지 않는다는 완전성 상태를 명시한다.
`group_by=work_type`의 `cluster_id`는 업무유형(예: `service`)을 뜻하며 상세 조회는
해당 업무유형의 모든 분야 군집을 합쳐 반환한다. `group_by=field`의 `cluster_id`는
물리 분야 군집(예: `service:81112002`)과 일치한다.

그래프 버전은 매일 게시 후 자동 정리한다. 게시된 버전은 cursor 안정성을 위해
7일 동안 보존하고 최신 게시 버전은 기간과 관계없이 항상 보호한다. 완료되지 않은
`building` 버전은 1일 후 정리하며, 버전 삭제 시 상세·노드·overview 행도 외래키
cascade로 함께 제거된다.

### API/MCP 사용자

배포된 Runtime의 `/v1/capabilities`에서 사용할 수 있는 Capability와 입력 schema를
조회하고 `/v1/capabilities/{id}:execute`를 호출한다. MCP는 같은 Runtime API의
protocol adapter다.

Admin Context API는 `/v1/admin/context/plan`에서 질문의 concept, Capability,
입력, artifact와 정책 결정을 포함한 Semantic Query Plan을 반환하고,
`/v1/admin/context/execute`에서 동일 질문을 다시 계획·검증한 뒤 실행한다.
기존 `/v1/admin/context/query`는 호환용 deprecated alias다. Runtime Capability와
Context 계획·실행은 OPA 결정을 통과해야 하며 Compose는 OPA 장애 시 fail-closed한다.
정책 변경은 `deploy/compose/opa/bundle/`에서 수행한다. Compose의 bundle build job은
Rego 검사·테스트 후 RSA 서명 Bundle을 만들며 OPA는 서명과 scope를 검증한 뒤에만
활성화한다. 실행 입력은 masking policy로 decision log에서 제거하고 결정 ID, actor,
action, resource, 결과와 bundle revision은 Application DB audit에 보존한다.

## 검증

```bash
uv run --locked --package teoria-provider-api pytest packages/provider_api/tests
uv run --locked --package teoria-platform pytest platform/tests
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-mcp pytest mcp/tests
uv run --locked --package teoria-platform teoria validate platform/registries
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
docker compose -f deploy/compose/compose.yaml config --quiet
```
