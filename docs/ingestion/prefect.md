# Prefect 기반 Pipeline 운영

Prefect는 Pipeline의 schedule, retry, 상태와 실행 그래프를 관리한다. 수집 로직과 DB schema는 `pipelines/`가 소유한다.

## 시작

루트 `.env`에 `TEORIA_CONNECTOR_PPS_CONTRACT_API_KEY`를 설정한다.

```bash
docker compose --env-file .env \
  -f deploy/compose/ingestion.yaml \
  up --build -d
```

| 서비스 | 역할 |
|---|---|
| `data-db`, `data-db-migrate` | 수집 DB와 migration |
| `prefect-db`, `prefect-server` | Prefect 상태, API와 UI |
| `prefect-init`, `deployment-apply` | Work pool과 Deployment 등록 |
| `ingestion-worker` | Flow 실행 |

UI는 `http://localhost:4200`이다. Worker에는 `.env` 전체가 아니라 Compose에 선언한 Pipeline 변수만 전달한다.

## 수동 실행

```bash
docker compose --env-file .env \
  -f deploy/compose/ingestion.yaml \
  run --rm deployment-apply \
  prefect deployment run '나라장터 계약정보 수집/pps-contract-daily' \
  --param start_date=2016-08-30 \
  --param end_date=2016-08-30
```

UI의 일별 하위 Flow에서 상품→공사→용역→외자→Raw 저장→정규화→Upsert→Checkpoint 순서와 재시도를 확인할 수 있다.

## 실패와 종료

- API와 DB 쓰기는 Task 단위로 재시도한다.
- Raw와 정규 적재는 idempotent하게 처리한다.
- 실패 실행은 감사 테이블에 기록하고 Checkpoint는 이동하지 않는다.
- 다음 실행은 Checkpoint에서 이틀을 겹쳐 지연 반영을 다시 읽는다.

```bash
docker compose --env-file .env \
  -f deploy/compose/ingestion.yaml \
  down
```

`down -v`는 수집 데이터와 Prefect 이력을 삭제하므로 로컬 데이터를 폐기할 때만 사용한다.
