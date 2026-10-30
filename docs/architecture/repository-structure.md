# 저장소 구조와 소유권

변경할 기능의 소유 위치를 먼저 정한다. Teoria는 AI-Native Metadata & Ontology Platform이며
공공조달은 첫 업무 영역이다. 조달 규칙을 실제 재사용 근거 없이 플랫폼 공통 계층으로 옮기지 않는다.

## 기준 위치

| 위치 | 기준으로 관리하는 내용 |
|---|---|
| `backend/src/teoria/features/` | 기능별 실행 코드·타입·서비스·저장소·HTTP 라우터·Flow |
| `backend/src/teoria/integrations/` | 외부 연결과 실제 재사용 기반 |
| `backend/src/teoria/entrypoints/` | 프로세스 시작·FastAPI lifespan·객체 조립 |
| `backend/contracts/runtime/` | Runtime Source·Object·Mapping·Capability 계약 |
| `backend/contracts/ingestion/` | Pipeline Connector·수집 계약 |
| `backend/config/` | 운영 입력 |
| `backend/authoring/` | Ontology 작성 입력·문서 그래프 예시·이관 자료 |
| `backend/migrations/application/` | Ontology·Binding·사전·승인 이력의 DB 변경 |
| `backend/migrations/data/` | 수집·문서 처리 상태와 참조의 DB 변경 |
| `backend/tests/` | 백엔드 기능·통합·구조 검사 |
| `frontend/src/app/` | 앱 조립·라우팅·탐색 |
| `frontend/src/features/` | 업무 화면 |
| `frontend/src/api/` | HTTP 계약 |
| `frontend/src/components/`, `frontend/src/lib/` | 프런트엔드에서 실제 공유하는 구성 |
| `backend/config/<feature>/prefect_deployments.yaml` | 공통 Flow 등록 정보·기본 파라미터·기본 schedule |
| `deploy/compose/prefect/`, `deploy/k3s/prefect/` | 환경별 Prefect pool·queue·실행 Job 정책 |
| `deploy/compose/`, `deploy/k3s/` | 환경별 배포 설정 |
| `docs/` | 현재 안내·문서용 예제·검증 기록 |
| `tests/documentation/` | 문서 링크·목차 검증 코드 |
| `archive/` | 비활성 업무 코드와 과거 문서 |

Python 프로젝트와 의존성 기준은 `backend/pyproject.toml`·`backend/uv.lock` 한곳이다.
별도 설치형 packages나 common/shared/utils 묶음을 미래 재사용만을 이유로 추가하지 않는다.

## 기능별 소유권

아래 위치는 `backend/src/teoria/` 기준이다.

| 위치 | 책임 |
|---|---|
| `features/semantic_modeling/ontology/` | 지속 가능한 업무 개념·Draft·검토·게시 |
| `features/semantic_modeling/binding/` | Stable Concept와 외부 의미 대상의 연결 |
| `features/semantic_modeling/registry/` | 실행 계약 검증·고정 bundle·Mapping codec |
| `features/semantic_modeling/goods_dictionary/` | 원문 표현·표준 정의·매핑·판정·감사 |
| `features/specification_processing/` | 규격서 파싱·추출·검증·표준 적용·평가·Flow·입력/결과 HTTP |
| `features/goods_normalization/` | 프로파일 후보·의미 판정·작성·승인·고정 계약 |
| `features/goods_notice_collection/` | 물품 공고 백업 복원·원문 버전·관측·첨부 참조; 자동 수집 배포는 비활성 |
| `features/metadata_management/` | 자산 맥락·제안/검토/적용·진단·metadata 수집 |
| `features/legal_information/` | 법령 수집·구조화·조회 |
| `features/runtime/` | 게시된 의미와 실행 계약의 조회·실행 |
| `features/workflow_management/` | 허용된 Prefect 배포·스케줄·실행·취소 관리 |
| `features/model_operations/` | 선택형 합성 데이터·학습·평가·등록·데모 배포 |
| `features/access_control/` | 인증 principal·역할·정책 |
| `integrations/provider_api/` | Provider wire·요청·응답·HTTP 실행 |
| `integrations/codex/` | 제한된 JSON 추론 subprocess·시간 제한·취소 |
| `integrations/prefect/` | 배포 등록·pool·queue 정책 |
| `integrations/data_operations/` | 수집 실행·raw·checkpoint·Data DB 연결 |
| `integrations/application_database/` | Application DB 연결·migration |
| `integrations/openmetadata/` | OpenMetadata 연결 |
| `integrations/mlflow/`, `integrations/model_serving/` | 모델 저장소·제한된 서빙 배포 연결 |
| `integrations/runtime_http/` | Runtime HTTP client |
| `entrypoints/composition/` | 기능 객체와 외부 client 조립 |
| `entrypoints/mcp/` | MCP 프로토콜 진입점 |

## 의존성과 데이터 권위

기능의 실행 코드·타입·저장소는 같은 소유 기능에 둔다. 기능과 integration은 entrypoint를 역으로 import하지 않는다.
기능 간 의존성은 순환하지 않아야 하며 공개 계약을 사용한다. 내부 저장소를 다른 기능이 직접 조작하지 않는다.

- 규격서 처리는 `goods_normalization/contracts/`와 사전의 공개 HTTP 계약을 사용한다.
- Pipeline의 의미 작성은 인증된 Admin HTTP API를 호출한다. Capability·Mapping Runtime을 직접 호출하지 않는다.
- MCP는 Runtime API만 사용한다. 직접 DB 접근·embedded 실행을 제공하지 않는다.
- Provider·Codex·실행 기반은 기능 구현을 역으로 import하지 않는다.
- OpenMetadata는 자산·기술·거버넌스 metadata의 기준이다. entity 본문을 Teoria DB에 복제하지 않는다.
- Application DB는 업무 의미·제안·승인 이력, Data DB는 실행·참조, 파일/S3는 문서별 본문을 소유한다.
- Runtime은 checksum을 검증한 게시 artifact를 적재한다. 운영에서 작성 DB나 원본 Registry를 직접 읽지 않는다.

상세 승인·게시 정책은 [아키텍처](overview.md)와 [Ontology](../platform/ontology.md),
Data DB 보존·정리는 [DB 안내](../pipelines/database.md)를 따른다.

## 코드와 실행 환경

API·MCP·각 Worker는 역할별 이미지·의존성·권한을 유지한다.
소스 폴더 통합이 프로세스나 credential 통합을 뜻하지 않는다.
파서는 별도 Python 환경에서 실행한다. 법령 Worker에는 문서 파서·Codex를 설치하지 않는다.
OpenMetadata ingestion dependency는 전용 일회성 Job에 두며 일반 Prefect Worker와 분리한다.

FastAPI 앱 생성·lifespan은 entrypoint, 기능별 HTTP는 소유 기능의 `*_router.py`에 둔다.
HTTP·DB는 native async로 연결하고, 생성한 client는 소유 lifespan에서 재사용·종료한다.
주입받은 client는 호출자가 소유한다. 승인·transaction·checkpoint 순서는 유지한다.

```bash
uv sync --project backend --locked --all-extras --all-groups
uv run --project backend --locked --all-extras --group orchestration pytest backend/tests
uv run --project backend --locked --extra api teoria validate backend/contracts/runtime
uv run --project backend --locked teoria-pipelines validate backend
```

## 변경과 검증

| 변경 | 함께 확인할 것 |
|---|---|
| 코드 이동·구조 변경 | import·진입점·테스트·배포·문서의 위치 일치 |
| Source/Connector | 원문 문서·검증 사례·정적/build/live 계약 검사 |
| Flow·Data DB migration | 기능 테스트와 Compose config |
| Application DB migration | 새 순번 SQL·백엔드 검사·Compose config |
| MCP | Runtime HTTP 통합 검사 |
| 문서 이동·통합·삭제 | 링크·heading·목차와 과거 자료의 연결 |

```bash
python3 -m tests.documentation.check_docs
uv run --project backend --locked --all-extras --group orchestration pytest tests/documentation
```

현재 사용·설계·운영·개발 안내는 주제별 기준 문서 하나를 갱신하고 같은 설명을 여러 페이지에 복제하지 않는다.
일반 변경의 테스트 결과마다 새 검증 문서를 만들지 않는다. 장기 추적이 필요한 배포·이관·품질 관측만
입력·버전·결과·한계와 함께 기록하고, 지난 기록은 `archive/documentation/verification/`에 보존한다.

테스트는 소유 프로젝트에 둔다. 루트 tests에는 저장소 공통·프로젝트 간 계약 검사를 둔다.
적용된 SQL·게시 artifact·이관 이력은 수정하지 않는다. 실제 실행 전에는 템플릿 검증을 배포 성공으로 기록하지 않는다.

Teoria 소유 이름은 snake_case, Python 클래스·React 컴포넌트는 PascalCase,
환경변수는 UPPER_SNAKE_CASE, CLI·Docker·배포 리소스는 kebab-case를 사용한다.
기존 docs 경로는 이름만 바꾸지 않는다. 이관 시 내부 링크와 보관 위치를 함께 정리한다.

## 백엔드 리소스의 용도

Source는 Runtime 직접 호출, Connector는 Pipeline 전용 호출 계약이다.
Provider reference의 registry 경로는 backend 기준이며 원본 wire 이름은 보존한다.
Runtime Mapping과 Semantic Binding을 혼용하지 않는다. 이전 codec은 호환 영역에만 두며 은퇴 업무를 재활성화하지 않는다.

Flow·Task는 소유 기능에 둔다. 공통 등록 정보·기본 파라미터·스케줄은 backend/config/<feature>/prefect_deployments.yaml,
환경별 pool·queue·Job 정책은 deploy/compose/prefect와 deploy/k3s/prefect에 둔다.
Compose는 로컬 배포, K3s와 GitHub 자동 배포는 deploy/k3s와 .github/workflows/deploy_k3s.yaml이 맡는다.
프런트엔드 빌드는 frontend/Dockerfile이 소유한다.

원본·운영 산출물·백업은 문서 정리 대상이 아니다. 루트 backups는 로컬 복구 자료이며,
정기 백업은 deploy/compose/postgres/backup.sh와 TEORIA_BACKUP_ROOT로 관리한다.
비활성 기업·조달 업무 코드는 archive/procurement_services, 과거 설명은
[문서 보관함](../../archive/documentation/index.md)에 둔다. 현재 안내와 검증 이력은 구분한다.
