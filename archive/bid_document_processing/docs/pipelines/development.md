# Pipelines 개발 안내

Pipelines는 외부 데이터를 수집하고 원본과 정규 데이터를 Teoria Data DB에 적재한다.
Prefect는 실행·스케줄·재시도를 관리한다. 업무 의미와 사용자별 참가 가능성 평가는
Platform이 담당하며 Pipeline 실행 코드가 Platform Runtime을 호출하지 않는다.

```text
Connector API → 조회 → Raw 저장 → 정규화 → 정규 적재 → Checkpoint
```

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
├── domains/
│   ├── public_procurement/
│   │   ├── contracts/              계약 수집
│   │   ├── bid_notices/            공고·첨부파일 획득과 보존
│   │   ├── bid_results/            낙찰 목록·개찰 보강
│   │   ├── industries/             업종 사전
│   │   └── bid_eligibility/        문서 파싱·요건 추출·검증
│   └── legal_information/laws/     법령 원문·시행 버전
├── metadata/                       격리된 OpenMetadata Job 실행
├── execution/                      실행 기록·Raw 저장·Checkpoint Task
├── checkpoints/                    수집 범위·재개 정책
├── persistence/                    DB·Raw·Object Storage 기반
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

입찰공고는 `ingestion_tasks.py`, `enrichment_tasks.py`, `document_tasks.py`,
`retention_tasks.py`로 수집·보강·첨부파일·보존 처리를 구분한다. 참가자격은
`extraction.py`가 모델 실행을, `validation.py`와 `repair/`가 근거 검증·의미 보정을
담당한다. 코드 위치 변경만으로 추출 버전이나 입력 fingerprint를 바꾸지 않는다.

새 배포는 기능의 `flows.py`를 참조한다. 이전 업종 배포를 위한 호환 모듈은 운영
entrypoint 전환 뒤 제거한다. 저장소의 선언값과 실제 Prefect 등록 상태는 별개이므로
전환 여부는 운영에서 확인한다.

## 개발과 검증

명령은 저장소 루트에서 실행한다. Flow를 로컬 실행할 때는 `orchestration` group,
OpenMetadata Job은 `metadata-orchestration`, Platform 계약 교차 검증은 `validation`
group이 필요하다. 기본 Worker에 OpenMetadata ingestion 패키지를 설치하지 않는다.

```bash
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

Pipeline과 Platform 사이의 DB 통합 테스트는 저장소 루트의 `tests/integration/`에 있다.
격리된 PostgreSQL의 `teoria_data` DB와 `teoria_pipeline`,
`teoria_runtime` role을 준비하고 `TEORIA_TEST_DATA_DATABASE_URL`을 설정한다.
기존 migration의 권한 계약이 DB 이름을 참조하므로 CI도 같은 이름을 사용한다.

```bash
uv run --locked --package teoria-pipelines --group validation pytest tests/integration
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
처리는 [공공조달 수집](domains/public_procurement.md)과 [법령 수집](law_collection.md)을 참고한다.
