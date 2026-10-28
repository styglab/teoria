# 물품 공고 근거 스키마·격리 복원 검증 — 2026-10-28

새 migration `101_goods_notice_evidence.sql`과 물품 전용 복원 도구를 추가했다.
운영 Data DB의 복사본을 격리 PostgreSQL 17에 복원하고 물품 공고·첨부 근거를 실제 적재해
COMMIT했다. **운영 DB에는 migration 101이나 물품 데이터를 적용하지 않았다.**

이 문서는 격리 검증 시점의 기록이다. 이후의 실제 운영 적용은
[물품 공고 운영 DB 복원](goods_notice_production_restore_2026_10_28.md)에 기록했다.

## 저장 책임

소유 기능은 `backend/src/teoria/features/goods_notice_collection/`, 프로세스 진입점은
`backend/src/teoria/entrypoints/goods_notice_restore.py`다.
계약·실행 명령과 조회 예시는 [Data DB 안내](../pipelines/database.md)를 따른다.

| 새 테이블 | 책임 |
|---|---|
| `goods_notice_import_batches` | 원본/선별 백업 해시, 백업 식별자, 건수·기록 시각 |
| `goods_notice_versions` | 공고번호·차수·원문 해시별 불변 JSON 버전 |
| `goods_notice_observations` | 백업 복원 또는 실제 수집 실행의 관측 근거 |
| `goods_notice_attachment_refs` | 원문 버전·슬롯별 URL·파일명 |

네 테이블은 UPDATE/DELETE를 거절한다. 버전의 물품 부모·원문 식별자·해시 형식을 검사하고
FK로 버전·관측·첨부·배치를 연결한다. 첨부 교체·삭제가 과거 해시 버전의 참조를 지우지 않는다.
파일명으로 병합하거나 URL query를 제거하지 않았다.

백업 복원은 `backup_import`로 기록하고 실제 API 실행·수집 시각은 NULL로 둔다.
향후 `api_fetch`에는 실제 ingestion 실행과 수집 시각이 모두 필요하다.
현재 공고 본문과 불변 버전 본문은 각각 저장하며 동일 해시의 재관측은 버전을 재사용한다.

## 실제 복원

입력은 [선별·검증한 물품 COPY 파일](goods_notice_backup_inventory_2026_10_28.md)이다.
압축 파일 SHA-256과 manifest를 대조하고 원문 해시·공고 식별자를 전수 검사했다.
운영 Data DB의 새 백업 **8,101,799 bytes**를 격리 DB에 복원해 기반으로 사용했다.

- PostgreSQL 17, CPU 2개·메모리 3 GiB 상한, 전용 일회성 볼륨.
- `network=none`, 공개 포트 없이 비공개 디렉터리 아래 UNIX socket으로 연결.
- 대상 DB 이름·빈 공고/투영/근거 테이블·기존 트리거 구성을 검사.
- gzip·JSON은 제한된 thread, COPY·SQL은 native async로 실행.
- staging·공고·버전·관측·첨부·투영 적재를 하나의 transaction에서 실행.
- 기존 공고 트리거 세 개만 transaction 안에서 잠시 중지하고, FK는 유지.
  최신 차수·계보 요약을 원래 정렬 규칙으로 재구성하고 트리거를 복구.
- `enrichment_checked_at`·`enrichment_claimed_at`을 NULL로 초기화.
  공고 차수·원문·해시·기존 계보 참조·취소/변경 공고는 보존.
- Provider API·첨부 다운로드·규격서 Flow·checkpoint 호출 없음.

| 격리 DB 결과 | 건수 |
|---|---:|
| 물품 공고·불변 원문 버전·백업 관측 | **각 758,443** |
| 첨부 참조 | **1,848,691** |
| 공고번호·최신 차수 투영 | **673,691** |
| 계보 요약의 공고 건수 합계 | **758,443** |

비물품 행, 남은 enrichment 상태, 현재 본문/버전 불일치, 첨부 URL/파일명 불일치,
가상 API 수집 시각, 최신 차수 불일치, 계보 건수 불일치는 모두 **0건**이다.
DB에 저장된 원문 **758,443건을 다시 읽어 canonical JSON SHA-256을 전수 계산했고
불일치는 0건**이다. 격리 DB의 실제 크기는 **6,976,894,643 bytes**(약 6.50 GiB)였다.
첨부 참조는 `ntceSpecDocUrl1`~`10`·`ntceSpecFileNm1`~`10` 범위다.
그 밖의 공고 상세·표준 문서 URL은 기존 공고 열에 보존했다.

## 보호·회귀 검사

- 복원 전후 기존 **20개 테이블의 행 수·내용 SHA-256 일치**.
  migration 101 적용 뒤의 복원 전 상태를 기준으로 비교했다.
  법령·규격서·ingestion·MLops 데이터가 포함된다.
- 규격서 실행 7건·문서 16건·산출물 68건 등 기존 데이터 보존.
- 빈 별도 DB에 migration **1~101 전체 적용 성공**.
- 복원 보호·이력 테스트 **21 passed**: 해시·건수·대상 DB·물품 조건 검사,
  원문 뒤 SQL 거절, 덮어쓰기 거절, 재실행 중복 방지, 후반 실패 시 전체 rollback과
  트리거 복구, 이력 수정/삭제 거절, 과거 첨부 유지와 관측·FK 제약.
- 전체 백엔드 **690 passed, 79 skipped**. 별도 DB 검사는 일반 실행에서 skip하고
  이 기능의 실제 DB 검사는 위의 별도 21개로 확인했다.
- Compose config·변경 코드 Ruff 검사 통과.
- 문서 링크 568개·문서 120개 검사에서 오류 0건.
- 실제 전체 파일의 CLI 재실행에서 `already_imported=true`를 반환해 중복 적재하지 않음을 확인했다.

대량 읽기 검증에는 세션의 `work_mem=256MB`, `max_parallel_workers_per_gather=0`을 사용했다.
초기 병렬 본문 비교의 불일치 0건을 확인했고, 부하 조정을 위해 첨부 비교를 중단한 뒤
새 검증 세션에서 재실행했다. 초기 성공 결과·쿼리 계획·조정 기록을 후속 결과와 함께 보존한다.
이 조정은 복원 데이터나 운영 설정을 변경하지 않았다.

## 운영 상태와 보관

`backups/teoria/goods_notice_restore_20261028T025004Z/`에 운영 백업, manifest,
보호 테이블 전후 해시, 복원·검증·회귀 로그와 스크립트를 보관한다.
원본 백업과 선별 파일은 변경하지 않았고 Provider 원문·실제 첨부 URL을 Git에 옮기지 않았다.
복구 디렉터리는 0700, 파일은 0600이며 `SHA256SUMS`로 보관 파일을 검증했다.
검사 후 격리 컨테이너·전용 볼륨·로컬 socket을 제거했다. 복원된 임시 DB를 계속 운영하지 않는다.

운영 읽기 전용 확인 결과는 **공고 0건, migration 100**, 새 근거 테이블 없음,
규격서 실행 7건·문서 16건이다. Data/App 컨테이너 통합이나 운영 이미지 재배포는 하지 않았다.
후속 작업은 최신 운영 백업 확보 후 migration 101과 물품 복원을 운영에 적용하는 것이다.

백업에 존재하는 데이터의 복원이며 수집 완전성·URL 다운로드 가능 여부·파일 내용·규격서 여부·
현행 Provider 호환성의 검증은 별도다. 기존 계보를 새로 추론하지 않았으며 일부 이전 공고 참조는
물품 이외 업무라 복원 범위 밖일 수 있다. 구형 첨부 처리·참가자격 판단·전체 조달 수집은 비활성이다.
