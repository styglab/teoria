# PostgreSQL 변경분을 DW에 반영하는 ETL 만들기

매일 저녁, 원천 PostgreSQL에서 **전날 수정된 주문**을 읽어 데이터웨어하우스(DW)에 반영해 보자.
새 주문뿐 아니라 과거 주문의 금액 수정, 취소, 삭제 표시도 반영한다.
원천과 DW는 이미 있다고 가정하며 DB나 테이블을 만드는 코드는 포함하지 않는다.

예제 파일은 [flows.py](../../backend/examples/db_sales/flows.py)와
[prefect.yaml](../../backend/examples/db_sales/prefect.yaml) 두 개다.

```text
처리 날짜 확정 → Extract         → Transform    → Validate     → Load
               updated_at 조회   상태 표기 통일  품질 검사      DW 주문 갱신
                                                실패하면 중단
```

ETL은 Extract(추출), Transform(변환), Load(적재)의 약자다. 여기에 **적재 전 검증**을 넣는다.
Python에는 처리 순서·SQL·검증 규칙을, `prefect.yaml`에는 실행 입력값과 배포 설정을 둔다.

## 1. 기존 테이블과 삭제 표시 이해하기

원천은 `public.orders`, 대상은 PostgreSQL 기반 DW의 `warehouse.orders`를 사용한다.
두 테이블에는 다음 컬럼이 이미 있어야 한다. 실제 이름이 다르면 예제의 SQL과 검증 규칙을 바꾼다.

| 컬럼 | 가정하는 타입·역할 |
|---|---|
| `order_id` | 비어 있지 않은 주문 ID. DW의 고유 키 |
| `order_date` | 주문한 날짜, `date`. 과거 날짜여도 처리 대상이 될 수 있음 |
| `amount` | 비어 있지 않은 0 이상의 숫자 |
| `status` | `pending`, `paid`, `cancelled` 중 하나 |
| `is_deleted` | 비어 있지 않은 `boolean`. 정상은 `false`, 삭제 표시는 `true` |
| `updated_at` | 비어 있지 않은 최종 변경 시각, `timestamptz` |

원천은 행을 물리적으로 지우는 대신 `is_deleted=true`로 바꾼다.
**추가·수정·취소·삭제 표시·복구 때마다 `updated_at`도 이전 값보다 큰 시각으로 갱신**해야 한다.
삭제 표시를 해도 나머지 컬럼은 유지된다고 가정한다. ETL이 읽기 전에 행을 제거하면 이 예제로는 삭제를 알 수 없다.

예를 들어 10월 15일에 다음 변경이 있었다면 세 주문을 모두 가져온다.

| 주문 | 원래 주문일 | 10월 15일 변경 | DW에 반영하는 내용 |
|---|---|---|---|
| A001 | 10월 15일 | 새 결제 주문 | 새 행 추가 |
| A002 | 9월 1일 | 주문 취소 | `status=cancelled`로 갱신 |
| A003 | 8월 10일 | 삭제 표시 | `is_deleted=true`로 갱신 |

DW에서도 삭제된 행을 남겨 상태를 확인할 수 있게 한다. 결제 매출을 조회할 때
`is_deleted=false AND status='paid'` 조건으로 제외한다. 이 예제는 주문의 최신 상태를 갱신하며,
모든 변경 이력을 별도 행으로 보관하는 모델은 아니다. 새 DW의 최초 전체 적재도 별도 단계다.

## 2. 전날의 조회 범위 고정하기

한국 시간 매일 **22:00**에 실행한다. 10월 16일에 예약된 Run은 다음 범위를 처리한다.

```text
business_date = 2026-10-15
시작: 2026-10-15 00:00:00+09:00  — 포함
종료: 2026-10-16 00:00:00+09:00  — 제외
```

```sql
SELECT order_id, order_date, amount, status, is_deleted, updated_at
FROM public.orders
WHERE updated_at >= %(window_start)s
  AND updated_at <  %(window_end)s
ORDER BY updated_at, order_id;
```

종료 시각을 제외하면 정확히 자정에 수정된 행은 다음 날짜에 포함된다.
`updated_at`을 날짜로 변환하지 않고 시각 범위로 비교하며, Python에서 시간대가 있는 값을 전달한다.
조회량이 많으면 원천의 `updated_at` 인덱스와 쿼리 실행 계획을 확인한다.

날짜를 생략하면 실제 시작 시각 대신 **Prefect 예약 시각의 한국 날짜 기준 전날**을 사용한다.
Worker가 늦게 실행돼도 원래 처리하려던 날짜를 유지하기 위해서다.
과거 날짜를 새 Run으로 재처리할 때는 `business_date`를 반드시 직접 지정한다.

## 3. 실행 환경 연결하기

`uv`, 기존 PostgreSQL 원천·DW, 접근 가능한 Prefect Server 또는 Prefect Cloud가 필요하다.
이번 예제는 **같은 머신의 저장소를 읽는 Process Worker**로 실행한다.
Worker는 Prefect에 등록된 작업을 받아 Python 프로세스로 실행하는 프로그램이다.

저장소 루트에서 다음 환경변수를 설정한다. 아래 주소와 계정은 자신의 접속 정보로 바꾼다.
Secret 관리 도구로 값을 주입해도 된다.

```bash
export PREFECT_API_URL='https://your-prefect-host/api'
export ETL_SOURCE_DATABASE_URL='postgresql://reader:password@source-host:5432/source_db'
export ETL_TARGET_DATABASE_URL='postgresql://writer:password@warehouse-host:5432/warehouse_db'
export ETL_EXAMPLE_DIRECTORY="$PWD/pipelines/examples/db_sales"

uv sync --locked --project backend --group orchestration --group etl-example
```

원천 계정에는 조회 권한, DW 계정에는 조회·추가·갱신 권한이 필요하다.
Prefect Cloud는 Workspace의 API URL과 `PREFECT_API_KEY`, Basic 인증을 사용하는
Server는 `PREFECT_API_AUTH_STRING`도 설정한다. 이미 구성된 접속 설정이 있으면 그대로 쓴다.
DB 비밀번호는 YAML의 `parameters`에 넣지 않는다. 이 입력값은 Prefect에 저장된다.

Great Expectations와 pandas는 `etl-example` 의존성 그룹에만 추가되어 있다.
기본 운영 Worker 이미지는 이 그룹과 예제 파일을 포함하지 않는다.
이 문서의 Worker는 아래 명령으로 따로 실행한다.

## 4. Flow의 실행 순서 읽기

Flow는 작업 전체, Task는 UI에서 실행 결과와 실패 지점을 확인할 수 있는 한 단계다.
`orders_etl`의 핵심 순서는 다음과 같다.

```python
window_start, window_end = resolve_window(business_date)
orders = await extract_orders.with_options(**db_policy)(window_start, window_end)
rows = transform_orders(orders)
if not rows:
    return 0
validate_orders(rows)
await load_orders.with_options(**db_policy)(rows)
```

DB를 읽고 쓰는 Task와 Flow는 비동기 함수이며 `await`로 완료를 기다린다.
변환·검증 Task는 일반 함수로 유지한다.

`extract_orders`는 변경 시각으로 조회한다. 결제 상태나 삭제 여부로 원천을 필터링하지 않는다.
`transform_orders`는 `" PAID "`를 `"paid"`로 바꾸는 등 상태 표기를 통일한다.
취소·삭제 행도 그대로 검증과 적재에 전달한다. 변경 행이 0건이면 저장 없이 성공으로 종료한다.
데이터 전체를 메모리에 읽는 작은 예제이므로 대량 데이터는 배치 단위로 나누어 처리한다.

### Load 전에 Great Expectations로 검증하기

Great Expectations(GX)는 데이터가 정해 둔 조건을 만족하는지 검사하는 라이브러리다.
변환 결과를 pandas DataFrame으로 바꿔 다음 조건을 확인한다.

| 검사 | 막으려는 문제 |
|---|---|
| 여섯 컬럼이 모두 비어 있지 않음 | 식별자·업무 값·변경 시각 누락 |
| 주문 ID가 중복되지 않음 | 한 배치에 같은 주문이 여러 번 등장 |
| 금액이 0 이상 | 음수 금액 적재 |
| 상태가 `pending`, `paid`, `cancelled` 중 하나 | 알 수 없는 상태 적재 |
| 삭제 표시가 boolean | `"true"` 같은 문자열을 삭제 값으로 오인 |

검사 한 개는 다음처럼 작성한다.

```python
check = gx.expectations.ExpectColumnValuesToBeBetween(column="amount", min_value=0)
result = batch.validate(check, result_format="BOOLEAN_ONLY")
if not result.success:
    raise ValueError("적재 중단: 금액 검사 실패")
```

GX가 실패 결과를 반환하는 것만으로 Flow가 중단되지는 않는다. **예외를 발생시켜야**
뒤의 `load_orders`가 호출되지 않는다. 예제에서는 실패한 규칙과 컬럼 이름만 오류에 남기고,
검사 결과의 원본 행을 출력하지 않는다. 삭제 표시 행도 같은 검사를 받는다.

### DW에 최신 상태 반영하기

`load_orders`는 주문 ID가 없으면 추가하고, 있으면 최신 값으로 갱신한다.
취소 상태와 삭제 표시도 함께 저장한다. 핵심 SQL은 다음과 같다.

```sql
INSERT INTO warehouse.orders AS target (...)
VALUES (...)
ON CONFLICT (order_id) DO UPDATE SET
    -- 날짜·금액·상태·삭제 표시·변경 시각 갱신
    ...
WHERE target.updated_at < EXCLUDED.updated_at;
```

위 코드는 구조 설명용이며 실행할 전체 SQL은 `flows.py`에 있다.
DW에 더 최신 값이 있으면 과거 데이터로 덮어쓰지 않는다. 같은 버전을 재실행하면 저장을 생략한다.
전체 배치를 한 트랜잭션으로 반영하므로 중간에 SQL이 실패하면 rollback된다.
완료 로그의 건수는 입력 건수이며, 실제 추가·갱신된 행 수와 다를 수 있다.

## 5. prefect.yaml에서 실행 정책 정하기

[예제 YAML](../../backend/examples/db_sales/prefect.yaml)의 주요 부분이다.

```yaml
parameters:
  business_date: null
  db_retries: 2
  db_retry_delay_seconds: 5
  db_task_timeout_seconds: 60
concurrency_limit:
  limit: 1
  collision_strategy: ENQUEUE
schedules:
  - cron: '0 22 * * *'
    timezone: Asia/Seoul
    active: false
```

`parameters`의 재시도·timeout 항목은 **이 예제 Flow가 정의한 입력값**이다.
Python에서 `.with_options(...)`로 Extract와 Load Task에 적용한다.
배포 항목 바로 아래에 `retries: 2`를 추가한다고 Task 재시도가 설정되는 것은 아니다.

| 정책 | 예제 값과 적용 위치 |
|---|---|
| DB 작업 재시도 | `db_retries: 2`: 최초 시도 후 최대 2회 추가 시도 |
| 재시도 간격 | `db_retry_delay_seconds: 5`: 재시도 전 5초 대기 |
| DB Task 제한 시간 | `db_task_timeout_seconds: 60`: 시도 한 번에 60초 |
| 날짜 확정·검증·변환 재시도 | Python의 `@task(retries=0)` |
| 전체 Flow 재시도·제한 시간 | Python의 `@flow(retries=0, timeout_seconds=300)` |
| 같은 배포의 동시 실행 | 한 번에 하나, 추가 실행은 대기 |
| 정기 실행 | 한국 시간 매일 22:00, 처음에는 비활성화 |

DB Task는 native async 연결을 사용한다. Prefect timeout 외에도 DB 자체의 실행 제한을 둔다.
코드에도 연결 제한 10초, SQL 실행 제한 30초, 적재 잠금 대기 제한 5초를 둔다.
실제 쿼리 시간에 맞춰 조정한다.

## 6. 배포하고 한 번 실행하기

먼저 Work pool을 만든다. Work pool은 어떤 Worker가 작업을 받을지 정하는 실행 대기 공간이다.
같은 이름의 pool이 이미 있다면 생성 명령은 생략한다.

```bash
uv run --locked --project backend --group orchestration --group etl-example \
  prefect work-pool create --type process example-etl

cd backend/examples/db_sales
uv run --locked --project backend --group orchestration --group etl-example \
  prefect deploy --all --prefect-file prefect.yaml
cd ../../..
```

이 명령은 Flow 입력값·스케줄·코드 위치를 Prefect에 등록한다. 코드를 서버로 업로드하지는 않는다.
YAML의 `pull`은 Worker가 실행 전에 `ETL_EXAMPLE_DIRECTORY`로 이동하도록 한다.
배포 시 이 값이 실제 절대 경로로 들어가므로 동일한 머신과 저장소 경로를 사용한다.

같은 터미널에서 Worker를 시작한다. 앞서 설정한 DB·Prefect 환경변수를 이 Worker가 상속한다.

```bash
uv run --locked --project backend --group orchestration --group etl-example \
  prefect worker start --pool example-etl
```

Worker를 켜 둔 채 Prefect UI의 Deployments → `orders-daily` → Run에서
`business_date`에 변경 데이터가 있는 날짜(예: `2026-10-15`)를 입력한다.
API 접속 설정을 한 별도 터미널에서 실행해도 된다.

```bash
uv run --locked --project backend --group orchestration --group etl-example \
  prefect deployment run 'orders-etl/orders-daily' --param business_date=2026-10-15
```

UI에서 처리 날짜 확정 → Extract → Transform → Validate → Load가 성공했는지 확인한다.
DW에서는 알고 있는 주문 ID로 상태·삭제 표시·변경 시각이 반영되었는지 확인한다.
`order_date`는 원래 주문한 날짜이므로 이번 배치 날짜와 다를 수 있다.

```sql
SELECT order_id, order_date, amount, status, is_deleted, updated_at
FROM warehouse.orders
WHERE order_id IN ('A001', 'A002', 'A003');

-- 분석에서 사용하는 정상 결제 주문
SELECT order_id, amount
FROM warehouse.orders
WHERE is_deleted = false AND status = 'paid';
```

Validate가 실패했다면 Load 실행 기록이 없어야 한다. 원본 값이나 변환·검증 규칙을
확인하고 고친 뒤 **같은 `business_date`**를 지정해 다시 실행한다.

## 7. 체크포인트와 재처리 범위

이 예제는 날짜를 지정하는 최소 배치이므로 별도 체크포인트 테이블을 만들지 않는다.
Prefect에서 Run별 조회 범위 로그와 성공·실패를 확인한다. **실패한 날짜와 실행되지 않은 날짜를
자동으로 찾아 보충하지는 않는다.** 빠진 날짜는 직접 지정해 실행해야 한다.
자동 복구가 필요하면 날짜별 완료 기록이나 마지막 성공 위치를 관리하는 단계를 추가한다.
체크포인트는 검증과 최종 적재가 모두 성공한 뒤에만 갱신한다.

원천 테이블에는 현재 행만 있으므로, 이후 다시 수정된 행은 과거 날짜 범위를 재조회할 때
나오지 않을 수 있다. 원천의 `updated_at` 소급 변경이나 지연 커밋에도 별도 대응이 필요하다.
이 예제는 날짜별 변경 이력을 완전히 복원하는 방식이 아니다. 동일한 입력으로 재처리해야 하면
추출 결과를 보관하고, 모든 변경을 놓치지 않아야 하면 CDC·변경 이력을 사용하는 방식으로 확장한다.

## 8. 수정한 내용을 반영하기

예를 들어 YAML의 `db_retries`를 `3`으로 바꿨다면 6절의 `prefect deploy`를 다시 실행한다.
정기 실행은 결과를 확인한 뒤 `active: true`로 바꾸고 다시 배포한다.
이전 예제의 `paid-orders` 배포가 남아 있다면 UI에서 해당 배포의 스케줄을 중지하고 새 배포를 사용한다.

Python을 바꿨다면 Worker가 읽는 같은 경로의 파일을 갱신하고 `version`도 올려 다시 배포한다.
실행 중인 Run이 끝난 후 변경한다. Process Worker는 다음 Run에서 그 파일을 읽는다.
운영 배포의 이미지 빌드·코드 전달·Worker 갱신은 [Prefect 운영 안내](prefect.md)를 따른다.

API 수집을 추가할 때 필요한 Connector와 Definition, 실제 기능 코드 배치는
[개발 안내](development.md)에서 이어서 확인한다. 이 DB 예제를 위해 API Connector나
별도 업무 정책 YAML을 만들 필요는 없다.

공식 참고: [Prefect 배포 YAML](https://docs.prefect.io/v3/how-to-guides/deployments/prefect-yaml),
[예약 시각 조회](https://docs.prefect.io/v3/api-ref/python/prefect-runtime-flow_run),
[GX DataFrame 검증](https://docs.greatexpectations.io/docs/core/introduction/try_gx/),
[PostgreSQL UPSERT](https://www.postgresql.org/docs/17/sql-insert.html).
