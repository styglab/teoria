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

Backfill은 `checkpoint_id`별로 날짜 정방향 진행 상태를 관리하므로 UI에서 기간별 작업을 독립적으로
실행할 수 있다. 기본 작업은 `pps_contract_backfill_2026`을 사용하고 종료일이 없으면 실행 시점의
어제까지 처리한다. 기본 Deployment는 Incremental과 역할이 겹치지 않도록 종료일을
`2026-07-31`로 고정한다.

```text
상품 → 공사 → 용역 → 외자 → Raw 저장 → 정규화 → Upsert → Checkpoint
```

원본은 `ingestion.raw_provider_records`, 감사 정보는 `ingestion.pipeline_runs`, 정규 데이터는 `public_procurement` schema에 저장한다. Checkpoint는 전체 적재 성공 후에만 이동한다.

Deployment는 `prefect.yaml`, DB schema는 `database/migrations/`가 소유한다. 실행 방법은 [Prefect 운영 가이드](../docs/ingestion/prefect.md)를 따른다.
