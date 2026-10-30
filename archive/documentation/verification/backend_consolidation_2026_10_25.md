# 백엔드 기능 모듈 통합 검증 — 2026-10-25

## 변경

`platform/`, `pipelines/`, `mcp/`와 세 내부 라이브러리의 활성 Python 코드를
`backend/src/teoria/`로 통합했다. 단일 프로젝트는 `backend/pyproject.toml`, 잠금은
`backend/uv.lock`이다. 관리 UI는 `frontend/`로 이동했다.
[구조와 소유권](../../../docs/architecture/repository-structure.md)이 기준이다.

- `features/`: 의미 모델, 규격서 처리, 물품 표준관리, 메타데이터, 법령, Runtime, 접근 제어
- `integrations/`: Provider API, Codex, OpenMetadata, Prefect, DB·Data 실행 기반, Runtime HTTP
- `entrypoints/`: 기능 라우터 조립, API·MCP·CLI 프로세스 시작

기존 CLI 이름·환경변수·HTTP 계약·Docker 서비스 이름은 유지했다. Prefect 배포 선언과
Compose·K3s·GitHub CI/CD의 코드·설정·migration 경로를 갱신했다.
기존 `docs/platform/`, `docs/pipelines/`, `docs/mcp/`, `docs/packages/` URL은 유지했다.
조달 이력 수집·분석과 구형 첨부 자동 처리는 보관 상태를 유지한다.

공유 Provider 근거 폴더의 `target: connector`와 `target: source`를 각 로더가 구분한다.
등록된 계약의 대상 불일치와 미등록 Source 문서 오류는 계속 검증하며, 경계 회귀 테스트를 추가했다.

## 검증 결과

| 대상 | 결과 |
|---|---|
| 백엔드 및 루트 기능 간 계약, 격리 PostgreSQL | 551 passed, 6 skipped |
| 건너뛴 선택 통합 테스트 별도 실행 | 6 passed |
| 선택 통합의 실행 환경 | 실제 격리 Prefect·PostgreSQL·MinIO, parser/model 응답은 제어된 fixture |
| 프런트엔드 | 45 passed, TypeScript·Vite build 성공 |
| 문서 검사기 | 7 passed |
| Compose 격리·인증·Worker 권한 | 6 passed |
| Registry | Source·Runtime Contract·Mapping·Capability 0, Data Type 11, Value Set 15 검증 성공 |
| Connector·수집 정의·통합 검증 | 법령 Connector 1개, 수집 정의 1개 검증 성공 |
| 법령 Connector Operation | 2개 모두 Build·Live 검증 성공 |
| Prefect 배포 목록 | versioned manifest에서 재생성, 일치 검사 성공 |
| Compose | 기본 및 metadata·metadata-orchestration·MCP profile config 검증 성공 |
| K3s | 경로 갱신과 deploy.sh 문법 검사; 실제 cluster 배포는 이 검증에 포함하지 않음 |
| Docker | Runtime·Authoring·MCP·규격서 Kubernetes Worker·법령·Metadata·Check·Frontend build 성공 |
| 관리 API 이미지 | OpenAPI 71개 경로, 물품 프로파일·법령 라우터 존재, health·overview HTTP 200 |
| MCP | 실제 STDIO initialize, Runtime HTTP discovery, tools/list 성공; 도구 0개 |
| 불변 파일 | 이동한 migration·적용 이력 130개가 변경 전과 바이트 단위 동일 |

선택 통합 테스트는 문서 처리 완료 재실행, 입력 충돌, S3 저장 실패 후 재개, Draft 보존,
실행 lease 인계·만료 Worker 차단과 실제 Prefect extraction Task 연결을 검증했다.
외부 모델 품질이나 실제 규격서 정확도를 검증한 결과로 해석하지 않는다.

## 운영 artifact 호환

새 Runtime 이미지에 기존 artifact volume을 읽기 전용으로 연결해 active bundle을 적재했다.

- version: `2026.10.25.1`
- checksum: `sha256:907356fe1bc90b4f0a44fcf8eb670c2f10a73827dd6fa7e920cc9da697e5a5f6`
- 활성 Capability: 0

기존 Published Ontology·승인 이력·artifact·운영 DB는 변경하지 않았다.
이미지는 `teoria-structure-*:test` 태그로 검증했으며 운영 서비스의 기존 이미지 태그를 덮어쓰지 않았다.
새 구조의 이미지를 운영에 배포하고 Prefect 선언을 재등록한 결과는 이 기록에 포함하지 않는다.

## 운영 전환 순서

1. 현재 실행을 확인하고 새 이미지로 전환할 Worker의 실행을 drain한다. 기존 Backfill 중단 상태를 유지한다.
2. 같은 소스 revision의 역할별 이미지를 배포한다. `backend/Dockerfile`의 target과 `frontend/Dockerfile`을 사용한다.
3. Application·Data migration 경로를 각각 `backend/migrations/application/`, `backend/migrations/data/`로 지정한다.
   이 변경으로 새로운 SQL을 적용할 필요는 없다.
4. 새 Worker 이미지가 준비된 뒤 Prefect 선언을 재등록한다. 기존 배포 이름·pool·queue와 수동 규격서 스케줄을 유지한다.
5. Admin·Runtime health, artifact checksum, 법령 작업, metadata ingestion과 MCP discovery를 확인한다.

MCP에는 Runtime token만, 법령 Worker에는 법령 credential만 주입한다. OpenMetadata ingestion은
전용 Worker가 공식 ingestion image를 ephemeral Job으로 실행한다. 데이터·권한의 경계는 통합하지 않는다.

후속 [운영 재배포 검증](backend_consolidation_deployment_2026_10_25.md)에서 실제 서비스 교체·등록·작업 실행 결과를 확인한다.
