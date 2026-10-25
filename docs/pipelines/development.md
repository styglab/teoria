# Pipelines 개발 안내

현재 활성 업무는 `public_procurement/specification_processing/`의 규격서 파싱·추출·
표준 후보 관리·고정 표준 적용이다. Prefect는 실행과 재시도, Pipeline은 산출물과 Data DB 상태를 소유한다.
Platform Capability나 Mapping Runtime을 Pipeline 안에서 직접 호출하지 않는다.

## 코드와 설정을 찾는 순서

1. [규격서 파이프라인](../procurement_specification_processing/pipeline.md)에서 manifest와 산출물 계약을 확인한다.
2. `pipelines/prefect.yaml`과 [배포 목록](deployments.md)에서 Flow 진입점을 찾는다.
3. `flows.py`·`tasks.py`에서 실행 순서와 I/O 경계를 읽는다.
4. `parsing/`, `extraction/`, `standardization/`, `storage/`에서 해당 책임을 수정한다.

| 경로 | 책임 |
|---|---|
| `src/teoria_pipelines/domains/public_procurement/specification_processing/` | 규격서 업무 구현과 평가 CLI |
| `src/teoria_pipelines/deployment.py` | Process·Kubernetes 배포 등록과 동시 실행 상한 |
| `src/teoria_pipelines/metadata/` | 격리된 OpenMetadata ingestion Job |
| `src/teoria_pipelines/persistence/` | 소유 프로젝트의 async DB 연결·migration |
| `database/migrations/` | Data DB schema와 적용 이력 |
| `prefect.yaml`, `prefect.metadata.yaml` | 규격서·Metadata 배포 선언 |

법령 수집은 `src/teoria_pipelines/domains/legal_information/laws/`에서 활성 운영한다.
전용 Connector·수집 정의·`prefect.legal_information.yaml`을 사용한다.
이전 기업·조달 수집은 `archive/procurement_services/`의 비활성 이력이다.
활성 Flow·Registry·이미지에서 import하거나 등록하지 않는다.
Connector 기반 수집 엔진과 Provider wire 라이브러리는 기반으로 유지하되 현재 활성 Connector는 `moleg_law_api`다.

## 기능 구현 규칙

Flow는 순서를 보여주고 주요 단계는 Prefect Task로 표현한다. 원문·JSON·Markdown·표준 본문은
파일/S3에 저장하고 Data DB에는 실행·문서별 상태·산출물 URI·checksum만 둔다.
완료 체크포인트는 모든 산출물 저장에 성공한 뒤 기록한다.
추출 결과는 authoritative Ontology가 아니며 새 표준은 `pipeline_selected_draft`다.

파서는 별도 실행 환경으로 호출한다. Worker 이미지는 독립된 Kory Parser Python 환경과
고정한 모델 CLI를 포함한다. 모델 인증은 별도 volume/Secret으로 제공하고 이미지·저장소·로그에 넣지 않는다.

## I/O와 동시 실행

HTTP·DB I/O는 native async와 `await`로 연결하고 계산·검증은 일반 함수로 유지한다.
DB 연결은 `persistence/connection.py`의 `connect()`를 사용한다.
같은 transaction의 순서와 rollback을 보존하며 연결을 Task·event loop 사이에 공유하지 않는다.
`TEORIA_PIPELINE_DATABASE_CONCURRENCY_LIMIT`는 event loop별·접속 URL별 상한이다.
parser·모델 호출에는 별도 동시 실행·timeout 제한을 둔다.

## 개발과 검증

```bash
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation teoria-pipelines validate-integration pipelines --platform-registries platform/registries
uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs --check docs/pipelines/deployments.md
docker compose -f deploy/compose/compose.yaml config --quiet
```

규격서 단위 테스트는 `tests/unit/domains/public_procurement/specification_processing/`에
코드와 대응하는 구조로 둔다. 실제 저장 통합 검사는 `tests/integration/test_specification_persistence.py`,
평가 계약은 `tests/integration/test_specification_evaluation.py`가 담당한다.
실제 DB 검사는 운영과 분리한 `TEORIA_TEST_DATA_DATABASE_URL`을 사용하며 미설정 시 건너뛴다.
파서·모델 품질 개선은 [고정 평가 절차](../procurement_specification_processing/evaluation.md)를 따른다.

새 migration은 순번 파일로 추가한다. 적용한 SQL은 수정하지 않는다.
실행·재개는 [Prefect](prefect.md), 저장·권한은 [Data DB](database.md),
Metadata Job은 [OpenMetadata](openmetadata.md), 향후 Connector 계약은 [Connector 안내](connectors.md)를 따른다.
