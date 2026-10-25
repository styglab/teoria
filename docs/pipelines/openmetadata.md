# OpenMetadata 메타데이터 수집

Teoria Data DB의 schema metadata를 OpenMetadata에 동기화하는 작업이다.
Prefect가 일정·재시도·timeout을 관리하고, 공식 ingestion image 기반의 일회성
컨테이너가 수집과 OpenMetadata REST 쓰기를 수행한다. Server 설치는
[OpenMetadata 배포](../deployment/openmetadata.md)를 먼저 완료한다.

## 구성과 수집 범위

| 위치 | 역할 |
|---|---|
| `backend/prefect.metadata.yaml` | 배포 이름·이미지·network·timeout·스케줄 |
| `backend/src/teoria/features/metadata_management/ingestion/openmetadata.py` | Flow와 Job 실행 Task |
| `deploy/compose/openmetadata/Dockerfile` | 공식 ingestion image에 설정을 넣는 이미지 |
| `deploy/compose/openmetadata/ingestion/teoria-postgres.yaml.example` | PostgreSQL connector와 REST sink 설정 |

현재 설정은 `DatabaseMetadata`로 `public_procurement`의 테이블·view·설명을 수집한다.
DataOps 원본·checkpoint·재시도 상태를 담는 `ingestion` schema는 제외한다.
Profiler, 샘플, usage와 query lineage는 이 작업에 포함되지 않으며 별도 workflow가
필요하다. `pg_stat_statements`는 schema metadata 수집의 필수 조건이 아니다.

일반 수집 Worker에는 `openmetadata-ingestion`을 설치하지 않는다. 전용
`prefect-metadata-worker`는 Docker SDK로 컨테이너를 실행하고 종료 후 제거한다.
Job에는 read-only Data DB credential과 OpenMetadata 쓰기 bot token만 전달한다.

## 이미지와 인증정보 준비

Server와 동일한 `OPENMETADATA_VERSION`으로 이미지를 빌드한다. 현재 저장소 기본값은
2.0.5다. 기존 `.env` 값은 기본값보다 우선하므로 배포 전에 실제 값을 확인한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  --profile metadata --profile metadata-ingestion build openmetadata-ingestion-job
```

`TEORIA_METADATA_DB_PASSWORD`와 `OPENMETADATA_INGESTION_BOT_TOKEN`을 배포 환경에
설정한다. Prefect deployment의 `image`, Flow 기본 이미지와 Worker의
`TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE`가 실제 이미지에 정확히 일치해야 한다.
Worker는 allowlist가 다른 이미지를 실행하지 않는다.

## 한 번 실행해 확인하기

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  --profile metadata --profile metadata-ingestion \
  run --rm openmetadata-ingestion-job
```

완료 후 OpenMetadata에서 `teoria_postgresql` 서비스의 `public_procurement` schema와
테이블을 확인한다. 재수집 전후 사용자 설명·Glossary 태그·소유자 보존도 확인한다.
샘플·프로파일이 없는 것은 이 workflow의 실패가 아니다.

## Prefect로 실행하기

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  --profile metadata --profile metadata-orchestration \
  up -d --build prefect-metadata-worker

docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  --profile metadata --profile metadata-orchestration \
  exec prefect-metadata-worker prefect deployment run \
  'OpenMetadata PostgreSQL 메타데이터 동기화/openmetadata-postgres-metadata-sync' --watch
```

Work pool 생성·Deployment 등록 서비스도 같은 metadata profile의 코드와 이미지를
사용한다. 예약 시각·활성 상태는 [배포 목록](deployments.md), 운영 등록 상태와 실패
Task는 Prefect UI에서 확인한다. OpenMetadata UI에서 ingestion을 생성·예약·재시도하지 않는다.

Task는 실패 시 두 번 재시도하며 컨테이너 timeout과 종료 코드를 확인한다. 실패하면
image allowlist, Docker network, Server 상태, read-only DB 접속과 bot 권한 순으로
확인한다. Job 로그에는 인증정보나 민감한 샘플을 남기지 않는다.

Compose의 전용 Worker는 host Docker socket을 사용하므로 일반 수집 Worker와 격리한다.
K3s는 socket mount 없이 전용 Metadata Worker가 namespaced Kubernetes Job을 생성한다.
실행 backend·Secret과 최초 bot 설정은 [K3s 배포](../deployment/k3s.md)를 따른다.
실제 EC2 실행 검증은 서버 설정 후 수행한다.
