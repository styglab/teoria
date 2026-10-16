# Data DB와 migration

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

## 원본·관찰·정규 데이터

Provider 원본은 `ingestion.raw_provider_payloads`에 hash 기준으로 한 번 저장하고,
실행별 조회 범위·관찰 시각은 `ingestion.raw_provider_observations`에 보관한다.
실행 감사는 `ingestion.pipeline_runs`, 업무 데이터는 `public_procurement`와
`legal_information` 스키마가 소유한다. 법령 XML은 전용 raw·snapshot 구조를 사용한다.

Pipeline writer와 Runtime reader의 role을 분리한다. Runtime에는 필요한 정규 relation과
read view만 허용하고 `ingestion` 작업 테이블·raw 권한을 확장하지 않는다.
OpenMetadata entity·설명·소유자·태그를 Data DB에 복제하지 않는다.

## 시각 컬럼 규칙

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

## 기능별 migration 적용 시 확인할 사항

첨부문서·참가요건 추출 테이블은 보류 기능의 기존 데이터로 보존한다. 현재 Worker는
이 테이블에 새 처리를 등록하지 않는다. `089_detach_notice_view_from_document_extraction.sql`은
공고 조회에서 추출 테이블 연결을 제거하며 종속 view의 기존 컬럼 위치는 NULL로 유지한다.
추출 결과 필드는 활성 Source·Mapping·Runtime 계약에서 제외한다.

`088_version_contract_ledger_refresh_requests.sql`은 계약 집계 갱신 요청에 버전을 추가한다.
Worker는 자신이 처리한 버전만 완료하므로 갱신 중 새로 요청한 작업을 보존한다.

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

`084_asset_collection_context.sql`은 명시한 공공조달 Pipeline output만 연결하는
`runtime_asset_collection_status` view와 Pipeline별 최근 실행 조회 index를 추가한다.
OpenMetadata entity ID·설명·컬럼 상태를 저장하지 않으며 view의 SELECT만 허용한다.
Prefect schedule은 복제하지 않고 ingestion 원본·작업 테이블 권한도 확장하지 않는다.
새 통합 자산 조회를 배포하기 전에 적용해야 한다. 커스텀 Pipeline ID 또는 파생
relation은 이름으로 추정하지 않으며 output 계약에 별도로 명시해야 한다.

`085_procurement_entity_search_index.sql`은 조달 개체 자동완성용 내부 검색 인덱스를
추가한다. `086_bid_notice_region_filter_indexes.sql`은 계약에 연결된 공고의 구조화 참가
지역조건을 네트워크·시장 조회에서 필터링하기 위한 공고번호·지역코드 인덱스를 추가한다.

`087_bound_bid_opening_retries.sql`은 선택 업체 검증값이 없는 과거 완료 건을 다시
백필 대상으로 전환한다. 불완전 응답과 조회 실패는 각각 제한된 재시도 횟수 이후
`partial_completed`와 `permanent_failure`로 종결하며 Runtime에는 `failed`로 제공한다.
