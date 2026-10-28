# 실행·검증 기록

현재 방법은 [문서 목차](../index.md)를 따른다. 이곳은 특정 입력·버전·환경에서 확인한 결과와 한계를 보존한다.
실행 성공·코드 검사·업무 의미 정확도를 구분한다. 날짜가 지난 결과를 현재 기능·건수·배포 상태로 사용하지 않는다.

## 현재 기능을 이해할 때 참고할 기록

| 기록 | 확인한 범위 |
|---|---|
| [사전 일괄 구축·개정·버전 고정](goods_dictionary_maintenance_2026_10_28.md) | 개정·영향 매핑·스냅샷·운영 반영과 실제 부분집합 검증 |
| [물품 공고 운영 DB 복원](goods_notice_production_restore_2026_10_28.md) | migration 101·공고 758,443건·첨부 1,848,691건 운영 반영·기존 20개 테이블 보존 |
| [물품 공고 근거 스키마·격리 복원](goods_notice_restore_validation_2026_10_28.md) | 공고 758,443건·첨부 1,848,691건 복원·기존 20개 테이블 보존·운영 미적용 |
| [표준 의미 자동 작성·승인의 운영 Worker 반영](goods_dictionary_deployment_2026_10_28.md) | Worker 교체·Codex 의미 판단·로컬 사전 승인 경로 |
| [구성 관계·방향 검증의 운영 Worker 반영](goods_relation_deployment_2026_10_28.md) | 운영 Worker 교체·실제 LC-MS 처리·구성·보류 |
| [구성 관계·작업 방향 검증 수정](goods_relation_repair_2026_10_28.md) | 고정 네 원본의 전후 비교·관계 규칙과 평가 한계 |
| [네 규격서의 전체 파이프라인 실행·품질 점검](goods_four_sample_pipeline_2026_10_27.md) | 네 규격서 전체 처리와 사전 후보 문제 |
| [물품 표준 정의·매핑 적용 검증](goods_meaning_dictionary_2026_10_27.md) | 원문 표현·표준 정의·매핑 분리 |
| [Data DB의 이전 조달 스키마 객체 정리 — 2026-10-28](data_schema_cleanup_2026_10_28.md) | 이전 조달 저장 객체 정리와 보존 범위 |
| [미사용 ingestion 구조 정리와 보존 기준 — 2026-10-28](ingestion_cleanup_2026_10_28.md) | 공통 ingestion 정리와 보존 기준 |

## 전체 이력

[날짜별 기록](history.md)에서 이전 배포·설계 이관·초기화·기능별 실행 증적을 찾는다.
폐기한 규격서 실험과 비활성 업무 설명은 [보관 문서](../../archive/documentation/index.md)에 있다.

새 기록은 입력·환경·버전·방법·결과·한계를 명시하고 실제 credential·개인정보·비공개 응답을 넣지 않는다.
