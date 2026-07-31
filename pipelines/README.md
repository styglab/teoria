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

`pps_contract_ingestion`은 날짜를 일별 하위 Flow로 나누고 다음 Task를 순차 실행한다.

```text
상품 → 공사 → 용역 → 외자 → Raw 저장 → 정규화 → Upsert → Checkpoint
```

원본은 `ingestion.raw_provider_records`, 감사 정보는 `ingestion.pipeline_runs`, 정규 데이터는 `public_procurement` schema에 저장한다. Checkpoint는 전체 적재 성공 후에만 이동한다.

Deployment는 `prefect.yaml`, DB schema는 `database/migrations/`가 소유한다. 실행 방법은 [Prefect 운영 가이드](../docs/ingestion/prefect.md)를 따른다.
