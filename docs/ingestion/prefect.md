# Prefect 기반 Pipeline 운영

Prefect는 Pipeline의 schedule, retry, 상태와 실행 그래프를 관리한다. 수집 로직과 DB schema는 `pipelines/`가 소유한다.

## 시작

루트 `.env`에 Connector 인증정보와 Prefect Basic Auth 계정을 설정한다.

```env
TEORIA_CONNECTOR_PPS_CONTRACT_API_KEY=...
TEORIA_CONNECTOR_PPS_BID_NOTICE_API_KEY=...
TEORIA_PREFECT_USERNAME=admin
TEORIA_PREFECT_PASSWORD=충분히-긴-비밀번호
TEORIA_OBJECT_STORAGE_ENDPOINT=https://minio.example.com
TEORIA_OBJECT_STORAGE_ACCESS_KEY=외부-MinIO-access-key
TEORIA_OBJECT_STORAGE_SECRET_KEY=외부-MinIO-secret-key
TEORIA_OBJECT_STORAGE_BUCKET=teoria
```

입찰 첨부파일은 기본적으로 입찰 마감 후 90일 동안 보존한다. 매일 03:45(Asia/Seoul)에
`pps-bid-document-retention`이 원본 첨부파일, 파싱 산출물과 AI 원본 출력만 삭제한다.
공고·문서 메타데이터, checksum, 면허·지역 제한과 정규화된 참가요건은 유지되며 삭제 결과는
`public_procurement.bid_document_purge_runs`에 기록된다. 보존기간과 회당 처리량은 다음 값으로
조정할 수 있다.

```env
TEORIA_PIPELINE_BID_DOCUMENT_RETENTION_DAYS=90
TEORIA_PIPELINE_BID_DOCUMENT_PURGE_BATCH_SIZE=500
```

`TEORIA_PREFECT_USERNAME`과 `TEORIA_PREFECT_PASSWORD`는 필수다. Prefect Server는 Basic Auth를
요구하고 init, Deployment 등록과 Worker는 같은 계정으로 API에 접속한다. 현재 4200 포트는
HTTP이므로 인터넷에 무제한 공개하지 않고 내부망, VPN 또는 방화벽 허용 IP 안에서 사용한다.
UI의 API 주소는 동일 출처의 `/api`를 사용하므로 localhost와 외부 서버 IP 접속에 같은 구성을 사용한다.

```bash
docker compose --env-file .env \
  -f deploy/compose.yaml \
  up --build -d
```

| 서비스 | 역할 |
|---|---|
| `postgres`, `postgres-migrate` | Teoria 공유 PostgreSQL과 migration |
| `prefect-db`, `prefect-redis` | Prefect 영속 상태, 메시징과 서비스 조정 |
| `prefect-server`, `prefect-services` | Prefect API/UI와 Scheduler 등 백그라운드 서비스 |
| `prefect-init`, `prefect-deploy` | Work pool과 Deployment 등록 |
| `prefect-worker` | Prefect Flow 실행 |

Object Storage는 Compose 외부의 S3 호환 MinIO를 사용한다. bucket은 배포 전에 생성하고 Pipeline
access key에는 해당 bucket의 객체 읽기·쓰기·삭제 권한만 부여한다. 공용 `teoria` bucket을
사용하고 업무별 객체를 경로로 분리한다. 입찰공고 첨부파일은
`public-procurement/bid-notices/{공고번호}/{차수}/original/` 아래에 저장한다.
기존 내장 MinIO 데이터가 있으면 동일한 bucket과 object key로 외부 저장소에 먼저 복사하고 객체
수 및 checksum을 확인한 후 worker endpoint를 전환한다.

첨부문서 파싱은 매시 25분 `teoria-ai-extraction` pool에서 실행한다. Codex Skill 기반
참가자격 추출은 ChatGPT 로그인과 대표 공고 검증을 마쳤으며 매시 35분 실행된다. API key는 worker에 전달하지 않는다. 인증 세션은
`codex-auth` Docker volume의 `/home/teoria/.codex`에 저장되며 이미지나 저장소에 포함되지 않는다.
추출 결과는 공고 요구조건만 포함하며
업체별 충족 판정은 Platform Runtime API와 MCP의 책임이다.

첨부파일 처리가 아직 `pending` 또는 `processing`이면 참가자격 추출을 기다린다. 재시도 한도를
소진했거나 미지원 형식인 파일이 있으면 성공적으로 파싱된 문서와 API 제한정보로 추출을 계속하고
결과를 `partial`, `requires_review=true`로 저장한다. 결과에는 전체·성공·누락 문서 수와 누락
파일명 및 오류 사유가 포함된다. 첨부파일이 없고 API 제한정보만 있으면 `api_only`, 모든 문서가
파싱됐으면 `complete`다. 이후 파서 개선으로 누락 문서가 파싱되면 입력 fingerprint가 변경되어
같은 공고도 다시 추출된다.

최초 한 번 다음 명령으로 device code 로그인을 완료하고 상태를 확인한다.

```bash
docker compose --env-file .env -f deploy/compose.yaml exec \
  prefect-ai-worker codex login --device-auth
docker compose --env-file .env -f deploy/compose.yaml exec \
  prefect-ai-worker codex login status
```

`auth.json`에는 갱신 가능한 인증 토큰이 있으므로 비밀번호처럼 취급한다. `codex-auth` volume을
백업본, 이미지, Git 또는 다른 서비스에 복사하지 않는다. 로그아웃하려면 worker에서
`codex logout`을 실행한다. 로그아웃하거나 인증이 만료되면 추출 Task는 재시도 후 실패하며,
재로그인 전에는 Prefect UI에서 `pps-bid-eligibility-extraction` schedule을 일시 중지한다.

Compose 배포 시 UI는 nginx의 `http://localhost:8081/prefect/`로 접근한다. Prefect Server의 4200 포트는 Compose 내부에서만 사용한다. Worker에는 `.env` 전체가 아니라 Compose에 선언한 Pipeline 변수만 전달한다.

## 계약정보 Deployment

| Deployment | 주기 | 역할 |
|---|---|---|
| `pps-contract-incremental` | 4시간마다 | 오늘을 포함한 최근 3일을 재조회하여 신규·변경 계약을 반영 |
| `pps-contract-backfill` | 매시 20분 | `2020-01-01`부터 `2025-12-31`까지 정방향으로 실행당 최대 30일 적재 |

두 Deployment는 독립 checkpoint를 사용한다. 기본 Backfill checkpoint는
`pps_contract_backfill_2020_2025`이고 `2020-01-01`부터 `2025-12-31`까지 정방향으로 진행한다. 범위를 완료하면
이후 예약 실행은 API를 호출하지 않는다.

별도 범위를 적재할 때는 UI에서 같은 Flow의 Custom Run이나 Schedule 파라미터에 고유한
`checkpoint_id`, `start_date`, `end_date`를 지정한다. 서로 다른 Backfill에 같은
`checkpoint_id`를 사용하면 진행 상태가 충돌하므로 사용하지 않는다.
Backfill의 `checkpoint_id`, `start_date`, `end_date`는 필수이며 `end_date`는 오늘보다 이전이어야 한다.

공공데이터포털은 데이터 갱신주기를 실시간으로 안내하지만 정확한 반영 지연은 보장하지 않는다.
Incremental은 지연 반영을 고려해 최근 3일을 중복 조회하며 정규 테이블에 upsert한다.

## 수동 실행

```bash
docker compose --env-file .env \
  -f deploy/compose.yaml \
  run --rm prefect-deploy \
  prefect deployment run '나라장터 계약정보 Backfill/pps-contract-backfill' \
  --param checkpoint_id=pps_contract_backfill_2020_2025 \
  --param start_date=2020-01-01 \
  --param end_date=2025-12-31 \
  --param batch_days=30
```

UI의 일별 하위 Flow에서 상품→공사→용역→외자→Raw 저장→정규화→Upsert→Checkpoint 순서와 재시도를 확인할 수 있다.

## 실패와 종료

- API와 DB 쓰기는 Task 단위로 재시도한다.
- Raw와 정규 적재는 idempotent하게 처리한다.
- 실패 실행은 감사 테이블에 기록하고 Checkpoint는 이동하지 않는다.
- 다음 실행은 Checkpoint에서 이틀을 겹쳐 지연 반영을 다시 읽는다.

```bash
docker compose --env-file .env \
  -f deploy/compose.yaml \
  down
```

`down -v`는 수집 데이터와 Prefect 이력을 삭제하므로 로컬 데이터를 폐기할 때만 사용한다.
