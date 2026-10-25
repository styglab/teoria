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
  registries/            # Source·Ontology·Binding·Mapping·Capability 계약
  connectors/            # 수집 전용 Provider 계약
  definitions/           # 수집 대상·Operation·output 계약
  config/                # 수집·메타데이터 입력
  references/providers/  # Provider 원문과 근거
  verification_cases/    # Connector 검증 입력
  prefect*.yaml          # Flow 배포·스케줄 선언
  migrations/
    application/         # Ontology·Binding·Suggestion·승인 이력
    data/                # 수집·규격서 실행 상태와 산출물 참조
  ontology_blueprints/   # Draft 작성 입력
  ontology_migrations/   # pending 입력과 applied 이력
frontend/
  src/app/               # 라우팅·앱 조립
  src/features/          # 기능별 화면
  src/components/        # 실제 재사용하는 UI 컴포넌트
  src/api/               # 관리 API HTTP 계약
  src/lib/               # UI에서 실제 공유하는 기반 코드
deploy/                  # Compose·K3s·GitHub 배포
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
| `features/semantic_modeling/authoring/`, `registry/` | 작성 저장소·계약 검증·immutable bundle 작성 |
| `features/specification_processing/` | 명시 입력 문서 파싱·정보 추출·고정 표준 적용·평가·Flow |
| `features/goods_normalization/candidates/` | 표준 후보 제안·AI 의미 판정·Draft 작성 |
| `features/goods_normalization/profiles/` | 프로파일 검토·승인·고정 패키지 발행 |
| `features/goods_normalization/contracts/` | 발행과 적용이 공유하는 versioned 데이터 계약 |
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
| `integrations/runtime_http/` | MCP의 Runtime HTTP client와 protocol 변환 |
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

이 경계는 `backend/tests/architecture/`에서 검사한다. 기능 간 새 호출은 이름 있는 공개
계약으로 제공하고 순환 의존을 추가하지 않는다. 내부 저장소를 다른 기능이 직접 조작하지 않는다.

## 코드와 실행 환경

Python 프로젝트는 `backend/pyproject.toml` 하나다. 기존 CLI 이름은 유지한다.

```bash
uv sync --project backend --locked --all-extras --all-groups
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests tests/integration
uv run --project backend --locked --extra api teoria validate backend/registries
uv run --project backend --locked teoria-pipelines validate backend
```

`backend/Dockerfile`은 `runtime`, `authoring`, `mcp`, `worker`, `kubernetes-worker`,
`law-worker`, `metadata-worker`, `check` target을 제공한다. API·MCP는 선택적 extra,
Worker는 역할별 dependency group을 설치한다. 규격서 parser는 별도 환경의 실행 파일이다.
법령 Worker에 parser·Codex 실행 파일을 설치하지 않고, OpenMetadata 공식 ingestion은
전용 Worker가 ephemeral Job으로 실행한다. 코드 통합이 프로세스·권한 통합을 의미하지 않는다.

## 변경과 검증

테스트는 `backend/tests/features/`, `integrations/`, `entrypoints/`, `integration/`에서
소유 코드에 대응한다. 루트 `tests/`는 저장소 문서와 기능 간 계약 검증을 둔다.
배포 검증은 `deploy/compose/tests/`가 소유한다.

구조 변경은 import·실행 명령·배포·문서·Skill 경로를 함께 갱신한다. 적용된 SQL과 게시
artifact의 본문·version·checksum은 수정하지 않는다. 구조 변경 자체에는 새 SQL migration이
필요하지 않다. 실제 환경 검증 전에는 이미지 build나 템플릿 검증을 운영 배포로 기록하지 않는다.

Teoria 소유 이름은 `snake_case`, Python 클래스·React 컴포넌트는 `PascalCase`, 환경변수는
`UPPER_SNAKE_CASE`, CLI·Docker·배포 리소스는 `kebab-case`다. 도구 고정 이름과 기존 문서 URL은 유지한다.

이 구조로의 이동과 실제 검증 범위는 [통합 검증 기록](../verification/backend_consolidation_2026_10_25.md)에 보존한다.
