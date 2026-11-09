# OpenMetadata Server 배포와 업그레이드

OpenMetadata는 기술·거버넌스·Semantic Metadata의 권위 저장소다.
Compose의 `semantic` 모듈로 Server, 검색엔진과 schema migration을 실행한다.
수집 일정·재시도는 Prefect가 담당하고 아래의 ingestion Job으로
실행한다. 기본 배포에 Airflow를 추가하지 않는다.

## Server 시작

[Compose 환경 설정](configuration.md)을 준비하고 실행한다.

```bash
bash deploy/compose/deploy.sh deploy --modules semantic
```

| 구성 | 역할 |
|---|---|
| `platform-postgres`의 `openmetadata_db` | OpenMetadata 전용 DB·role |
| `openmetadata-search` | 검색 인덱스 |
| `openmetadata-migrate` | Server 시작 전 schema migration |
| `openmetadata-server` | UI와 REST API, 기본 host port 8585 |

OpenMetadata DB와 인덱스는 Teoria Application DB나 Data DB가 아니다.
기본 버전은 `OPENMETADATA_VERSION=2.0.5`다. 기존 `.env`가 이전 버전을 지정하면
그 값으로 실행하므로 저장소 기본값 변경만으로 기존 catalog가 업그레이드되지 않는다.
버전은 검증한 값을 고정한다.

## 수집과 Platform 연결

1. Server health와 UI `http://localhost:8585/`를 확인한다.
2. bot token을 저장소 밖에서 준비하고 아래 수집 Job을 실행한다.
3. OpenMetadata에서 schema와 자산을 확인한다.
4. Admin API에 `TEORIA_OPENMETADATA_ENABLED=true`, API base URL과 bot token을 설정한다.
5. Admin 데이터 카탈로그에서 동일 자산·설명·참조를 확인한다.

ingestion은 쓰기 bot을 사용하고, Teoria Admin에는 조회·승인된 제안 적용에 필요한
권한을 부여한다. 조회 전용 운영이면 별도 read-only bot을 사용한다. 인증정보를
이미지·YAML·로그에 기록하지 않는다. 세부 참조는 [자산 맥락](../platform/metadata.md)을 따른다.

## 기존 catalog 업그레이드

새 버전은 운영 DB를 복원한 격리 환경에서 먼저 검증한다. DB migration, 전체 검색
재색인, 자산 ID·FQN·설명·소유자·태그·Glossary·Binding 참조 보존, Teoria API 연계와
재수집을 확인한다. 기존 버전 복원도 검증한다. 이전 검증 결과로 현재 환경의 성공을 대신하지 않는다.

검증한 버전을 운영에 반영할 때는 다음 순서를 따른다.

1. Metadata ingestion schedule을 일시 정지하고 진행 중인 Job과 관리 쓰기를 종료한다.
2. 그 시점의 `openmetadata_db`를 백업한다. 이전 검증용 백업으로 대신하지 않는다.
3. Server를 중지하고 선택한 버전의 migration Job을 실행한다.
4. migration 성공 후 Server를 시작하고 전체 검색을 재색인한다.
5. 동일 버전의 ingestion image, Worker allowlist와 Prefect deployment parameter를 반영한다.
6. 자산·Binding 참조·Teoria API·사용자 metadata 보존을 재검증한 뒤 schedule을 재개한다.

Server·migration·ingestion image, ingestion Dockerfile build argument, Prefect 이미지
파라미터·Flow 기본값·Worker allowlist를 함께 확인한다. 검색엔진 호환 버전도 배포
정의와 선택한 OpenMetadata 버전의 요구사항을 대조한다.

## 실패 시 복구

쓰기와 ingestion을 중지하고 변경 전 DB 백업을 복원한 뒤 기존 Server·ingestion·Worker·
Prefect 파라미터를 함께 복구하고 검색을 재색인한다. image tag만 내리는 것으로 DB
migration을 되돌릴 수 없다. 공유 `platform-postgres` 전체 volume이 아니라
`openmetadata_db`만 복구해 Prefect·Teoria Application DB가 함께 되돌아가지 않게 한다.

DB 백업은 인증 설정을 포함할 수 있으므로 접근을 제한하고 Git에 추가하지 않는다.
백업·상세 로그의 보존 경로와 기간은 작업별로 정하고 일회성 credential·컨테이너·network는
검증 종료 후 정리한다. EC2 K3s에서 Prefect가 Kubernetes Job을 실행하는 구성은 [K3s 배포](k3s.md)를 따른다.

## Prefect 수집 Job

수집 일정·retry는 Prefect가 관리한다. 일반 Worker에 ingestion 패키지를 설치하지 않고
공식 ingestion image 기반의 일회성 Docker/Kubernetes Job을 사용한다. 기본 Airflow 구성은 없다.
현재 `DatabaseMetadata`는 `public_procurement`의 테이블·view·설명을 수집하고 `ingestion` schema는 제외한다.
샘플·Profiler·usage·query lineage는 별도 workflow가 필요하다.

- 공통 Flow·일정: `backend/config/metadata_management/prefect_deployments.yaml`
- 환경별 image·pool·Job: `deploy/compose/prefect/metadata_management.yaml`, `deploy/k3s/prefect/metadata_management.yaml`
- 설정 예시: `deploy/compose/openmetadata/ingestion/teoria-postgres.yaml.example`

Server와 같은 버전으로 이미지를 빌드한다. `TEORIA_METADATA_DB_PASSWORD`는 read-only DB 계정,
`OPENMETADATA_INGESTION_BOT_TOKEN`은 쓰기 bot이다. image·Flow 기본값·
`TEORIA_OPENMETADATA_INGESTION_ALLOWED_IMAGE`를 일치시킨다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  -f deploy/compose/compose_semantic.yaml build openmetadata-ingestion-job
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml \
  -f deploy/compose/compose_semantic.yaml run --rm openmetadata-ingestion-job
```

완료 후 `teoria_postgresql`의 자산을 확인하고 재수집 전후 사용자 설명·Glossary·소유자 보존을 검증한다.
Job 실패 시 image allowlist → network → Server → DB 읽기 → bot 권한을 확인한다.
Compose 전용 Worker는 Docker socket 때문에 격리한다. K3s는 전용 namespaced Job을 사용한다.
예약·재시도는 OpenMetadata UI가 아닌 [Prefect](../pipelines/prefect.md)에서 관리한다.
