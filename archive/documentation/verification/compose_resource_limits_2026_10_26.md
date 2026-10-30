# Compose 자원 상한 적용 — 2026-10-26

모든 Compose 서비스와 Docker로 생성하는 OpenMetadata ingestion Job·MCP 세션에 CPU·메모리 상한을 지정했다.
상한은 RAM 예약량이 아니며, 현재 부하에서 검증한 초기 운영 예산이다. 최대 문서·동시 부하의 최소 필요량을 확정한 것은 아니다.
현재 기준은 [Compose 자원 예산](../../../docs/deployment/compose.md#cpu메모리-예산)과 `deploy/compose/compose.yaml`이다.

## 운영 서비스의 적용값

| 서비스 | CPU 상한 | 메모리 상한 MiB |
|---|---:|---:|
| `admin-api` | 1 | 512 |
| `metadata-assessment-worker` | 0.5 | 512 |
| `nginx` | 0.5 | 128 |
| `opa` | 0.5 | 256 |
| `openmetadata-search` | 2 | 6144 |
| `openmetadata-server` | 2 | 2048 |
| `platform-postgres` | 2 | 2048 |
| `policy-control-plane` | 0.5 | 256 |
| `postgres` | 2 | 4096 |
| `prefect-law-worker` | 1 | 1024 |
| `prefect-metadata-worker` | 0.5 | 512 |
| `prefect-redis` | 0.25 | 256 |
| `prefect-server` | 1 | 1024 |
| `prefect-services` | 1 | 1024 |
| `prefect-worker` | 4 | 8192 |
| `runtime-api` | 1 | 512 |
| `runtime-redis` | 0.25 | 256 |

운영 서비스 17개의 메모리 상한 합계는 28.125GiB다. 실제 점유량이나 예약량을 의미하지 않는다.
규격서 Worker는 최대 문서의 peak를 확인하기 전까지 기존 4 CPU·8GiB를 유지했다. 다른 일회성 서비스까지 포함해 Compose 서비스 31개 모두 양수 상한을 갖는다.

## 내부 예산과 임시 Job

- Runtime Redis: 컨테이너 256MiB, 데이터 64MiB, `allkeys-lru`.
- Prefect Redis: 컨테이너 256MiB, 데이터 128MiB, `noeviction`; 기존 AOF와 volume을 보존했다.
- nginx는 CPU quota에 맞춰 worker 수를 조정하도록 autotune을 활성화했다.
- JVM heap은 기존 설정을 유지하고 전체 컨테이너 제한을 추가했다. 검색 엔진의 실측 RSS가 약 4.2GiB여서 초기 상한은 6GiB로 정했다.
- Docker ingestion Job은 기본 1 CPU·2GiB이며, 실제 실행 중 `NanoCpus`·`Memory`를 inspect해 확인했다.
- ingestion CPU·memory 입력은 0·음수·비정상 크기를 거부하여 무제한 Job이 생성되지 않도록 검증했다.
- Codex bridge로 시작하는 MCP 세션은 기본 0.5 CPU·256MiB다. K3s ingestion Job은 기존 requests/limits를 유지한다.

## 운영 적용 과정

실행 중 Prefect·AI 진단 작업이 없음을 확인하고 pool 세 개를 일시정지했다. 변경 전 이미지·자원 설정·배포 상태·복구 Compose override를 owner-only 파일로 보관했다.
복구 자료는 `backups/teoria/resource_limits_20261026T091052Z/`에 있다.

Data DB의 hot file cache 때문에 실행 중 4GiB로 축소하는 시도가 커널에서 거부됐다. 무리하게 축소를 반복하지 않고
Data·Control PostgreSQL을 정상 종료하고 기존 volume을 유지해 재기동했다. 두 DB에 60초 정상 종료 유예를 명시했다.
현재 DB 상한은 각각 4GiB·2GiB이며 healthy·OOM 없음이다. 재시작 후 Docker 메모리 수치 감소에는 cache 회계와 warm-up 영향이 있으므로 애플리케이션 RAM 절감량으로 단정하지 않는다.

API·정책·검색·OpenMetadata 등은 가능한 범위에서 in-place 자원 변경을 적용했다. Redis와 nginx는 command/env를 반영해 교체했고,
metadata Worker는 임시 Job 제한을 포함한 새 이미지로 교체했다. 나머지 기능 이미지·DB migration·Ontology 게시·Runtime bundle은 변경하지 않았다.
준비 상태 확인 뒤 pool pause 상태를 원래대로 복원했다.

## 검증

- ingestion Docker/Kubernetes 동작·정리·잘못된 자원값 검증: 15 passed.
- 전체 Compose 서비스 상한·Redis headroom·인증·volume 분리 검증: 9 passed.
- metadata Worker 이미지 build 성공, 문서·Compose 설정·정적 이름 검사·diff 검사 성공.
- 실제 운영 17개 서비스의 CPU·메모리 값이 Compose와 동일하고 정의된 healthcheck healthy, OOM 종료 없음.
- UI·SPA·Admin/Runtime health·인증 API·법령 검색·Prefect UI/API 정상. MCP STDIO initialize·discovery 성공, 현재 Tool 수 0.
- 기존 배포 26개 ID·설정·pause·schedule 및 Ontology·Binding·진단 상태별 건수 보존.
- 실제 ingestion 컨테이너 한도 1 CPU·2GiB 확인. 법령·metadata 실제 Worker 실행 Completed.

| 작업 | Flow run ID | 시작 UTC | 종료 UTC |
|---|---|---|---|
| `moleg-law-daily` | `42c417d8-84e2-4bb1-9e86-7d018c4b5936` | 2026-10-26 09:18:39.770146+00:00 | 2026-10-26 09:18:53.469847+00:00 |
| `openmetadata-postgres-metadata-sync` | `d62a08d7-1b75-4a8f-87f6-c6c4969bf89c` | 2026-10-26 09:18:46.346589+00:00 | 2026-10-26 09:19:03.611057+00:00 |
| metadata 최종 입력 검증 이미지 | `a77b7602-e89b-4edc-8b07-31803e74ede6` | 2026-10-26 09:23:46.744659+00:00 | 2026-10-26 09:24:04.004171+00:00 |

Docker host는 swap limit 기능을 지원하지 않아 swap 제어 경고가 출력된다. CPU·RAM 상한은 실제 inspect로 검증했다.
큰 실제 규격서 전체 AI 처리·최대 동시 부하·장기간 memory 안정성 평가는 수행하지 않았다. 실제 부하에서 headroom·OOM·throttling을 확인하며 조정한다.
운영 컨테이너 수는 17개이며 개발 환경 포함 18개를 유지한다. 이 작업은 K3s 실제 클러스터 재배포를 포함하지 않는다.

기록: 2026-10-26T09:27:02.507746+00:00
