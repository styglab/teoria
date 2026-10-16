# 공공조달 데이터 수집과 문서 처리

공고·계약·낙찰 목록과 업종 사전을 수집하고, 공고 문서를 파싱해 참가요건을 추출한다.
수집 실행은 `pipelines/src/teoria_pipelines/domains/public_procurement/`가 소유한다.
업체가 요건을 충족하는지 평가하는 기능과 집계 의미는 Platform이 담당한다.

## 수집 기능과 저장 흐름

| 기능 | 구현 위치 | 주요 처리 |
|---|---|---|
| 계약 | `contracts/flows.py`, `tasks.py` | 최신·보정·과거 수집, 결손 재시도 |
| 공고 | `bid_notices/flows.py`, Task 모듈 | 기본 공고, 면허·지역 보강, 첨부파일 |
| 낙찰·개찰 | `bid_results/flows.py`, `tasks.py` | 낙찰 목록, 공고별 참여업체 보강 |
| 업종 | `industries/flows.py`, `tasks.py` | 업종 사전 |
| 문서·요건 | `bid_eligibility/` | 파싱, 근거 추출, 검증과 조건식 구성 |

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

입찰 첨부파일은 기본적으로 입찰 마감 후 90일 동안 보존한다. 별도 보존 처리 Deployment인
`pps-bid-document-retention`이 원본 첨부파일, 파싱 산출물과 AI 원본 출력만 삭제한다.
공고·문서 메타데이터, checksum, 면허·지역 제한과 정규화된 참가요건은 유지되며 삭제 결과는
`public_procurement.bid_document_purge_runs`에 기록된다. 보존기간과 회당 처리량은 다음 값으로
조정할 수 있다.

```env
TEORIA_PIPELINE_BID_DOCUMENT_RETENTION_DAYS=90
TEORIA_PIPELINE_BID_DOCUMENT_PURGE_BATCH_SIZE=500
```

## 문서 파싱과 참가요건 추출

첨부문서 파싱과 Codex Skill 기반 참가자격 추출은 `teoria-ai-extraction` pool에서 실행한다.
각 Deployment의 예약 시각·활성 상태는 [배포 목록](../deployments.md)을 따른다. API key는 worker에 전달하지 않는다. 인증 세션은
`codex-auth` Docker volume의 `/home/teoria/.codex`에 저장되며 이미지나 저장소에 포함되지 않는다.
추출 결과는 공고 요구조건만 포함하며
업체별 충족 판정은 Platform Runtime API와 MCP의 책임이다.

Codex는 인용 근거가 있는 원자 요건 Fact와 각 Fact의 `common`, `single`, `consortium`
배치만 생성한다. 최종 `all`/`any` 조건식은 Pipeline의 결정론적 Expression Builder가 조립한다.
Builder는 요건 참조 완전성, 잘못된 대안 그룹, AND 경로의 중복 요건을 검사하며 전역 배치가
동일 Fact의 하위 참가방식 배치를 포함하는 경우 이를 안전하게 흡수한다. 대표 단독·공동수급 및
대안 조합은 골든 데이터 회귀 테스트로 관리한다.

추출 배치는 문서가 준비된 공고에 80%, 첨부문서가 없는 API 전용 공고에 20%를 우선 배정한다.
문서 공고는 기본적으로 Codex Skill로 추출한다. 단, 단일 문서·단일 블록 전체가 지원되는 단순
면허·지역·중소기업확인서 형식과 정확히 일치하면 결정론적 fast path로 처리한다. 추가 문장이나
다른 구조화 출처가 하나라도 있으면 누락을 피하기 위해 전체를 기존 Codex 경로로 보낸다. API 전용
공고의 면허제한과 참가가능지역은 Codex를 호출하지 않고 구조화된 출처를 그대로 결정론적으로
정규화한다. 면허 제한그룹 내부와 복수 참가가능지역은
대안(`any`), 서로 다른 면허 제한그룹과 지역 조건 사이는 동시조건(`all`)으로 보존한다.

AI 입력은 공고별 checksum으로 중복 문서를 제거한다. 모델 원본은 검증 전에 attempt별 Object로
저장하며 스키마·인용 검증 실패도 Data DB에 `failed`로 기록한다. 실패 fingerprint는 1시간 동안
재선택하지 않는다. 하위 공고 Task가 하나라도 최종 실패하면 성공한 공고 결과는 보존하되 Flow는
`Failed`로 표시한다. 긴 PDF/HWP 블록은 원본 block ID와 문자 offset을 보존한 900자 이하 하위
블록으로 세분화한다. checksum이 달라도 정규화 텍스트가 88% 이상 유사한 PDF/HWP는 AI 입력에서
한 건으로 묶고 PDF를 대표 문서로 사용한다. 모델 인용은 원문 블록과 다시 대조하며 법령 괄호나
접속어가 생략된 경우 토큰·문자 유사도와 후보 유일성을 확인한 뒤 실제 원문 블록으로 교정한다.
후처리에서는 동일 type·operator·holder scope와 자연 식별 코드를 가진 문서·구조화 API 요건을
하나로 병합하고 모든 출처를 Evidence로 보존한다. 동일 Evidence는 자연키로 중복 제거한다.
상위 `requires_review`는 문서 보류뿐 아니라 `needs_review` 요건 또는 미해결 후보가 있어도 활성화한다.

구형 XLS는 LibreOffice Calc로 XLSX 변환 후 파싱하고 ZIP은 안전한 크기·개수 한도 안에서 지원
문서를 전개한다. 텍스트가 없는 PDF에는 아직 OCR을 적용하지 않으며 `pdf_text_unavailable` 또는
`text_unavailable_deferred`로 보류하여 `requires_review` 대상에 포함한다.

첨부파일 처리가 아직 `pending` 또는 `processing`이면 참가자격 추출을 기다린다. 재시도 한도를
소진했거나 미지원 형식인 파일이 있으면 성공적으로 파싱된 문서와 API 제한정보로 추출을 계속하고
결과를 `partial`, `requires_review=true`로 저장한다. 결과에는 전체·성공·누락 문서 수와 누락
파일명 및 오류 사유가 포함된다. 첨부파일이 없고 API 제한정보만 있으면 `api_only`, 모든 문서가
파싱됐으면 `complete`다. 이후 파서 개선으로 누락 문서가 파싱되면 입력 fingerprint가 변경되어
같은 공고도 다시 추출된다.

첨부파일 저장·파싱·추출의 회당 처리량과 동시 실행 한도도 배포 목록에서 확인한다.
추출은 파싱 완료 또는 미지원 확정 문서만 사용하며, 미지원 문서가 있으면 결과를 `partial`로
표시해 Runtime Assessment가 전체 충족을 확정하지 않도록 한다.

참가자격 추출 큐는 용역 공고를 다른 업무유형보다 먼저 선택하고, 용역 내부와 나머지 업무유형
내부에서는 공고게시시각이 최신인 순서로 처리한다. 처리 가능한 용역 공고가 남아 있는 동안에는
물품·공사·외자 공고가 선택되지 않으며, 용역 공고가 없을 때 남은 유형의 최신 공고를 처리한다.

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

## 구현을 수정할 때

입찰공고 Task는 `ingestion_tasks.py`, `enrichment_tasks.py`, `document_tasks.py`,
`retention_tasks.py`에 구분한다. 참가요건의 `tasks.py`는 실행 경계,
`extraction.py`는 모델 실행, `validation.py`와 `repair/`는 순수 검증·보정,
`expression.py`는 조건식 구성을 담당한다.

추출은 공고의 요건을 보존하는 작업이며 특정 업체의 적격 여부를 확정하지 않는다.
추출 버전·입력 fingerprint·인용 계약은 폴더 재배치로 변경하지 않는다.
회귀 테스트는 `pipelines/tests/unit/domains/public_procurement/bid_eligibility/`에서 찾는다.
실행·수동 재시도는 [Prefect](../prefect.md), 의미 기준은
[Platform 조달 집계](../../platform/domains/public_procurement/contract_aggregation.md)를 참고한다.
과거 데이터 결손의 시점별 점검은 [수집 점검 기록](../../verification/procurement_collection_2026_10_12.md)에 보존한다.
