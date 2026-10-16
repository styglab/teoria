# 입찰공고 현재 상태 기준

입찰공고의 현재 상태는 공고명이나 자유문 텍스트로 추론하지 않고 구조화된 원천과
조달 사건을 기준으로 산정한다.

## 상태 필드

- `notice_status`: 기존 공고 계보 생명주기인 `active`, `cancelled`, `superseded`를
  유지한다.
- `current_status`: 화면에서 사용할 현재 조달 상태다. 값은 `scheduled`, `open`,
  `closed`, `awarded`, `contracted`, `failed`, `cancelled`다.
- `status_source`: 상태 판정에 사용한 원천 Operation 또는 정규 relation이다.
- `status_confirmed_at`: 원천 상태를 확인한 시각이다. 일정으로 산정하는 일반
  예정·진행·마감은 원천 확인시각이 없을 수 있다.

호환성을 위해 기존 `notice_status`의 의미를 변경하지 않는다. 새 화면은
`current_status`를 우선 사용한다.

## 우선순위와 근거

1. `cancelled`: 나라장터 공고종류가 `취소공고`인 경우다. 취소 사유는 원천
   `chgNtceRsn`, 취소 시각은 원천 변경시각 또는 취소공고 게시시각을 사용한다.
2. `contracted`: 해당 공고에 연결된 계약 원천이 존재하는 경우다.
3. `awarded`: 해당 공고에 연결된 최종낙찰 원천이 존재하는 경우다.
4. `failed`: 나라장터 낙찰정보서비스의 `개찰결과 유찰 목록 조회`에서
   `opengRsltDivNm=유찰`로 확인된 경우다. `nobidRsn`을 유찰 사유로 사용한다.
5. `scheduled`, `open`, `closed`: 위 사건이 없을 때 구조화된 게시·마감시각으로
   산정한다. 유찰 원천이 확인되지 않은 마감 공고는 `closed`를 유지한다.

`search_procurement_activity`의 `stage`와 `stage_counts`도 유찰 `failed`와 취소
`cancelled`를 별도로 센다. 모든 stage의 합은 `stage_counts.all` 및 필터 전 그룹 수와
일치해야 한다.

## 정정·취소 계보

- `original_notice_id`: 계보의 최초 공고
- `current_notice_id`: 계보의 최신 공고
- `revision_number`: 게시순서를 0부터 센 정정 순번
- `is_latest_revision`: 현재 레코드가 계보의 최신 공고인지 여부

계보는 나라장터의 이전 공고번호 원천 필드로 연결하며 제목 유사성은 사용하지 않는다.
