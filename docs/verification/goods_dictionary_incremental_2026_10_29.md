# 사전 증분 관리 구현 검증 — 2026-10-29

기존 표준관리 Flow의 06 단계에 증분 관리를 통합했다. 별도 Flow는 추가하지 않았다.
현재 문맥과 승인 정의 개정을 확인하고, 새 문맥은 관련 과거 추출 참조를 자동 조회한다.
Codex 변경안·독립 검증·영향 검사를 통과한 묶음만 Admin API로 반영한다.
문서처리는 지정한 사전 스냅샷을 유지한다.

## 검증

- 백엔드 전체: 732 passed, 79 skipped. 외부 환경이 필요한 검사는 실행되지 않았다.
- 증분 관리 전용: 7 passed. 수치만 변경된 문맥 재사용, 캐시 재사용,
  역할·원문 문구 변경 시 검토, 과거 참조 누락·해시 불일치 보류, 기존 의미로의 잘못된 재적용 방지.
- 문서 테스트: 9 passed.
- Compose config, Prefect 배포 문서 일치 검사, git diff 공백 검사 통과.
- 전체 문서 링크 검사: 기존 검증 문서의 로컬 .artifacts 링크 누락 25건 확인.

모델 응답과 Admin 저장소를 대체한 통합 단위 테스트이며 실제 Codex 품질 검증으로 간주하지 않는다.

## 적용 상태

소스·테스트·문서·배포 선언을 수정했다. 운영 DB 마이그레이션과 이미지 교체는 아직 실행하지 않았다.
필요한 신규 migration은 Application DB `022_goods_mapping_scope.sql`, Data DB
`102_specification_source_lookup.sql`이다. 과거 적용 migration은 수정하지 않았다.

분류 미제공 매핑은 미분류 문맥에 한정한다. 명시적 분류 독립 범위와 구분하며
이전 고정 스냅샷은 당시 해석을 유지한다. 확인된 문맥은 실행 완료 뒤에만 재사용한다.

자세한 동작과 산출물은 [파이프라인](../procurement_specification_processing/pipeline.md),
[사전](../platform/goods_dictionary.md)을 참고한다.
