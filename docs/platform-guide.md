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

수집 코드는 `pipelines/src/teoria_pipelines/domains/<domain>/<feature>/`에서
Flow·Task·client·정규화를 함께 관리한다. 여러 수집 작업이 사용하는 실행 관리는
`execution/`, DB·Object Storage 접근은 `persistence/`에 둔다.
OpenMetadata ingestion Job은 `metadata/`가 소유한다. 새 Prefect 배포는 기능별
Flow 경로를 사용하며 기존 `flows/` 경로는 호환 진입점으로 유지한다.
공공조달 개찰 보강은 전체 API 응답을 검증한 뒤 상위 10위·낙찰자 업체 집합과
정규 저장 결과를 대조해 완료한다. 전체 참가자 수를 저장 대상 수로 사용하지 않는다.
기존 backlog와 과거 계약 gap은 [Connector guide](ingestion/connectors.md)의
완료·재검증 기준에 따라 처리한다.

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

Suggestion 적용은 승인된 제안별 실행권과 만료 시간으로 중복 실행을 막는다.
변경을 시작하기 전의 실패는 같은 승인으로 재시도할 수 있다. 외부 변경이 시작된
작업은 결과 확인 전까지 다시 쓰지 않는다. 적용 성공 기록은 최종 상태 갱신과
분리해 남겨 DB 기록 실패 후 복구할 수 있게 한다. 인증된 검토자는
`POST /v1/admin/intelligence/suggestions/{suggestion_id}/applications/reconcile`로
복구한다. 이 경로는 OpenMetadata를 수정하지 않고 성공 기록 또는 현재 description·
Glossary 할당을 읽어 확인한다. 결과를 증명할 수 없는 생성 작업은 검증 필요로
유지한다. 재시도·복구 주체와 이전 시도 이력을 Application DB에 기록한다.

### Ontology owner와 Binding reviewer

Published version에서 새 Draft를 만들고 review·approval 후 publish한다.
수정·검토·게시와 Binding 승인은 동일 Ontology의 잠금 규칙을 따른다. 게시할
본문의 검증·조회·checksum·상태 전환·감사 기록은 같은 트랜잭션에서 처리하며
동일 Ontology의 Published version은 하나만 허용한다. Binding과
AI Suggestion은 승인 전까지 권위 정보가 아니다. 상세 계약은
[Ontology](architecture/ontology.md)를 따른다.
Ontology 변경 Suggestion 승인도 새 Draft와 변경 항목만 생성하며, 별도의 Ontology
review·approval·publish 단계를 생략하지 않는다.

### Capability 개발자

Runtime Object, Mapping과 Capability를 업무 소유 Domain Registry에 정의한다.
`domains/<domain>/runtime_contracts/<contract_id>.yaml`에서 폴더는 업무 소유자를,
파일명과 `runtime_contract.id`는 실행 계약 namespace를 나타낸다. 조달 평가의
`assessment` 계약과 두 평가 Capability는 `public_procurement`가 소유한다. 직접 실행 API는
Source, 지속 수집 API는 Connector로 작성한다. [Registry guide](registry/README.md)와
[Source authoring](registry/source-authoring.md)을 따른다.

코드로 구현하는 Capability는 `platform/src/teoria/domains/<domain>/`에 두고 해당
Domain의 `processors.py`에서 handler를 등록한다. 기본 Runtime 구성은
`runtime/composition.py`가 조립하며 공통 Runner에 processor별 분기를 추가하지 않는다.
query 결과 후처리도 Domain에 등록한다. 현재 조달 질문 해석·계획·집계와 입찰
참가 가능성·시장 분석·분류 구현은 `domains/public_procurement/`가 소유한다.
Context Engine은 query handler를 주입받아 plan과 execute의 정책 검증을 수행한다.

시장 분석 코드는 `market_analysis/`의 기능별 하위 폴더와 참여·활동 모듈에서
찾는다. 세부 소유권은 [시장 분석 모듈 안내](../platform/src/teoria/domains/public_procurement/market_analysis/README.md)를
따른다. 조달 데이터 profile·shadow 검증과 참가자격 Registry 검증도 같은 Domain이
소유한다. Admin 서비스 조립은 `admin/composition.py`, Registry의 기본 검증
조립은 `registry/composition.py`가 담당한다.

Platform 설정은 `src/teoria/settings.py`에서 관리한다. 참가 가능성 평가의
실행·근거·캐시·판정·결과 생성은 `bid_eligibility/`의 이름 있는 모듈에 나뉘어
있으며 Domain 테스트도 같은 기능 위치를 따른다. 호환 모듈은 이전 import만
지원하고 새 구현은 정식 경로를 사용한다.

공공조달 기관·업체 프로필의 참여 분석은 `outcome.participation_analysis`에
관측 참여·확정 결과·그중 낙찰·성공률의 분자와 분모를 제공한다. 수집 중인
연도의 미관측 참여는 표시용 `null`과 `수집 중` 상태로 구분하고, 상위 10위와
원천 응답에 있는 최종 낙찰업체만 보존하는 범위를 명시한다. 전체 성공률은
추정하지 않는다. 도움말과 화면은 입찰체크에서 구현한다.

공공조달 기관·업체 프로필의 계약 건수, 변경계약 병합, 연도 귀속과 공동수급 금액은
[공공조달 계약 집계 기준](domains/public_procurement/contract_aggregation.md)을 따른다.
이 규칙은 첫 vertical의 Domain 규칙이며 Platform 공통 집계 규칙으로 간주하지 않는다.
물품·용역·공사의 현재 분야 표시 기준과 향후 버전형 분류체계의 범위는
[공공조달 분야 분류 기준과 확장 계획](domains/public_procurement/procurement_classification.md)에
정의한다.

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

## 법령 근거 수집 기반

법제처 법령 목록·본문은 `pipelines`의 `legal_information/laws`에서 수집한다.
법령 ID·MST·시행일을 구분하고 원문 hash와 파서 버전별 snapshot을 Data DB에
보존한다. 이 단계는 근거 저장소이며 Business Ontology, 법률 판정, 위험등급
태깅과 OpenMetadata 적용 기능을 제공하지 않는다.
[법령 수집 실행 및 경계](ingestion/law_collection.md)를 참고한다.

### 데이터 관측 근거와 법령 검색

Data Assets 상세에서 OpenMetadata 저장 샘플·최신 프로파일을 조회한다.
샘플 값은 기본적으로 가리고 `metadata_sample_reader` 역할이 있을 때만 원천이
허용한 값을 표시한다. 미수집과 권한 오류를 구분하며 Teoria DB에는 복제하지 않는다.
[샘플·프로파일 조회](ingestion/metadata_data_evidence.md)를 참고한다.

법령 검색은 인증된 Admin API의 키워드 검색과 snapshot 기반 문서 조회로 시작한다.
아직 Runtime Capability·MCP Tool 또는 임베딩 검색 기능은 아니다.
[검색 계약](ingestion/law_collection.md)을 참고한다.
현재 OpenMetadata 1.12.6과 최신 안정 릴리스 2.0.5의 차이는
[업그레이드 검토](architecture/openmetadata_upgrade_assessment.md)에 정리했다.
