# Prefect 기반 Pipeline 운영

Prefect는 Pipeline의 schedule, retry, 상태와 실행 그래프를 관리한다. 수집 로직과 DB schema는 `pipelines/`가 소유한다.

## 시작

루트 `.env`에 Connector 인증정보와 Prefect Basic Auth 계정을 설정한다.

```env
TEORIA_CONNECTOR_PPS_CONTRACT_API_KEY=...
TEORIA_PREFECT_USERNAME=admin
TEORIA_PREFECT_PASSWORD=충분히-긴-비밀번호
```

`TEORIA_PREFECT_USERNAME`과 `TEORIA_PREFECT_PASSWORD`는 필수다. Prefect Server는 Basic Auth를
요구하고 init, Deployment 등록과 Worker는 같은 계정으로 API에 접속한다. 현재 4200 포트는
HTTP이므로 인터넷에 무제한 공개하지 않고 내부망, VPN 또는 방화벽 허용 IP 안에서 사용한다.
UI의 API 주소는 동일 출처의 `/api`를 사용하므로 localhost와 외부 서버 IP 접속에 같은 구성을 사용한다.

```bash
docker compose --env-file .env \
  -f deploy/compose.yaml \
  up --build -d
```

| 서비스 | 역할 |
|---|---|
| `data-db`, `data-db-migrate` | 수집 DB와 migration |
| `prefect-db`, `prefect-redis` | Prefect 영속 상태, 메시징과 서비스 조정 |
| `prefect-server`, `prefect-services` | Prefect API/UI와 Scheduler 등 백그라운드 서비스 |
| `prefect-init`, `prefect-deploy` | Work pool과 Deployment 등록 |
| `prefect-worker` | Prefect Flow 실행 |

Compose 배포 시 UI는 nginx의 `http://localhost:8081/prefect/`로 접근한다. Prefect Server의 4200 포트는 Compose 내부에서만 사용한다. Worker에는 `.env` 전체가 아니라 Compose에 선언한 Pipeline 변수만 전달한다.

## 계약정보 Deployment

| Deployment | 주기 | 역할 |
|---|---|---|
| `pps-contract-incremental` | 4시간마다 | 오늘을 포함한 최근 3일을 재조회하여 신규·변경 계약을 반영 |
| `pps-contract-backfill` | 매시 20분 | `2020-01-01`부터 `2025-12-31`까지 정방향으로 실행당 최대 30일 적재 |

두 Deployment는 독립 checkpoint를 사용한다. 기본 Backfill checkpoint는
`pps_contract_backfill_2020_2025`이고 `2020-01-01`부터 `2025-12-31`까지 정방향으로 진행한다. 범위를 완료하면
이후 예약 실행은 API를 호출하지 않는다.

별도 범위를 적재할 때는 UI에서 같은 Flow의 Custom Run이나 Schedule 파라미터에 고유한
`checkpoint_id`, `start_date`, `end_date`를 지정한다. 서로 다른 Backfill에 같은
`checkpoint_id`를 사용하면 진행 상태가 충돌하므로 사용하지 않는다.
Backfill의 `checkpoint_id`, `start_date`, `end_date`는 필수이며 `end_date`는 오늘보다 이전이어야 한다.

공공데이터포털은 데이터 갱신주기를 실시간으로 안내하지만 정확한 반영 지연은 보장하지 않는다.
Incremental은 지연 반영을 고려해 최근 3일을 중복 조회하며 정규 테이블에 upsert한다.

## 수동 실행

```bash
docker compose --env-file .env \
  -f deploy/compose.yaml \
  run --rm prefect-deploy \
  prefect deployment run '나라장터 계약정보 Backfill/pps-contract-backfill' \
  --param checkpoint_id=pps_contract_backfill_2020_2025 \
  --param start_date=2020-01-01 \
  --param end_date=2025-12-31 \
  --param batch_days=30
```

UI의 일별 하위 Flow에서 상품→공사→용역→외자→Raw 저장→정규화→Upsert→Checkpoint 순서와 재시도를 확인할 수 있다.

## 실패와 종료

- API와 DB 쓰기는 Task 단위로 재시도한다.
- Raw와 정규 적재는 idempotent하게 처리한다.
- 실패 실행은 감사 테이블에 기록하고 Checkpoint는 이동하지 않는다.
- 다음 실행은 Checkpoint에서 이틀을 겹쳐 지연 반영을 다시 읽는다.

```bash
docker compose --env-file .env \
  -f deploy/compose.yaml \
  down
```

`down -v`는 수집 데이터와 Prefect 이력을 삭제하므로 로컬 데이터를 폐기할 때만 사용한다.
