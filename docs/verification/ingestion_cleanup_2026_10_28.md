# 미사용 ingestion 구조 정리와 보존 기준 — 2026-10-28

운영 `teoria_data`에 새 migration `100_prune_unused_ingestion_progress.sql`을 적용하고
COMMIT했다. Data DB와 App DB의 컨테이너·역할·볼륨 구성은 유지했다.

## 실제 변경

- 비어 있고 활성 코드 참조가 없는 `ingestion.pipeline_operation_progress`를 제거했다.
- `pipeline_runs`에서 모든 값이 0인 이전 조달 카운트 여섯 열을 제거했다.
  대상은 `contract_count`, `notice_count`, `document_count`, `award_count`,
  `opening_participant_count`, `notice_outcome_count`다.
- 공통 Python 실행 모델의 `LoadSummary.raw_records`가 저장되는 `raw_record_count`는 유지했다.
  Python 모델은 이미 `raw_records` 한 필드만 사용하므로 런타임 모델을 추가 변경하지 않았다.
- 남은 ingestion 테이블 8개에 `VACUUM (ANALYZE, TRUNCATE FALSE)`를 실행했다.
  live 데이터를 삭제하거나 전체 파일을 재작성하지 않았으며 OS 공간 회수를 주장하지 않는다.

정리 후 Data DB는 **테이블 23개·법령 뷰 2개**, ingestion은 다음 **8개 테이블**이다.

```text
pipeline_runs
pipeline_checkpoints
pipeline_backfill_gaps
raw_provider_payloads
raw_provider_observations
law_raw_payloads
law_raw_observations
schema_migrations
```

`pipeline_backfill_gaps`는 현재 비어 있지만 결손 재시도 저장 메서드가 있고 물품 과거 수집에
사용할 기반이므로 보존했다. 공통 JSON 원본·관측 저장소도 물품 수집을 위해 유지했다.
법령 원본은 bytes·content type을 보존하는 별도 계약이므로 공통 JSON 저장소와 합치지 않았다.

## 보존 기준과 컨테이너

기본 정책을 [Data DB 안내](../pipelines/database.md)에 명시했다.
checkpoint와 그 참조 실행, 원본 근거·관측·법령 snapshot 연결은 보존한다.
참조 없는 완료·실패 실행이나 해결된 결손 기록도 현재는 자동 삭제하지 않는다.
과거 공고 복원과 근거 조회를 위해 보존 연한을 임의로 줄이거나 TTL purge를 배포하지 않았다.
정기 삭제를 추가하려면 pipeline·기준일·참조·백업·삭제 건수를 소유 기능에서 정해야 한다.

운영 `postgres`는 `teoria_data`, `platform-postgres`는 `teoria_app`·Prefect·OpenMetadata를
계속 담당한다. 두 운영 컨테이너 ID가 전후 동일함을 확인했다.
컨테이너 통합·재배포·메모리 상한 변경이나 Prefect DB 직접 정리는 수행하지 않았다.

## 검증과 보호

최신 Data DB를 백업하고 네트워크 없는 별도 PostgreSQL 17 tmpfs에 실제 복원했다.
새 migration은 다음 조건을 확인한 뒤 `RESTRICT`로 정리한다.

- Operation progress가 한 행이라도 있으면 거절한다.
- 제거할 카운트에 0 이외의 값이나 NULL이 있으면 정보 손실 가능성으로 거절한다.
- 예상하지 못한 뷰 등 의존성이 있으면 실패하고 transaction을 rollback한다.

검증 결과는 다음과 같다.

- 백엔드 **688 passed, 60 skipped**. 별도 opt-in 환경 검사는 skip으로 남겼다.
- 실제 복원한 pre-100 격리 DB의 보호 검사 **10 passed**.
- 빈 격리 DB에 **migration 1~100 전체 적용 성공**.
- 해당 빈 DB에서 실제 `PostgresStore`를 사용한 합성 fixture 검증 성공:
  실행 시작 → 원본 저장·중복 제거 → 물품 공고 저장 → checkpoint → 실행 완료.
  실제 Provider API 호출이나 운영 물품 공고 수집을 수행한 검사는 아니다.
- Compose config, 추가 테스트의 Ruff 검사·형식 검사 통과.
- 실제 운영 Worker 두 개의 실행 저장 메서드가 제거 대상 열을 참조하지 않음을 확인했다.
- 운영에서 보존 검사와 정리를 먼저 시험하고 ROLLBACK한 뒤 동일 SQL을 COMMIT했다.
- 보존 테이블 **23개**의 행 수와 투영된 내용 SHA-256이 전후 동일했다.
  비교 시 제거가 허용된 0 값 카운트 열과 새 migration 100 이력 행만 제외했다.
- 정리 후 관계 목록이 사전 목록에서 대상 테이블 하나만 뺀 집합과 정확히 일치했다.
- Admin·Runtime health와 고정 기준일 `2026-10-28`의 법령 검색이 HTTP 200이며 응답이 동일했다.
- Runtime 활성 artifact pointer·checksum이 동일했다.

일반 vacuum은 삭제된 tuple의 공간을 재사용 가능하게 하고 planner 통계를 갱신한다.
`TRUNCATE FALSE`로 테이블 끝 절단을 끄고 `VACUUM FULL`을 사용하지 않았다.

## 복구 자료

`backups/teoria/ingestion_cleanup_20261028T021728Z/`에 다음을 보존했다.

- 정리 전 전체 `teoria_data_before.dump`: **8,108,490 bytes**.
- 원본 migration과 SHA-256, 대상·보존 목록, rollback/apply SQL.
- 실제 복원·보호 검사·전체 테스트·빈 DB 저장 검증 로그.
- 운영 Worker 호환성·전후 서비스·컨테이너·관계 목록과 `result.json`.
- vacuum 실행 기록과 `SHA256SUMS`.

복구 디렉터리는 owner-only이며 Provider 원본 본문·인증정보를 Git이나 문서에 기록하지 않았다.
기존 백업은 변경하지 않았다. 격리 컨테이너와 tmpfs 검증 DB는 마지막에 제거했다.
물품 공고 복원·신규 수집 배포와 자동 삭제 일정은 이번 작업에 포함하지 않았다.
