# Prefect 실행과 장애 대응

Prefect는 수집 Flow와 OpenMetadata Job의 스케줄·재시도·실행 상태를 관리한다.
수집 계약과 정규화·저장 로직은 Pipelines가 소유한다. 이 문서는 실행을 시작하고
실패 지점을 찾아 재개하는 절차를 설명한다.

## 시작 전 준비

[Compose 배포](../deployment/compose.md)에 따라 `deploy/compose/.env`를 준비한다.
Connector 인증정보, Data DB writer URL, 외부 Object Storage와 Prefect Basic Auth 계정이
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
| `prefect-init`, `prefect-deploy` | Work pool 생성·Deployment 등록 |
| `prefect-worker` | 일반 수집 실행 |
| `prefect-ai-worker` | 문서 파싱·Codex 기반 요건 추출 |

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

## 문서·AI Worker 로그인

전용 Worker에서 최초 device code 로그인을 완료한다.

```bash
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml exec \
  prefect-ai-worker codex login --device-auth
docker compose --env-file deploy/compose/.env -f deploy/compose/compose.yaml exec \
  prefect-ai-worker codex login status
```

인증 세션은 `codex-auth` volume의 `/home/teoria/.codex`에 보관한다. 갱신 가능한 토큰이
포함되므로 Git·이미지·일반 백업에 복사하지 않는다. API key를 이 Worker에 전달하지 않는다.
로그아웃은 Worker에서 `codex logout`을 실행한다. 인증이 만료되면 관련 schedule을
일시 중지하고 재로그인한 뒤 재개한다.

## 실패 지점 찾기와 재개

1. Flow에서 실패 Task를 확인한다. Provider 요청, Raw 저장, 정규 적재, 문서 처리 중 어느 단계인지 구분한다.
2. 인증·응답 오류·속도 제한·DB 연결·Object Storage를 해당 단계의 로그와 실행 기록으로 확인한다.
3. 성공한 Raw·정규 결과와 checkpoint를 확인한 뒤 같은 입력으로 재개한다. 진행 위치를 임의로 앞당기지 않는다.
4. 완료 후 원본 관찰과 정규 적재를 확인한다. 최근 성공 시각만으로 전체 기간의 수집 완전성을 판단하지 않는다.

API·DB 쓰기는 Task 단위로 재시도하고 Raw·정규 적재는 중복 실행을 고려한다.
실패한 단위는 checkpoint를 진행시키지 않는다. 일부 성공을 보존하는 chunk와 결손 큐의
처리는 Domain별 정책을 따른다. 재조회 중첩 기간도 Flow·배포 파라미터별로 확인한다.

```bash
docker compose -f deploy/compose/compose.yaml logs -f prefect-worker
docker compose -f deploy/compose/compose.yaml down
```

`down -v`는 수집 데이터와 실행 이력을 삭제하므로 데이터를 폐기할 때만 사용한다.
Worker에는 `.env` 전체가 아니라 Compose가 선언한 변수만 전달한다.
