# Teoria Data Pipelines

`pipelines/`는 Connector, Prefect 수집과 Teoria Data DB 쓰기를 소유한다. Platform Runtime을 import하지 않고 공통 API 실행만 `teoria-provider`를 사용한다.

```text
Connector → Extract → Raw → Normalize → Upsert → Checkpoint
```

## 검증

```bash
uv run --locked --package teoria-pipelines pytest pipelines/tests
uv run --locked --package teoria-pipelines teoria-pipelines validate pipelines
uv run --locked --package teoria-pipelines --group validation \
  teoria-pipelines validate-integration pipelines \
  --platform-registries platform/registries
```

## PPS 계약 Flow

나라장터 계약 수집은 최신 데이터용 `pps_contract_incremental`과 과거 데이터용
`pps_contract_backfill`로 나뉜다. 두 Flow는 독립 checkpoint를 사용하고 날짜를 일별 하위 Flow로
나누어 다음 Task를 순차 실행한다.

Backfill은 `checkpoint_id`별로 최신 날짜에서 과거 방향 진행 상태를 관리하므로 UI에서 기간별 작업을
독립적으로 실행할 수 있다. 기본 작업은 `pps_contract_backfill_2021_2026`을 사용하고
`2026-09-13`부터 `2021-01-01`까지 처리한다.

```text
상품 → 공사 → 용역 → 외자 → Raw 저장 → 정규화 → Upsert → Checkpoint
```

신규 원본 본문은 hash 기준으로 `ingestion.raw_provider_payloads`에 한 번만 저장하고 실행별
관찰 이력은 `ingestion.raw_provider_observations`에 기록한다. migration 036 이전의 중복 원본
테이블은 migration 037에서 제거했다. 실행 감사 정보는 `ingestion.pipeline_runs`, 정규 데이터는
`public_procurement` schema에 저장한다.
Checkpoint는 원본 관찰과 정규 적재가 모두 성공한 뒤에만 이동한다.

입찰공고는 최신 데이터용 `pps_bid_notice_ingestion`과 과거 데이터용
`pps_bid_notice_backfill_2021_2026`을 독립 checkpoint로 운영한다. Backfill은
`2026-09-13`부터 `2021-01-01`까지 최신 날짜 우선으로 진행하며 공고와 면허·지역 제한은
저장하되, 과거 첨부파일은 다운로드 대기열에 추가하지 않는다.

최신 공고는 당일 범위를 10분마다 조회하고 최근 3일을 매일 보정한다. 계약과 낙찰은
최근 3일을 4시간마다 조회하며, 지연 등록과 정정을 위해 최근 30일을 매일, 최근 90일을
매주 별도 Deployment로 보정한다. 정확한 실행 시각과 조회 기준은
[최신 데이터 수집·보정 주기](../docs/ingestion/prefect.md#최신-데이터-수집보정-주기)를 따른다.

Deployment는 `prefect.yaml`, DB schema는 `database/migrations/`가 소유한다. 실행 방법은 [Prefect 운영 가이드](../docs/ingestion/prefect.md)를 따른다.
