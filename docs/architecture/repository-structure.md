# Repository structure and ownership

경계는 코드 위치뿐 아니라 비밀정보, DB 권한과 배포 단위를 결정한다.

| 프로젝트 | 소유 | 제외 |
|---|---|---|
| `platform` | Business Ontology, Semantic Binding, Metadata Intelligence, Semantic Registry, Runtime, 직접 Source 실행, OpenMetadata REST integration | Prefect, MCP transport, OpenMetadata metadata 복제 |
| `pipelines` | Connector, Prefect, raw·정규화·적재, Data DB migration | Ontology, Capability, MCP |
| `mcp` | MCP Tool, protocol 변환, Runtime API client | Source 키, DB, Registry 실행 |
| `packages/provider_api` | API schema, request/response 검증, HTTP retry·오류 | Registry, Prefect, MCP |

## 통신과 의존

```text
pipelines ──SQL write contract──▶ Teoria Data DB
platform  ──SQL read contract───▶ Teoria Data DB
platform  ──REST reference──────▶ OpenMetadata
mcp       ──Runtime HTTP API────▶ platform
platform  ──▶ teoria-provider-api ◀── pipelines
```

- Pipeline 실행 코드는 Platform Runtime을 import하지 않는다.
- MCP는 Runtime API만 호출하며 Platform Runtime을 embedded import하지 않는다.
- `teoria-provider-api`는 Platform이나 Pipelines를 역으로 import하지 않는다.
- `common`, `shared`, `utils` 패키지는 만들지 않는다. 안정된 공통 계약만 이름 있는 패키지로 추출한다.
- 예외적으로 Pipeline 통합 검증 진입점은 Platform Registry를 지연 import할 수 있다.

`packages/`에는 둘 이상의 프로젝트가 실제로 사용하는 설치형 라이브러리만 둔다.
각 패키지는 독립 `pyproject.toml`, 테스트와 단일 책임을 가지며 Platform이나
Pipelines를 역으로 import하지 않는다. 미래 사용을 예상한 빈 패키지나
`common`, `shared`, `utils` 성격의 묶음은 만들지 않는다.

Platform 배포 이미지는 실행 경계에 따라 나눈다. `runtime` target은 Runtime 코드와
Registry만 포함하고, `authoring` target은 Admin·migration·검증에 필요한
`ontology_migrations/`, `references/`, `database/`를 추가로 포함한다.

## 계약 위치

| 목적 | 위치 |
|---|---|
| Runtime 직접 API·DB | `platform/registries/sources/` |
| 지속 수집 API | `pipelines/connectors/` |
| API→DB 정규화 | `pipelines/src/teoria_pipelines/domains/<domain>/<feature>/normalization.py` |
| Source·DB→Ontology 변환 | `platform/src/teoria/runtime/mapping/transforms/` |
| Data DB schema | `pipelines/database/migrations/` |
| Teoria Application DB schema | `platform/database/migrations/` |
| OpenMetadata REST boundary | `platform/src/teoria/metadata/openmetadata/` |
| Business Ontology v2 | `platform/src/teoria/ontology/` |
| Semantic Binding | `platform/src/teoria/binding/` |
| Metadata Intelligence | `platform/src/teoria/intelligence/` |
| Company 식별 기능 | `platform/src/teoria/domains/company/identity/` |
| 조달 질문 해석·계획·집계 | `platform/src/teoria/domains/public_procurement/context.py` |
| 조달 참가 가능성·시장 분석·분류·관리 API | `platform/src/teoria/domains/public_procurement/` |

Platform 내부에서도 실행 orchestration과 Domain 구현을 분리한다.
`runtime/capability/runner.py`는 등록된 handler를 호출하고 입력 바인딩,
Source 실행, timeout과 materialization을 소유한다. Domain별 processor와
query 후처리는 각 Domain의 `processors.py`에 등록하고
`runtime/composition.py`가 기본 구성을 조립한다. Registry의 processor 문자열을
임의 Python import 경로로 해석하지 않는다.

`context/service.py`는 의미 조회와 plan·execute의 정책 검증을 소유한다.
질문 해석과 결과 집계는 주입된 query handler가 담당하며 기본 구성은
`context/composition.py`에서 공공조달 handler를 선택한다. 새 기능 등록과
Domain 선택을 위해 공통 Runner나 Context Engine에 Domain별 분기를 추가하지 않는다.

공공조달 시장 분석은 `domains/public_procurement/market_analysis/` 안에서
프로필·참여·경쟁사·계약 이력·활동·공고 비교 기능별로 구현한다. `processor.py`는
기존 import의 호환 경로이며 새 호출은 기능 모듈을 직접 참조한다. Data DB
프로파일링과 identity shadow 검증은 Domain의 `data_profile.py`,
`identity_validation.py`가 소유하며 범용 `ontology/`에 조달 SQL을 두지 않는다.

시장 분석의 프로필·관계·계약·입찰 맥락·관련 사업은 각각 `profiles/`,
`relationships/`, `contracts/`, `bid_context/`, `related_projects/`에 묶는다.
SQL 문장은 `sql/`, DB 조회 경계는 `readers/`가 소유한다.

참가자격의 `assessment.py`는 단건·일괄 실행을 조립한다. `evidence_loader.py`는
근거 조회, `evidence_snapshot.py`는 snapshot 조합, `assessment_cache.py`는 캐시,
`outcomes.py`와 `expression_projection.py`는 판정 집계, `result_builder.py`는
Runtime 응답 객체 생성을 소유한다. 기능 테스트는 `tests/unit/domains/`에서
같은 Domain과 기능 위치를 따른다.

설정은 `settings.py`, 속성 의미 문맥 API는 `admin/property_context_api.py`,
Mapping 값 변환은 `runtime/mapping/transforms/`를 사용한다. 이전 `config.py`,
`semantic_api.py`, `mapping/functions/`, `market_context/`와 참가자격
`processor.py`는 호환용 재노출 경로다. 새 코드가 이 경로에 의존하지 않도록
architecture 테스트로 검사한다. 기존 HTTP 경로·codec ID·Registry ID는 유지한다.

Registry의 구조·타입·참조 검증은 `registry/validation/`이 소유한다. 참가자격
규칙 검증은 Domain의 `bid_eligibility/registry_validation.py`가 담당하고
`registry/composition.py`가 기본 검증기에 연결한다. CLI·Admin·Source 검증은
이 기본 구성을 사용한다. 실행과 검증의 evaluator 이름은 Domain의 동일한
등록 테이블을 기준으로 한다.

Admin의 `api.py`는 HTTP 앱 설정과 진입점이며 `composition.py`가 서비스와
Router를 조립한다. Registry 조회와 Ontology migration 보고서는 각각 이름 있는
Router로 분리한다. 조달 참가자격 조회와 현재 조달 migration 선택은 Domain이
소유한다. 기존 HTTP 경로·인증 정책·Registry ID는 코드 재배치로 변경하지 않는다.

시장 분석의 Reader는 `market_analysis/readers/` 안에서 프로필·관계·유사 사업·
참여·결과·활동·계약별로 분리하고 SQL import를 명시한다. `records.py`는
프로필 사건의 날짜와 참여 시각·Decimal 금액·누락값 계약을 검증하는 내부 Data DB
타입이며 Ontology 또는 Runtime Object가 아니다.
`profiles/participation_analysis.py`는 같은 업체·입찰 사건 집합의 관측 성공률과
별도 낙찰 실적을 구분한다. Data DB의 `runtime_bid_opening_collection_status`는
Runtime에 수집 상태만 노출하며 `ingestion` 스키마 권한을 확장하지 않는다.

Application DB의 `intelligence.application_attempts`는 승인된 Suggestion 적용의
실행 주체·시도·결과를 기록한다. 실행권 token은 재시도 전후의 작업을 구분하고
효과 시작·성공 기록은 외부 변경의 중복 실행을 막는다. Metadata entity 상태를
복제하지 않고 적용 결과의 참조만 보관한다. Ontology와 Binding의 상태 변경은
Ontology 소유 행을 먼저 잠그고 각 version·Binding을 검증한다.

Registry의 `domains/<domain>/`은 업무 소유권이며 Runtime 계약 namespace와
동일한 개념이 아니다. 계약은 `runtime_contracts/<contract_id>.yaml`에 둔다.
`company`는 `company` 계약을, `public_procurement`는 `public_procurement`와
`assessment` 계약을 소유한다. 참가자격 평가 Capability도 공공조달에 둔다.
새 파일명은 계약 ID와 일치하며 소유 폴더명과는 독립적이다. 이전 발행 구조의
`domains/<namespace>/runtime_contract.yaml`은 읽기 호환만 지원한다.

기존 Registry의 `assessment` namespace와 `assessment.*`, `market_context.*`,
`company_identity.*` processor ID는 게시된 계약의 호환성을 위해 유지한다.
`assessment`의 현재 기능 소유자는 공공조달이며 범용 평가 Domain을 뜻하지 않는다.
Python 코드 재배치로 Published Ontology 또는 artifact를 변경하지 않는다.
Registry 파일 이동은 경로를 포함하는 checksum이 달라지므로 새 release로 발행한다.
기존 Published release와 artifact를 직접 수정하지 않는다.

OpenMetadata의 entity 본문은 Platform DB에 저장하지 않는다. Binding에
필요한 `MetadataTargetRef`만 `teoria_app`에 정규화해 저장하며 이는
metadata cache가 아니다. Capability는 독립 knowledge source로 유지하고
Ontology와의 연결은 Semantic Binding으로 표현한다.

같은 수집 API를 Source와 Connector에 중복 등록하지 않는다. Pipeline이 적재한 DB는 Platform의 Database Source와 Mapping으로 Ontology에 연결한다.

## Prefect 구조

```text
src/teoria_pipelines/
├── domains/public_procurement/
│   ├── contracts/       flows.py, tasks.py, client.py, normalization.py
│   ├── bid_notices/     공고 수집·첨부문서 획득
│   ├── bid_results/     개찰·낙찰 수집
│   ├── industries/      업종 사전 수집
│   ├── bid_eligibility/ 문서 선택·모델 추출·검증·보정
│   └── provider_response.py  조달 API 응답·오류 처리
├── metadata/           격리된 OpenMetadata ingestion Job 실행
├── execution/          재사용되는 실행·Raw 저장·checkpoint Task
├── checkpoints/        cursor와 재개 정책
├── persistence/        raw·정규 데이터와 checkpoint 저장
└── flows/              기존 Prefect 배포 경로의 호환 import
```

- Flow는 얇게 유지한다.
- API 호출과 DB 쓰기는 Task로, 순수 변환은 일반 함수로 둔다.
- Deployment와 schedule은 `pipelines/prefect.yaml`에 둔다.
- Checkpoint는 모든 적재가 성공한 뒤 갱신한다.
- 새 배포 entrypoint는 기능 패키지의 `flows.py`를 가리킨다. 기존 `flows/`는
  같은 Flow 객체를 re-export하며 실행 구현을 복제하지 않는다.
- `pipelines/connectors/`의 YAML은 Provider wire 계약이고 기능 패키지의
  `client.py`는 호출 코드다. Reference·verification case와 Data DB migration
  위치는 유지한다.
- 참가자격의 Task는 실행 경계이며 `extraction.py`가 모델 실행을,
  `validation.py`와 `repair/`가 순수 근거 검증·의미 보정을 소유한다.
  폴더 재배치만으로 추출 의미·버전·입력 fingerprint를 변경하지 않는다.

## DB와 배포

- Pipeline 계정은 Data DB 쓰기, Runtime 계정은 정규 relation 읽기만 허용한다.
- MCP에는 Data DB 권한을 주지 않는다.
- migration과 Database Source 호환성은 통합 검증으로 확인한다.
- 각 배포 프로젝트는 자체 `pyproject.toml`과 Dockerfile을 갖고 루트 `uv.lock`을 공유한다.

배포 설정은 제품 이름이 아니라 실행 환경을 최상위 경계로 둔다.

```text
deploy/
├── compose/
│   ├── compose.yaml
│   ├── nginx/
│   └── openmetadata/   # Compose 전용 설정과 ingestion 예제
└── experimental/
    └── k3s/            # 아직 지원하지 않는 Kubernetes scaffold
```

Prefect와 OpenMetadata 서비스 정의는 모두 `compose.yaml`에 둔다. 특정
서비스의 Compose 전용 보조 파일만 `deploy/compose/<service>/`에 두며,
Kubernetes 배포가 지원 수준에 도달하기 전에는 모든 관련 scaffold를
`deploy/experimental/k3s/` 아래에 둔다.

```bash
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

새 기능은 의미·Runtime이면 `platform`, 지속 수집이면 `pipelines`, MCP protocol이면 `mcp`에 둔다.
특정 vertical domain의 정책은 해당 Domain Registry와 명시적인 기능 패키지에
두며, 두 번째 domain에서 재사용이 확인되기 전에는 Platform 공통 추상화로
승격하지 않는다.

## Naming

Teoria가 소유하는 repository path와 내부 ID의 기본 형식은 `snake_case`다.
예: `admin_ui/`, `runtime_client.py`, `get_company_profile.yaml`,
`001_create_runtime_tables.sql`. 예외는 도구 고정 이름, 외부 계약 원문,
`PascalCase`인 클래스·React 컴포넌트, `UPPER_SNAKE_CASE`인 환경변수와
`kebab-case`인 CLI·Docker·배포 리소스다. 기존 문서의 `kebab-case` 파일은
링크 호환을 위해 유지하며 신규 파일부터 이 규칙을 적용한다.

## 법령 데이터 수집

통합 자산 조회는 `platform/src/teoria/metadata/asset_context.py`와 Admin metadata router가
소유한다. 공공조달의 운영 read view 조회는 `domains/public_procurement/metadata_operations.py`,
Pipeline output 계약과 read view는 Pipeline의 `084_asset_collection_context.sql`이 소유한다.
조회 계정에 ingestion 스키마나 raw table 권한을 추가하지 않는다. 여러 DB의 정보를
요청 시 조합하며 OpenMetadata entity와 운영 상태를 Application DB에 복제하지 않는다.

`pipelines/src/teoria_pipelines/domains/legal_information/laws/`는 공식 API client,
Prefect Flow·Task, XML 파싱과 법령 저장 repository를 소유한다. 대상은
`pipelines/config/law_targets.yaml`, Data DB는 `legal_information` 스키마다.
법령 데이터 수집만 하는 정의는 `sink.type: data_database`를 사용하고 Runtime
Source를 요구하지 않는다. Runtime이 직접 읽을 때 Database Source 계약을 추가한다.
법령 문서 구조는 Business Ontology로 자동 발행하지 않는다.

법령 키워드 검색과 고정 snapshot 문서 조회는 Platform의
`domains/legal_information/search.py`와 `admin_api.py`가 소유한다. 현재 Admin
진단 기능이며 Runtime Capability·MCP Tool 등록은 별도 계약이다. Pipeline은
법령 검색용 읽기 view를 소유하며 Platform이나 Application DB로 법령을 복제하지 않는다.
OpenMetadata 저장 샘플·프로파일 조회는 `metadata/openmetadata/`와 Admin metadata
router가 소유한다. 샘플·프로파일 DTO는 일시 조회 응답이며 Teoria DB 모델이 아니다.
