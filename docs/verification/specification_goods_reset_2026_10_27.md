# 기존 물품 모델 삭제와 규격서 물품 모델 재작성

사용자의 명시적인 기존 모델 삭제·재작성 요청으로 물품 모델을 초기화했다.
기존 모델의 이름이나 version만 바꾸지 않고 운영 DB의 모델·후보·프로파일·Binding·관찰과
서버 전용 조회 구현을 제거했다. 새 `goods` 1.0.0은 검토용 Draft다.

## 삭제 범위

| 대상 | 실제 삭제 |
|---|---:|
| 기존 namespace | `goods`, `computer_server` 2개 |
| 기존 Ontology version | 3 |
| 기존 concept | 160 |
| 정규화 프로파일 / 이벤트 | 3 / 11 |
| 의미 작성 operation | 1; 신규 개념 제안 73건을 포함한 후보 상태 제거 |
| Binding / 미참조 Capability target | 10 / 8; 관련 Binding review는 FK cascade 삭제 |
| 기존 Ontology audit event | 170 |
| 숫자 관찰 / 문서 처리 실행 / 표준관리 workflow | 6 / 2 / 1 |
| 문서별 실행 결과 / 산출물 참조 | 4 / 10 |
| 운영 규격서 산출물 파일 | 17 |
| 이전 live bundle | `2026.10.27.1`, `2026.10.27.2` |

서버 전용 Capability 4개와 Source·Mapping·Runtime contract, `goods_querying` feature,
숫자 관찰 준비·적재 경로, 서버 프로파일·구형 blueprint와 해당 기능 전용 테스트를 제거했다.
원문 추출·일반 정규화·파일/S3 산출물·Data DB 완료 checkpoint 기반은 유지했다.
Data migration 095가 이전 숫자 관찰 view/table을 제거한다. 적용된 migration 본문은 변경하지 않았다.

Application DB 삭제는 소유 namespace와 참조 ID를 고정한 한 transaction에서 실행했다.
삭제 전 rollback 연습과 실제 commit 모두 물품 외 앱 데이터 19개 묶음의 전체 행 checksum이 일치했다.
기존 published/deprecated revision 삭제는 명시적 운영 purge SQL에서만 수행했고, 해당 5개 revision 보호
trigger를 transaction 안에서 일시 해제·복원했다. FK 검사는 유지했고, 완료 후 비활성화된 trigger는 0개다.
일반 API의 Published 불변성 정책을 변경하지 않았다.

SQL·분류 manifest·실행 receipt는
`backend/authoring/ontology_migrations/applied/2026_10_specification_goods_reset/`에 보존한다.
SQL의 inventory guard는 새 모델에 재실행하는 것을 거절한다.

## 새 Draft

version ID: `6bf176a6-913a-4b05-9a95-b8bbf6ba7866`.
인증된 Admin principal `system:admin`으로 작성했고 Draft 상태를 유지했다.
객체 6개·속성 35개·관계 13개이며 validation diagnostic은 0개다.

| 객체 | 책임 |
|---|---|
| `goods.specification_document` | 특정 원본 버전의 규격서 |
| `goods.specified_item` | 문서가 지시하는 물품·구성 대상 |
| `goods.property_statement` | 대상의 속성 값·조건·역할·범위 |
| `goods.composition_statement` | 구성의 상하위·수량·포함 조건·근거 |
| `goods.requirement_statement` | 설치·교육·검수 등 속성 하나로 축약하지 않은 요구 |
| `goods.evidence` | 특정 문서 버전의 구절·위치 근거 |

물품/구성품을 배타적인 고정 타입으로 나누지 않고 대상의 유형과 문맥상 역할을 구분했다.
상위·하위 대상은 구성 명세를 통해 연결하며 원문의 포함·선택·제외·범위를 보존하도록 정의했다.
속성 명세의 원문 값과 표준 속성 참조를 분리했다. 문서·대상 언급·속성·구성·요구는 근거로 연결한다.

이것은 schema 구조 검증이다. 새 typed value·조건·유형 참조·명세 계약, 실제 원문 검증,
게시·승인 프로파일, 새 Runtime 탐색과 새 데이터 적재까지 완료했다는 뜻은 아니다.
이전 추출·정규화 결과를 새 모델의 인스턴스로 다시 등록하지 않았다.

## Runtime과 보존

서버 전용 모델을 포함하지 않는 Registry·bundle `2026.10.27.3`으로 먼저 전환하고 DB를 삭제했다.
Runtime은 기존 `teoria` Published artifact와 관련 승인 Binding을 사용하며 물품 Capability는 0개다.
구형 live bundle 2개를 제거해 이전 물품 모델을 다시 활성화하는 경로도 정리했다.
Runtime·Admin·규격서 Worker에 reset 이미지를 배포한다. 병행 수정 중인 Parser·프런트엔드는 이번 작업에 포함하지 않는다.

원본 규격서, 법령·OpenMetadata와 물품 외 Ontology·Binding·기반 데이터는 유지했다.
최소 평가 사용 이력과 기존 applied SQL·이관 기록도 보존했다.
반영 전 dump·운영 산출물·이전 bundle과 로컬 결과는
`backups/teoria/specification_goods_reset_20261027/`에 checksum과 함께 보관한다.
전체 Data DB나 기존 대용량 백업의 복원 검사는 수행하지 않았다.

실행 입력·구조 검증·rollback 연습·실제 삭제 결과와 HTTP 확인은
`.artifacts/specification_goods_reset_2026_10_27/`에 있다.

새 모델 화면:
`/admin/semantic-model/ontology?version=6bf176a6-913a-4b05-9a95-b8bbf6ba7866`.

## 최종 확인

- 백엔드·문서 검사: 594 passed / 45 skipped. 제외된 외부 환경 검사를 성공으로 집계하지 않았다.
- Registry validate: Source·Runtime contract·Mapping·Capability 0개, 유효.
- 명시적 reset manifest의 migration report와 Compose config, 변경 파일 whitespace 검사 통과.
- 실제 gateway의 Admin·Runtime health와 새 모델 화면 HTTP 200.
- 인증 없는 Runtime discovery HTTP 401, 인증된 discovery 빈 목록.
- 이전 Capability 4개와 이전 Ontology version 3개의 실제 요청 HTTP 404.
- `computer_server` version 목록은 빈 목록, `goods`는 새 1.0.0 Draft 하나만 존재.
- 프로파일·의미 작성 operation·기존 문서 실행·workflow 0건, 기존 숫자 관찰 table 제거 확인.
- 이전 실제 입력 원본 2개의 SHA-256 유지, 새 백업 파일 5개의 checksum 검사 통과.

Runtime·Admin·규격서 Worker의 기본 `latest` 태그도 reset 이미지로 맞췄다.
