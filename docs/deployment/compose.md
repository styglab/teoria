# Compose 배포와 운영

`deploy/compose/compose.yaml`이 현재 지원하는 로컬 배포 진입점이다.
규격서 처리 Worker와 Ontology·Binding·Runtime·OpenMetadata 기반을 조립한다.
이전 조달·기업 분석과 조달 API 수집은 배포 대상이 아니다.
법령 수집·조회는 별도 pool·Worker로 복구했다.
환경변수는 [설정 안내](configuration.md), 규격서 실행은 [Prefect](../pipelines/prefect.md),
실제 전환 결과는 [배포 검증 기록](../verification/goods_focus_deployment_2026_10_25.md)을 따른다.
EC2 K3s는 [별도 배포](k3s.md)이며 Compose 성공을 K3s 운영 성공으로 기록하지 않는다.

## Docker Compose

기본 project name은 `teoria`다. 기존 배포에서는 project name과 환경 파일을 그대로 사용한다.
project name 변경은 새 볼륨을 선택하므로 데이터 이관 없이 바꾸지 않는다.
현재 Metadata와 선택적 진단 Worker를 포함한 구성은 다음 명령으로 확인한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile metadata --profile metadata-orchestration --profile intelligence config --quiet
```

## 기본 스택

| 구성 | 역할 |
|---|---|
| nginx·Admin UI/API | 단일 공개 진입점과 의미 모델·메타데이터 관리 |
| Runtime API·Redis | checksum 검증된 bundle의 Capability discovery·실행과 캐시 |
| OPA·Policy Control Plane | 서명 정책과 결정 로그 |
| Prefect Server·Services·Redis | workflow 실행·예약·재시도 |
| 법령 Worker | `teoria-legal-information` pool, 법제처 credential만 사용 |
| 규격서 Worker | `teoria-specification` pool의 명시 입력 작업 |
| PostgreSQL 2개 | Data DB와 Application·Prefect·OpenMetadata DB 분리 |
| OpenMetadata·검색 엔진·Metadata Worker | 카탈로그와 격리 ingestion Job |

외부 HTTP는 nginx 기본 포트 `8081`로만 받는다. Admin·Runtime·Prefect·OPA는 내부 네트워크를 사용한다.
Admin·Runtime·OPA는 별도 token, Prefect는 계정을 사용한다. 토큰 없는 접근과 실제 인증 요청을 모두 검증한다.

| 대상 | 기본 주소 |
|---|---|
| Admin UI | `http://localhost:8081/` |
| Admin API docs | `http://localhost:8081/admin-api/docs` |
| Runtime API docs | `http://localhost:8081/runtime-api/docs` |
| Prefect | `http://localhost:8081/prefect/` |
| nginx health | `http://localhost:8081/health` |

OpenMetadata의 별도 접속 경로는 [배포 안내](openmetadata.md)를 따른다.
MCP는 Runtime HTTP API를 사용하는 선택적 STDIO 프로세스다.

## 규격서 입력·산출물·모델 인증

| volume | 컨테이너 경로 | 용도 |
|---|---|---|
| `specification-inputs` | `/app/specification_inputs` | 명시 입력 원본, Worker에서 읽기 전용 |
| `specification-artifacts` | `/app/specification_artifacts` | 원문 보관·추출 JSON·표준 draft·Markdown |
| `specification-model-auth` | `/home/teoria/.codex` | 모델 CLI 인증, 이미지와 분리 |

manifest에는 컨테이너 기준 URI를 입력한다. S3를 사용할 때는 [파이프라인 설정](../procurement_specification_processing/pipeline.md)을 따른다.
모델 CLI는 이미지에 고정하지만 계정 인증은 별도 volume 또는 Secret으로 제공한다.
인증 상태 검사는 credential 본문을 출력하지 않는다. 모델 인증이 없는 기동 성공을 AI 추출 성공으로 간주하지 않는다.

## 이미지 빌드·migration·등록

기존 DB·네트워크·볼륨을 유지하면서 변경된 서비스를 지정한다.
Metadata Worker를 지정할 때는 의존 서비스의 `metadata` profile도 활성화한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile metadata --profile metadata-orchestration build runtime-api admin-api admin-ui prefect-worker prefect-metadata-worker
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml run --rm --no-deps postgres-migrate
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml run --rm --no-deps prefect-deploy
```

migration은 새 순번만 적용한다. 규격서 상태·참조 테이블은 `090`, schema 권한은 `091`에 있다.
기존 수집 pool과 배포는 일시정지를 유지하고 과거 실행·checkpoint를 지우지 않는다.
규격서 배포는 cron 없이 manifest를 받는다. [배포 목록](../pipelines/deployments.md)을 확인한다.

## 법령 기능 배포

`prefect-law-worker`는 parser·모델 CLI를 설치하지 않는 `law-worker` 이미지다.
`TEORIA_CONNECTOR_MOLEG_LAW_API_KEY`는 이 Worker에만 주입한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml build prefect-law-worker admin-api
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml run --rm --no-deps prefect-law-deploy
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile intelligence up -d --no-deps prefect-law-worker admin-api metadata-assessment-worker
```

법령 전용 pool·예약만 재개한다. Runtime bundle과 업무 Capability는 변경하지 않는다.
[법령 복구 검증](../verification/law_recovery_2026_10_25.md)을 따른다.

## Runtime bundle 전환

코드 이미지 교체와 bundle 활성화는 별도 단계다. 이전 조달 bundle을 그대로 적재하면
제거한 query Capability가 계속 노출될 수 있다. 새 Registry로 불변 bundle을 만들고
checksum 검증 후 active pointer를 원자적으로 바꾼다. [Runtime 절차](../platform/runtime.md)를 따른다.

artifact volume은 운영 API에서 읽기 전용이다. 발행 작업만 별도 일회성 컨테이너에서 쓰기 mount를 사용한다.
기존 root 소유 volume에는 그 작업의 쓰기 권한만 부여하고 운영 API의 권한을 넓히지 않는다.
이전 version과 `active.json`의 version·checksum을 보존한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml --profile metadata --profile metadata-orchestration --profile intelligence up -d --no-deps runtime-api admin-api admin-ui prefect-worker prefect-metadata-worker metadata-assessment-worker
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
