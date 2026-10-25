# 수집·문서 처리 개발 안내

수집과 문서 처리는 `backend/`의 기능 모듈이며 Prefect Worker에서 별도로 실행한다.
Python 프로젝트는 하나지만 실행 권한과 데이터 책임은 [저장소 구조](../architecture/repository-structure.md)를 따른다.

## 코드와 설정

아래 경로는 `backend/` 기준이다.

| 위치 | 책임 |
|---|---|
| `src/teoria/features/specification_processing/` | 규격서 파싱·정보 추출·고정 표준 적용·평가·Flow |
| `src/teoria/features/legal_information/collection/` | 법령 수집·구조화·적재·Flow |
| `src/teoria/features/metadata_management/ingestion/` | 격리된 OpenMetadata ingestion Job |
| `src/teoria/integrations/prefect/` | Process·Kubernetes 배포·pool·queue·동시 실행 상한 |
| `src/teoria/integrations/data_operations/` | Connector 계약·실행·checkpoint·Data DB 기반 |
| `src/teoria/integrations/provider_api/` | Provider wire 계약과 HTTP 실행 |
| `migrations/data/` | Data DB schema와 적용 이력 |
| `connectors/`, `definitions/`, `config/` | 수집 계약·대상·업무 입력 |
| `prefect.yaml`, `prefect.metadata.yaml`, `prefect.legal_information.yaml` | 기능별 배포 선언 |

규격서는 [파이프라인 계약](../procurement_specification_processing/pipeline.md)과 manifest를 먼저 읽고
`flows.py`·`tasks.py`에서 순서를 확인한다. 세부 변경 위치는 `parsing/`, `extraction/`,
`normalization/`, `storage/`다. 표준 적용은 이 기능에서 수행하고 후보 제안·프로파일 승인은
`features/goods_normalization/`이 소유한다.

공고·계약·기업 분석과 구형 첨부 자동 수집은 `archive/`에 보관한다. 활성 Flow·Registry·이미지로
다시 연결하지 않는다. 현재 활성 Connector는 법령 수집용 `moleg_law_api`다.

## 실행과 권한

Flow는 주요 단계를 Prefect Task로 표현한다. 원문·추출 JSON·Markdown·표준 본문은 파일/S3,
실행 상태·문서별 요약·산출물 URI·checksum은 Data DB에 둔다. 모든 산출물 저장과 적재가
성공한 뒤 완료 checkpoint를 갱신한다. DB 연결은 `integrations/data_operations/persistence/connection.py`를 사용한다.

규격서 Worker에는 별도 환경의 parser 실행 파일과 Codex CLI·인증이 필요하다.
법령 Worker는 parser·Codex 실행 파일 없이 전용 pool에서 실행한다. OpenMetadata ingestion은
전용 Worker가 공식 ingestion image를 ephemeral Job으로 실행한다. 일반 Worker에 ingestion SDK를 설치하지 않는다.

문서 처리에서 Runtime·의미 작성 저장소를 직접 호출하지 않는다. 상위 표준관리 Flow는 인증된
Admin HTTP API를 사용한다. 추출 결과와 추출 표준 자동 채택은 Published Ontology가 아니다.

## 검증

```bash
uv sync --project backend --locked --all-extras --all-groups
uv run --project backend --locked --all-extras --all-groups pytest backend/tests tests/integration
uv run --project backend --locked teoria-pipelines validate backend
uv run --project backend --locked --extra api teoria-pipelines validate-integration backend --platform-registries backend/registries
uv run --project backend --locked teoria-pipelines deployment-docs --check docs/pipelines/deployments.md
docker compose -f deploy/compose/compose.yaml config --quiet
```

규격서 단위 테스트는 `backend/tests/features/specification_processing/`, 법령은
`backend/tests/features/legal_information/collection/`, Data DB 통합은
`backend/tests/integration/data_operations/`에 둔다. 운영과 분리된
`TEORIA_TEST_DATA_DATABASE_URL`로 검사하며 미설정 시 DB 테스트는 건너뛴다.
새 migration은 `backend/migrations/data/`에 순번 파일로 추가하고 적용된 SQL은 수정하지 않는다.

[Prefect 운영](prefect.md), [Data DB](database.md), [Metadata Job](openmetadata.md),
[Connector 작성](connectors.md), [고정 평가 절차](../procurement_specification_processing/evaluation.md)를 함께 따른다.
