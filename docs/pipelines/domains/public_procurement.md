# 공공조달 데이터 수집

공고·계약·낙찰 목록과 업종 사전을 수집한다.
수집 실행은 `pipelines/src/teoria_pipelines/domains/public_procurement/`가 소유한다.
집계 의미와 조회 기능은 Platform이 담당한다.

## 수집 기능과 저장 흐름

| 기능 | 구현 위치 | 주요 처리 |
|---|---|---|
| 계약 | `contracts/flows.py`, `tasks.py` | 최신·보정·과거 수집, 결손 재시도 |
| 공고 | `bid_notices/flows.py`, Task 모듈 | 기본 공고, API 면허·지역 보강 |
| 낙찰·개찰 | `bid_results/flows.py`, `tasks.py` | 낙찰 목록, 공고별 참여업체 보강 |
| 업종 | `industries/flows.py`, `tasks.py` | 업종 사전 |

나라장터 계약은 `pps_contract_incremental`과 `pps_contract_backfill`이 독립 checkpoint를
사용한다. 일별 하위 Flow에서 상품·공사·용역·외자를 조회한 뒤 Raw 저장·정규화·적재를
수행한다. 원본과 정규 적재가 모두 성공한 뒤에만 진행 위치를 갱신한다.
Raw 본문은 hash 기준으로 한 번 보관하고 실행별 관찰은 별도 기록한다.
테이블과 감사시각 규칙은 [Data DB](../database.md)를 참고한다.

## 보강과 원본 보존

공고별 면허·지역 보강은 기본 1 RPS의 완전 순차 호출로 제한한다. 최신 공고 수집은 변경 공고를
즉시 보강하지만, 과거 공고 Backfill은 기본 공고만 적재하고 체크포인트를 독립적으로 갱신한다.
과거 참가제한은 `pps-bid-notice-enrichment-backfill`이 7일 이상 지난 미처리 공고를 배포 파라미터의 처리량으로
선점하고 5건 단위로 Raw 저장과 정규 적재를 완료한다. 일부 청크가 429로 실패해도 완료된 공고의
`enrichment_checked_at`은 보존되며, 실패한 선점은 60분 뒤 다시 처리할 수 있다.

계약 Backfill은 날짜별 Operation 완료 상태를 보존한다. 제공기관 오류가 반복되는 날짜·Operation은
`ingestion.pipeline_backfill_gaps`에 기록하고 다음 날짜로 계속 진행한다. 별도 Deployment인
`pps-contract-backfill-gap-retry`가 결손을 페이지 크기 20, 10, 1 순서로 재시도하며 성공한 결손은
해결 시각을 기록한다. 따라서 단일 제공기관 오류가 전체 역사 수집 체크포인트를 막지 않는다.

첨부파일 다운로드·파싱·입찰요건 추출과 참가 가능성 판단은 보류했다.
해당 기능은 현재 배포와 수집 큐에 포함하지 않는다. 당시 보류·제거 범위는
[검증 기록](../../verification/bid_document_archive_2026_10_16.md)을 따른다.
파일 보관본은 현재 저장소에서 제거되었으며, 당시 기존 DB와 객체는 보존했다.

## 최신·보정·과거 수집의 구분

입찰공고는 공고게시일시, 계약은 계약체결일자, 낙찰은 개찰일시를 조회 기준으로 사용한다.
공고 API의 목록 Operation은 공고번호 단건 조회를 지원하지 않는다. 최근 3일 보정은
지연 반영과 정정을 보완하기 위한 별도 Deployment이며 예약 여부는 배포 목록에서 확인한다.
낙찰은 개찰 후 최종낙찰 확정이 늦어질 수 있어 30일·90일
보정을 별도로 실행한다. 이 주기와 2021년 이후 과거 데이터를 채우는 Backfill은 서로
독립적이다.

### 계약 수집

계약은 최신 수집·30일 및 90일 보정·역방향 Backfill·결손 재시도로 나눈다.
구체적인 예약 상태와 파라미터는 [Deployment 목록](../deployments.md)을 확인한다.

증분 수집과 Backfill은 독립 checkpoint를 사용한다. 기본 계약 Backfill checkpoint는
`pps_contract_backfill_2021_2026`이고 `2026-09-13`부터 `2021-01-01`까지 역방향으로 진행한다. 범위를 완료하면
이후 예약 실행은 API를 호출하지 않는다.

별도 범위를 적재할 때는 UI에서 같은 Flow의 Custom Run이나 Schedule 파라미터에 고유한
`checkpoint_id`, `start_date`, `end_date`를 지정한다. 서로 다른 Backfill에 같은
`checkpoint_id`를 사용하면 진행 상태가 충돌하므로 사용하지 않는다.

### 공고 수집

입찰공고는 최신 수집·보정·기본 공고 Backfill·과거 참가제한 보강으로 나눈다.
구체적인 예약 상태와 파라미터는 [Deployment 목록](../deployments.md)을 확인한다.

입찰공고 Backfill은 `pps_bid_notice_backfill_2021_2026` checkpoint를 사용한다.
기본 공고 원본과 정규 공고 저장이 성공하면 날짜를 과거로 이동한다.
면허·지역 제한은 독립 보강 큐가 처리하며 과거 첨부파일은 등록하지 않는다.

### 낙찰·개찰 수집

낙찰 목록 수집과 개찰 참여업체 보강은 독립 Flow다. 증분·보정·Backfill·보강의
예약 상태와 범위는 [Deployment 목록](../deployments.md)을 확인한다.

낙찰 목록 수집은 정규화·적재와 개찰 보강 대상 등록이 성공하면 체크포인트를 갱신한다.
공고별 개찰조회는 별도 `pps-bid-opening-enrichment` Flow가 처리하며, 실패 건은
30분·2시간·12시간·1일 간격으로 재시도한다. 따라서 제공기관 개찰 API 지연은 낙찰
증분 수집이나 Backfill 체크포인트를 막지 않는다.
Backfill의 `checkpoint_id`, `start_date`, `end_date`는 필수이며 `end_date`는 오늘보다 이전이어야 한다.

공공데이터포털은 데이터 갱신주기를 실시간으로 안내하지만 정확한 반영 지연은 보장하지 않는다.
Incremental은 지연 반영을 고려해 최근 3일을 중복 조회하며 정규 테이블에 upsert한다.

## 개찰 보강 완료 판정

개찰 원본은 모든 페이지의 totalCount·행 수·중복·공고 키와 알려진 낙찰자를
검증한 뒤 저장한다. 일부 페이지만 조회하거나 응답이 잘린 경우 기존 참여업체를
교체하지 않고 해당 공고만 재시도한다. 정규 저장 대상은 순위 1~10위와 낙찰자다.
전체 참가자 수와 정규 저장 수를 비교하지 않는다. 수집 상태의
`participant_count`는 원본 조회 행 수를 유지하고, `selected_business_numbers`는
검증한 저장 대상 업체 집합을 보관한다. 같은 낙찰 원본 hash에 대해 정규 테이블의
업체 집합이 정확히 일치해야 queue를 완료한다. 기존 상태의 NULL 집합은 미검증이며
재조회 없이 일괄 완료로 바꾸지 않는다. 전체 조회는 기존 timeout·호출 속도 제한을
따르므로 참가자가 많은 공고는 제한 시간 내에 완료하지 못해 재시도할 수 있다.

응답 불완전은 최대 3회 시도 후 `partial_completed`, 조회 실패는 최대 5회 시도 후
`permanent_failure`로 종결한다. 두 상태는 Runtime에서 `failed`이며 전체 성공으로
합산하지 않는다. 원인을 해결한 뒤 운영자가 재처리 여부를 판단한다.
처리 제한은 `087_bound_bid_opening_retries.sql`과 해당 repository가 소유한다.

성공한 낙찰·개찰 응답은 정규화 후 보존하지 않는다. 수집 계약의
`retain_raw_records: false`에 따라 정규 원천 hash·실행 이력·검증한 업체 집합으로
추적하며 Raw 건수 대신 정규 처리 건수와 보강 완료 상태를 확인한다.

## 구현을 수정할 때

입찰공고 Task는 `ingestion_tasks.py`와 `enrichment_tasks.py`가 수집·API 보강을 담당한다.
수집 날짜와 Backfill 경계는 `public_procurement/calendar.py`의 한국시간 날짜를 사용한다.
감사시각은 UTC로 저장한다. 계약 집계 갱신은 요청 버전별로 완료 처리하므로 갱신 중 들어온
새 요청은 다음 실행까지 큐에 남는다. 같은 분야의 동시 갱신은 DB advisory lock으로 제한한다.

실행·수동 재시도는 [Prefect](../prefect.md), 의미 기준은
[Platform 조달 집계](../../platform/domains/public_procurement/contract_aggregation.md)를 참고한다.
과거 데이터 결손의 시점별 점검은 [수집 점검 기록](../../verification/procurement_collection_2026_10_12.md)에 보존한다.
