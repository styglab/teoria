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
teoria-postgres-1
teoria-prefect-worker-1
teoria_default
teoria_data-db # 기존 데이터를 보존하기 위해 유지하는 물리 volume 이름
```

환경 분리는 `-p teoria-dev`, `-p teoria-staging`처럼 project name을 덮어쓴다.

## 기본 스택

루트 `.env`에 Prefect Basic Auth 계정을 설정한다.

```env
TEORIA_PREFECT_USERNAME=admin
TEORIA_PREFECT_PASSWORD=충분히-긴-비밀번호
TEORIA_RUNTIME_API_TOKEN=충분히-긴-임의-토큰
TEORIA_LOCAL_RUNTIME_DB_PASSWORD=충분히-긴-로컬-비밀번호
TEORIA_OBJECT_STORAGE_ENDPOINT=https://minio.example.com
TEORIA_OBJECT_STORAGE_ACCESS_KEY=외부-MinIO-access-key
TEORIA_OBJECT_STORAGE_SECRET_KEY=외부-MinIO-secret-key
TEORIA_OBJECT_STORAGE_BUCKET=teoria
# 비워 두면 Compose 내부 PostgreSQL을 사용한다.
TEORIA_PIPELINE_DATA_DATABASE_URL=
TEORIA_RUNTIME_DATA_DATABASE_URL=
```

Prefect 계정과 Runtime 비밀값이 없으면 Compose는 시작하지 않는다. 외부 HTTP 요청은 nginx의 단일 포트로만 받고, Admin UI/API, Runtime API와 Prefect Server는 Compose 내부 네트워크에만 노출한다.
Pipeline Object Storage도 Compose에서 실행하지 않으며 사전에 준비된 외부 S3 호환 MinIO와 bucket을 사용한다.

Data DB는 기본적으로 Compose의 `postgres`를 사용한다. 외부 PostgreSQL을 사용할 때는 `.env`에
writer용 `TEORIA_PIPELINE_DATA_DATABASE_URL`과 read-only Runtime용
`TEORIA_RUNTIME_DATA_DATABASE_URL`을 각각 설정한다. 두 URL은 동일한 database를 가리키되 DB role은
분리해야 한다. 외부 DB의 role·database 생성, TLS, 방화벽과 백업은 외부 DB 운영 영역이며 Compose의
`postgres-init`이 외부 DB 계정을 생성하지 않는다.

```env
TEORIA_PIPELINE_DATA_DATABASE_URL=postgresql://teoria_pipeline:비밀번호@db.example.com:5432/teoria_data?sslmode=require
TEORIA_RUNTIME_DATA_DATABASE_URL=postgresql://teoria_runtime:비밀번호@db.example.com:5432/teoria_data?sslmode=require
```

기존 Compose MinIO에서 전환할 때는 새 endpoint와 bucket을 설정하기 전에 기존 `teoria` bucket을
외부 MinIO로 복사하고 객체 수와 checksum을 검증한다. DB의 `object_key`는 bucket 내부 상대 경로라
동일한 bucket 구조로 복사하면 DB 변경은 필요 없다. 검증이 끝나기 전에는 기존 MinIO container와
`teoria_bid-document-storage` volume을 삭제하지 않는다. 외부 저장소 전환 후 `docker compose up`
시 남은 로컬 MinIO container는 orphan으로 표시될 수 있으며, 데이터 검증을 마친 뒤에만 제거한다.

```bash
docker compose --env-file .env \
  -f deploy/compose.yaml \
  up --build -d
```

기본 `up`은 다음 순서로 실행한다.

```text
PostgreSQL → migration ┐
                    ├→ prefect-worker
Prefect DB ─┬→ Server → work pool → prefect-deploy ┘
Redis ──────┴→ Background Services
```

`prefect-ai-worker`는 API key 대신 ChatGPT-managed Codex 로그인을 사용한다. 최초 배포 후
다음 명령으로 전용 `codex-auth` volume에 로그인 세션을 만든다.

```bash
docker compose --env-file .env -f deploy/compose.yaml exec \
  prefect-ai-worker codex login --device-auth
```

이 volume에는 비밀번호에 준하는 갱신 토큰이 저장되므로 Git, 이미지 또는 일반 백업에 포함하지 않는다.

공개 주소는 다음과 같다.

| 대상 | 주소 |
|---|---|
| Platform Admin UI | `http://localhost:8081/` |
| Admin API docs | `http://localhost:8081/admin-api/docs` |
| Runtime API docs | `http://localhost:8081/runtime-api/docs` |
| Prefect UI | `http://localhost:8081/prefect/` |
| nginx health | `http://localhost:8081/health` |

공개 포트는 `TEORIA_HTTP_PORT`로 변경할 수 있으며 기본값은 `8081`이다. Teoria PostgreSQL에 로컬 SQL client로 접근할 때는 포트를 공개하지 않고 `docker compose exec postgres psql`을 사용한다. MCP는 STDIO이므로 기본 백그라운드 서비스에 포함하지 않는다.

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
