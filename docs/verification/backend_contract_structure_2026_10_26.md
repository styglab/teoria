# 계약·작성 입력·Prefect 배포 구조 정리 — 2026-10-26

하나의 Python 백엔드 안에서 기능 구현·선언형 계약·운영 입력·배포 선언의 위치를 구분했다.
API 직접 호출과 Prefect 수집 DB 조회라는 기존 Runtime 경로를 유지한다.
현재 소유권과 디렉터리 구조는 [저장소 구조](../architecture/repository-structure.md)를 따른다.

## 이동

| 이전 경로 | 현재 경로 |
|---|---|
| `backend/registries/` | `backend/contracts/runtime/` |
| `backend/connectors/` | `backend/contracts/ingestion/connectors/` |
| `backend/definitions/` | `backend/contracts/ingestion/pipelines/` |
| `backend/verification_cases/`의 법령 입력 | `backend/verification_cases/ingestion/` |
| `backend/config/law_targets.yaml` | `backend/config/legal_information/collection_targets.yaml` |
| `backend/ontology_blueprints/` | `backend/authoring/ontology_blueprints/` |
| `backend/ontology_migrations/` | `backend/authoring/ontology_migrations/` |
| `backend/prefect.yaml` | `deploy/prefect/specification_processing.yaml` |
| `backend/prefect.legal_information.yaml` | `deploy/prefect/legal_information.yaml` |
| `backend/prefect.metadata.yaml` | `deploy/prefect/metadata_management.yaml` |

계약·설정·작성 입력·이관 이력·Prefect YAML 33개는 이동 전 본문과 SHA-256이 동일하다.
법령 Provider Reference metadata의 `registry` 연결만 새 계약 위치에 맞게 바꿨다.
Provider wire 계약·Operation·외부 필드·실행 스케줄·pool·입력값은 변경하지 않았다.

Python 기능의 import 경로·HTTP·MCP·CLI 이름은 유지한다. 빈 Source·Domain·Runtime 검증 입력
디렉터리는 미리 만들지 않는다. 현재 업무 Capability는 계속 0개이며 과거 조달 기능을 재등록하지 않았다.

## 실행 연결

- Runtime Registry 기본 경로와 CLI·Compose·CI·Skill·현재 가이드의 경로를 갱신했다.
- 수집 로더는 `backend`를 기준으로 `contracts/ingestion`과 `references/providers`를 읽는다.
- Runtime Source와 Ingestion Connector는 같은 Provider 근거 디렉터리를 사용하되 target 권위를 구분한다.
- 새 Runtime 계약 위치에서도 Reference metadata의 `registry`는 `backend` 기준 상대 경로다.
  기존 artifact와 보관 Registry의 경로 해석은 유지한다.
- Admin 조립에서 현재 물품 migration manifest의 새 작성 입력 위치를 사용한다.
- Prefect 등록·검증·문서 생성은 `deployment_manifests.py`의 동일한 배포 위치를 사용한다.
  CLI의 `--pipelines backend`와 `--kind ingestion` 호환 이름은 유지한다.
- Worker 이미지에는 `/app/backend`와 `/app/deploy/prefect`를 함께 포함한다.
  Compose의 파일 mount와 검증 이미지도 같은 구조를 사용한다.
- [Deployment 목록](../pipelines/deployments.md)을 새 선언 위치에서 다시 생성했다.

적용된 Application/Data SQL 본문은 변경하지 않았다. 이미 발행한 artifact 내부의
`registries/` 형식과 version·checksum도 수정하지 않는다. 작업 디렉터리 구조와 게시 포맷은 별도다.

## 검증

최종 전체 실행: **553 passed**, 건너뛴 테스트 없음(180.32초).
기존 Starlette TestClient의 HTTPX 관련 deprecation warning 1건이 남아 있다.


- 전체 백엔드·기능 간 계약 테스트는 격리 PostgreSQL·MinIO·Prefect 평가 자원을 구성해 실행했다.
  이전 경로를 참조한 테스트 두 개를 수정하고 새 위치의 API Source 근거 검증을 추가한 뒤 전체를 재실행했다.
- 등록 회귀 검증은 Process·Kubernetes 양쪽의 Flow 입력·스케줄·pool·secret 경계를 확인한다.
- 법령 Connector의 `get_law_version`·`list_law_versions`는 Build와 Live 모두 passed다.
  credential과 원문 응답은 검증 기록에 보관하지 않았다.
- Registry·수집 계약·통합 계약과 현재 물품 migration 분류 검증은 성공했다.
  migration report의 Published 대상 DB 대조는 `not_checked`다.
- 문서 검사기 테스트 7개·Compose 테스트 6개와 Compose 설정 검증은 성공했다.
- 자동 생성 Deployment 목록 일치, F821·F822·F823·F811 및 `git diff --check`를 검증했다.
- Runtime·Authoring·법령·규격서·Metadata·MCP·Check 이미지 7종을 build했다.
- Check 이미지의 실제 통합 계약 검증, Authoring 앱 생성과 현재 manifest 조회,
  법령 이미지의 배포 6개·대상 법령 6개 조회가 성공했다.
- 새 Runtime 이미지에서 기존 운영 artifact volume을 read-only로 열어 checksum 검증과 적재를 완료했다.

기존 artifact는 version `2026.10.25.1`, bundle checksum
`sha256:907356fe1bc90b4f0a44fcf8eb670c2f10a73827dd6fa7e920cc9da697e5a5f6`다.
이번 작업에서는 새 Registry release·Ontology 게시·DB migration·운영 컨테이너 교체를 하지 않았다.
K3s 실제 클러스터 배포 결과를 뜻하지 않는다.
