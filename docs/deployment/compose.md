# Compose 배포와 운영

`deploy/compose/compose.yaml`은 지원되는 로컬 개발·통합 배포의 단일 진입점이다.
환경변수는 [환경 설정](configuration.md), 수집 실행은 [Prefect 운영](../pipelines/prefect.md),
선택적 metadata 서비스는 [OpenMetadata 배포](openmetadata.md)를 따른다.
EC2 운영 배포는 [K3s](k3s.md)를 따른다.

## Docker Compose

`deploy/compose/compose.yaml`이 전체 로컬 Teoria 스택과 선택적 검증 작업의 단일 진입점이다.

```text
deploy/
├── compose/           로컬 전체 스택 + 선택 profile
│   ├── compose.yaml
│   ├── .env.example
│   └── nginx/         공개 HTTP nginx 이미지와 설정
└── k3s/              EC2 단일 노드와 GitHub 자동 배포
```

Compose project name은 `teoria`다. 별도 `container_name` 없이 다음 이름이 자동 생성된다.

```text
teoria-postgres-1
teoria-prefect-worker-1
teoria_default
teoria_data-db # 기존 데이터를 보존하기 위해 유지하는 물리 volume 이름
```

환경 분리는 `-p teoria-dev`, `-p teoria-staging`처럼 project name을 덮어쓴다.
DB·Runtime artifact·OPA를 포함한 모든 관리 볼륨은 project name에 따라 분리된다.
기본 `teoria`의 기존 `teoria_data-db`, `teoria_platform-db` 등은 그대로 사용한다.
기존 배포의 project name을 바꾸면 새 빈 볼륨을 사용하므로 데이터 이관 없이 이름을
변경하지 않는다. 같은 호스트에서 환경을 함께 실행할 때 공개 HTTP 포트도 다르게 지정한다.

## 기본 스택

`deploy/compose/.env`는 Compose 입력값의 기준이다. 컨테이너 내부 경로·주소와
운영 정책은 `compose.yaml`이 정의한다. 호스트에서 직접 실행할 때의 주소·인증 설정은
[환경 설정](configuration.md#호스트에서-직접-실행)을 따른다.

```env
TEORIA_PREFECT_USERNAME=admin
TEORIA_PREFECT_PASSWORD=충분히-긴-비밀번호
TEORIA_RUNTIME_API_TOKEN=충분히-긴-임의-토큰
TEORIA_ADMIN_API_TOKEN=Runtime과-다른-충분히-긴-임의-토큰
TEORIA_OPA_CONTROL_PLANE_TOKEN=Runtime과 다른-충분히-긴-임의-토큰
TEORIA_OPA_BUNDLE_REVISION=배포-commit-또는-policy-release-id
TEORIA_LOCAL_RUNTIME_DB_PASSWORD=충분히-긴-로컬-비밀번호
# 비워 두면 Compose 내부 PostgreSQL을 사용한다.
TEORIA_PIPELINE_DATA_DATABASE_URL=
TEORIA_RUNTIME_DATA_DATABASE_URL=
```

Prefect 계정, Admin·Runtime·OPA Control Plane 비밀값이 없으면 Compose는 시작하지 않는다.
Admin API는 Compose에서 항상 Bearer 인증을 사용한다. 외부 HTTP 요청은 nginx의 단일 포트로만 받고, Admin UI/API, Runtime API, OPA와 Policy Control Plane은 Compose 내부 네트워크에만 노출한다.

Data DB는 기본적으로 Compose의 `postgres`를 사용한다. 외부 PostgreSQL을 사용할 때는 `.env`에
writer용 `TEORIA_PIPELINE_DATA_DATABASE_URL`과 read-only Runtime용
`TEORIA_RUNTIME_DATA_DATABASE_URL`을 각각 설정한다. 두 URL은 동일한 database를 가리키되 DB role은
분리해야 한다. 외부 DB의 role·database 생성, TLS와 방화벽은 외부 DB 운영 영역이며 Compose의
`postgres-init`이 외부 DB 계정을 생성하지 않는다. 아래 백업 스크립트는 실제 설정된
Data DB를 논리 백업하며, 외부 DB 서비스의 백업·복구 정책을 대신하지 않는다.

Data DB 컨테이너는 병렬 쿼리의 동적 공유 메모리를 위해 `shm_size: 1gb`를 사용한다.
Docker 기본값인 64MB가 부족하면 디스크 여유와 무관하게 `could not resize shared memory
segment`와 `No space left on device` 오류가 발생할 수 있다. 이 설정 변경은 기존 Data DB
volume을 유지한 채 `postgres` 컨테이너를 재생성해야 적용된다.

```env
TEORIA_PIPELINE_DATA_DATABASE_URL=postgresql://teoria_pipeline:비밀번호@db.example.com:5432/teoria_data?sslmode=require
TEORIA_RUNTIME_DATA_DATABASE_URL=postgresql://teoria_runtime:비밀번호@db.example.com:5432/teoria_data?sslmode=require
```

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  up --build -d
```

기본 `up`은 다음 순서로 실행한다.

```text
PostgreSQL → migration ┐
                    ├→ prefect-worker
Prefect DB ─┬→ Server → work pool → prefect-deploy ┘
Redis ──────┴→ Background Services
```

OPA는 `opa-bundle-build`가 Rego를 검사하고 RSA 서명 Bundle을 생성한 뒤 시작한다.
`policy-control-plane`은 인증된 Bundle download, gzip decision log와 status 수집만
제공한다. OPA healthcheck는 `/health?bundles=true&plugins=true`를 사용하므로 최초
Bundle 활성화나 management plugin 초기화가 실패하면 Runtime과 Admin API가 시작되지
않는다. signing private key, Bundle과 OPA last-known-good state는 각각 이름 있는
volume에 보존된다.

수집 Worker는 기본 CPU 4·메모리 8GiB 안에서 Flow를 최대 2개 실행한다.
`TEORIA_PIPELINE_WORKER_CPUS`, `TEORIA_PIPELINE_WORKER_MEMORY`로 컨테이너 전체
상한을 바꾸고, `TEORIA_PIPELINE_CONCURRENCY`로 동시 실행 수를 조정한다.
Process 실행이므로 Flow별 CPU·메모리 격리를 제공하지 않는다. 최신 수집 우선·Backfill 1개
정책은 K3s와 공유하며 [Prefect 운영](../pipelines/prefect.md)을 따른다.
등록 정책 변경 시 `prefect-deploy`를 다시 실행하고 Worker 환경변수 변경 시 Worker를 재생성한다.

실행 중인 수집을 보존하는 Worker 재배포는 이미지 빌드 → 수집·Metadata work pool 일시정지 →
기존 실행 완료 대기 → 등록 서비스 성공 확인 → Worker 재생성 → 자원 상한·동작 확인 →
원래 실행 상태 복원 순서로 진행한다. pool 일시정지는 새 실행 제출만 막으며 기존 실행을
중단하지 않는다. 처음부터 일시정지돼 있던 pool은 재배포 후에도 일시정지를 유지한다.
`--no-deps`로 대상 서비스만 갱신하면 이 변경과 관계없는 DB·API 컨테이너를 유지할 수 있다.

`prefect-redis`는 Prefect 메시징 전용이고 `runtime-redis`는 Runtime Capability 결과 캐시
전용이다. Runtime API를 여러 replica로 실행해도 Registry 버전과 Capability 입력이 같은 결과를
공유한다. Redis 조회·저장 장애는 Capability 실행을 중단시키지 않고 캐시 미사용으로 전환된다.

첨부파일·문서 요건 기능은 보류되어 AI Worker와 Object Storage 설정을 기본 배포에서 제거했다.
과거 보관 객체와 인증 volume은 자동 삭제하지 않는다.

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
docker compose -f deploy/compose/compose.yaml --profile tools run --build --rm platform-check
docker compose -f deploy/compose/compose.yaml --profile tools run --build --rm pipelines-check
docker compose -f deploy/compose/compose.yaml --profile mcp run --rm mcp
```

검증 서비스는 로컬 Registry와 Reference를 read-only로 mount한다.

```bash
docker compose \
  -f deploy/compose/compose.yaml \
  --profile tools run --rm platform-check
```

## 상태와 종료

```bash
docker compose -f deploy/compose/compose.yaml ps
docker compose -f deploy/compose/compose.yaml logs -f prefect-worker
docker compose -f deploy/compose/compose.yaml down
```

`down -v`는 수집 데이터와 Prefect 이력을 삭제하므로 데이터를 폐기할 때만 사용한다. Worker에는 `.env` 전체가 아니라 Compose에 선언한 Pipeline 변수만 전달한다.

## PostgreSQL 백업과 복원 확인

실행 중인 Compose 스택에서 다음 명령을 사용한다. Bash, Python 3, Docker Compose가 필요하다.

```bash
bash deploy/compose/postgres/backup.sh
```

기본 환경 파일은 `deploy/compose/.env`이며 `TEORIA_ENV_FILE`로 변경한다.
Compose와 같은 환경변수 우선순위를 사용하고, `COMPOSE_PROJECT_NAME`으로 대상을 선택한다.
백업 기본 경로는 `backups/<project>/<UTC timestamp>/`다.

```bash
TEORIA_ENV_FILE=/path/to/staging.env \
COMPOSE_PROJECT_NAME=teoria-staging \
TEORIA_BACKUP_ROOT=/secure/backups \
  bash deploy/compose/postgres/backup.sh
```

- `teoria_data.dump`: `postgres-migrate`에 설정된 실제 Data DB URL을 사용한다. 외부 DB를 설정하면 내부 DB 대신 외부 DB를 백업한다.
- `teoria_app.dump`, `prefect.dump`, `openmetadata_db.dump`: 해당 project의 `platform-postgres`에서 백업한다.
- `SHA256SUMS`, PostgreSQL 버전과 project 정보: 백업 파일 검증과 복원 환경 선택에 사용한다. 연결 URL·암호는 기록하지 않는다.

Data DB 클라이언트는 해당 project의 실행 중인 `postgres` 컨테이너를 사용한다.
외부 서버로 접속할 네트워크·권한이 필요하고, 서버 버전에 대응하는 `pg_dump`여야 한다.
외부 DB용 파일 기반 TLS 인증을 쓴다면 클라이언트 컨테이너에서도 해당 파일에 접근할 수 있어야 한다.

진행 중이거나 실패한 백업은 `.incomplete` 디렉터리에 남는다. 모든 덤프의 archive 목록과
checksum 검사가 성공한 후에만 완료 이름으로 변경한다. 디렉터리·파일은 기본적으로
현재 사용자만 접근하며, 실패 상세는 해당 백업의 `*.stderr.log`에서 확인한다.

`pg_restore --list`와 checksum 성공은 복원 성공을 보장하지 않는다. 운영과 분리한
PostgreSQL에서 덤프를 복원하고 중요 테이블을 조회해 확인한다. DB 초기화·role 생성은
복원 전에 수행하며, 별도 검증 DB에서는 `pg_restore --no-owner --no-acl`로 복원할 수 있다.
Runtime artifact·OPA 키·객체 저장소·Codex 인증정보는 이 DB 백업에 포함하지 않는다.
