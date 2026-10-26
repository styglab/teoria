# 의미 모델·Runtime 개발 안내

Ontology·Binding·메타데이터 진단과 Runtime은 통합 Python 백엔드의 기능 모듈이다.
프로젝트와 의존성의 기준은 `backend/pyproject.toml`과 `backend/uv.lock`이다.
전체 배치는 [저장소 구조](../architecture/repository-structure.md)를 따른다.

## 변경 위치

아래 경로는 `backend/src/teoria/` 기준이다.

| 위치 | 책임 |
|---|---|
| `features/semantic_modeling/ontology/` | Ontology Draft·검토·승인·게시·저장소 |
| `features/semantic_modeling/binding/` | Stable Concept ID와 의미 대상 연결 |
| `features/semantic_modeling/registry/` | Source·Mapping·Capability 검증과 immutable bundle |
| `features/goods_normalization/candidates/` | 근거 기반 후보·AI 의미 판정·Draft 생성 |
| `features/goods_normalization/profiles/` | 프로파일 작성·승인·고정 패키지 발행 |
| `features/metadata_management/catalog/` | 자산 맥락과 관리 라우터 |
| `features/metadata_management/intelligence/` | Suggestion·검토·적용과 비동기 진단 |
| `features/legal_information/` | 법령 검색·원문 조회와 `collection/` 수집 |
| `features/runtime/` | Source·Mapping·Capability 실행과 Context |
| `features/access_control/` | 인증 principal·정책·OPA 제어 |
| `integrations/openmetadata/` | OpenMetadata client와 변환 |
| `integrations/application_database/` | Application DB async 연결·migration 실행 |
| `entrypoints/*_api.py`, `entrypoints/composition/`, `entrypoints/commands/` | HTTP 서비스 조립과 CLI 명령 |

각 기능의 HTTP 라우터와 저장소 구현은 해당 기능 안에 둔다. `entrypoints/composition/`은
기능을 조립하며 업무 규칙을 모으는 공통 서비스 계층이 아니다. UI는 `frontend/`에 있다.

## 실행과 확장

`teoria-admin-api`, `teoria-runtime-api`, `teoria-policy-control-plane`,
`teoria-metadata-assessment-worker`와 관리 CLI `teoria` 이름을 유지한다.
API 의존성은 `--extra api`로 설치한다. 현재 활성 업무 Capability는 없으며 기존 조달
구현은 `archive/procurement_services/`의 비활성 이력이다.

새 업무 기능은 이름 있는 `features/` 패키지에 둔다. Runtime의 명시적 processor·query hook은
`features/runtime/composition.py`와 `features/runtime/context/composition.py`에서 연결한다.
공통 Runner에 조달별 분기를 추가하거나 보관 코드를 역으로 import하지 않는다.

Published Ontology는 직접 수정하지 않는다. 새 Draft에서 검토·승인·게시하고 Runtime은
checksum 검증 artifact만 읽는다. Mapping은 source record→Runtime Object,
Binding은 개념↔자산·용어·Capability 연결이며 서로 다른 계약이다.

## I/O와 동시 실행

Application DB의 async 연결은 `integrations/application_database/postgres.py`를 사용한다.
Admin 쓰기는 인증된 principal을 actor로 기록하며 body의 actor를 권위 정보로 신뢰하지 않는다.
승인·적용·transaction 순서를 유지하고 AI 출력은 승인 전 Suggestion으로 취급한다.
OpenMetadata entity는 참조만 저장한다. 원문·문서별 관찰 본문은 파일/S3에 유지한다.

## 검증

```bash
uv sync --project backend --locked --all-extras --all-groups
uv run --project backend --locked --all-extras --all-groups pytest backend/tests tests/integration
uv run --project backend --locked --extra api teoria validate backend/contracts/runtime
docker compose -f deploy/compose/compose.yaml config --quiet
```

Application DB migration은 `backend/migrations/application/`에 새 순번으로 추가한다.
적용한 SQL은 수정하지 않는다. DB 통합 검증은 운영과 분리된 `TEORIA_TEST_APP_DATABASE_URL`을 사용한다.

앱 생성은 Admin·Runtime 모두 진입점이 소유하며 `APIRouter`는 해당 기능의 `*_router.py`에 둔다.
HTTP client는 lifespan 동안 재사용하고 종료 시 소유한 자원만 닫는다.
Ontology·물품 프로파일의 업무 정책은 Service, SQL·잠금·감사 저장은 Repository가 담당한다.
승인·게시·감사는 동일 connection과 transaction을 유지한다.
