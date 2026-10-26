# Pipeline Deployment 목록

이 표는 `deploy/prefect/*.yaml`에서 생성한다. 수동으로 수정하지 않는다.
저장소에 선언된 설정이며 실행 중인 Prefect Server 상태를 조회한 결과는 아니다.

```bash
uv run --locked --project backend teoria-pipelines deployment-docs > docs/pipelines/deployments.md
uv run --locked --project backend teoria-pipelines deployment-docs --check docs/pipelines/deployments.md
```

## `moleg-law-daily`

지정 법령의 전체 버전 목록을 확인하고 신규·변경·현행·시행예정 본문을 수집한다. 독립 법령 pool에서 실행하며 조달 Backfill은 재개하지 않는다.

- 선언: `deploy/prefect/legal_information.yaml`
- Flow: `teoria.features.legal_information.collection.flows.sync_moleg_laws`
- Work pool: `teoria-legal-information`
- Work queue: `laws`
- 수집 계약: `moleg_law_ingestion`
- 파라미터: `pipeline_root=/app/backend`, `reconcile_all=False`, `requests_per_second=1`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `15 4 * * 1-6` | `Asia/Seoul` | 활성 |

## `moleg-law-weekly-reconciliation`

지정 법령의 모든 연혁 본문을 재조회해 기존 식별자의 원문 정정도 보존한다. 독립 법령 pool에서 실행하며 조달 Backfill은 재개하지 않는다.

- 선언: `deploy/prefect/legal_information.yaml`
- Flow: `teoria.features.legal_information.collection.flows.sync_moleg_laws`
- Work pool: `teoria-legal-information`
- Work queue: `laws`
- 수집 계약: `moleg_law_ingestion`
- 파라미터: `pipeline_root=/app/backend`, `reconcile_all=True`, `requests_per_second=1`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `15 4 * * 0` | `Asia/Seoul` | 활성 |

## `openmetadata-postgres-metadata-sync`

Teoria Data PostgreSQL metadata를 격리된 OpenMetadata ingestion container로 동기화한다.

- 선언: `deploy/prefect/metadata_management.yaml`
- Flow: `teoria.features.metadata_management.ingestion.openmetadata.sync_openmetadata_postgres`
- Work pool: `teoria-metadata`
- Work queue: `default`
- 파라미터: `image=teoria-openmetadata-ingestion:2.0.5`, `network=teoria_default`, `timeout_seconds=1800`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `0 5 * * *` | `Asia/Seoul` | 활성 |

## `specification-standard-management`

명시적으로 입력한 규격서에서 표준 후보를 수집하고 추출 표준 draft를 생성한다.

- 선언: `deploy/prefect/specification_processing.yaml`
- Flow: `teoria.features.specification_processing.flows.standard_management_flow`
- Work pool: `teoria-specification`
- Work queue: `documents`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| — | — | 수동 실행 |

## `specification-document-processing`

명시적으로 입력한 규격서에 고정된 표준 버전을 적용하고 결과와 근거를 보존한다.

- 선언: `deploy/prefect/specification_processing.yaml`
- Flow: `teoria.features.specification_processing.flows.document_processing_flow`
- Work pool: `teoria-specification`
- Work queue: `documents`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| — | — | 수동 실행 |

## `specification-standard-workflow`

추출·Platform 의미 판정·승인 상태 확인·고정 표준 저장·재적용을 연결하고 체크포인트에서 재개한다.

- 선언: `deploy/prefect/specification_processing.yaml`
- Flow: `teoria.features.specification_processing.standard_workflow.standard_workflow_flow`
- Work pool: `teoria-specification`
- Work queue: `documents`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| — | — | 수동 실행 |
