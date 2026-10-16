# Pipeline Deployment 목록

이 표는 `pipelines/prefect*.yaml`에서 생성한다. 수동으로 수정하지 않는다.
저장소에 선언된 설정이며 실행 중인 Prefect Server 상태를 조회한 결과는 아니다.

```bash
uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs > docs/pipelines/deployments.md
uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs --check docs/pipelines/deployments.md
```

## `openmetadata-postgres-metadata-sync`

Teoria Data PostgreSQL metadata를 격리된 OpenMetadata ingestion container로 동기화한다.

- 선언: `pipelines/prefect.metadata.yaml`
- Flow: `teoria_pipelines.metadata.openmetadata.sync_openmetadata_postgres`
- Work pool: `teoria-metadata`
- Work queue: `default`
- 파라미터: `image=teoria-openmetadata-ingestion:2.0.5`, `network=teoria_default`, `timeout_seconds=1800`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `0 5 * * *` | `Asia/Seoul` | 활성 |

## `pps-industry-weekly`

나라장터 표준업종과 근거법규 전체 사전을 매주 일요일 동기화한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.industries.flows.sync_pps_industries`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `pps_industry_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `0 3 * * 0` | `Asia/Seoul` | 활성 |

## `pps-bid-notice-ingestion`

신규·변경 나라장터 입찰공고를 수집하고 공고번호별 면허제한과 참가가능지역을 보강한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_notices.flows.sync_pps_bid_notices`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `pps_bid_notice_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `lookback_days=1`, `enrichment_batch_size=20`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `0 * * * *` | `Asia/Seoul` | 활성 |

## `pps-contract-incremental`

최근 나라장터 계약정보를 4시간마다 다시 조회하여 신규·변경 데이터를 반영한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.contracts.flows.sync_pps_contract_incremental`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `pps_contract_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `lookback_days=3`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `0 */4 * * *` | `Asia/Seoul` | 활성 |

## `pps-contract-event-ledger-refresh`

변경된 공식 조달분야의 원계약·공동수급 귀속 원장과 인사이트 사전집계를 갱신한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.contracts.flows.refresh_pps_contract_event_ledger`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `pps_contract_ingestion`
- 파라미터: `batch_size=5`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `15 * * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-result-incremental`

최근 3일의 최종낙찰과 해당 공고의 개찰 참여업체 결과를 4시간마다 갱신한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_results.flows.sync_pps_bid_results_incremental`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `pps_bid_result_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `lookback_days=3`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `30 */4 * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-notice-reconciliation-3d`

최근 3일의 신규·변경 입찰공고와 참가제한 정보를 매일 보정한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_notices.flows.sync_pps_bid_notices`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_bid_notice_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `lookback_days=3`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `10 1 * * *` | `Asia/Seoul` | 비활성 |

## `pps-contract-reconciliation-30d`

최근 30일 계약정보의 지연 등록과 정정을 매일 보정한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.contracts.flows.sync_pps_contract_incremental`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_contract_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `lookback_days=30`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `0 2 * * *` | `Asia/Seoul` | 활성 |

## `pps-contract-reconciliation-90d`

최근 90일 계약정보의 장기 지연·정정을 매주 보정한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.contracts.flows.sync_pps_contract_incremental`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_contract_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `lookback_days=90`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `0 3 * * 0` | `Asia/Seoul` | 활성 |

## `pps-bid-result-reconciliation-30d`

최근 30일 개찰 건의 지연 낙찰 확정과 참여업체 결과를 매일 보정한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_results.flows.sync_pps_bid_results_incremental`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_bid_result_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `lookback_days=30`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `30 2 * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-result-reconciliation-90d`

최근 90일 개찰 건의 장기 지연 낙찰 확정을 매주 보정한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_results.flows.sync_pps_bid_results_incremental`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_bid_result_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `lookback_days=90`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `30 3 * * 0` | `Asia/Seoul` | 활성 |

## `pps-contract-backfill`

계약정보를 실행당 7일씩 역순 Backfill하며 실패한 날짜·Operation은 결손 큐로 격리해 전체 진행을 계속한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.contracts.flows.sync_pps_contract_backfill`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_contract_ingestion`
- 파라미터: `checkpoint_id=pps_contract_backfill_2021_2026`, `start_date=2021-01-01`, `end_date=2026-09-13`, `pipeline_root=/app/pipelines`, `batch_days=7`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `20 4 * * *` | `Asia/Seoul` | 활성 |

## `pps-contract-backfill-gap-retry`

계약 Backfill 결손 Operation을 작은 페이지 크기로 최대 15회까지 매일 재시도한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.contracts.flows.retry_pps_contract_backfill_gaps`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_contract_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `source_pipeline_id=pps_contract_backfill_2021_2026`, `batch_size=1`, `retry_days=1`, `max_attempts=15`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `20 5 * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-notice-backfill`

2026-09-13부터 2021-01-01까지 최신 날짜 우선으로 첨부파일과 참가제한 보강을 제외한 기본 입찰공고를 Backfill한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_notices.flows.sync_pps_bid_notice_backfill`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_bid_notice_ingestion`
- 파라미터: `checkpoint_id=pps_bid_notice_backfill_2021_2026`, `start_date=2021-01-01`, `end_date=2026-09-13`, `pipeline_root=/app/pipelines`, `batch_days=7`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `50 * * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-notice-enrichment-backfill`

기본 공고와 독립적으로 7일 이상 지난 미처리 공고의 면허제한과 참가가능지역을 제한된 호출량으로 보강한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_notices.flows.sync_pps_bid_notice_enrichment_backfill`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_bid_notice_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `batch_size=20`, `chunk_size=5`, `minimum_age_days=7`, `lease_minutes=60`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `25 * * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-result-backfill`

현재 연도 포함 최근 5개 회계연도(2022년 이후) 낙찰정보를 최신 연도 우선으로 Backfill한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_results.flows.sync_pps_bid_results_backfill`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_bid_result_ingestion`
- 파라미터: `checkpoint_id=pps_bid_result_backfill_5y`, `start_date=2022-01-01`, `end_date=2026-09-13`, `pipeline_root=/app/pipelines`, `batch_days=30`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `40 * * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-opening-incremental-enrichment`

신규 낙찰의 개찰 참여업체 Top 10과 낙찰업체를 우선 보강한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_results.flows.enrich_pps_bid_opening_participants`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `pps_bid_result_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `batch_size=30`, `lease_minutes=15`, `queue_mode=incremental`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `*/5 * * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-notice-outcome-enrichment`

낙찰이 확인되지 않은 개찰 공고를 조달청 유찰 목록으로 확인해 확정 상태와 사유를 보강한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_results.flows.enrich_pps_bid_notice_outcomes`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `pps_bid_result_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `batch_size=100`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `3-59/5 * * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-opening-backfill-enrichment`

최근 5개년 개찰 참여업체를 5분마다 최대 180개 공고씩 최신 건부터 과거 방향으로 지속 보강한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_results.flows.enrich_pps_bid_opening_participants`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `pps_bid_result_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `batch_size=180`, `lease_minutes=30`, `queue_mode=backfill`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `1-59/5 * * * *` | `Asia/Seoul` | 활성 |

## `pps-bid-opening-retry-enrichment`

실패·부분 수집된 개찰 건을 유형별 상한과 지연 정책으로 재시도한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.public_procurement.bid_results.flows.enrich_pps_bid_opening_participants`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `pps_bid_result_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `batch_size=60`, `lease_minutes=15`, `queue_mode=retry`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `7,22,37,52 * * * *` | `Asia/Seoul` | 활성 |

## `moleg-law-daily`

지정 법령의 전체 버전 목록을 확인하고 신규·변경·현행·시행예정 본문을 수집한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.legal_information.laws.flows.sync_moleg_laws`
- Work pool: `teoria-ingestion`
- Work queue: `latest`
- 수집 계약: `moleg_law_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `reconcile_all=False`, `requests_per_second=1`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `15 4 * * 1-6` | `Asia/Seoul` | 활성 |

## `moleg-law-weekly-reconciliation`

지정 법령의 모든 연혁 본문을 재조회해 기존 식별자의 원문 정정도 보존한다.

- 선언: `pipelines/prefect.yaml`
- Flow: `teoria_pipelines.domains.legal_information.laws.flows.sync_moleg_laws`
- Work pool: `teoria-ingestion`
- Work queue: `backfill`
- 수집 계약: `moleg_law_ingestion`
- 파라미터: `pipeline_root=/app/pipelines`, `reconcile_all=True`, `requests_per_second=1`

| Cron | Timezone | 예약 상태 |
|---|---|---|
| `15 4 * * 0` | `Asia/Seoul` | 활성 |
