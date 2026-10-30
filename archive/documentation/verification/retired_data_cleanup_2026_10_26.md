# 이전 조달 데이터와 규격서 실험 정리 — 2026-10-26

사용자 요청에 따라 규격서 실험 산출물·미사용 goods Draft와 예전 공고·계약 데이터를 정리했다.
**운영 Data DB는 91.85GiB에서 76.29MiB로 감소했다.**
법령·게시 Ontology·승인 이력·현재 Runtime bundle은 보존했다.

## 결과

| 대상 | 실제 결과 |
|---|---|
| Data DB | 일반 table 36개 비움, materialized view 1개를 빈 기반 데이터로 갱신 |
| 공유 ingestion 이력 | 명시한 조달 pipeline ID 21개의 실행 32,991건·checkpoint 13건·operation progress 1,093건·backfill gap 4건 제거 |
| 남은 실행 | 법령 pipeline 2개의 실행 19건·checkpoint 2건 유지 |
| 미사용 Draft | `goods 0.1.0` Draft 1개와 전용 개념·항목·Draft audit 정리 |
| Ontology 이력 | 게시 `teoria 0.1.4` 1개·deprecated version 11개·Binding 검토 589건 유지 |
| 파일 | 생성 산출물 273개·39,743,439 bytes 삭제; 원본 121개와 평가 metadata 1개는 원래 경로·checksum 유지 |
| 서비스 | Admin·Runtime·gateway·인증 조회·법령 검색 HTTP 200 |
| 운영 설정 | 규격서 Prefect pool을 원래 unpaused로 복원; 법령·metadata·은퇴 pool의 pause 상태 보존 |

법령·전용 raw 자료·migration 기록·Ontology·Binding·물품 프로파일·진단 이력 등
**보호 dataset 37개의 행수와 내용 SHA-256이 전후 동일**하다.
법령 실행 이력까지 포함한 38개 보호 범위는 삭제 transaction 안에서도 검사했다.
법령 검색은 기준일을 `2026-10-26`으로 고정해 응답이 동일함을 확인했다.
Runtime version과 bundle 응답도 동일했다.

현재 규격서 실행·워크플로·정규화 프로파일 데이터는 비어 있다.
새 서버 문서의 AI 추출, Ontology 게시와 새 Runtime bundle 전환은 이번 정리에 포함하지 않았다.

## 복구 자료

- DB 4개 전체 dump와 SHA256SUMS: `backups/teoria/20261026T142810Z/`.
- 목록·guard SQL·별도 Application dump·실험 파일 archive·검증 로그:
  `backups/teoria/retired_data_cleanup_20261026T143141Z/`.
- 저장 위치는 같은 서버의 로컬 디스크다. 원격 사본을 만든 것은 아니다.
- 복구 디렉터리는 owner-only이며 credential·원문 응답·개인정보를 이 문서에 포함하지 않는다.

Data DB dump는 9,907,077,294 bytes다. Application·Prefect·OpenMetadata dump도 함께 보존한다.
별도 `teoria_app_before.dump`와 실험 파일 395개를 담은 `experiment_artifacts.tar.gz`도 있다.
각 artifact member의 SHA-256을 원본과 대조한 뒤 생성 파일만 삭제했다.
작업 디렉터리의 `cleanup_result.json`, `protected_state_comparison.json`, `SHA256SUMS`에 결과를 기록했다.

## 실제 실행과 검증

1. 관계별 크기·table 유형·외래키와 실행 상태를 조사했다. 원본 응답 connector는
   `pps_bid_notice_api`, `pps_contract_api`, `pps_industry_api` 3개임을 확인했다.
2. 미사용 goods Draft에 게시 artifact·검토·Binding·프로파일·파생 version 참조가 없음을 확인했다.
3. DB 4개의 dump 생성 성공·archive 목록·전체 checksum을 검증했다.
4. Application dump를 별도 PostgreSQL에 실제 복원하고 Draft 삭제 SQL을 시험했다.
   복원본의 보호 Application dataset 27개의 행수·내용 hash가 원본과 동일했다.
5. Data DB 전체와 인덱스의 복원을 시작했으나, 사용자와 검증 필요성을 확인한 뒤 중단했다.
   **Data DB 전체 복원 완료나 모든 인덱스 복원 성공으로 기록하지 않는다.**
6. 대체 검증으로 `pg_restore --no-owner --no-privileges --file=/dev/null`을 실행해
   Data archive 전체를 읽었다. 압축·archive 오류 없이 exit 0이었다.
7. 실제 운영 Data/Application DB에서 삭제 SQL을 실행하고 보호 데이터 hash·빈 대상 조건을
   확인한 뒤 **ROLLBACK**했다. 초기 시험에서 materialized view를 일반 table과 구분해야 함을
   발견했고, 일반 table은 `TRUNCATE ... RESTRICT`, view는 빈 기반 데이터로 `REFRESH`하도록 수정했다.
8. 동일한 guard SQL을 실제 적용하고 COMMIT했다. 전체 대상 37개가 비었고 보존 대상은 같았다.
9. 서비스와 법령 응답·Runtime bundle을 확인하고 pause 상태를 복원했다. 임시 복원 컨테이너는 제거했다.

실행한 파일은 `cleanup_retired_data_guarded.sql`, `cleanup_unused_draft_guarded.sql`이다.
목록 밖 pipeline이나 활성 실행, Draft의 신규 참조, 보호 데이터 변경, 비어 있지 않은 정리 대상을
발견하면 exception으로 transaction을 rollback한다. `CASCADE`와 schema 삭제는 사용하지 않았다.
Schema·적용 migration·view·role과 현재 게시 artifact의 본문·version·checksum은 유지했다.
Runtime 캐시에는 정리할 항목이 없었다. OpenMetadata entity와 모델 인증 volume도 변경하지 않았다.

삭제 후 규격서 평가·서버 조회 관련 검사는 123 passed, 1 opt-in integration skipped였다.
문서 링크 검사와 `git diff --check`도 통과했다.
대용량 Data DB 전체 복원은 이번 정리의 필수 검증으로 삼지 않았으며,
향후 환경 전체의 재해복구 훈련과는 구분한다.
