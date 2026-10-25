# 저장소 구조와 소유권

새 기능을 추가하거나 기존 동작을 수정할 때 어느 프로젝트가 책임지는지 정하는 문서다.
전체 데이터 흐름과 권위 경계는 [아키텍처](overview.md)를 먼저 참고한다.

## 현재 활성 범위

규격서 파싱·물품 정보 추출·표준 후보 관리와 물품 Ontology 구축, 메타데이터 진단용 법령 수집·조회를 활성 범위로 한다.
Ontology·Binding·Mapping·Capability·Runtime·Context·OpenMetadata·Prefect 기반은 유지한다.
법령 기능은 `legal_information` 소유 패키지와 전용 배포로 운영한다.
기존 기업·조달 이력 분석과 API 수집 코드·계약·전용 테스트는 `archive/procurement_services/`에
비활성 보관한다. 활성 코드·Registry·이미지에서 이를 import하거나 재등록하지 않는다.
기존 migration·게시 이력·데이터는 보존한다. [시작 안내](../platform-guide.md)를 따른다.

## 프로젝트 선택

| 변경하려는 내용 | 소유 프로젝트 | 개발 안내 |
|---|---|---|
| 업무 의미, Ontology, Binding, 메타데이터 진단, 사용자 요청 실행 | `platform/` | [Platform](../platform/development.md) |
| 외부 데이터 수집, 정규화, 적재, Prefect, Data DB migration | `pipelines/` | [Pipelines](../pipelines/development.md) |
| MCP Tool, protocol 변환, Runtime HTTP client | `mcp/` | [MCP Gateway](../mcp/gateway.md) |
| Provider API wire 계약과 HTTP 요청·응답 처리 | `packages/provider_api/` | [Provider API](../packages/provider_api.md) |
| 서비스 조립, 이미지, 네트워크와 배포 설정 | `deploy/` | [Compose](../deployment/compose.md) |

공공조달은 첫 vertical domain이다. 조달 고유 정책은 해당 Domain Registry와 이름 있는
기능 패키지에 두며, 두 번째 Domain에서 실제 재사용이 확인되기 전에는 Platform 공통
계층으로 승격하지 않는다.

## 통신과 의존 방향

```text
pipelines ──SQL write──▶ Teoria Data DB ◀──SQL read── platform
platform  ──REST───────▶ OpenMetadata
mcp       ──HTTP───────▶ Platform Runtime API
platform  ──import────▶ teoria-provider-api ◀──import── pipelines
```

Pipeline 실행 코드는 Platform Capability나 Mapping Runtime을 호출하지 않는다.
MCP는 Runtime HTTP API만 호출하고 Source 키·DB 권한·embedded Runtime을 갖지 않는다.
Pipeline의 별도 통합 검증 진입점만 Platform Registry를 지연 import할 수 있다.

`packages/`에는 둘 이상의 프로젝트가 실제 사용하는 설치형 라이브러리만 둔다.
`goods_normalization/`은 Platform의 프로파일 발행과 Pipelines의 적용에서 함께 사용하는 데이터 계약이며
실행 코드·DB·소유 프로젝트를 import하지 않는다.
`codex_inference/`는 두 프로젝트가 실제 사용하는 JSON 전용 Codex subprocess 실행·시간 제한·취소 처리를 소유한다.
각 패키지는 독립 `pyproject.toml`, 테스트와 단일 책임을 가지며 소유 프로젝트를
역으로 import하지 않는다. 미래 재사용을 위한 빈 패키지나 `common`, `shared`,
`utils` 묶음을 만들지 않는다.

## 계약과 설정의 기준 위치

| 목적 | 기준 위치 |
|---|---|
| Runtime이 직접 호출하는 API·DB | `platform/registries/sources/` |
| Runtime Object·Mapping·Capability | `platform/registries/domains/<domain>/` |
| Provider API 원문과 근거 | 각 프로젝트의 `references/providers/` |
| 지속 수집 API 계약 | `pipelines/connectors/` |
| 수집 대상·Operation·output 계약 | `pipelines/definitions/<domain>/` |
| 수집 업무 입력 | `pipelines/config/` |
| 수집·Metadata Job 배포와 스케줄 | `pipelines/prefect.yaml`, `pipelines/prefect.metadata.yaml` |
| 두 배포의 Prefect 등록·Queue·동시 실행 정책 | `pipelines/src/teoria_pipelines/deployment.py` |
| Data DB schema | `pipelines/database/migrations/` |
| Application DB schema | `platform/database/migrations/` |
| Ontology 이관 입력과 적용 이력 | `platform/ontology_migrations/pending/`, `applied/` |
| 로컬 개발·통합 배포 | `deploy/compose/` |
| EC2 K3s 배포·GitHub CD | `deploy/k3s/`, `.github/workflows/deploy_k3s.yaml` |

같은 수집 API를 Source와 Connector에 중복 등록하지 않는다. Pipeline이 적재한 DB를
Runtime이 읽으면 Database Source와 Mapping을 작성한다. 적용한 SQL migration과
게시한 Ontology·Runtime artifact는 수정하지 않고 새 migration 또는 version을 만든다.

## 기능별 코드 배치

실행 코드·타입·저장소 구현은 소유 Domain의 기능 패키지에 모은다. 공통 계층은
실제 재사용하는 기반 코드만 소유하고 Domain 구현을 역으로 import하지 않는다.
Flow와 HTTP·CLI 진입점은 실행 순서와 조립을 보여주며, 큰 업무 책임은 이름 있는
모듈로 분리한다. 파일 수나 줄 수만을 이유로 나누지 않는다.

Platform의 Runtime·Admin·Context 조립과 Domain 등록은
[Platform 개발 안내](../platform/development.md), Flow·Task·정규화·repository의
배치는 [Pipelines 개발 안내](../pipelines/development.md)를 따른다.

## 테스트 배치

테스트는 검증 대상의 소유권을 따른다. 프로젝트 단독 단위·DB 통합 검증은 각
프로젝트의 `tests/`에 두고, 루트 `tests/`에는 저장소 공통 검사와 프로젝트 사이
계약·연동 검증을 둔다. DB를 사용한다는 이유만으로 루트 통합 테스트로 분류하지 않는다.
배포 설정 검증은 `deploy/compose/tests/`가 소유한다. 기능별 테스트 경로는
`unit/domains/<domain>/<feature>/`처럼 소유 코드와 대응하며 공통 기반 검증은
`unit/`에 유지한다. 프로젝트 간 테스트가 다른 프로젝트의 테스트 모듈을 import하지 않는다.

## 이름과 문서 배치

Teoria 소유 경로와 내부 ID의 기본 형식은 `snake_case`다. 클래스·React 컴포넌트는
`PascalCase`, 환경변수는 `UPPER_SNAKE_CASE`, CLI·Docker·배포 리소스는
`kebab-case`다. 도구가 고정한 이름과 외부 Provider의 wire 표기는 유지한다.
기존 문서의 `kebab-case` 이름은 호환 계획 없이 이름만 바꾸지 않는다.

설명 문서는 `docs/`에 모으고 코드 디렉터리에 README를 분산하지 않는다.
`docs/`에는 문서와 문서용 예제·템플릿만 둔다. 문서 검사기와 회귀 테스트는
`tests/documentation/`에 함께 두며 루트 `tools/`를 추가하지 않는다.
문서는 `platform/`, `pipelines/`, `mcp/`, `packages/`의 소유권을 따르며 전체 설계는
`architecture/`, 서비스 배포는 `deployment/`, 외부 연동은 `integration/`에 둔다.
조달 규격서 처리의 현재 계약·개선 평가와 서비스 설계 자료는 한곳에서 읽도록
[`procurement_specification_processing/`](../procurement_specification_processing/index.md)에
모은다. 이 문서 배치는 실행 코드·계약의 프로젝트 소유권을 변경하지 않는다.
현재 계약과 절차는 계속 갱신하고, 날짜·버전에 종속된 결과는 `verification/`에 보관한다.
문서 작성·통합 기준과 읽는 순서는 [문서 목차](../index.md)를 따른다.
