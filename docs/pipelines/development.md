# Pipelines 개발 안내

Pipelines는 외부 데이터를 수집하고 원본과 정규 데이터를 Teoria Data DB에 적재한다.
Prefect는 실행·스케줄·재시도를 관리한다. 업무 의미와 사용자 요청 실행은
Platform이 담당하며 Pipeline 실행 코드가 Platform Runtime을 호출하지 않는다.

```text
Connector API → 조회 → Raw 저장 → 정규화 → 정규 적재 → Checkpoint
```

위는 Raw 보존 수집의 흐름이다. 낙찰·개찰의 성공 응답은 정규화 후 버리며 원천 hash와
실행 이력을 보존한다. 기능별 정책은 [Data DB](database.md#원본관찰정규-데이터)를 따른다.

Prefect가 처음이라면 [PostgreSQL ETL 예제](writing_pipelines.md)를 먼저 실행해 본다.
이 문서는 실제 수집 기능의 코드 위치와 개발·검증 환경을 설명한다.

## 코드와 설정을 찾는 순서

1. [배포 목록](deployments.md)에서 실행 이름, Flow entrypoint와 수집 계약을 찾는다.
2. `pipelines/definitions/<domain>/<pipeline_id>.yaml`에서 Connector·Operation·적재 대상을 확인한다.
3. 기능 패키지의 `flows.py`에서 순서를, Task 모듈에서 재시도와 I/O 경계를 읽는다.
4. API 요청은 `client.py`, 값 변환은 `normalization.py`, SQL·transaction은 `repository.py`를 수정한다.

아래 트리는 `pipelines/` 기준이다.

```text
connectors/                         Provider wire 계약
references/providers/               계약의 원문 근거
verification_cases/                 Operation별 검증 입력
definitions/<domain>/               수집·output 계약
config/                             법령 대상 같은 업무 입력
prefect.yaml                        데이터 수집 Deployment
prefect.metadata.yaml               OpenMetadata Job Deployment
database/migrations/                Data DB schema
src/teoria_pipelines/
├── cli.py                          검증·migration·worker·law 명령
├── deployment.py                   두 배포의 Prefect 등록·Queue·실행 정책
├── domains/
│   ├── public_procurement/
│   │   ├── contracts/              계약 수집
│   │   ├── bid_notices/            공고·API 면허·지역 정보 수집
│   │   ├── bid_results/            낙찰 목록·개찰 보강
│   │   ├── industries/             업종 사전
│   └── legal_information/laws/     법령 원문·시행 버전
├── metadata/                       격리된 OpenMetadata Job 실행
├── execution/                      실행 기록·Raw 저장·Checkpoint Task
├── checkpoints/                    수집 범위·재개 정책
├── persistence/                    비동기 DB 연결·Raw·실행 기록·Checkpoint 저장
└── flows/pps_industries.py          기존 운영 배포 한 개의 호환 경로
```

## 기능 구현 규칙

각 기능은 Flow·Task·client·정규화와 전용 `models.py`·`repository.py`를 함께 둔다.
Flow는 단계 조합을 보여주고 API 호출과 DB 쓰기는 Prefect Task로 표현한다.
원본 응답과 정규 적재가 모두 성공한 뒤 Checkpoint를 갱신한다.

기능별 repository는 독립적으로 생성한다. `public_procurement/repository.py`는
조달 실행 건수 기록만, `public_procurement/tasks.py`는 그 완료 기록의 Task 경계만
소유한다. 공통 `LoadSummary`는 원본 건수, Domain의 `models.py`는 조달 집계를
담당한다. 공통 `persistence/`가 조달 구현을 import하지 않게 유지한다.

입찰공고는 `ingestion_tasks.py`와 `enrichment_tasks.py`로 수집과 API 보강을 구분한다.
첨부파일·문서 요건 기능은 `archive/bid_document_processing/`에 보류하며 실행 패키지에 포함하지 않는다.

새 배포는 기능의 `flows.py`를 참조한다. 이전 업종 배포를 위한 호환 모듈은 운영
entrypoint 전환 뒤 제거한다. 저장소의 선언값과 실제 Prefect 등록 상태는 별개이므로
전환 여부는 운영에서 확인한다.

## I/O와 동시 실행

API·DB Task는 `async def`로 정의하고 Flow에서 `await`한다. 변환·검증 Task는 일반
함수로 유지한다. 독립 Operation을 병렬화할 때도 Provider rate limit과 재시도 정책을
지키며 Raw 저장 → 정규 적재 → Checkpoint 순서를 바꾸지 않는다.

DB 연결은 `persistence/connection.py`의 `connect()`가 소유한다.
`TEORIA_PIPELINE_DATABASE_CONCURRENCY_LIMIT`의 기본값은 10이며 event loop별·DB별
활성 연결을 제한한다. 여기서 DB는 동일한 접속 URL 단위다. 여러 Worker·프로세스의 상한은 합산해서 DB 연결 예산에 맞춘다.
연결을 재사용하는 pool이 아니며 Prefect Task 사이에 connection·transaction을 전달하지 않는다.
성공 시 commit, 예외·취소 시 rollback 후 연결을 닫고 대기 슬롯을 반환한다.

동기 SDK가 필요한 Docker·Kubernetes Job 실행은 별도 동기 Task 경계에서 처리한다.
CLI 진입점만 `asyncio.run()`을 사용하며 Flow 내부에 중첩하지 않는다.
[Prefect Task 호출](https://reference.prefect.io/prefect/tasks/)과
[Psycopg 비동기 연결](https://www.psycopg.org/psycopg3/docs/advanced/async.html)을 참고한다.

## 개발과 검증

명령은 저장소 루트에서 실행한다. Flow를 로컬 실행할 때는 `orchestration` group,
OpenMetadata Job은 `metadata-orchestration`, Platform 계약 교차 검증은 `validation`
group이 필요하다. 기본 Worker에 OpenMetadata ingestion 패키지를 설치하지 않는다.
K3s 실행 template와 Prefect 실행 정책 통합 검증에는 `kubernetes-orchestration` group을 사용한다.

```bash
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

Pipeline 단독 DB 통합 테스트는 `pipelines/tests/integration/`, Pipeline과 Platform 사이의
계약·조회 통합 테스트는 저장소 루트 `tests/integration/`에 둔다.
법령 snapshot 저장·재파싱은 `pipelines/tests/integration/test_law_persistence.py`,
법령 수집 결과의 Platform 검색과 Runtime 읽기 권한은 루트
`tests/integration/test_law_search_contract.py`에서 검증한다. XML 입력은 Pipeline 소유
fixture를 사용하며 각 테스트 모음이 필요한 DB 상태를 직접 준비한다.

조달 단위 테스트는 `pipelines/tests/unit/domains/public_procurement/` 아래에 두며
`contracts/`, `bid_notices/`, `bid_results/`, `industries/`가 실행 코드의 기능과 대응한다.
조달 달력·여러 조달 기능에 걸친 migration 검증은 해당 Domain 바로 아래에,
공통 checkpoint·저장·설정·배포 검증은 `unit/`에 둔다. pytest는 `importlib` 모드를
사용하므로 기능별 `test_repository.py` 같은 파일명이 충돌하지 않는다.

격리된 PostgreSQL의 `teoria_data` DB와 `teoria_pipeline`,
`teoria_runtime` role을 준비하고 `TEORIA_TEST_DATA_DATABASE_URL`을 설정한다.
기존 migration의 권한 계약이 DB 이름을 참조하므로 CI도 같은 이름을 사용한다.

```bash
uv run --locked --package teoria-pipelines --group validation pytest pipelines/tests/integration tests/integration
```

Flow 또는 Data DB migration을 변경하면 Compose도 검증한다. Deployment를 변경하면
목록을 재생성하고 선언과 문서의 일치를 확인한다.

```bash
docker compose -f deploy/compose/compose.yaml config --quiet
uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs > docs/pipelines/deployments.md
uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs --check docs/pipelines/deployments.md
```

Connector 변경의 Operation별 Build·Live 검증은 [Connector 작성](connectors.md)을 따른다.
실행·재시도는 [Prefect 운영](prefect.md), 저장 규칙은 [Data DB](database.md), 업무별
처리는 [공공조달 수집](domains/public_procurement.md)과 [법령 수집](domains/legal_information.md)을 참고한다.
