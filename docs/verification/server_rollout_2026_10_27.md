# 서버 규격서 2건 운영 반영 검증

> 과거 작업의 검증 기록이다. 이 문서의 물품 모델·조회 기능·관찰 데이터는 후속
> [초기화](specification_goods_reset_2026_10_27.md)로 운영에서 삭제했다. 이전 산출물은 백업에 보관한다.

Compose 운영에서 두 규격서를 새로 추출하고 승인한 서버·메모리 프로파일로 적용했다.
Runtime bundle `2026.10.27.1`을 활성화하고 인증된 실제 HTTP 검색·비교·근거 조회를 확인했다.
두 문서의 전체 처리 상태는 `partial`이며, 모든 추출·표준 후보의 승인을 완료한 것은 아니다.

## 입력과 실행 경계

기존에 확보한 원본 중 서버 본체가 확인되는 두 문서를 선택했다. 두 원본은 과거 평가에
노출된 development 문서이며 신규 무작위 표본이나 독립 검증 문서로 집계하지 않는다.
분류 근거는 보존된 과거 평가의 `classification_metadata_snapshot`에서 복원했으며,
원본과 분류 metadata의 SHA-256을 실행 입력에서 검증했다.

| 문서 | 공고 번호 | 원문에서 확인한 메모리 조건 |
|---|---|---|
| `server_fresh_17` | `R26BK01781846` | `2 x 16GB DDR5-4800 RDIMM 동등 이상`; 모듈당 값과 시스템 합계를 구분 |
| `server_fresh_18` | `R26BK01771789` | `DDR5 메모리 총 512GB 이상`; GPU별 141GB와 구분 |

같은 분류번호의 워크스테이션을 컴퓨터 서버와 동일시하지 않았다. 전체 메모리 값이
원문에 명시되지 않은 문서에서 모듈 용량과 수량을 곱해 관찰을 생성하지 않는다.

운영 `procurement-standard-workflow`는 Prefect·Python 코드와 Codex JSON 추론을 실행한다.
Skill을 읽거나 호출하는 단계는 없다. 개발자의 추출 평가 절차와 운영 Flow를 구분한다.

## 추출 평가의 한계

`server_rollout_review_20261027_01`은 과거 사례를 유지한 calibration replay로 실행했다.
baseline에서 실패 문서 0, partial 문서 2, 원문 근거 없는 엔티티·관계·요구조건 0을 관찰했다.
고정 사례는 entity 2/6, requirement 0/3이었으며 추출 명칭과 기존 alias 라벨의 차이가 있다.
이 점수를 요구조건의 실제 누락률이나 전체 정확도로 해석하지 않는다.

finish의 Parser fingerprint 검사에서 별도로 변경되던 파서 소스의 차이를 검출했다.
파서 버전과 의존성 해시는 같고 소스 해시가 달랐으므로 평가 결과 확정을 중단했다.
상태는 `aborted`, cleanup은 `complete`이며 임시 산출물 11,209,250 bytes를 삭제했다.
다른 작업의 Parser 수정은 변경하거나 되돌리지 않았다. 평가 개선·회귀 통과를 주장하지 않는다.

운영 검증은 별도 새 추출을 실행하며 이전 평가의 추출 checkpoint를 사용하지 않는다.
고정 Worker 이미지의 Parser 0.9.15 소스 해시는 다음과 같다.

```text
51ec296859d90dd0162045109e24e8914a2295377aad23a67c89d2775d27e40c
```

## 적용한 기반

- `computer_server` Ontology 0.1.0: 객체 2개, 속성 4개, 구성 관계 1개를 인증된 Admin API로
  작성하고 validation의 진단 0건과 binding 호환성을 확인한 뒤 submit·approve·publish했다.
- `server_memory` 기본 프로파일: revision `48bb401e-90c6-4840-8c85-5ac3294dbcc8`을
  검토·승인하고 checksum이 있는 고정 패키지로 내보냈다.
- 변경 주체는 인증 설정의 principal `system:admin`이다. 평가 라벨을 사람이 검토했다고 기록하지 않았다.
- Data migration `093_specification_query_observations.sql` 적용.
- Registry release `2026.10.27.1` 생성 및 Capability Binding 5건 승인.
- Admin·규격서 Worker·Runtime을 `server-rollout-20261027` 이미지로 갱신하고,
  실제 검증 후 기본 Compose의 `latest` 태그도 같은 이미지로 승격했다.
- 운영 workflow ID: `server_rollout_20261027_01`.

## 후보 검토와 운영 관찰

상위 표준관리 Flow는 기존 개념 연결 2건, 신규 개념 제안 73건, 보류 67건을 생성한 뒤
`awaiting_approval`로 종료했다. 교육·증명서·소프트웨어 등을 포함하는 신규 제안은
이번 메모리 조회 범위의 승인이 아니므로 Draft로 유지했다.
제안 Ontology version ID는 `5df87ade-f861-4402-9c0d-7751b8364724`다.
상위 Flow가 모든 후보 승인과 후속 단계까지 완료됐다고 표시하지 않는다.

서버·메모리 조회에 필요한 연결은 별도로 원문 대조하여 프로파일 1.0.1로 작성·승인했다.
revision은 `0f77e75d-4cde-4cb4-b28d-5b2ebdf7640a`이며, 기존의 승인된 0.1.0 Ontology를 사용한다.
`Computation Node`, `제조사 완제품 서버`, `Memory: DDR5 총 512GB 이상`의 실제 명칭과
`module_capacity` 속성명을 추가했다. 수치·문서 ID를 Business Ontology 개념으로 만들지 않았다.

`server_memory_20261027_01` 문서 처리 Flow는 방금 생성한 운영 추출의 checksum과 원본을 검증한 뒤
승인 패키지를 적용했다. 평가용 임시 추출이나 과거 실험 checkpoint는 사용하지 않았다.
원본 신규 추출 후 고정 표준 적용에 같은 추출을 재사용한 것이므로 결과의 `reused_extraction: true`는 정상이다.

| 결과 | 수량 |
|---|---:|
| 처리 문서 / 실패 문서 | 2 / 0 |
| 추출 요구조건 | 310 |
| 승인 프로파일로 적용한 요구조건 | 3 |
| 자동 보류 요구조건 | 307 |
| 적용 엔티티 / 관계 | 4 / 2 |
| 최종 실행 상태 | `partial` |

보류에는 현재 프로파일 범위 밖의 CPU·GPU·소프트웨어 조건과 해석을 확정하지 않은 조건이 포함된다.
두 문서 모두 원문에서 미처리 구간 2개가 남았다. 전체 요구조건 추출·표준화 완료로 해석하지 않는다.
16GB는 `per_module`이지만 연산이 `raw`로 남아 숫자 관찰로 적재하지 않았다.
512GB는 구성 목록·상세 규격·검수 조건의 서로 다른 원문 근거 3개를 각각 관찰로 적재했다.
따라서 관찰 3건은 문서 3개나 서버 3대를 뜻하지 않는다.

## 실제 Runtime HTTP 결과

활성 bundle checksum은 `sha256:c8b47e49ac96af133f60d831b1b3751ae7bce5d6ccfca95f08361c17e69ca05b`다.
`teoria`와 `computer_server` 게시 artifact 2개, 승인 Binding 21개, Capability 4개를 포함한다.
은퇴한 대상의 Binding 22개는 새 bundle에서 제외하며 DB의 기존 승인 이력은 변경하지 않았다.

| 요청 | 확인 결과 |
|---|---|
| 인증 없는 discovery | HTTP 401 |
| 인증된 discovery | 공개 검색·비교·근거 조회 3개; 내부 조회 제외 |
| `memory_min: 64` | 서버 문서 1개의 512GB 요구조건 관찰 3건 |
| `memory_min: 600` | 0건 |
| `memory_min: 16, scope: per_module` | raw 연산 조건을 숫자 조회에서 제외하여 0건 |
| page 2 / page_size 1 | 1건, 전체 관찰 수 3건 |
| 두 문서 비교 | `not_comparable`, `missing_aligned_requirement`; 16GB를 총량으로 환산하지 않음 |
| 원문 근거 조회 | `verified`, `3) Memory: DDR5 총 512GB 이상(S03)` 및 checksum·근거 node 반환 |
| 존재하지 않는 observation의 근거 조회 | `not_found` |

두 문서의 수치 차이 계산이 성공한 것은 아니다. 비교 API가 정렬할 수 없는 조건을 안전하게 거절한
사례다. 정확히 정렬되는 두 실제 문서의 양성 비교 검증과 독립 품질 평가는 후속 작업으로 남는다.

## 확인과 보존

반영 전 Application DB dump·SHA-256·기존 이미지 ID·활성 bundle 참조는
`backups/teoria/server_rollout_20261027/`에 보존한다. 기존 전체 백업은 삭제하지 않았다.
명시 입력, 분류 근거, API 응답, 실행 로그와 실제 Runtime 검증 결과는
로컬 `.artifacts/server_rollout_2026_10_27/`에 있다.
운영 원본은 `teoria_specification-inputs`, 추출·정규화 본문은 `teoria_specification-artifacts`
volume에 저장한다. Worker는 원본 volume을 읽기 전용으로 사용한다.

사전 검증: 백엔드 테스트 603 passed / 46 skipped, Runtime Registry validate 통과,
Compose config 통과, Runtime·Authoring·Worker 이미지 build 통과.
조건부 제외 테스트를 실제 외부 환경 검증 성공으로 집계하지 않는다.
문서 검사 7 passed와 변경 문서의 whitespace 검사를 통과했다. 운영 gateway를 통한
Admin·Runtime health, 관리 화면과 Runtime API 문서의 HTTP 200 및 인증된 discovery도 확인했다.
원문 사전 검토용 임시 파싱 파일 22개(1,015,809 bytes)를 정리하고 입력 원본·분류 근거와
운영 산출물·최소 검토 기록은 보존했다.

관리 화면은 `/admin/semantic-model/ontology`, 계약 목록은 `/admin/developer/capabilities`,
실제 실행 API는 `/runtime-api/docs`에서 확인한다. 현재 gateway의 로컬 포트는 8081이다.
이번 검증의 최초 Flow run ID는 `7a135dfc-482e-4efd-97a3-43829a246293`이다.
고정 표준 적용 Flow run ID는 `d62e1689-8699-4955-a861-4e3a5c553b4e`다.

이전 bundle `2026.10.25.1`과 이전 이미지 ID를 보존했으며 되돌릴 때는 bundle 활성 참조와
Runtime 이미지를 함께 복원한다. 이번 additive migration이나 작성·승인 이력을 삭제할 필요는 없다.
