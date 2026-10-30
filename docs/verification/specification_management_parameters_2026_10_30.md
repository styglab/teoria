# 규격서 표준관리 실행 파라미터·운영 반영 — 2026-10-30

기존 `specification-standard-management` 배포에 기본·선택·고급 입력과 기본값을 등록했다.
새 Flow나 정기 공고 수집 배포는 추가하지 않았다. 보관 공고 DB의 읽기와 이번 실행의 첨부 확보만 수행한다.

## 입력과 처리

- 기본: 세부품명 10자리 코드, 목표 규격서 파일 수 30.
- 선정: 최신 게시일순, 최근 365일, 공고 확인 상한 300.
- 관리: 초기 구축·증분 갱신·고정 사전 품질 평가. 갱신·평가에는 기준 사전 URI·sha256 필요.
- 품질: 기본 평가용 5개, 구축용 최소 5개, 보류 표현 허용 수 0.
- 실행: 문서 동시 실행 2, 모델 동시 실행 4, 호출 제한 180초. 실행 ID·저장 위치는 자동 결정 가능.

목표는 공고 수가 아닌 중복 제거된 확보 파일 수다. 형식 서명까지 검사한 파일명 기반 후보이며
실제 본문의 규격서 여부나 추출 품질 전체를 확보 시점에 보장하지 않는다.
규격·시방·사양·specification 명칭의 지원 형식만 자동 선정한다. ZIP·이름 불명확 문서는 자동 선정하지 않는다.
다중 분류 공고는 첨부별 분류를 임의로 결정하지 않고 제외한다.
파싱·추출 완료 수는 따로 기록하고, 평가 자료가 부족하면 자동 반영을 보류한다.
같은 공고의 첨부는 구축용·평가용으로 분리하지 않는다. 품질 평가는 사람의 정답 평가를 대체하지 않는다.

## 검증 결과

- 백엔드 전체: **745 passed, 79 skipped**.
- 문서 테스트: **9 passed**.
- Compose config·배포 문서 일치 검사·공백 검사 통과.
- 새 입력 기본값·범위 검사, 누락/실패/중복 제외, 목표 미달, 선정 목록 고정,
  혼합 분류 제외, 공고별 평가 격리와 평가 부족 시 반영 보류를 테스트했다.
- 실제 Worker 권한으로 공고 후보 SELECT, 과거 추출 조회와 문맥 캐시 SQL을 확인했다.
- 실제 Admin 인증으로 snapshot·related-context 응답, 6개 승인 매핑의 명시적 분류 범위를 확인했다.
- Prefect 배포 ID `be281dd8-da46-4057-9cc2-fbe26494accc`를 유지하고 6개 입력 필드와 기본값을 확인했다.
- Admin healthy, 새 Worker ONLINE·최근 heartbeat 확인. 교체 전 활성 실행 0개.
- 두 역할의 설치 Python 파일 **111개**가 소스와 일치하며 기존 volume·기타 환경 설정을 유지했다.
- 실제 규격서 대량 처리·Codex 호출은 시작하지 않았다. 실제 모델의 추출·의미 품질 검증 결과로 간주하지 않는다.

## 운영 변경

Application DB `022_goods_mapping_scope.sql`, Data DB `102_specification_source_lookup.sql`만 신규 적용했다.
기존 적용 SQL은 수정하지 않았다. 이전 이미지와 backup을 보존했다.

- teoria-admin-api-1: `teoria-platform-authoring:specification-parameters-20261030-v1`, `sha256:b27d005ff487c15b7ea58a696df3effd0958f9cdca4eb9208b7392e901b204ab`.
- teoria-prefect-worker-1: `teoria-pipelines:specification-parameters-20261030-v1`, `sha256:ab3720a66371fbb880e1f474725c375135598cc5398b4cf843f19a4a2695c674`.

백업:

- `backups/specification_parameters_20261030_005738/application_goods.dump` (528072 bytes), SHA256 `074048bbdd14f508438cf9e645f4290a9ad260bd100757054102edfa7116d514`.
- `backups/specification_parameters_20261030_005738/specification_runs.dump` (14022 bytes), SHA256 `0306d140d024d35965479bc72c49096333bcc8cc894f9a4bbfb3218565fba258`.

로컬 운영 증거는 `.artifacts/specification_parameters_20261030/`의 `deployment.json`, `smoke.json`,
`backups.json`에 보관한다. 별도 환경에서는 이 로컬 파일이 없을 수 있다.

사용 방법은 [파이프라인 실행 입력](../procurement_specification_processing/pipeline.md#prefect-실행-입력과-기본값)을 따른다.
