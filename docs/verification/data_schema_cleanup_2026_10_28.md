# Data DB의 이전 조달 스키마 객체 정리 — 2026-10-28

이 문서는 migration 99 적용 시점의 기록이다. 후속
[ingestion 정리](ingestion_cleanup_2026_10_28.md)로 현재 Data DB는 테이블 23개·뷰 2개다.

사용자의 물품 공고 복원 전 정리 요청에 따라 운영 `teoria_data`에
`099_remove_retired_procurement_storage.sql`을 실제 적용하고 COMMIT했다.
정리 대상은 모두 비어 있는 이전 조달 전용 객체다. Application DB·OpenMetadata DB·
Prefect DB와 게시 artifact는 변경하지 않았다.

## 실제 결과

| 구분 | 결과 |
|---|---:|
| 빈 이전 조달 테이블 | 27개 삭제 |
| 이전 Runtime·상태 조회 뷰 | 13개 삭제 |
| 조달 엔티티 검색 물리화 뷰 | 1개 삭제 |
| 계약 원장·검색 인덱스 갱신 함수 | 2개 삭제 |
| 남은 Data DB 관계 | 테이블 24개·법령 뷰 2개 |
| 보존 데이터 검증 | 24개 테이블의 기존 행 수·내용 SHA-256 일치 |

스키마 전체를 삭제하지 않았다. `public_procurement` 안에 활성 규격서 데이터와
복원할 물품 공고 기반이 함께 있으며, `ingestion`도 법령과 공통 수집 기반이 사용한다.
삭제 전 데이터가 이미 비어 있었으므로 이번 작업의 목적은 대용량 확보보다 구조 정리다.

삭제한 테이블은 계약·공급업체·낙찰·개찰·업종·참가자격 판단·구형 첨부 처리와
전용 큐·상태 저장소다. 정확한 목록은 새 migration과 비공개 복구 디렉터리의 `plan.json`에 있다.
`CASCADE`나 객체 이름 패턴에 따른 포괄 삭제를 사용하지 않았다.

## 보존 범위

- 물품 공고 복원 기반: `bid_notices`, `bid_notice_latest_versions`, `bid_notice_lineage_summaries`.
- 공고의 원본 payload·차수·계보·최신 차수 갱신 함수와 trigger, 기존 공고 열과 인덱스.
- 규격서 실행·문서별 결과·산출물 참조·표준관리 workflow의 네 테이블.
- `legal_information` 전체와 전용 raw payload·관측 이력.
- 공통 pipeline 실행·checkpoint·operation progress·backfill gap·원본 보존 기반과 migration 이력.
- 활성 `mlops_demo` 고객·활동 데이터.

기존 migration 1~98은 수정하지 않았으며 새 99만 추가했다.
보존 비교에서는 새 migration 이력 행 한 개를 제외하고 기존 migration 행들을 비교했다.
다른 보존 테이블은 전체 행을 비교했다. 데이터 본문은 로그에 출력하지 않고
행 JSON의 SHA-256을 정렬·집계한 내용 hash와 행 수만 기록했다.

구형 `bid_notice_documents`는 비어 있는 다운로드·파싱 상태 저장소라 제거했다.
공고 첨부 URL을 담는 `bid_notices.source_payload`와 원래 백업은 유지했다.
물품 공고 복원·신규 첨부 목록 설계·새 수집 배포는 아직 실행하지 않았다.

활성 capability artifact에는 삭제 대상 SQL 조회가 없음을 확인했다.
게시 Binding에 남아 있는 이전 OpenMetadata 자산 참조와 검토·게시 이력은 변경하지 않았다.
이는 역사적 metadata 참조를 보존한다는 뜻이며 삭제된 물리 테이블이 계속 존재한다는 뜻은 아니다.
이번 작업에서 OpenMetadata entity를 직접 삭제하거나 published Binding을 수정하지 않았다.

## 적용 전 검증과 보호

1. 실제 catalog·행 수·외래키·뷰 의존성·활성 코드·artifact를 조사해 대상을 한정했다.
2. 최신 Data DB 전체 dump를 생성하고 SHA-256·archive 목록을 확인했다.
3. 네트워크가 없는 별도 PostgreSQL 17의 tmpfs에 그 dump를 실제 복원했다.
4. 격리 DB에서 삭제·보존, 데이터가 있는 대상의 거절, 외부 의존성의 거절,
   stale 물리화 뷰의 데이터 보호, 재실행을 검증했다.
   공고 보존 검사에는 정리 후 새 차수를 넣어 최신 차수 trigger가 동작하는 검사도 포함한다.
5. 빈 별도 DB에도 migration 1~99 전체를 적용했다. 기존 migration의 고정 DB grant에 필요한
   테스트 DB와 runtime·pipeline·metadata 역할을 격리 cluster에 준비했다.
6. 실제 운영 DB에서 동일 SQL과 보존 검사를 실행하고 ROLLBACK했다.
7. 같은 SQL을 적용하면서 보존 대상은 SHARE lock, 삭제 대상은 ACCESS EXCLUSIVE lock으로
   확인·삭제 사이의 변경을 막았다. 빈 테이블·물리화 뷰와 의존성 검사를 통과한 뒤 COMMIT했다.

새 migration은 데이터가 한 행이라도 있으면 예외를 발생시키며, 외부 의존성이 있으면
`RESTRICT`로 실패한다. 운영 실행 wrapper는 기존 보존 데이터의 hash가 달라도 전체를
rollback하며 migration 이력 등록까지 같은 transaction에서 수행한다.

## 검증 결과

- 백엔드: **688 passed, 50 skipped**. Opt-in DB 검사 등 미설정 환경 검사는 skip으로 남겼다.
- 실제 복원한 격리 DB에서 새 보호 검사: **5 passed**.
- 빈 DB: **migration 99개 전체 적용 성공**.
- Compose config, 추가 테스트의 Ruff 검사·형식 검사, 문서 링크·diff whitespace 검사 통과.
  기존 검증 문서 네 개의 누락된 index 연결도 보완했다.
- 실제 정리 후 남은 관계가 사전 목록에서 삭제 대상을 뺀 집합과 정확히 일치했다.
- Admin·Runtime health: 전후 HTTP 200.
- 기준일 `2026-10-28`로 고정한 법령 검색: 전후 HTTP 200과 응답 hash 일치.
- 활성 Runtime artifact: `2026.10.27.3`, pointer·checksum 전후 동일.

서비스 재시작이나 schema 삭제로 유지보수 범위를 넓히지 않았다.

## 백업과 복구 근거

최신 복구 디렉터리는 `backups/teoria/data_schema_cleanup_20261028T011516Z/`다.
`teoria_data_before.dump`는 **8,284,705 bytes**이며 SHA-256은
`7a4929bcda36fa738b8a44016bf82435887bb679550fc93d30663d772f92c070`이다.
기존 2026-10-26 대용량 전체 백업은 그대로 유지했다.

디렉터리에는 목록·원본 migration·보존 manifest·rollback/apply SQL·실제 복원과 테스트 로그·
보존 hash·전후 서비스 검사·최종 `result.json`을 남겼다. 원본 데이터와 복구 자료는
owner-only 디렉터리에 두고 Git에 추가하지 않았다.
격리 검증 컨테이너와 tmpfs DB는 검증 후 제거했다.

복구가 필요하면 먼저 이 dump를 격리 DB에 복원한 뒤 필요한 삭제 객체를 선택적으로 복구한다.
현재 활성 데이터가 생긴 운영 DB에 과거 전체 dump를 그대로 덮어쓰는 방식은 사용하지 않는다.
