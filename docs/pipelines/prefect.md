# Prefect 실행과 장애 대응

Prefect는 수집 Flow와 OpenMetadata Job의 스케줄·재시도·실행 상태를 관리한다.
수집 계약과 정규화·저장 로직은 Pipelines가 소유한다. 이 문서는 실행을 시작하고
실패 지점을 찾아 재개하는 절차를 설명한다.

Flow·Task가 낯설다면 [간단한 PostgreSQL ETL 예제](writing_pipelines.md)부터 따라 해 본다.
이 문서는 등록된 Deployment의 실행과 장애 대응을 설명한다.

동일한 Flow를 Compose에서는 Process Worker로, K3s에서는 실행별 Kubernetes Job으로
실행한다. K3s의 work pool 변환·작업별 자원·전체 예산과 동시 실행 상한은
[K3s 배포](../deployment/k3s.md#정해진-자원-안에서-파이프라인-병렬-실행)를 따른다.

## 시작 전 준비

[Compose 배포](../deployment/compose.md)에 따라 `deploy/compose/.env`를 준비한다.
Connector 인증정보, Data DB writer URL과 Prefect Basic Auth 계정이
필요하다. Compose 밖에서 실행할 때는 `TEORIA_ENV_FILE=deploy/compose/.env`를 지정한다.

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml up --build -d
```

UI는 `http://localhost:8081/prefect/`다. Compose의 Prefect 4200 포트는 내부 통신용이며,
init·배포 등록·Worker가 같은 Basic Auth 계정으로 접속한다.

| 서비스 | 역할 |
|---|---|
| `postgres`, `postgres-migrate` | Data DB와 schema migration |
| `platform-postgres` | DB·role을 분리한 Application·Prefect·OpenMetadata DB |
| `prefect-server`, `prefect-services`, `prefect-redis` | API·UI·스케줄과 메시징 |
| `prefect-deploy` | 공통 등록 명령으로 Work pool·Queue 정책·Deployment 등록 |
| `prefect-worker` | 일반 수집 실행 |

Metadata 전용 Worker와 ingestion Job은 [OpenMetadata 수집](openmetadata.md)을 따른다.

## 실행할 Deployment 찾기

[배포 목록](deployments.md)에서 Flow, 파라미터, pool과 예약 상태를 확인한다.
목록은 저장소 YAML에서 생성한 선언값이다. 운영 UI의 등록값·활성 상태·최근 실행과
대조해야 실제 운영 상태를 알 수 있다.

`pipelines/prefect.yaml`은 수집, `prefect.metadata.yaml`은 Metadata Job을 정의한다.
Deployment의 `pipeline:<definition_id>`와 `domain:<domain_id>` tag로 수집 계약과
소유 Domain을 찾는다. YAML 변경 후에는 재등록하고 목록도 재생성한다.

```bash
uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs > docs/pipelines/deployments.md
uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs --check docs/pipelines/deployments.md
```

## 수동 실행과 진행 확인

Compose와 K3s는 `teoria-pipelines register`를 공통 진입점으로 사용한다.
Compose는 `--backend process`, K3s는 `--backend kubernetes`를 지정한다.
`--kind ingestion|metadata|all`로 등록 범위를 선택한다. 배포별 entrypoint·스케줄·입력은
원본 YAML을 공유하며 환경별 사본만 생성한다. 실행 정책 구현은
`pipelines/src/teoria_pipelines/deployment.py`가 소유한다.

| Queue | 대상 | 우선순위 | 기본 동시 실행 상한 |
|---|---|---|---|
| `latest` | 최신 수집·주기적 API 보강·사전 동기화 | 1 | 2 |
| `backfill` | 과거 수집·보정·Backfill 결손 재처리 | 10 | 1 |

전체 수집 상한은 `TEORIA_PIPELINE_CONCURRENCY=2`, Backfill·보정 상한은
`TEORIA_PIPELINE_BACKFILL_CONCURRENCY=1`이다. 두 배포에서 같은 정책을 적용하며
Metadata는 별도 pool의 동시 실행 1개로 관리한다. 우선순위는 다음 제출 순서에 적용되고
실행 중인 작업을 선점하지 않는다. 같은 Deployment의 `CANCEL_NEW` 중복 방지 정책은 유지한다.
동시 실행 상한 변경 후에는 등록 명령을 다시 실행한다. 한 Prefect Server에 두 환경을
같은 Deployment 이름으로 중복 등록하면 서로 갱신하므로 운영 환경별 Prefect Server를 사용한다.

예를 들어 아래 명령은 지정한 기간의 계약 Backfill을 요청한다. 같은 진행 위치를
재개하려면 같은 checkpoint를 사용하고, 독립 범위에는 새 `checkpoint_id`를 사용한다.

```bash
docker compose --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml run --rm prefect-deploy \
  prefect deployment run '나라장터 계약정보 Backfill/pps-contract-backfill' \
  --param checkpoint_id=pps_contract_backfill_2021_2026 \
  --param start_date=2021-01-01 \
  --param end_date=2026-09-13 \
  --param batch_days=1
```

UI에서 일별 하위 Flow와 API 조회→Raw 저장→정규화→Upsert→완료 기록 Task를 확인한다.
재실행은 완료 기록이 있는 Operation을 건너뛰고 모든 Operation이 완료돼야 날짜
checkpoint를 이동한다. Backfill 종료일은 오늘 이전 날짜를 사용한다.
수집·보강·과거 결손의 구체적인 정책은 [공공조달 수집](domains/public_procurement.md)을 따른다.

## 실패 지점 찾기와 재개

1. Flow에서 실패 Task를 확인한다. Provider 요청, Raw 저장, 정규 적재 중 어느 단계인지 구분한다.
2. 인증·응답 오류·속도 제한·DB 연결를 해당 단계의 로그와 실행 기록으로 확인한다.
3. 성공한 Raw·정규 결과와 checkpoint를 확인한 뒤 같은 입력으로 재개한다. 진행 위치를 임의로 앞당기지 않는다.
4. 완료 후 원본 관찰과 정규 적재를 확인한다. 최근 성공 시각만으로 전체 기간의 수집 완전성을 판단하지 않는다.

API·DB 쓰기는 Task 단위로 재시도하고 Raw·정규 적재는 중복 실행을 고려한다.
실패한 단위는 checkpoint를 진행시키지 않는다. 일부 성공을 보존하는 chunk와 결손 큐의
처리는 Domain별 정책을 따른다. 재조회 중첩 기간도 Flow·배포 파라미터별로 확인한다.

Process Worker 재시작은 다른 Worker나 Kubernetes Job의 종료 증거가 아니다.
Compose 시작 시 Data DB의 `running` 기록 중 Prefect가 종료 상태로 확인한 실행만
미완료로 정리하며, Prefect 상태·부모 Flow·checkpoint를 강제로 변경하지 않는다.
Prefect가 Completed여도 DB 완료 기록이 없으면 적재 성공으로 간주하지 않는다.
아직 Running이거나 Prefect ID 연결을 확인할 수 없는 기록은 그대로 두고 실제
실행 프로세스·Job 종료를 확인한 뒤 운영자가 Prefect에서 상태를 정리한다.
K3s Dispatcher는 시작 시 실행 중인 Job을 일괄 취소하지 않는다.

```bash
docker compose -f deploy/compose/compose.yaml logs -f prefect-worker
docker compose -f deploy/compose/compose.yaml down
```

`down -v`는 수집 데이터와 실행 이력을 삭제하므로 데이터를 폐기할 때만 사용한다.
Worker에는 `.env` 전체가 아니라 Compose가 선언한 변수만 전달한다.

## 수집이 실제로 진행되는지 확인하기

Worker의 `ONLINE`과 Flow의 `Completed`만으로 데이터가 모두 채워졌다고 판단하지 않는다.
다음 항목을 함께 확인한다.

1. 배포의 예약 시각·활성 상태, 최근 성공·실패·재시도와 10분 이상 늦은 실행을 확인한다.
2. `ingestion.pipeline_runs`의 완료 시각과 기능별 처리 건수를 확인한다. 재조회·갱신이
   포함되므로 처리 건수는 신규 고유 레코드 수와 다를 수 있다.
3. `ingestion.pipeline_checkpoints`를 조회해 성공한 범위까지만 진행했는지 확인한다.
   역방향 Backfill은 날짜가 과거로 이동하며, 시작 날짜에 도달한 예약은 처리할 구간이 없을 수 있다.
4. 개찰 보강의 `pending`·`processing`·`retry_wait`, `partial_completed`·`permanent_failure`와
   계약 `pipeline_backfill_gaps`의 미해결 구간을 따로 확인한다.
5. 현재 예약 간격과 비교한다. 4시간마다 실행하는 계약·낙찰의 마지막 성공이
   시간 단위 공고보다 오래됐다는 이유만으로 장애로 판정하지 않는다.

`CANCEL_NEW`에 따른 중복 예약 취소는 실행 중인 기존 수집을 취소한 것과 구분한다.
부분 응답이나 조회 실패를 보강 큐에 남긴 Flow는 `Completed`일 수 있으므로,
실행 실패 0건을 전체 데이터 완전성의 증거로 사용하지 않는다.
원본 비보존 경로의 `raw_record_count=0` 해석은 [Data DB](database.md)를 따른다.
시간대·건수·남은 결손을 포함한 최근 확인은
[2026-10-16 배포·수집 검증](../verification/async_deployment_collection_2026_10_16.md)에 있다.
