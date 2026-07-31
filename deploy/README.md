# Docker Compose

모든 Compose project name은 `teoria`다. 별도 `container_name`은 지정하지 않으며 Docker Compose가 다음처럼 일관된 이름을 만든다.

```text
container  teoria-data-db-1
image      teoria-ingestion-worker
network    teoria_default
volume     teoria_data-db
```

한 호스트에서 환경을 나눌 때는 파일을 수정하지 않고 `-p teoria-dev`, `-p teoria-staging`처럼 project name을 덮어쓴다. 서비스 ID에는 `teoria-`를 반복하지 않는다.

## 파일 선택

| 목적 | 파일 | 실행 방식 |
|---|---|---|
| Registry·Pipeline 이미지 검증 | `compose.yaml` | `run --rm` |
| MCP STDIO | `compose.yaml` | `--profile mcp run --rm` |
| 검증 시 로컬 파일 mount | `compose.dev.yaml` | `compose.yaml`과 함께 사용 |
| Data DB + Prefect 전체 수집 스택 | `compose/ingestion.yaml` | `up -d` |

`compose.dev.yaml`은 단독 실행 파일이 아니라 `compose.yaml`의 override다. `compose/ingestion.yaml`은 Data Plane과 Prefect를 함께 시작하는 독립 파일이다.

## 검증과 MCP

```bash
docker compose -f deploy/compose.yaml run --build --rm registry-check
docker compose -f deploy/compose.yaml run --build --rm pipeline-check
docker compose -f deploy/compose.yaml --profile mcp run --rm mcp
```

로컬 Registry를 mount한 검증:

```bash
docker compose \
  -f deploy/compose.yaml \
  -f deploy/compose.dev.yaml \
  run --rm registry-check
```

## 수집 스택

```bash
docker compose --env-file .env \
  -f deploy/compose/ingestion.yaml \
  up --build -d

docker compose --env-file .env \
  -f deploy/compose/ingestion.yaml \
  ps

docker compose --env-file .env \
  -f deploy/compose/ingestion.yaml \
  down
```

시작 순서는 Data DB→migration, Prefect DB→Server→work pool→Deployment→Worker다. Prefect UI는 `http://localhost:4200`이다. `down -v`는 `teoria_data-db`와 `teoria_prefect-db`를 삭제하므로 데이터를 폐기할 때만 사용한다.

`--env-file .env`는 루트 설정을 Compose 변수로 읽지만 Worker에는 파일 전체가 아니라 YAML에 선언한 Pipeline 변수만 전달한다. Flow 실행은 [Prefect 가이드](../docs/ingestion/prefect.md)를 따른다.
