# Data DB와 migration

Data DB migration은 `backend/migrations/data/`가 기준이다. 기능별 저장 책임은 소유 feature에,
공통 실행·원본·checkpoint 기반은 `integrations/data_operations/`에 둔다.
Runtime은 게시된 Database Source 계약으로 정규 relation을 읽으며 migration을 실행하지 않는다.

- `ingestion`: 실행 감사, 원본 Provider 응답, Checkpoint
- `legal_information`: 법령·버전·원문 snapshot·조문·첨부와 검색 뷰
- `public_procurement`: 규격서 실행·문서별 상태·산출물 참조·표준관리 workflow와 물품 공고 복원 기반
- `mlops_demo`: 선택형 모델 운영 데모의 고객·활동 데이터

파일명은 적용 순서를 포함한 `<3자리 번호>_<설명>.sql`을 사용한다. 적용된 파일명은 `ingestion.schema_migrations`에 기록되므로 이미 적용한 migration 파일을 수정하지 않고 새 파일을 추가한다.

```bash
uv run --locked --project backend \
  teoria-pipelines migrate \
  --migrations backend/migrations/data
```

실행에는 `TEORIA_PIPELINE_DATA_DATABASE_URL`이 필요하다. 로컬 Compose에서는 `postgres-migrate` 일회성 서비스가 같은 명령을 실행한다.

## 규격서 실행과 참조

`090_specification_processing_runs.sql`의 세 테이블을 사용한다.
`specification_processing_runs`는 실행·표준 참조·완료 상태,
`specification_processing_documents`는 문서별 결과 요약,
`specification_processing_artifacts`는 URI·checksum·크기·미디어 유형을 저장한다.
원문·추출 본문·표준 본문은 파일/S3에 둔다. 완료 상태는 모든 산출물 저장 뒤 기록한다.
`091`은 Pipeline·Runtime role에 schema 사용 권한을 부여한다.

## 원본·관찰·정규 데이터

공통 JSON Provider 원본은 `raw_provider_payloads`에 내용 hash로 중복 제거하고,
실행별 관측은 `raw_provider_observations`로 분리한다. 법령의 원본 bytes·content type은
전용 `law_raw_payloads`와 관측 이력에 보존하며 JSON 저장소로 임의 변환하지 않는다.
규격서 실행의 완료 여부는 소유 기능의 실행·산출물 계약으로 판정한다.

`099`는 빈 이전 계약·낙찰·개찰·참가자격·구형 첨부 처리 객체를 제거했다.
`100`은 비어 있는 `pipeline_operation_progress`와 모든 값이 0인 이전 조달 전용 실행
카운트 여섯 열을 제거한다. 공통 실행 모델의 `raw_records`는 DB의 `raw_record_count`에 저장한다.
물품·문서 등 기능별 처리 개수는 해당 기능의 결과 계약에서 관리한다.

## 물품 공고 복원·첨부 근거

`101_goods_notice_evidence.sql`은 다음 네 테이블을 추가한다. 2026-10-28 운영 Data DB에
물품 공고 758,443건·첨부 참조 1,848,691건을 복원했다.
[운영 복원 기록](../verification/goods_notice_production_restore_2026_10_28.md)과
[격리 검증 기록](../verification/goods_notice_restore_validation_2026_10_28.md)은 구분한다.

| 테이블 | 저장 책임 |
|---|---|
| `goods_notice_import_batches` | 원본 백업·선별 파일 SHA-256, 백업 식별자, 복원 건수·기록 시각 |
| `goods_notice_versions` | 공고번호·차수·원문 해시별 불변 JSON 버전 |
| `goods_notice_observations` | 백업 복원 또는 실제 실행의 관측 근거·시각 |
| `goods_notice_attachment_refs` | 버전·슬롯별 원본 URL·파일명; 다운로드 상태를 의미하지 않음 |

원문·관측·첨부 참조·복원 배치는 append-only다. 백업 복원은 `backup_import`로 기록하고
실제 API 수집 시각·실행을 만들지 않는다. 향후 `api_fetch` 관측에는 실제 ingestion 실행과
수집 시각이 모두 필요하다. 같은 차수의 원문이 바뀌면 새 해시 버전으로 보존하며,
첨부 삭제·교체가 과거 버전의 참조를 지우지 않는다. 이 스키마 추가만으로 collector가 실행되지는 않는다.
기존 `bid_notices.source_payload`는 현재 상태로 유지하므로 최초 복원에서는 현재 본문과
불변 버전 본문을 각각 저장한다. 이후 동일 해시의 재관측은 버전을 재사용한다.
백업 압축 크기만으로 DB 용량을 추산하지 않고 본문·TOAST·인덱스를 함께 고려한다.

복원 코드는 `features/goods_notice_collection/backup_restore.py`, 프로세스 진입점은
`entrypoints/goods_notice_restore.py`다. 원본 백업에서 물품만 선별·별도 검증한 뒤
manifest에 백업 식별자·원본/선별 파일 해시·공고/첨부 건수를 기록한다.
연결 문자열은 환경변수로만 전달한다.

```bash
uv run --project backend --locked python -m teoria.entrypoints.goods_notice_restore \
  --subset /private/backup/goods_bid_notices.copy.sql.gz \
  --manifest /private/backup/restore_manifest.json \
  --expected-database teoria_goods_restore_check
```

기본 연결 환경변수는 `TEORIA_TEST_GOODS_RESTORE_DATABASE_URL`이다. 실제 DB 이름이
`--expected-database`와 다르면 거절한다. migration은 사전에 별도로 적용한다.
기존 공고·투영·근거 테이블이 비어 있어야 하며, 동일 선별 파일·동일 manifest의 재실행은
기존 완료 배치를 반환한다. 다른 출처나 건수의 재실행과 기존 데이터 덮어쓰기는 거절한다.

gzip·JSON 검증은 제한된 thread에서, COPY·SQL은 native async 연결에서 순서대로 실행한다.
staging 검증 후 공고·근거·첨부·최신 차수·계보 요약을 하나의 transaction에서 적재한다.
대량 복원 동안 공고 전용 세 트리거만 transaction 안에서 잠시 중지하고 투영을 일괄 재구성한다.
FK·제약은 유지하며 알 수 없는 트리거가 있으면 거절한다. 실패하면 DDL을 포함해 롤백한다.
`enrichment_checked_at`·`enrichment_claimed_at`은 초기화하고 원문의 차수·기존 계보 참조는 보존한다.
일부 이전 공고가 물품 이외 업무라면 해당 참조가 복원 범위 밖에 있을 수 있다.
복원은 공고 테이블에 배타 잠금을 잡으므로 운영 반영 때는 공고 이용 경로의 중단 시간을 고려한다.

복원 DB에서 최신 차수·현재 원문 버전의 첨부 목록을 확인하는 운영 조회 예시는 다음과 같다.
버전 해시까지 연결해야 이전 원문의 첨부가 현재 목록에 섞이지 않는다.

```sql
SELECT n.notice_number, n.notice_order, n.notice_name,
       a.document_slot, a.file_name, a.source_url
FROM public_procurement.bid_notices n
JOIN public_procurement.bid_notice_latest_versions l
  USING (notice_number, notice_order)
JOIN public_procurement.goods_notice_attachment_refs a
  USING (notice_number, notice_order, source_record_hash)
WHERE n.work_type = 'goods';
```

이는 운영 점검 SQL이다. Runtime·MCP 조회를 노출하려면 별도 게시 계약과 검증이 필요하다.

## 수집 이력과 원본의 보존 기준

현재 기본 정책은 **업무 원본·근거·진행 위치를 유지하고 나이만으로 자동 삭제하지 않는 것**이다.
과거 물품 공고 복원과 원문 근거 조회를 지원하므로 짧은 TTL을 새로 적용하지 않는다.

| 대상 | 보존 기준 |
|---|---|
| `schema_migrations` | 적용 이력을 계속 보존한다. 과거 파일을 수정하거나 이력 행을 지워 재실행하지 않는다. |
| `pipeline_checkpoints` | pipeline별 현재 진행 위치와 참조 실행을 유지한다. 정리 작업이 cursor를 진전·후퇴시키지 않는다. |
| `pipeline_runs` | checkpoint·관측·법령 수집 등이 참조하는 실행을 보존한다. 참조 없는 완료·실패 실행도 현재는 자동 삭제하지 않는다. |
| `raw_provider_payloads` | 관측과 정규 데이터·문서 근거가 사용하는 원본을 보존한다. SQL FK 외의 source hash 연결도 고려한다. |
| `raw_provider_observations` | 같은 원본을 언제 어느 실행에서 관측했는지 보존한다. 원본 중복 제거와 관측 이력 삭제를 혼동하지 않는다. |
| `law_raw_payloads`, `law_raw_observations` | 법령 snapshot의 재파싱·정정 비교·근거 조회를 지원하도록 원본과 관측을 함께 보존한다. |
| `pipeline_backfill_gaps` | 미해결 구간은 재시도 완료 전까지 유지한다. 해결된 구간도 현재는 조사 이력으로 유지한다. |

TTL 기반 purge나 정기 삭제 배포는 설정하지 않았다. 추후 기간 보존을 도입할 때는
대상 pipeline·기준일·근거 의존성·백업·삭제 건수를 명시하고, 실행과 payload를 연결한
참조를 확인한 뒤 소유 기능의 transaction 경계에서 처리한다. Prefect 내부 실행 로그는
Prefect가 소유하며 Data DB 정리로 Prefect DB를 직접 삭제하지 않는다.

물리 유지보수는 일반 `VACUUM ANALYZE`와 autovacuum을 기본으로 한다. 일반 vacuum이
공간을 재사용 가능하게 만드는 것과 파일 크기를 줄이는 것은 다르다.
테이블 재작성·배타 잠금을 수반하는 `VACUUM FULL`을 기본 정리 절차로 사용하지 않는다.

## DB 인스턴스 경계

`teoria_data`는 수집·복원·대량 적재를 담당하는 별도 PostgreSQL 컨테이너에 유지한다.
`teoria_app`은 현재 Prefect·OpenMetadata DB와 `platform-postgres` 인스턴스를 공유한다.
업무 DB·역할·볼륨 경계를 유지하며 이번 ingestion 정리에서 컨테이너를 통합하지 않는다.

migration은 적용된 파일을 수정하지 않고 새 순번으로 추가한다.
현재 처리·저장 계약은 [규격서 파이프라인](../procurement_specification_processing/pipeline.md),
실행·실패 대응은 [Prefect](prefect.md)를 따른다.
