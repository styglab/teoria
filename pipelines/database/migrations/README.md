# Data database migrations

Teoria Data Pipelines가 수집 DB의 물리 schema와 migration을 소유한다. Semantic Platform은 Database Source Registry를 통해 정규 relation을 읽을 뿐 migration을 실행하지 않는다.

- `ingestion`: 실행 감사, 원본 Provider 응답, Checkpoint
- `public_procurement`: 정부조달 계약과 기관·공급자 정규 데이터

파일명은 적용 순서를 포함한 `<3자리 번호>_<설명>.sql`을 사용한다. 적용된 파일명은 `ingestion.schema_migrations`에 기록되므로 이미 적용한 migration 파일을 수정하지 않고 새 파일을 추가한다.

```bash
uv run --locked --package teoria-pipelines \
  teoria-pipelines migrate \
  --migrations pipelines/database/migrations
```

실행에는 `TEORIA_PIPELINE_DATA_DATABASE_URL`이 필요하다. 로컬 Compose에서는 `postgres-migrate` 일회성 서비스가 같은 명령을 실행한다.

## Timestamp convention

- 변경 가능한 업무·정규화 테이블은 `created_at`, `updated_at`을 사용한다.
- `created_at`은 최초 INSERT 시각이며 이후 변경하지 않는다.
- `updated_at`은 실제 저장 값이 변경되는 UPDATE에서만 갱신한다.
- 불변 원본과 실행·적용 이벤트는 의미가 명확한 `fetched_at`, `started_at`,
  `finished_at`, `applied_at`을 유지한다.
- 외부 제공기관이 기록한 시각은 `source_*_at`으로 DB 레코드의 감사 시각과
  구분한다.
- 모든 시각 컬럼은 PostgreSQL `timestamptz`를 사용한다.

입찰 참가자격 추출은 첨부문서 처리 커버리지를 함께 저장한다. 일부 문서가 반복 실패하거나
미지원 형식이어도 사용 가능한 문서와 정형 제한정보로 `partial` 결과를 생성하며, 누락 문서와
오류 사유를 `unavailable_documents`에 기록한다.
