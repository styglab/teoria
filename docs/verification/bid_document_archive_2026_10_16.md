# 첨부문서·입찰요건 기능 보류 검증

2026-10-16 사용자 요청에 따라 첨부파일 다운로드·파싱·문서 요건 추출과
업체별 참가자격 판단을 현재 제품에서 제거했다. 보관 범위와 재개 기준은
[archive](../../archive/bid_document_processing/README.md)에 있다.

## 변경과 배포

- 전용 코드·Registry·Skill·테스트와 과거 문서는 원래 경로를 유지해 archive에 보관했다.
  공유하던 파일은 변경 전 사본을 보관하고 활성 실행 연결을 제거했다.
- 문서 다운로드·파싱·요건 추출·보존기간 삭제 Prefect Deployment 4개를 운영에서 제거했다.
  AI pool은 중지하고 AI Worker 컨테이너와 기본 배포 정의를 제거했다.
- Runtime bundle `2026.10.16.90`을 새로 생성·검증·활성화하고 API와 Worker를 배포했다.
  checksum은 `sha256:2307532eb8b64ea0c2c37df1c4235535cd00ddd9f3fe150c068f5ffdd4333c1b`다.
  이전 게시본과 Published Ontology·승인 이력·Application DB는 변경하지 않았다.
  유지하는 Capability Binding은 기존 계약과 동일함을 검사한 배포 snapshot이며,
  승인된 계약 target과 Binding identity를 보존했다.
- migration `088`은 집계 갱신 큐의 요청 버전을 추가한다. 같은 분야의 동시 갱신은
  transaction advisory lock으로 제한하고 처리한 버전만 삭제한다.
- migration `089`는 공고 조회의 문서 추출 테이블 연결을 제거한다.
  종속 view용 NULL 호환 컬럼은 유지하며 활성 Runtime 응답에는 포함하지 않는다.
- 조달 수집 날짜·Backfill·날짜 유효성 검사는 한국시간 달력을 사용한다.
  저장하는 감사시각은 UTC를 유지한다.

## 검증 결과

- Pipelines와 별도 PostgreSQL 통합 검증: 140개 통과.
  갱신 중 새 요청, 동시 Worker, 갱신 실패 시 요청 보존과 한국시간 자정 경계를 검증했다.
- Platform: 306개 통과, 환경 조건이 필요한 24개 건너뜀.
- MCP: 11개 통과.
- Connector·Pipeline·Platform 교차 계약, Registry, 새 Ontology 분류 manifest,
  Compose config와 Python 미정의 이름 검사를 통과했다.
- 운영 공고 수집 Run `5a66fd86-1ed8-4c6c-acf6-70a16d588af2`: `COMPLETED`.
  원본 23건·정규 공고 23건·문서 0건이며 checkpoint는 `2026-10-09`로 갱신됐다.
- 기존 첨부파일은 296,812건으로 수집 전후 동일하며 마지막 수정시각도 동일했다.
- Runtime discovery는 public Capability 30개를 제공한다. 제거한 요건·판정 Capability
  5개와 관리자 문서 요건·규칙 API 3개는 404를 반환한다. 일반 공고 조회는 200이며
  추출 결과 필드가 없다.

이미 적용된 migration, 기존 DB의 문서·추출 결과, 외부 Object Storage 객체와 인증
volume은 삭제하지 않았다. API가 제공하는 공고·면허·지역 정보 수집은 유지한다.
