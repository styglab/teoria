# Docker Compose

`deploy/compose.yaml`이 전체 로컬 Teoria 스택과 선택적 검증 작업의 단일 진입점이다.

```text
deploy/
├── compose.yaml       전체 스택 + 선택 profile
├── nginx/             공개 HTTP nginx 이미지와 설정
│   ├── Dockerfile
│   └── nginx.conf
└── README.md
```

Compose project name은 `teoria`다. 별도 `container_name` 없이 다음 이름이 자동 생성된다.

```text
teoria-data-db-1
teoria-prefect-worker-1
teoria_default
teoria_data-db
```

환경 분리는 `-p teoria-dev`, `-p teoria-staging`처럼 project name을 덮어쓴다.

## 기본 스택

루트 `.env`에 Prefect Basic Auth 계정을 설정한다.

```env
TEORIA_PREFECT_USERNAME=admin
TEORIA_PREFECT_PASSWORD=충분히-긴-비밀번호
TEORIA_RUNTIME_API_TOKEN=충분히-긴-임의-토큰
TEORIA_LOCAL_RUNTIME_DB_PASSWORD=충분히-긴-로컬-비밀번호
```

Prefect 계정과 Runtime 비밀값이 없으면 Compose는 시작하지 않는다. 외부 HTTP 요청은 nginx의 단일 포트로만 받고, Admin UI/API, Runtime API와 Prefect Server는 Compose 내부 네트워크에만 노출한다.

```bash
docker compose --env-file .env \
  -f deploy/compose.yaml \
  up --build -d
```

기본 `up`은 다음 순서로 실행한다.

```text
Data DB → migration ┐
                    ├→ prefect-worker
Prefect DB ─┬→ Server → work pool → prefect-deploy ┘
Redis ──────┴→ Background Services
```

공개 주소는 다음과 같다.

| 대상 | 주소 |
|---|---|
| Platform Admin UI | `http://localhost:8081/` |
| Admin API docs | `http://localhost:8081/admin-api/docs` |
| Runtime API docs | `http://localhost:8081/runtime-api/docs` |
| Prefect UI | `http://localhost:8081/prefect/` |
| nginx health | `http://localhost:8081/health` |

공개 포트는 `TEORIA_HTTP_PORT`로 변경할 수 있으며 기본값은 `8081`이다. Data DB에 로컬 SQL client로 접근할 때는 포트를 공개하지 않고 `docker compose exec data-db psql`을 사용한다. MCP는 STDIO이므로 기본 백그라운드 서비스에 포함하지 않는다.

## 선택 profile

| Profile | 서비스 | 실행 방식 |
|---|---|---|
| `tools` | `platform-check`, `pipelines-check` | 일회성 검증 |
| `mcp` | `mcp` | STDIO 실행 |

```bash
docker compose -f deploy/compose.yaml --profile tools run --build --rm platform-check
docker compose -f deploy/compose.yaml --profile tools run --build --rm pipelines-check
docker compose -f deploy/compose.yaml --profile mcp run --rm mcp
```

검증 서비스는 로컬 Registry와 Reference를 read-only로 mount한다.

```bash
docker compose \
  -f deploy/compose.yaml \
  --profile tools run --rm platform-check
```

## 상태와 종료

```bash
docker compose -f deploy/compose.yaml ps
docker compose -f deploy/compose.yaml logs -f prefect-worker
docker compose -f deploy/compose.yaml down
```

`down -v`는 수집 데이터와 Prefect 이력을 삭제하므로 데이터를 폐기할 때만 사용한다. Worker에는 `.env` 전체가 아니라 Compose에 선언한 Pipeline 변수만 전달한다.
