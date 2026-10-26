# 저장소 구조와 소유권

Teoria는 하나의 Python 백엔드와 별도의 React 프런트엔드로 구성한다.
제품 경계는 AI-Native Metadata & Ontology Platform이며 공공조달은 첫 vertical이다.
업무 코드의 소유권과 데이터 권위는 [아키텍처](overview.md)를 따른다.

## 기준 위치

```text
backend/
  pyproject.toml          # 유일한 활성 Python 프로젝트와 실행 명령
  uv.lock                # 백엔드 의존성 잠금
  src/teoria/
    features/            # 기능의 실행·타입·저장소·라우터
    integrations/        # 외부 시스템 연결과 재사용되는 실행 기반
    entrypoints/         # HTTP·MCP·CLI 시작과 서비스 조립
    settings.py          # API 서비스 설정
  tests/                 # 기능·연결·진입점·DB 통합·구조 검증
  contracts/
    runtime/             # Core·Source·Runtime Object·Mapping·Capability 계약
    ingestion/
      connectors/        # 수집 전용 Provider 계약
      pipelines/         # Operation·저장 대상·근거 보존 정책
  config/                # 기능별 운영 입력·수집 대상
  references/providers/  # Provider 원문과 근거
  verification_cases/    # runtime/·ingestion/ 계약 검증 입력
  authoring/
    ontology_blueprints/ # Draft 작성 입력
    ontology_migrations/ # pending 입력과 applied 이력
  migrations/
    application/         # Ontology·Binding·Suggestion·승인 이력
    data/                # 수집·규격서 실행 상태와 산출물 참조
frontend/
  src/app/               # 라우팅·앱 조립
  src/features/          # 기능별 화면
  src/components/        # 실제 재사용하는 UI 컴포넌트
  src/api/               # 관리 API HTTP 계약
  src/lib/               # UI에서 실제 공유하는 기반 코드
deploy/
  prefect/               # Flow schedule·pool·배포 선언
  compose/               # 로컬 서비스 배포
  k3s/                   # EC2 서비스 배포
```

`src/teoria`는 Python import namespace다. 프런트엔드의 `src/app`은 앱 조립 위치이며
Python 패키지 이름과 대응시키지 않는다. 문서의 기존 `docs/platform/`, `docs/pipelines/`,
`docs/mcp/`, `docs/packages/` URL은 링크 호환을 위해 유지한다.

## 기능별 소유권

아래 경로는 `backend/src/teoria/` 기준이다.

| 위치 | 책임 |
|---|---|
| `features/semantic_modeling/ontology/` | 지속 가능한 업무 의미·Draft·검토·게시 |
| `features/semantic_modeling/binding/` | Stable Concept ID와 외부 의미 대상의 연결 |
| `features/semantic_modeling/ontology/service.py`, `repository.py` | 작성·검토·게시 정책과 transaction 내 저장 |
| `features/semantic_modeling/registry/` | 계약 검증·immutable bundle·공개 Mapping codec |
| `features/specification_processing/` | 명시 입력 문서 파싱·정보 추출·고정 표준 적용·평가·Flow |
| `features/goods_normalization/candidates/` | 표준 후보 제안·AI 의미 판정·Draft 작성 |
| `features/goods_normalization/profiles/` | `service.py`의 프로파일 정책과 `repository.py`의 저장·감사 |
| `features/goods_normalization/contracts/` | 발행과 적용이 공유하는 versioned 데이터 계약 |
| `features/goods_querying/` | 서버 요구조건 비교·원문 근거 조회의 Runtime 처리기 |
| `features/metadata_management/` | 자산 맥락·Suggestion/Review/Application·AI 진단·메타데이터 ingestion |
| `features/legal_information/` | 법령 조회와 `collection/`의 수집·구조화·적재 |
| `features/runtime/` | 게시 artifact의 Source·Mapping·Capability·Context 실행 |
| `features/access_control/` | 인증 principal·권한 정책·OPA 제어 |
| `integrations/provider_api/` | Provider wire 계약·요청 생성·응답 검증·HTTP 실행 |
| `integrations/openmetadata/` | OpenMetadata 연결 |
| `integrations/codex/` | JSON 전용 subprocess 추론·시간 제한·취소 |
| `integrations/prefect/` | 배포 등록·pool·queue·동시 실행 정책 |
| `integrations/data_operations/` | 실제 재사용하는 수집 계약·실행·checkpoint·Data DB 연결 |
| `integrations/application_database/` | Application DB async 연결과 migration 실행 |
| `integrations/runtime_http/` | Runtime HTTP client와 구조화 오류 |
| `entrypoints/mcp/` | MCP STDIO·Tool·protocol schema·환경 설정 |
| `entrypoints/` | 관리·Runtime HTTP 앱 조립, MCP STDIO, CLI 프로세스 |

기능 내부에 필요한 API·모델·서비스·저장소를 함께 둔다. 모든 기능에 동일한 계층이나
빈 디렉터리를 만들지 않는다. 조달 고유 정책을 두 번째 domain의 실제 재사용 없이
공통 기반으로 승격하지 않는다. 공고·계약·기업 분석과 구형 첨부 자동 처리는
`archive/`에 보관하며 활성 import·Registry·배포에 연결하지 않는다.

## 의존성과 데이터 권위

- 문서 처리 코드는 물품 프로파일의 공개 `contracts`를 사용한다. 의미 작성 저장소와
  Runtime을 직접 호출하지 않는다. 상위 표준관리 Flow의 의미 작성 요청은 인증된
  Admin HTTP API를 사용한다.
- MCP는 Runtime HTTP API만 호출한다. DB·의미 작성 코드·embedded Runtime을 사용하지 않는다.
- Provider·Codex·Data 실행 기반은 기능 구현을 역으로 import하지 않는다.
  수집 계약과 Semantic Registry의 대조는 별도의 검증 명령에서 수행한다.
- OpenMetadata는 기술·거버넌스 metadata의 authoritative source다. Teoria DB에 entity를 복제하지 않는다.
- Application DB는 Ontology·Binding·Suggestion·Context·정규화 프로파일 및 승인 이력을 소유한다.
  Data DB는 수집·문서 처리 결과와 실행 상태·산출물 참조를 소유한다. 큰 본문은 파일/S3에 둔다.
- AI 결과는 Suggestion이다. 검토·승인 없이 Published Ontology나 authoritative metadata를 변경하지 않는다.
- 운영 Runtime은 checksum 검증된 versioned artifact만 읽는다. authoring DB와 Registry를 직접 읽지 않는다.

Admin·Runtime·Policy Control Plane의 FastAPI 앱 생성은 `entrypoints/*_api.py`와
`entrypoints/policy_control_plane.py`, 객체 조립은 `entrypoints/composition/`, HTTP 라우터는
소유 기능의 `*_router.py`에 둔다. 기능과 외부 연결은 진입점을 역으로 import하지 않는다.
API가 생성한 Provider·OpenMetadata·OPA·Context HTTP client는 FastAPI lifespan에서 열고 닫는다.
외부에서 주입한 client의 소유권은 호출자에게 유지한다.
AI 진단 Worker도 OpenMetadata·추론 HTTP client를 프로세스의 async context에서 재사용하고
종료·취소 시 닫는다. OpenMetadata ingestion은 Docker client와 생성된 컨테이너의 정리를
각각 등록해 생성·대기·로그·삭제 실패 시에도 연결 종료를 시도한다.

이 경계와 기능 간 비순환 의존은 `backend/tests/architecture/`에서 검사한다. 기능 간 새 호출은 이름 있는 공개
계약으로 제공하고 순환 의존을 추가하지 않는다. 내부 저장소를 다른 기능이 직접 조작하지 않는다.

## 코드와 실행 환경

Python 프로젝트는 `backend/pyproject.toml` 하나다. 기존 CLI 이름은 유지한다.

```bash
uv sync --project backend --locked --all-extras --all-groups
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests tests/integration
uv run --project backend --locked --extra api teoria validate backend/contracts/runtime
uv run --project backend --locked teoria-pipelines validate backend
```

`backend/Dockerfile`은 `runtime`, `authoring`, `mcp`, `worker`, `kubernetes-worker`,
`law-worker`, `metadata-worker`, `check` target을 제공한다. API·MCP는 선택적 extra,
Worker는 역할별 dependency group을 설치한다. 규격서 parser는 별도 환경의 실행 파일이다.
법령 Worker에 parser·Codex 실행 파일을 설치하지 않고, OpenMetadata 공식 ingestion은
전용 Worker가 ephemeral Job으로 실행한다. 코드 통합이 프로세스·권한 통합을 의미하지 않는다.

## 변경과 검증

테스트는 `backend/tests/features/`, `integrations/`, `entrypoints/`, `integration/`에서
소유 코드에 대응한다. 백엔드 내부 기능 간 계약 검증도 `backend/tests/integration/`에 둔다.
루트 `tests/`는 저장소 문서와 프로젝트·배포 구성요소 간 연동 검증을 둔다.
배포 검증은 `deploy/compose/tests/`가 소유한다.

구조 변경은 import·실행 명령·배포·문서·Skill 경로를 함께 갱신한다. 적용된 SQL과 게시
artifact의 본문·version·checksum은 수정하지 않는다. 구조 변경 자체에는 새 SQL migration이
필요하지 않다. 실제 환경 검증 전에는 이미지 build나 템플릿 검증을 운영 배포로 기록하지 않는다.

Teoria 소유 이름은 `snake_case`, Python 클래스·React 컴포넌트는 `PascalCase`, 환경변수는
`UPPER_SNAKE_CASE`, CLI·Docker·배포 리소스는 `kebab-case`다. 도구 고정 이름과 기존 문서 URL은 유지한다.

이 구조로의 이동과 실제 검증 범위는 [통합 검증 기록](../verification/backend_consolidation_2026_10_25.md)에 보존한다.

Mapping codec의 `common.*`, `company.*`, `tax.*` ID는 이전 게시 계약과 호환된다.
순수 기본 변환은 `registry/codecs/primitives.py`, 이전 기업·과세 전용 변환은
`registry/codecs/legacy/`에 격리한다. 검증과 실행이 같은 resolver를 사용하며 이를 통해
은퇴한 Source·Capability·수집 배포를 다시 등록하지 않는다.

## 백엔드 리소스의 용도

실행 코드와 파일 기반 입력·계약은 역할이 달라 분리한다. 아래 디렉터리는 현재 사용하는
입력 또는 재현·복구 이력이므로 이름만 보고 제거하지 않는다.

| 위치 | 유지하는 이유 |
|---|---|
| `backend/config/` | 법령 수집 대상 `legal_information/collection_targets.yaml` |
| `backend/contracts/ingestion/connectors/` | 법령 Provider의 요청·응답 wire 계약 |
| `backend/contracts/ingestion/pipelines/` | 법령 수집 Operation·cursor·sink·provenance 계약 |
| `backend/references/` | Connector 계약을 검증하는 Provider 원문과 metadata |
| `backend/verification_cases/ingestion/` | 법령 Connector의 build/live 검증 입력 |
| `backend/migrations/` | 신규 DB 구축과 기존 DB의 순차 upgrade; 적용 SQL은 불변 |
| `backend/authoring/ontology_blueprints/` | 물품 Draft 생성·확장·요구사항 보강의 작성 입력 |
| `backend/authoring/ontology_migrations/` | 현재 물품 분류 manifest와 불변 `applied/` 이력 |
| `backend/contracts/runtime/core/` | 계약 검증에 사용하는 data type·value set |

`entrypoints/composition/`의 두 모듈은 Admin·Runtime 서비스와 외부 client를 조립한다.
FastAPI request dependency는 기능의 `dependencies.py`가 담당한다. FastAPI는 특정 조립 폴더
이름을 강제하지 않는다. 이 위치는 앱의 조립과 기능 구현을 분리하기 위한 저장소 규칙이다.

일반 주문 ETL 예제는 `archive/examples/db_sales/`, 현행 구성이 아닌 과거 분류 입력 두 개는
`archive/ontology_migrations/pending/`에 보존한다. 보관된 manifest는 회귀 검증의 역사적 입력이며
운영 조립에서 읽지 않는다. 내용 없는 Registry 디렉터리와 중복 `.gitkeep`은 두지 않는다.

루트 `backups/`는 애플리케이션 실행에 필요하지 않은 로컬 복구 자료다. Git과 Docker 빌드
문맥에서 제외한다. 현재 덤프를 폴더 정리 과정에서 삭제하지 않는다. 정기 백업의 기준 위치는
`deploy/compose/postgres/backup.sh`의 `TEORIA_BACKUP_ROOT`로 다른 영구 저장소에 지정할 수 있다.


Runtime은 API Source 직접 호출과 수집 DB의 Database Source 조회를 모두 지원한다.
두 경로의 레코드는 Runtime Mapping으로 Object·Link를 만들고 Capability에서 사용한다.
Ontology·Semantic Binding의 검토·승인은 이 데이터 실행 경로와 별도다.

Flow·Task와 처리 구현은 소유 기능에 둔다. Prefect 배포 선언은 `deploy/prefect/`가 소유하고,
`integrations/prefect/deployment_manifests.py`가 등록·검증·문서 생성에 같은 경로를 제공한다.
개발 저장소와 Worker 이미지 모두 `backend/`와 `deploy/`를 형제 디렉터리로 유지한다.
기존 CLI `--pipelines backend`와 `--kind ingestion`은 호환 이름으로 유지한다.

Reference metadata의 `registry`는 `backend/` 기준 상대 경로다. 계약 내용·원본 Provider 필드는
위치 변경으로 수정하지 않는다. 이미 발행한 artifact 내부의 `registries/`와 적용된 SQL·
Ontology 이력 본문은 보존한다. 작업 디렉터리 이동으로 과거 artifact 형식을 바꾸지 않는다.


프런트엔드 빌드는 `frontend/Dockerfile`이 소유한다. Compose의 `gateway` target은 정적 UI와
API·Prefect proxy를 한 nginx에 제공한다. K3s의 `standalone` target은 UI만 제공하고 Traefik이
각 Service로 직접 라우팅한다. 환경별 proxy 설정은 `deploy/compose/nginx/nginx.conf`와
`deploy/k3s/application/ingress.yaml`이 소유한다.

서버 숫자 관찰의 준비·적재는 `features/specification_processing/storage/query_observations.py`와
실행 Repository가 소유하며 실행 완료와 같은 transaction을 사용한다. 조회 계약은
`contracts/runtime/domains/goods/`와 `sources/specification_observations.yaml`에 있다.
비교·근거 처리기는 `features/goods_querying/`에 두고 `entrypoints/composition/runtime.py`에서
등록한다. Pipeline은 조회 처리기나 Runtime을 호출하지 않는다.
서버 의미와 프로파일 작성 입력은 `authoring/ontology_blueprints/computer_server.yaml`과
`authoring/normalization_profiles/computer_server_memory.yaml`이다.
