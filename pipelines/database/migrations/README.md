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
- 타임존 표기가 없는 제공기관 시각은 제공기관의 명시된 지역 타임존으로 먼저
  해석한 뒤 UTC로 변환한다. 나라장터의 입찰공고 시각은 `Asia/Seoul`로 해석한다.

입찰 참가자격 추출은 첨부문서 처리 커버리지를 함께 저장한다. 일부 문서가 반복 실패하거나
미지원 형식이어도 사용 가능한 문서와 정형 제한정보로 `partial` 결과를 생성하며, 누락 문서와
오류 사유를 `unavailable_documents`에 기록한다.

`081_bid_opening_runtime_collection_status.sql`은 참여 분석에 필요한 수집 상태를
`public_procurement.runtime_bid_opening_collection_status` view로 제공한다.
Runtime에는 이 view의 SELECT만 허용하고 ingestion 작업 테이블은 노출하지 않는다.
새 Platform 참여 분석을 배포하기 전에 이 migration을 적용해야 한다.

`082_legal_information_law_collection.sql`은 법령 ID·MST·시행일별 목록,
인증값이 제거된 원문 bytes·관측, 파서 버전별 snapshot, 조항 계층과 별표 정보를
추가한다. 기존 조달 테이블이나 적용된 migration을 수정하지 않는다.
Runtime 읽기 권한은 추가하지 않는다.

`083_legal_information_search_views.sql`은 수집 상태를 포함한 법령 버전 view와
조문·부칙 하위 내용을 합친 검색 view를 추가한다. `teoria_runtime`에는 스키마
USAGE와 두 view SELECT만 부여하며 원문·스냅샷·Raw 테이블 권한은 부여하지 않는다.
