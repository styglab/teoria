# Compose 배포와 운영

`deploy/compose/compose.yaml`이 현재 지원하는 로컬 배포 진입점이다.
규격서 처리 Worker와 Ontology·Binding·Runtime·OpenMetadata 기반을 조립한다.
이전 조달·기업 분석과 조달 API 수집은 배포 대상이 아니다.
법령 수집·조회는 별도 pool·Worker로 복구했다.
환경변수는 [설정 안내](configuration.md), 실행·스케줄은 [Prefect 운영](../pipelines/prefect.md)을 따른다.
EC2 K3s는 [별도 배포](k3s.md)이며 Compose 성공을 K3s 운영 성공으로 기록하지 않는다.

## Docker Compose

기본 project name은 `teoria`다. 기존 배포에서는 project name과 환경 파일을 그대로 사용한다.
project name 변경은 새 볼륨을 선택하므로 데이터 이관 없이 바꾸지 않는다.
현재 Metadata와 선택적 진단 Worker를 포함한 구성은 다음 명령으로 확인한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile metadata --profile metadata-orchestration --profile intelligence config --quiet
```

환경 파일은 Compose의 보간 입력만 관리한다. `.env.example`은 지원 입력을 기능별로 안내하고,
실제 `.env`는 계정·비밀번호, 검증한 이미지 태그와 필요한 override만 유지한다.
MinIO 관리자 변수의 이전 이름 이관은 [환경 파일 관리](configuration.md#compose-환경-파일-관리)를 따른다.

Prefect의 process Pool·Queue는 `deploy/compose/prefect/`가 소유한다.
Flow·기본 파라미터·스케줄은 `backend/config/<feature>/prefect_deployments.yaml`에서 읽어 합성한다.
등록 명령의 `--backend process`는 Compose 설정, `--backend kubernetes`는 K3s 설정을 선택한다.
환경 파일을 통째로 복제하거나 기본 스케줄을 양쪽에서 관리하지 않는다.

## 기본 스택

| 구성 | 역할 |
|---|---|
| nginx(UI 포함)·Admin/Runtime API | 단일 공개 진입점과 의미 모델·메타데이터 관리 |
| Runtime API·Redis | checksum 검증된 bundle의 Capability discovery·실행과 캐시 |
| OPA·Policy Control Plane | 서명 정책과 결정 로그 |
| Prefect Server·Services·Redis | workflow 실행·예약·재시도 |
| 법령 Worker | `teoria-legal-information` pool, 법제처 credential만 사용 |
| MinIO·스토리지 초기화 | 규격서 원본·산출물의 기본 객체 저장소와 역할별 계정·권한 |
| 규격서 Worker | `teoria-specification` pool의 명시 입력 작업 |
| PostgreSQL 2개 | Data DB와 Application·Prefect·OpenMetadata DB 분리 |
| OpenMetadata·검색 엔진·Metadata Worker | 카탈로그와 격리 ingestion Job |

MCP는 클라이언트가 연결할 때 `docker run --rm -i` 또는 `docker compose run --rm mcp`로 실행한다.
일반 서비스 기동에 상시 `mcp` 컨테이너를 포함하지 않는다.

외부 HTTP는 nginx 기본 포트 `8081`로만 받는다. Admin·Runtime·Prefect·OPA는 내부 네트워크를 사용한다.
Admin·Runtime·OPA는 별도 token, Prefect는 계정을 사용한다. 토큰 없는 접근과 실제 인증 요청을 모두 검증한다.

| 대상 | 기본 주소 |
|---|---|
| Admin UI | `http://localhost:8081/` |
| Admin API docs | `http://localhost:8081/admin-api/docs` |
| Runtime API docs | `http://localhost:8081/runtime-api/docs` |
| Prefect | `http://localhost:8081/prefect/` |
| MinIO 객체 브라우저 | `http://localhost:8081/minio/` |
| nginx health | `http://localhost:8081/health` |

MinIO 객체 브라우저는 MinIO 계정으로 로그인한다. 관리 계정은 `.env`의 `TEORIA_MINIO_ROOT_USER`·`TEORIA_MINIO_ROOT_PASSWORD`를 사용한다.
외부 도메인·HTTPS를 쓰면 `TEORIA_MINIO_BROWSER_REDIRECT_URL`을 해당 공개 주소의 `/minio/`로 설정한다.
S3 API 9000과 브라우저 9001을 별도 호스트 포트로 공개하지 않고 nginx의 `/minio/`만 사용한다.

OpenMetadata의 별도 접속 경로는 [배포 안내](openmetadata.md)를 따른다.
MCP는 Runtime HTTP API를 사용하는 선택적 STDIO 프로세스다.

## 규격서 입력·산출물·모델 인증

| volume | 컨테이너 경로 | 용도 |
|---|---|---|
| MinIO `teoria-artifacts` bucket | `s3://teoria-artifacts` | 원본·추출·판정·사전 스냅샷·보고서·중간 진단 |
| `model-objects` | MinIO `/data` | 객체 저장소의 영구 디스크. 기존 모델 bucket과 별도로 규격서 bucket 관리 |
| `specification-model-auth` | `/home/teoria/.codex` | 모델 CLI 인증, 이미지와 분리 |

규격서 Admin API와 Worker에는 로컬 입력·산출물 volume을 마운트하지 않는다.
MinIO는 기본 스택이며 별도 object-storage profile은 필요 없다.
`minio-init` 이미지는 `deploy/compose/minio/`에서 빌드하고, 기본 bucket과 전용 계정을 준비한다.
`.env.example`의 Worker/API 저장소 secret을 별도로 설정한다. Worker는 산출물 쓰기, API는 입력 쓰기와 산출물 읽기를 허용하며 삭제 권한은 부여하지 않는다.
manifest에는 `s3://` URI를 입력한다. 자세한 설정은 [파이프라인 설정](../procurement_specification_processing/pipeline.md)을 따른다.
모델 CLI는 이미지에 고정하지만 계정 인증은 별도 volume 또는 Secret으로 제공한다.
인증 상태 검사는 credential 본문을 출력하지 않는다. 모델 인증이 없는 기동 성공을 AI 추출 성공으로 간주하지 않는다.

## 이미지 빌드·migration·등록

기존 DB·네트워크·볼륨을 유지하면서 변경된 서비스를 지정한다.
Metadata Worker를 지정할 때는 의존 서비스의 `metadata` profile도 활성화한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile metadata --profile metadata-orchestration build minio-init runtime-api admin-api nginx prefect-worker prefect-metadata-worker
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml run --rm --no-deps postgres-migrate
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml run --rm --no-deps prefect-deploy
```

migration은 새 순번만 적용한다. 규격서 상태·참조 테이블은 `090`, schema 권한은 `091`, 상위 표준관리 workflow는 `092`에 있다.
Application DB에는 `017` 물품 프로파일·`018` 관계 설명·`019` 의미 판정 operation을 적용했다.
기존 수집 pool과 배포는 일시정지를 유지하고 과거 실행·checkpoint를 지우지 않는다.
규격서 배포는 cron 없이 manifest를 받는다. [배포 목록](../pipelines/deployments.md)을 확인한다.

## 규격서 Worker 이미지 선택

`TEORIA_SPECIFICATION_WORKER_IMAGE`는 prefect-worker 이미지에만 적용한다. 기본값은
`teoria-pipelines:latest`다. 특정 릴리스를 유지하려면 로컬 `deploy/compose/.env`에서 지정한다.
각 릴리스는 별도 태그를 사용하고 변경한 Worker만 재생성한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml up -d --no-deps --no-build prefect-worker
```

기존 법령·메타데이터·모델 Worker의 이미지를 함께 변경하지 않는다. 실행 중인 규격서 작업이 없을 때 교체하고,
이전 이미지·볼륨·환경을 보존한다. [구성 관계 수정 배포](../../archive/documentation/verification/goods_relation_deployment_2026_10_28.md)는
실제 원본 처리를 확인했다. 후속 [사전 의미 자동 승인 배포](../../archive/documentation/verification/goods_dictionary_deployment_2026_10_28.md)는
새 Worker heartbeat와 기존 원문 추출 부분집합의 실제 Codex·Admin API 승인·결과 저장을 확인했다.

Admin HTTP만 별도 반영할 때는 `TEORIA_ADMIN_API_IMAGE`에 릴리스 태그를 지정하고
`admin-api`만 재생성한다. 다른 authoring 역할 이미지에는 이 변수를 적용하지 않는다.

## 데이터 자산 진단의 Codex 실행

데이터 자산 상세의 진단 요청은 `metadata-assessment-worker`에서 Codex로 실행한다.
HTTP 모델 URL·토큰·출력 토큰 설정은 제거했다. 모델 고정값과 개별 호출 제한시간은
`TEORIA_ASSESSMENT_CODEX_MODEL`·`TEORIA_ASSESSMENT_CODEX_TIMEOUT_SECONDS`를 사용한다.
Codex 로그인은 `metadata-model-auth` 전용 볼륨에 준비한다. 규격서 Worker의 실행·인증 볼륨은 변경하지 않는다.
`TEORIA_ASSESSMENT_WORKER_IMAGE`로 이 Worker만 별도 배포할 수 있다.
[진단 실행과 인증 준비](../platform/metadata/asset_assessment.md#설정과-실행)를 참고한다.

## 법령 기능 배포

`prefect-law-worker`는 parser·모델 CLI를 설치하지 않는 `law-worker` 이미지다.
`TEORIA_CONNECTOR_MOLEG_LAW_API_KEY`는 이 Worker에만 주입한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml build prefect-law-worker admin-api
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml run --rm --no-deps prefect-law-deploy
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile intelligence up -d --no-deps prefect-law-worker admin-api metadata-assessment-worker
```

법령 전용 pool·예약만 재개한다. Runtime bundle과 업무 Capability는 변경하지 않는다.
[법령 복구 검증](../../archive/documentation/verification/law_recovery_2026_10_25.md)을 따른다.

## Runtime bundle 전환

코드 이미지 교체와 bundle 활성화는 별도 단계다. 이전 조달 bundle을 그대로 적재하면
제거한 query Capability가 계속 노출될 수 있다. 새 Registry로 불변 bundle을 만들고
checksum 검증 후 active pointer를 원자적으로 바꾼다. [Runtime 절차](../platform/runtime.md)를 따른다.

artifact volume은 운영 API에서 읽기 전용이다. 발행 작업만 별도 일회성 컨테이너에서 쓰기 mount를 사용한다.
기존 root 소유 volume에는 그 작업의 쓰기 권한만 부여하고 운영 API의 권한을 넓히지 않는다.
이전 version과 `active.json`의 version·checksum을 보존한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile metadata --profile metadata-orchestration --profile intelligence up -d --no-deps runtime-api admin-api nginx prefect-worker prefect-metadata-worker metadata-assessment-worker
```

pool을 일시정지하고 기존 작업 종료를 확인한 뒤 Worker를 교체한다.
healthcheck, Prefect heartbeat·등록 상태, 공개 URL의 인증과 새 `/v1/version`을 확인한다.
nginx의 내부 DNS 갱신까지 기다린다. 새 bundle은 discovery·실제 요청으로 검증한다.
진단 Worker는 해당 모델 gateway를 설정한 경우에만 실행한다.

## 상태와 종료

```bash
docker compose -f deploy/compose/compose.yaml ps
docker compose -f deploy/compose/compose.yaml logs --tail 100 runtime-api admin-api prefect-worker
```

`down -v`는 기존 수집 데이터·게시 artifact·인증 volume까지 삭제할 수 있으므로 이번 전환에 사용하지 않는다.
되돌릴 때는 이전 이미지와 검증된 이전 artifact를 함께 선택한다. DB schema를 과거 SQL로 덮어쓰지 않는다.

## PostgreSQL 백업과 복원 확인

```bash
bash deploy/compose/postgres/backup.sh
```

기본 환경 파일은 `deploy/compose/.env`, 별도 파일은 `TEORIA_ENV_FILE`로 지정한다.
Data DB가 외부 URL이면 실제 설정된 DB를 백업한다.
`teoria_app`, `prefect`, `openmetadata_db`는 Control/Application PostgreSQL에서 백업한다.
완료 파일과 checksum을 확인하고 운영과 분리한 PostgreSQL에 실제 복원해 검증한다.
WAL·Runtime artifact·모델 인증·파일/S3 산출물은 DB dump와 별도다.


## 화면과 진입점

Compose는 `frontend/Dockerfile`의 `gateway` target으로 React 정적 파일과 API·Prefect
reverse proxy를 하나의 `nginx` 서비스에 포함한다. 별도 `admin-ui` 서비스는 없다.
프런트엔드를 바꾸면 `docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml build nginx`로
빌드하고 `up -d --no-deps nginx`로 반영한다. 이전 배포에서 남은 `teoria-admin-ui-1`은
새 nginx의 화면·API 확인이 끝난 뒤 개별 제거한다. 전체 프로젝트의 orphan 일괄 제거는 하지 않는다.


## CPU·메모리 예산

`compose.yaml`의 모든 서비스에 `cpus`와 `mem_limit`을 명시한다. 상시 서비스뿐 아니라
migration·검증 도구·일회성 Job도 포함한다. 메모리 상한은 그만큼의 RAM을 미리 점유하는 설정이 아니다.

현재 부하를 기준으로 API·제어 서비스에는 128–512MiB, Prefect 서버와 background 서비스에는
각 1GiB를 설정했다. Data DB 4GiB·Control DB 2GiB·OpenMetadata 2GiB·검색 엔진 6GiB이며,
규격서 Worker는 큰 문서의 최대 사용량 검증 전까지 기존 4 CPU·8GiB를 유지한다.
구체적인 현재 값은 Compose 파일이 기준이다.

Redis의 내부 데이터 한도는 컨테이너 상한보다 낮게 둔다. Prefect Redis는 `noeviction`으로
작업·이벤트 키를 임의로 삭제하지 않고, Runtime 캐시는 `allkeys-lru`를 사용한다.
DB `shm_size`, JVM heap, Redis `maxmemory`는 컨테이너 전체 메모리 제한과 별도다.

Prefect metadata Worker가 생성하는 Docker ingestion Job도 기본 1 CPU·2GiB로 제한한다.
`TEORIA_OPENMETADATA_INGESTION_CPUS`·`TEORIA_OPENMETADATA_INGESTION_MEMORY`로 조정하며,
동일 값이 수동 `openmetadata-ingestion-job` 서비스에도 적용된다. K3s ingestion Job은
기존 별도 requests·limits를 유지한다. Codex MCP 세션은 기본 0.5 CPU·256MiB로 실행한다.

운영 적용은 실행 중 작업을 확인하고 pool을 잠시 멈춘 상태에서 수행한다. DB의 기존 파일 캐시로
인해 live 한도 축소가 거부되면 정상 종료·같은 볼륨으로 재기동한 후 실제 적용값을 확인한다.
측정과 실제 작업 검증 없이 한도를 유휴 사용량까지 낮추지 않는다.
