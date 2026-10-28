# 구성 관계·방향 검증의 운영 Worker 반영

2026-10-28 사용자의 명시적 운영 반영 요청에 따라 로컬 Compose의 규격서 Worker를 교체했다.
코드 수정·격리 평가만 수행한 이전 기록과 구분한다. K3s나 외부 운영 환경에 배포한 기록은 아니다.

## 반영 범위

- 대상: teoria-prefect-worker-1 / pool teoria-specification.
- 이전 이미지: teoria-pipelines:goods-source-label-guard-20261027
  (5ec917d215e85d1aa323e9e662d1d12e54b027a8832e207dab567b754f8fb3bc).
- 현재 이미지: teoria-pipelines:goods-relations-20261028
  (d5964eca422717fdad0885ecc881b620c6a79336126a0448497fefc3d671c89c).
- 기존 이미지 위에 entity_relation_extraction.py, tasks.py, reporting.py, evaluation.py,
  evaluation_cases.py만 반영했다. 배포한 파일의 checksum이 검증한 작업공간 코드와 일치함을 확인했다.
- 기존 base의 flows.py와 작업공간 파일 차이는 끝의 공백/개행뿐이다. 기능 차이는 없다.
- 실행 중/Pending/Cancelling 작업이 없음을 확인하고 교체했다. 볼륨·환경·권한·네트워크·pool은 보존했다.
- 새 ProcessWorker의 ONLINE 상태와 heartbeat를 확인했다. 이전 Worker 이력은 삭제하지 않았다.
- API·Runtime·법령·메타데이터·모델 Worker를 교체하지 않았다. DB migration을 실행하지 않았다.

## 재기동 시 이미지 유지

Compose의 prefect-worker에 TEORIA_SPECIFICATION_WORKER_IMAGE 선택을 추가했다. 기본값은
teoria-pipelines:latest이며 로컬 deploy/compose/.env에는 현재 릴리스 태그를 지정했다.
공용 latest 태그를 바꾸지 않아 다른 Pipeline 역할의 이미지를 변경하지 않는다.

동일 Compose 재기동이 현재 태그를 선택하는지 config로 확인했다. 예제 환경 파일과 설정 안내도 갱신했다.
역할별 이미지 분리 검사 등 Compose 테스트 13개가 통과했다. Docker Compose config 검증도 성공했다.

이전 버전으로 되돌릴 경우 해당 변수에 이전 명시 태그를 지정하고 prefect-worker만 --no-deps --no-build로
재생성한다. 작업 중에는 재시작하지 않는다. 이전 이미지와 모든 원문·산출물·DB 이력을 유지했다.

## 운영에서 실제 원본 처리

새 Worker 안에서 기존 LC-MS PDF를 원본부터 새로 처리했다. extraction_checkpoint는 사용하지 않았다.

- run_id: goods_relations_deployment_20261028_01
- Prefect run: 487c2fb3-d493-402f-a4c2-dc8918523beb
- Flow: procurement-standard-management
- 모델 gpt-6.1-sol, 파서 0.9.15.
- Task 00–08, 보고서 저장, 완료 checkpoint까지 성공. 약 3분 29초.
- 처리 문서 1, 실패 문서/실패 추출 chunk 0.
- 대상 56개, 활성 관계 62개, 속성 관찰 188개.
- 구성 목록 9개 전부 item→root component_of와 in_procurement_scope를 함께 갖는다.
- 작업 관계의 잘못된 출발 유형과 문서/작업→장비 구성 유형 오류가 없음을 확인했다.
- 유량 0.0001~10 mL/min의 range 조건을 보존했다.
- 불확실한 동일 대상 1건, 두 제출 문서의 관계 종류 2건을 held_relations에 보존했다.
- 보고서의 [범위·구성] 통합 표시와 보류 사유 표를 확인했다.

Prefect 실행은 Completed지만 문서 결과는 partial이다. 보류 관계 3건과 표준 의미가 정렬되지 않은
188개 관찰을 완료된 의미 정렬로 표시하지 않는다. 새 구성 규칙의 배포 확인이며 전체 정확도 개선의 재판정이 아니다.
이전 고정 네 문서 평가의 inconclusive 한계는 유지한다.

원문 표현은 이번 실행에서 신규 8건·재사용 117건·정의 충돌 보류 6건이다.
현재 원문 등록 327개이며 승인된 로컬 표준 정의 2개·매핑 2개는 유지했다.
원문 등록을 새 표준 개념 또는 Published Ontology로 승격하지 않았다.

별도로 새 이미지 안에서 통제된 추론 응답을 이용한 runtime smoke도 실행했다.
구성/범위 병존, 재판정 후 보류, 원래 방향 보존, 보고서 결합 표시에 통과했다.
이 검사는 실제 모델 추출과 구분한다.

## 확인 위치

- [실제 실행 결과](../../.artifacts/goods_relation_deployment_20261028/results/index.md)
- [배포 검증 요약](../../.artifacts/goods_relation_deployment_20261028/verification.json)
- [운영 원문 추출](../../.artifacts/goods_relation_deployment_20261028/results/extracted.json)
- [선행 코드·4문서 비교](goods_relation_repair_2026_10_28.md)

전체 운영 산출물은 specification-artifacts 볼륨의
/app/specification_artifacts/goods_relations_deployment_20261028 아래에 저장됐다.
로컬 복사본은 .artifacts/goods_relation_deployment_20261028/results/에 있다.
